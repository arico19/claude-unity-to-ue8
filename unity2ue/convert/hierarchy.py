"""Conversión de escenas (.unity) y prefabs (.prefab) a árboles de nodos neutrales.

Cada GameObject se convierte en un nodo con transform (ya en espacio UE), componentes
convertidos e hijos. Las instancias de prefab (``PrefabInstance``) se convierten en
nodos que referencian el Blueprint generado para ese prefab, con sus overrides.
"""

from __future__ import annotations

import re
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
        if prefab_info is not None and prefab_info.category == "model":
            # En un FBX el fileID de su transform raíz es interno del modelo; Unity siempre guarda
            # m_LocalPosition del transform raíz de la instancia, así que se identifica por eso
            # (si no, se pierden la escala y la rotación de la instancia).
            root_transform_id = next(
                (ref_file_id(m.get("target")) for m in mod.get("m_Modifications") or []
                 if str(m.get("propertyPath")) == "m_LocalPosition.x" and ref_guid(m.get("target")) == guid),
                None,
            )

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
        if prefab_info is not None and prefab_info.category == "model":
            # FBX arrastrado directamente a la escena/prefab: no hay Blueprint del modelo; se crea
            # el componente de malla en el propio nodo (si no, el actor queda invisible).
            return {
                "id": str(inst.file_id),
                "name": name,
                "active": active,
                "tag": "Untagged",
                "layer": 0,
                "static": False,
                "transform": transform_to_ue(position, rotation, scale),
                "components": [self._model_mesh_component(prefab_info, ref, overrides, f"{self.path}:{name}")],
                "children": [],
                "model_instance": prefab_info.path,
            }
        if overrides:
            self.ctx.info(
                f"{self.path}:{name}",
                f"{len(overrides)} overrides de prefab en objetos internos registrados en el JSON (aplicación parcial).",
            )
        # Componentes añadidos en la instancia/variante (p.ej. un script que el prefab base no tiene).
        added: list[dict[str, Any]] = []
        for entry in mod.get("m_AddedComponents") or []:
            obj = self.doc.get(ref_file_id((entry or {}).get("addedObject")))
            target = ref_file_id((entry or {}).get("targetCorrespondingSourceObject"))
            if obj is None:
                continue
            if root_go_id is not None and target != root_go_id:
                self.ctx.warn(f"{self.path}:{name}", "Componente añadido a un objeto interno del prefab: "
                                                     "se añade a la raíz del actor")
            converted = convert_component(obj, self.ctx, f"{self.path}:{name}")
            added.extend(converted if isinstance(converted, list) else [converted] if converted else [])
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
                "added_components": added,
            },
        }

    def _model_mesh_component(self, info: Any, ref: dict[str, Any] | None, overrides: list[dict[str, Any]],
                              src: str) -> dict[str, Any]:
        """Componente de malla para una instancia directa de un modelo (FBX/OBJ/glTF)."""
        # Con esqueleto si el FBX tiene rig (animationType != None) y algún SkinnedMeshRenderer.
        # (Unity 2022+ puede no listar los sub-objetos en el .meta: entonces basta con el rig.)
        subs = info.sub_objects
        has_skin = any(cls == C.SKINNED_MESH_RENDERER for cls, _fid, _n in subs) or not subs
        skeletal = has_skin and int(info.importer.get("animationType", 0) or 0) != 0
        mesh = dict(ref or {}, kind="model")
        self.ctx.mark_model(mesh, skeletal=skeletal, source=src)
        # Materiales sobrescritos en la instancia (m_Materials.Array.data[i]) o remapeados en el .meta.
        slots: dict[int, dict[str, Any] | None] = {}
        for o in overrides:
            m = re.match(r"m_Materials\.Array\.data\[(\d+)\]", o.get("property") or "")
            if m and o.get("object_reference"):
                slots[int(m.group(1))] = o["object_reference"]
        if not slots:
            for i, e in enumerate(info.importer.get("externalObjects") or []):
                first = (e or {}).get("first") or {}
                if "Material" in str(first.get("type", "")):
                    slots[i] = self.ctx.asset_ref((e or {}).get("second"), src)
        materials = [slots.get(i) for i in range(max(slots) + 1)] if slots else []
        return {"type": "SkeletalMesh" if skeletal else "StaticMesh", "mesh": mesh, "materials": materials,
                "cast_shadow": True, "visible": True}

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
        result = [n for _, n in roots]
        self._fix_skinned_meshes(result)
        return result

    def _fix_skinned_meshes(self, roots: list[dict[str, Any]]) -> None:
        """Ajustes para modelos con esqueleto (SkinnedMeshRenderer).

        * En Unity la malla con skin la colocan sus huesos, no el transform de su GameObject (que
          en los FBX suele llevar la corrección de ejes, -90 en X). UE ya aplica esa corrección al
          importar y coloca la SkeletalMesh respecto a la raíz del modelo, así que el nodo de la
          malla pasa a transform identidad (si no, el personaje sale tumbado).
        * Los huesos (GameObjects sin componentes referenciados en m_Bones) no aportan nada en UE:
          ya están en el esqueleto. Se eliminan salvo que lleven algo colgado (p.ej. un arma).
        """
        bones: set[int] = set()
        for smr in self.doc.by_class(C.SKINNED_MESH_RENDERER):
            bones |= {ref_file_id(b) for b in smr.get("m_Bones") or []}
            bones.add(ref_file_id(smr.get("m_RootBone")))
        bones.discard(0)
        tid_of = {id(n): tid for tid, n in self.nodes_by_transform.items()}
        identity = transform_to_ue({"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 0, "w": 1}, {"x": 1, "y": 1, "z": 1})
        pruned = 0

        def visit(node: dict[str, Any]) -> bool:
            """Devuelve True si el nodo debe conservarse."""
            nonlocal pruned
            node["children"] = [c for c in node.get("children", []) if visit(c)]
            # (No en instancias de modelo: ahí el transform es el de la instancia, con su escala.)
            if not node.get("model_instance") and any(
                    c.get("type") == "SkeletalMesh" for c in node.get("components", [])):
                node["transform"] = dict(identity)
                node["skinned_transform_ignored"] = True
            is_bone = tid_of.get(id(node)) in bones
            if is_bone and not node.get("components") and not node["children"] and not node.get("prefab"):
                pruned += 1
                return False
            return True

        roots[:] = [r for r in roots if visit(r)]
        if pruned:
            self.ctx.info(self.path, f"{pruned} huesos sin nada colgado omitidos (ya están en el esqueleto de UE)")

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
