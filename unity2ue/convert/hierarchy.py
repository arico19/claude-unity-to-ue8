"""Conversión de escenas (.unity) y prefabs (.prefab) a árboles de nodos neutrales.

Cada GameObject se convierte en un nodo con transform (ya en espacio UE), componentes
convertidos e hijos. Las instancias de prefab (``PrefabInstance``) se convierten en
nodos que referencian el Blueprint generado para ese prefab, con sus overrides.
"""

from __future__ import annotations

from typing import Any

from ..unity import class_ids as C
from ..unity.yaml_parser import UnityDocument, UnityObject, ref_file_id, ref_guid
from .components import convert_component, merge_render_components
from .context import ConversionContext
from .coords import color_to_linear, transform_to_ue

_TRANSFORM_PROPS = ("m_LocalPosition", "m_LocalRotation", "m_LocalScale")


def _component_ids(go: UnityObject) -> list[int]:
    ids = []
    for entry in go.get("m_Component") or []:
        if not isinstance(entry, dict):
            continue
        if "component" in entry:
            ids.append(ref_file_id(entry["component"]))
        else:  # formato antiguo: {"4": {fileID: X}}
            for v in entry.values():
                ids.append(ref_file_id(v))
    return [i for i in ids if i]


class HierarchyConverter:
    def __init__(self, ctx: ConversionContext, unity_path: str, doc: UnityDocument) -> None:
        self.ctx = ctx
        self.path = unity_path
        self.doc = doc
        # transform fileID -> GameObject fileID
        self.transform_owner: dict[int, int] = {}
        # PrefabInstance fileID -> nodo
        self.instance_nodes: dict[int, dict[str, Any]] = {}
        self.nodes_by_transform: dict[int, dict[str, Any]] = {}

    # ------------------------------------------------------------------ utilidades
    def _stripped_instance(self, file_id: int) -> int | None:
        """Si ``file_id`` es un objeto 'stripped', devuelve su PrefabInstance."""
        obj = self.doc.get(file_id)
        if obj is not None and obj.stripped:
            return ref_file_id(obj.get("m_PrefabInstance")) or None
        return None

    def _transform_of(self, go: UnityObject) -> UnityObject | None:
        for cid in _component_ids(go):
            comp = self.doc.get(cid)
            if comp is not None and comp.class_id in C.TRANSFORM_CLASSES:
                return comp
        return None

    # ------------------------------------------------------------------ nodos
    def _game_object_node(self, go: UnityObject, transform: UnityObject) -> dict[str, Any]:
        name = str(go.get("m_Name") or "GameObject")
        src = f"{self.path}:{name}"
        components: list[dict[str, Any]] = []
        for cid in _component_ids(go):
            comp = self.doc.get(cid)
            if comp is None or comp.class_id in C.TRANSFORM_CLASSES:
                continue
            if comp.stripped:
                continue
            converted = convert_component(comp, self.ctx, src)
            if isinstance(converted, list):
                components.extend(converted)
            elif converted:
                components.append(converted)
        node: dict[str, Any] = {
            "id": str(go.file_id),
            "name": name,
            # fileIDs del GameObject y sus componentes (para resolver referencias locales).
            "unity_ids": [str(go.file_id), *(str(c) for c in _component_ids(go))],
            "active": bool(int(go.get("m_IsActive", 1) or 0)),
            "tag": str(go.get("m_TagString") or "Untagged"),
            "layer": int(go.get("m_Layer", 0) or 0),
            "static": bool(int(go.get("m_StaticEditorFlags", 0) or 0)),
            "transform": transform_to_ue(
                transform.get("m_LocalPosition"), transform.get("m_LocalRotation"), transform.get("m_LocalScale")
            ),
            "components": merge_render_components(components),
            "children": [],
        }
        if transform.class_id == C.RECT_TRANSFORM:
            node["ui_rect"] = {
                k: transform.get(k)
                for k in ("m_AnchorMin", "m_AnchorMax", "m_AnchoredPosition", "m_SizeDelta", "m_Pivot")
            }
        return node

    def _instance_node(self, inst: UnityObject) -> dict[str, Any]:
        mod = inst.get("m_Modification") or {}
        source = inst.get("m_SourcePrefab") or {}
        guid = ref_guid(source)
        ref = self.ctx.asset_ref(source, self.path)
        prefab_info = self.ctx.project.guids.get(guid)
        name = prefab_info.abs_path.stem if prefab_info else "PrefabInstance"
        root_transform_id = self._prefab_root_transform(guid)
        root_go_id = self._prefab_root_game_object(guid)

        pos: dict[str, Any] = {}
        rot: dict[str, Any] = {}
        scl: dict[str, Any] = {}
        active = True
        overrides: list[dict[str, Any]] = []
        for m in mod.get("m_Modifications") or []:
            target = m.get("target") or {}
            tid = ref_file_id(target)
            prop = str(m.get("propertyPath") or "")
            value = m.get("value")
            if tid == root_transform_id and ref_guid(target) == guid:
                base, _, axis = prop.partition(".")
                if base in _TRANSFORM_PROPS and axis:
                    {"m_LocalPosition": pos, "m_LocalRotation": rot, "m_LocalScale": scl}[base][axis] = value
                    continue
                if base in ("m_LocalEulerAnglesHint", "m_RootOrder"):
                    continue
            if tid == root_go_id and ref_guid(target) == guid:
                if prop == "m_Name" and value:
                    name = str(value)
                    continue
                if prop == "m_IsActive":
                    active = bool(int(value or 0))
                    continue
            obj_ref = m.get("objectReference")
            overrides.append(
                {
                    "target_file_id": tid,
                    "property": prop,
                    "value": value,
                    "object_reference": self.ctx.asset_ref(obj_ref, self.path) if ref_file_id(obj_ref) else None,
                }
            )
        base_t = self._prefab_root_local_transform(guid)
        position = {**base_t.get("m_LocalPosition", {}), **pos}
        rotation = {**base_t.get("m_LocalRotation", {"x": 0, "y": 0, "z": 0, "w": 1}), **rot}
        scale = {**base_t.get("m_LocalScale", {"x": 1, "y": 1, "z": 1}), **scl}
        if overrides:
            self.ctx.info(
                f"{self.path}:{name}",
                f"{len(overrides)} overrides de prefab en objetos internos registrados en el JSON (aplicación parcial).",
            )
        return {
            "id": str(inst.file_id),
            "name": name,
            "active": active,
            "tag": "Untagged",
            "layer": 0,
            "static": False,
            "transform": transform_to_ue(position, rotation, scale),
            "components": [],
            "children": [],
            "prefab": {
                "guid": guid,
                "unity_path": prefab_info.path if prefab_info else None,
                "ue_class_path": (ref or {}).get("ue_class_path"),
                "overrides": overrides,
                "removed_components": [ref_file_id(r) for r in mod.get("m_RemovedComponents") or []],
            },
        }

    # --------------------------------------------------------- info de prefabs fuente
    def _prefab_doc(self, guid: str | None) -> UnityDocument | None:
        try:
            return self.ctx.project.load_guid(guid)
        except Exception:  # noqa: BLE001
            return None

    def _prefab_root_transform(self, guid: str | None, depth: int = 0) -> int | None:
        doc = self._prefab_doc(guid)
        if doc is None or depth > 16:
            return None
        for t in doc.by_class(*C.TRANSFORM_CLASSES):
            if not t.stripped and not ref_file_id(t.get("m_Father")):
                return t.file_id
        # Variante de prefab: la raíz es un transform 'stripped' de una instancia sin padre.
        for inst in doc.by_class(C.PREFAB_INSTANCE):
            parent = ref_file_id((inst.get("m_Modification") or {}).get("m_TransformParent"))
            if parent:
                continue
            base_guid = ref_guid(inst.get("m_SourcePrefab"))
            base_root = self._prefab_root_transform(base_guid, depth + 1)
            for t in doc.by_class(*C.TRANSFORM_CLASSES):
                if t.stripped and ref_file_id(t.get("m_PrefabInstance")) == inst.file_id:
                    if ref_file_id(t.get("m_CorrespondingSourceObject")) == base_root:
                        return t.file_id
        return None

    def _prefab_root_game_object(self, guid: str | None) -> int | None:
        doc = self._prefab_doc(guid)
        root_t = self._prefab_root_transform(guid)
        if doc is None or root_t is None:
            return None
        t = doc.get(root_t)
        if t is not None and not t.stripped:
            return ref_file_id(t.get("m_GameObject"))
        for go in doc.by_class(C.GAME_OBJECT):
            if go.stripped and t is not None and ref_file_id(go.get("m_PrefabInstance")) == ref_file_id(
                t.get("m_PrefabInstance")
            ):
                return go.file_id
        return None

    def _prefab_root_local_transform(self, guid: str | None) -> dict[str, Any]:
        doc = self._prefab_doc(guid)
        root_t = self._prefab_root_transform(guid)
        if doc is None or root_t is None:
            return {}
        t = doc.get(root_t)
        if t is None or t.stripped:
            return {}
        return {k: t.get(k) or {} for k in _TRANSFORM_PROPS}

    # ------------------------------------------------------------------ árbol
    def build(self) -> list[dict[str, Any]]:
        doc = self.doc
        # 1) Nodos de GameObjects reales
        for go in doc.by_class(C.GAME_OBJECT):
            if go.stripped:
                continue
            t = self._transform_of(go)
            if t is None:
                self.ctx.warn(self.path, f"GameObject '{go.get('m_Name')}' sin Transform; ignorado.")
                continue
            self.transform_owner[t.file_id] = go.file_id
            self.nodes_by_transform[t.file_id] = self._game_object_node(go, t)
        # 2) Nodos de instancias de prefab
        for inst in doc.by_class(C.PREFAB_INSTANCE):
            if not inst.get("m_SourcePrefab"):
                continue
            self.instance_nodes[inst.file_id] = self._instance_node(inst)

        # 3) Resolver padres
        def resolve_parent(parent_tid: int) -> dict[str, Any] | None:
            if not parent_tid:
                return None
            if parent_tid in self.nodes_by_transform:
                return self.nodes_by_transform[parent_tid]
            inst_id = self._stripped_instance(parent_tid)
            if inst_id and inst_id in self.instance_nodes:
                return self.instance_nodes[inst_id]
            return None

        roots: list[tuple[int, dict[str, Any]]] = []
        order_hint: dict[int, int] = {}  # id de nodo -> orden entre hermanos
        for tid, node in self.nodes_by_transform.items():
            t = doc.get(tid)
            assert t is not None
            parent_tid = ref_file_id(t.get("m_Father"))
            for idx, child in enumerate(t.get("m_Children") or []):
                order_hint[ref_file_id(child)] = idx
            parent = resolve_parent(parent_tid)
            if parent is None:
                if parent_tid:
                    self.ctx.warn(self.path, f"Padre {parent_tid} de '{node['name']}' no encontrado; se deja en raíz.")
                roots.append((int(t.get("m_RootOrder", 0) or 0), node))
            else:
                if parent.get("prefab") is not None:
                    node["attach_to_prefab_object"] = str(parent_tid)
                parent["children"].append(node)
        for inst_id, node in self.instance_nodes.items():
            inst = doc.get(inst_id)
            assert inst is not None
            parent_tid = ref_file_id((inst.get("m_Modification") or {}).get("m_TransformParent"))
            parent = resolve_parent(parent_tid)
            if parent is None:
                roots.append((1 << 30, node))
            else:
                parent["children"].append(node)

        # Orden de raíces: SceneRoots (Unity 2022+) o m_RootOrder
        scene_roots = doc.by_class(C.SCENE_ROOTS)
        if scene_roots:
            ordered_ids = [ref_file_id(r) for r in scene_roots[0].get("m_Roots") or []]
            rank = {}
            for i, rid in enumerate(ordered_ids):
                node = self.nodes_by_transform.get(rid)
                if node is None:
                    inst = self._stripped_instance(rid)
                    node = self.instance_nodes.get(inst) if inst else None
                if node is not None:
                    rank[id(node)] = i
            roots.sort(key=lambda r: rank.get(id(r[1]), 1 << 31))
        else:
            roots.sort(key=lambda r: r[0])
        return [n for _, n in roots]

    def environment(self) -> dict[str, Any]:
        rs = next(iter(self.doc.by_class(C.RENDER_SETTINGS)), None)
        if rs is None:
            return {}
        return {
            "fog": bool(int(rs.get("m_Fog", 0) or 0)),
            "fog_color": color_to_linear(rs.get("m_FogColor")),
            "fog_mode": int(rs.get("m_FogMode", 3) or 0),
            "fog_density": float(rs.get("m_FogDensity", 0.01) or 0.0),
            "ambient_sky_color": color_to_linear(rs.get("m_AmbientSkyColor")),
            "ambient_intensity": float(rs.get("m_AmbientIntensity", 1) or 0.0),
            "skybox_material": self.ctx.asset_ref(rs.get("m_SkyboxMaterial"), self.path),
            "sun": ref_file_id(rs.get("m_Sun")),
        }


def convert_scene(ctx: ConversionContext, unity_path: str) -> dict[str, Any]:
    doc = ctx.project.load(unity_path)
    hc = HierarchyConverter(ctx, unity_path, doc)
    roots = hc.build()
    return {
        "kind": "scene",
        "unity_path": unity_path,
        "name": ctx.naming.imported_name(unity_path),
        "ue_level_path": ctx.naming.level_path(unity_path),
        "environment": hc.environment(),
        "roots": roots,
    }


def convert_prefab(ctx: ConversionContext, unity_path: str) -> dict[str, Any]:
    doc = ctx.project.load(unity_path)
    hc = HierarchyConverter(ctx, unity_path, doc)
    roots = hc.build()
    variant_of = None
    if roots and roots[0].get("prefab") and len(roots) == 1:
        variant_of = roots[0]["prefab"]
    root = roots[0] if roots else None
    if len(roots) > 1:
        ctx.warn(unity_path, f"El prefab tiene {len(roots)} raíces; se usa la primera.")
    return {
        "kind": "prefab",
        "unity_path": unity_path,
        "name": ctx.naming.imported_name(unity_path),
        "ue_blueprint_path": ctx.naming.blueprint_path(unity_path),
        "variant_of": variant_of,
        "root": root,
        "dependencies": sorted(_prefab_dependencies(root)) if root else [],
    }


def _prefab_dependencies(node: dict[str, Any]) -> set[str]:
    deps: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        prefab = n.get("prefab")
        if prefab and prefab.get("unity_path"):
            deps.add(prefab["unity_path"])
        stack.extend(n.get("children", []))
    return deps


def iter_nodes(nodes: list[dict[str, Any]]):
    stack = list(nodes)
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.get("children", []))
