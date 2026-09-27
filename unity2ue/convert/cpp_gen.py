"""Generación de esqueletos C++ (UE 5.8) a partir de scripts C# de Unity.

Estrategia:
* ``MonoBehaviour``  -> ``UActorComponent`` derivado de ``UUnityBehaviour`` (capa de
  compatibilidad generada en el módulo) que invoca Awake/Start/Update/OnTrigger*...
* ``ScriptableObject`` -> ``UPrimaryDataAsset``.
* ``[Serializable]`` class/struct -> ``USTRUCT``; ``enum`` -> ``UENUM``.
* Clases estáticas -> ``UBlueprintFunctionLibrary``; resto -> ``UObject``.

Los cuerpos de los métodos se emiten como TODO con el C# original comentado, listos
para que el agente ``csharp-to-cpp`` de Claude Code los traduzca uno a uno.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..naming import cpp_property_name, to_pascal
from .csharp import CSField, CSFile, CSMethod, CSType
from .type_map import ProjectType, TypeMapper, cpp_default

STATUS_STUB = "UNITY2UE_STATUS: STUB"
STATUS_TRANSLATED = "UNITY2UE_STATUS: TRANSLATED"

MONO_BASES = {"MonoBehaviour", "NetworkBehaviour", "Behaviour", "StateMachineBehaviour"}
SO_BASES = {"ScriptableObject"}
EDITOR_BASES = {"Editor", "EditorWindow", "PropertyDrawer", "ScriptableWizard", "AssetPostprocessor",
                "DecoratorDrawer", "ScriptedImporter"}

# Mensaje Unity -> firma C++ (override de UUnityBehaviour)
UNITY_MESSAGES: dict[str, str] = {
    "Awake": "void Awake()",
    "Start": "void Start()",
    "OnEnable": "void OnEnable()",
    "OnDisable": "void OnDisable()",
    "OnDestroy": "void OnDestroy()",
    "Update": "void Update(float DeltaTime)",
    "LateUpdate": "void LateUpdate(float DeltaTime)",
    "FixedUpdate": "void FixedUpdate(float InFixedDeltaTime)",
    "OnTriggerEnter": "void OnTriggerEnter(AActor* Other)",
    "OnTriggerExit": "void OnTriggerExit(AActor* Other)",
    "OnTriggerStay": "void OnTriggerStay(AActor* Other)",
    "OnTriggerEnter2D": "void OnTriggerEnter(AActor* Other)",
    "OnTriggerExit2D": "void OnTriggerExit(AActor* Other)",
    "OnTriggerStay2D": "void OnTriggerStay(AActor* Other)",
    "OnCollisionEnter": "void OnCollisionEnter(AActor* Other, const FHitResult& Hit)",
    "OnCollisionEnter2D": "void OnCollisionEnter(AActor* Other, const FHitResult& Hit)",
    "OnMouseDown": "void OnMouseDown()",
    "OnMouseEnter": "void OnMouseEnter()",
    "OnMouseExit": "void OnMouseExit()",
    "OnApplicationQuit": "void OnApplicationQuit()",
}
UNSUPPORTED_MESSAGES = {
    "OnCollisionExit": "UE no tiene evento 'hit exit': usar overlaps o seguimiento manual.",
    "OnCollisionStay": "UE no tiene 'hit stay': usar OnComponentHit continuo o Tick.",
    "OnGUI": "IMGUI -> recrear como Widget UMG.",
    "OnDrawGizmos": "Usar DrawDebug* (DrawDebugHelpers.h) o un UPrimitiveComponent de editor.",
    "OnDrawGizmosSelected": "Usar DrawDebug* en un componente de visualización de editor.",
    "OnValidate": "Usar PostEditChangeProperty (WITH_EDITOR).",
    "Reset": "Usar el constructor / PostInitProperties.",
    "OnAnimatorMove": "Root motion: configurar en el Animation Blueprint.",
    "OnAnimatorIK": "IK: usar Control Rig / nodos IK en el Animation Blueprint.",
    "OnBecameVisible": "Usar WasRecentlyRendered() en Tick.",
    "OnBecameInvisible": "Usar WasRecentlyRendered() en Tick.",
    "OnControllerColliderHit": "Usar OnComponentHit del CapsuleComponent del Character.",
    "OnApplicationPause": "Usar FCoreDelegates::ApplicationWillEnterBackgroundDelegate.",
}

# Miembros de UObject/UActorComponent/UUnityBehaviour que no se pueden redeclarar.
RESERVED_MEMBERS = {
    "FixedDeltaTime", "Owner", "World", "PrimaryComponentTick", "ComponentTags", "AssetUserData", "Activate",
    "Deactivate", "SetActive", "IsActive", "SetEnabled", "IsEnabled", "GetOwner", "GetWorld", "GetName", "Destroy",
    "DestroyComponent", "GetComponent", "GetComponents", "CompareTag", "Instantiate", "DestroyActor", "InvokeAfter",
    "InvokeRepeating", "GetTransform", "GetGameObject", "BeginPlay", "EndPlay", "TickComponent", "Rename",
    "GetClass", "GetOuter", "IsValid", "Tick", "Name", "Class", "Outer", "Super", "ThisClass",
}

ZERO_INIT = {"float": "0.f", "double": "0.0", "int32": "0", "uint32": "0", "int64": "0", "uint64": "0",
             "int16": "0", "uint16": "0", "uint8": "0", "int8": "0", "bool": "false"}

CLASS_INCLUDES = {
    "component": ["UnityCompat/UnityBehaviour.h"],
    "data_asset": ["Engine/DataAsset.h"],
    "object": ["UObject/Object.h"],
    "library": ["Kismet/BlueprintFunctionLibrary.h"],
    "interface": ["UObject/Interface.h"],
}
CLASS_BASES = {
    "component": "UUnityBehaviour",
    "data_asset": "UPrimaryDataAsset",
    "object": "UObject",
    "library": "UBlueprintFunctionLibrary",
}


@dataclass
class ScriptPlan:
    """Resultado del análisis de un fichero .cs."""

    unity_path: str
    file: CSFile
    main_type: CSType | None
    kind: str  # component | data_asset | struct | enum | object | library | interface | editor | empty
    cpp_name: str  # sin prefijo
    header_rel: str  # p.ej. "Unity/Gameplay/PlayerController.h"
    field_maps: dict[str, dict[str, str]] = field(default_factory=dict)  # clase -> {unity_field: CppName}


def _is_editor_path(path: str) -> bool:
    return "/Editor/" in f"/{path}" or path.startswith("Assets/Editor")


def classify_types(files: dict[str, CSFile]) -> dict[str, str]:
    """Devuelve nombre de tipo C# -> tipo de conversión, resolviendo herencia en el proyecto."""
    decls: dict[str, CSType] = {}
    for f in files.values():
        for t in f.all_types():
            decls.setdefault(t.name, t)
    cache: dict[str, str] = {}

    def kind_of(name: str, depth: int = 0) -> str:
        if name in cache:
            return cache[name]
        t = decls.get(name)
        if t is None or depth > 32:
            return "external"
        if t.kind == "enum":
            k = "enum"
        elif t.kind == "interface":
            k = "interface"
        else:
            k = ""
            for b in t.bases:
                bname = re.sub(r"<.*>", "", b).split(".")[-1]
                if bname in MONO_BASES:
                    k = "component"
                elif bname in SO_BASES:
                    k = "data_asset"
                elif bname in EDITOR_BASES:
                    k = "editor"
                elif bname in decls and decls[bname].kind != "interface":
                    inherited = kind_of(bname, depth + 1)
                    if inherited in ("component", "data_asset", "editor", "object"):
                        k = inherited
                if k:
                    break
            if not k:
                attrs = {a.split("(")[0].split(".")[-1] for a in t.attributes}
                if t.kind in ("struct", "record") or "Serializable" in attrs:
                    k = "struct"
                elif "static" in t.modifiers:
                    k = "library"
                else:
                    k = "object"
        cache[name] = k
        return k

    return {name: kind_of(name) for name in decls}


def build_plans(files: dict[str, CSFile], naming_fn) -> tuple[list[ScriptPlan], dict[str, ProjectType]]:
    """Crea un plan por fichero y el registro global de tipos del proyecto."""
    kinds = classify_types(files)
    project_types: dict[str, ProjectType] = {}
    plans: list[ScriptPlan] = []
    used_cpp: set[str] = set()
    for path, f in sorted(files.items()):
        stem = PurePosixPath(path).stem
        main = next((t for t in f.types if t.name == stem), f.types[0] if f.types else None)
        if _is_editor_path(path):
            kind = "editor"
        elif main is None:
            kind = "empty"
        else:
            kind = kinds.get(main.name, "object")
        rel_dir = PurePosixPath(path).parent
        parts = [p for p in rel_dir.parts if p not in ("Assets", "Scripts", "Packages")]
        cpp_main = naming_fn(main.name, kind) if main else to_pascal(stem)
        header_rel = "/".join(["Unity", *[to_pascal(p) for p in parts], f"{cpp_main}.h"])
        plan = ScriptPlan(path, f, main, kind, cpp_main, header_rel)
        plans.append(plan)
        if kind in ("editor", "empty"):
            continue
        for t in f.all_types():
            tk = kinds.get(t.name, "object")
            if tk == "editor":
                continue
            base = naming_fn(t.name, tk) if t is main else to_pascal(t.name)
            prefix = {"struct": "F", "enum": "E", "component": "U", "data_asset": "U", "object": "U",
                      "library": "U", "interface": "U"}[tk]
            cpp = prefix + base
            if cpp in used_cpp:
                cpp = prefix + to_pascal(t.outer or stem) + base
            used_cpp.add(cpp)
            project_types.setdefault(t.name, ProjectType(tk, cpp, header_rel, t))
    return plans, project_types


# ---------------------------------------------------------------------- generación
def _comment_block(text: str, indent: str = "\t") -> str:
    lines = text.splitlines() or [""]
    return "\n".join(f"{indent}// {ln}".rstrip() for ln in lines)


def _uproperty_specifiers(f: CSField, category: str) -> str:
    specs = []
    meta = []
    attrs = {a.split("(")[0].strip().split(".")[-1]: a for a in f.attributes}
    if "HideInInspector" in attrs:
        specs.append("BlueprintReadWrite")
    elif f.serialized:
        specs += ["EditAnywhere", "BlueprintReadWrite"]
    specs.append(f'Category = "{category}"')
    if "Range" in attrs:
        m = re.search(r"\(\s*([-\d.fF]+)\s*,\s*([-\d.fF]+)\s*\)", attrs["Range"])
        if m:
            lo, hi = (x.rstrip("fF") for x in m.groups())
            meta += [f'ClampMin = "{lo}"', f'ClampMax = "{hi}"', f'UIMin = "{lo}"', f'UIMax = "{hi}"']
    if "Min" in attrs:
        m = re.search(r"\(\s*([-\d.fF]+)\s*\)", attrs["Min"])
        if m:
            meta.append(f'ClampMin = "{m.group(1).rstrip("fF")}"')
    if "Tooltip" in attrs:
        m = re.search(r'\(\s*"(.*)"\s*\)', attrs["Tooltip"])
        if m:
            meta.append(f'ToolTip = "{m.group(1)}"')
    if "TextArea" in attrs or "Multiline" in attrs:
        meta.append("MultiLine = true")
    if meta:
        specs.append(f"meta = ({', '.join(meta)})")
    return ", ".join(specs)


def _header_category(f: CSField, current: str) -> str:
    for a in f.attributes:
        if a.split("(")[0].strip().split(".")[-1] == "Header":
            m = re.search(r'"(.*)"', a)
            if m and m.group(1).strip():
                return m.group(1).strip()
    return current


_AUTO_PROP = re.compile(r"\{\s*(?:(?:public|private|protected|internal)\s+)?get\s*;\s*"
                        r"(?:(?:public|private|protected|internal)\s+)?(?:set|init)?\s*;?\s*\}\s*(?:=\s*(.+?))?;?\s*$",
                        re.S)


def _by_value(t: str) -> str:
    """Tipo de retorno por valor: los stubs devuelven ``{}`` y una referencia a un temporal no compila."""
    if t.startswith("const ") and t.endswith("&"):
        return t[len("const "):-1].strip()
    return t


class CppGenerator:
    def __init__(self, module_name: str, project_types: dict[str, ProjectType]) -> None:
        self.module = module_name
        self.api = f"{module_name.upper()}_API"
        self.types = project_types
        self.mapper = TypeMapper(project_types)
        # Nombres de miembros de la clase en curso: UHT no permite que un parámetro los oculte.
        self._members: set[str] = set()
        # UFUNCTION ya declaradas en la clase en curso: UHT no admite sobrecargas.
        self._ufuncs: set[str] = set()
        # Includes / declaraciones adelantadas del fichero en curso (también para parámetros y retornos).
        self._includes: set[str] = set()
        self._forwards: set[str] = set()

    # ----------------------------------------------------------- parámetros
    def _params(self, params: str) -> tuple[str, str, bool]:
        """Devuelve (declaración, definición sin valores por defecto, compatible UFUNCTION)."""
        if not params.strip():
            return "", "", True
        from .csharp import _split_top

        decl_parts, def_parts, ok = [], [], True
        for raw in _split_top(params, ","):
            p = re.sub(r"\[[^\]]*\]", "", raw).strip()
            if not p:
                continue
            default = None
            if "=" in p:
                p, default = (x.strip() for x in p.split("=", 1))
            tokens = p.split()
            mods = [t for t in tokens[:-2] if t in ("ref", "out", "in", "params", "this")]
            ptype = " ".join(t for t in tokens[:-1] if t not in ("ref", "out", "in", "params", "this"))
            pname = to_pascal(tokens[-1].lstrip("@"))
            if pname in self._members:
                pname = f"In{pname}"
            ct = self.mapper.map(ptype, pname)
            self._includes |= ct.includes
            self._forwards |= ct.forward
            # Los delegados dinámicos (FUnityEvent) no pueden ser parámetros de UFUNCTION.
            ok = ok and ct.uproperty and ct.decl != "FUnityEvent"
            cpp_t = ct.param
            if "ref" in mods or "out" in mods:
                cpp_t = ct.decl.replace("TObjectPtr<", "").rstrip(">") + "*&" if ct.is_object else f"{ct.decl}&"
            elif "in" in mods and not cpp_t.startswith("const "):
                cpp_t = f"const {cpp_t}&"
            elif cpp_t == "FString":
                cpp_t = "const FString&"
            decl = f"{cpp_t} {pname}"
            def_parts.append(decl)
            cdef = cpp_default(default, ct, self.types) if default else None
            decl_parts.append(f"{decl} = {cdef}" if cdef else decl)
        return ", ".join(decl_parts), ", ".join(def_parts), ok

    # ----------------------------------------------------------- tipos
    def _enum(self, t: CSType, cpp: str) -> str:
        values = ",\n".join(f"\t{v}" for v in t.enum_values) or "\tNone"
        return f"UENUM(BlueprintType)\nenum class {cpp} : uint8\n{{\n{values}\n}};\n"

    def _fields_block(self, t: CSType, owner_cpp: str, includes: set[str], forwards: set[str],
                      field_map: dict[str, str], statics: list[str], struct: bool = False) -> tuple[list[str], list[str]]:
        """Devuelve (líneas públicas, líneas privadas) con las propiedades."""
        public, private = [], []
        category = "Unity"
        for f in t.fields:
            category = _header_category(f, category)
            ct = self.mapper.map(f.type, f.name)
            includes |= ct.includes
            forwards |= ct.forward
            name = cpp_property_name(f.name)
            if name in RESERVED_MEMBERS and not struct:
                name = f"Unity{name}"
            field_map[f.name] = name
            default = cpp_default(f.default, ct, self.types)
            lines: list[str] = []
            if ct.note:
                lines.append(f"\t// NOTE(unity2ue): {ct.note}")
            if f.is_static:
                if "const" in f.modifiers and default is not None:
                    lines.append(f"\tstatic inline const {ct.decl.replace('TObjectPtr<', '').rstrip('>') if ct.is_object else ct.decl} {name} = {default};")
                else:
                    # Los UPROPERTY no pueden ser estáticos.
                    decl_t = ct.param if ct.is_object else ct.decl
                    lines.append(f"\tstatic {decl_t} {name};")
                    statics.append(f"{decl_t} {owner_cpp}::{name}{' = ' + default if default else ''};")
                (public if "public" in f.modifiers else private).extend(lines + [""])
                continue
            if default is None and not f.default:
                default = ZERO_INIT.get(ct.decl)
            init = f" = {default}" if default else ""
            if not default and f.default and f.default.strip() not in ("null",) and not f.default.startswith("new List"):
                lines.append(f"\t// TODO(unity2ue): valor inicial C#: {f.default}")
            if ct.uproperty:
                if f.serialized or ct.is_object or struct:
                    lines.append(f"\tUPROPERTY({_uproperty_specifiers(f, category)})" if (f.serialized or struct)
                                 else "\tUPROPERTY(Transient)")
                lines.append(f"\t{ct.decl} {name}{init};")
            else:
                lines.append(f"\t// TODO(unity2ue): tipo sin equivalente directo: {f.type} {f.name}")
            (public if (f.serialized or "public" in f.modifiers or struct) else private).extend(lines + [""])
        for p in t.properties:
            m = _AUTO_PROP.search(p.source)
            ct = self.mapper.map(p.type, p.name)
            includes |= ct.includes
            forwards |= ct.forward
            name = to_pascal(p.name)
            if m and ct.uproperty and "=>" not in p.source.split("{")[0]:
                default = cpp_default(m.group(1), ct, self.types) if m.group(1) else None
                public.append(f"\t// Propiedad automática C#: {p.source.strip().splitlines()[0]}")
                public.append("\tUPROPERTY(BlueprintReadWrite, Category = \"Unity\")" if not ct.is_object
                              else "\tUPROPERTY(Transient, BlueprintReadWrite, Category = \"Unity\")")
                public.append(f"\t{ct.decl} {name}{' = ' + default if default else ''};\n")
            else:
                public.append("\t// TODO(unity2ue): propiedad C# con lógica -> getter/setter:")
                public.append(_comment_block(p.source.strip()))
                public.append(f"\t{_by_value(ct.param)} Get{name}() const;\n")
        return public, private

    def _method_decl(self, m: CSMethod, kind: str, overrides: bool, static_class: bool) -> tuple[str, str, str | None]:
        """Devuelve (declaración, firma para la definición, nota)."""
        if kind == "component" and m.name in UNITY_MESSAGES:
            sig = UNITY_MESSAGES[m.name]
            ret, rest = sig.split(" ", 1)
            return f"\tvirtual {sig} override;", f"{ret} {{cls}}::{rest}", None
        ret_ct = self.mapper.map(m.return_type or "void")
        self._includes |= ret_ct.includes
        self._forwards |= ret_ct.forward
        note = None
        ret = _by_value(ret_ct.param)
        if m.return_type.split("<")[0] in ("IEnumerator", "IEnumerable") and m.name not in ("GetEnumerator",):
            ret = "void"
            note = "Corrutina Unity: usar FTimerHandle, FLatentActionInfo o UE5Coro."
        params_decl, params_def, ok = self._params(m.params)
        name = to_pascal(m.name)
        if name in RESERVED_MEMBERS and kind in ("component", "data_asset", "object"):
            name = f"{name}Unity"
        is_static = "static" in m.modifiers or static_class
        ufunc = ok and ret_ct.uproperty and "private" not in m.modifiers and kind != "struct"
        # UHT: un override de un UFUNCTION no puede llevar UFUNCTION(), ni puede haber sobrecargas.
        if "override" in m.modifiers or name in self._ufuncs:
            ufunc = False
        if ufunc and kind != "interface":
            self._ufuncs.add(name)
        prefix = "static " if is_static else ("virtual " if ({"virtual", "abstract", "override"} & set(m.modifiers)) else "")
        suffix = " override" if "override" in m.modifiers and overrides else ""
        lines = []
        if ufunc and kind != "interface":
            lines.append('\tUFUNCTION(BlueprintCallable, Category = "Unity")')
        if kind == "interface":
            return f"\tvirtual {ret} {name}({params_decl}) = 0;", "", note
        lines.append(f"\t{prefix}{ret} {name}({params_decl}){suffix};")
        return "\n".join(lines), f"{ret} {{cls}}::{name}({params_def})", note

    def _method_body(self, m: CSMethod, sig: str, owner: str, note: str | None) -> str:
        head = sig.replace("{cls}", owner)
        body = [head, "{", f"\t// TODO(unity2ue): traducir el cuerpo original C# de {m.name}:"]
        if note:
            body.append(f"\t// NOTE: {note}")
        body.append(_comment_block(m.body or "(vacío)"))
        if not head.startswith("void "):
            body.append("\treturn {};")
        body.append("}")
        return "\n".join(body)

    def _class(self, t: CSType, kind: str, cpp: str, plan: ScriptPlan, includes: set[str], forwards: set[str],
               cpp_defs: list[str]) -> str:
        field_map: dict[str, str] = {}
        statics: list[str] = []
        base_cls = CLASS_BASES.get(kind, "UObject")
        project_base = None
        for b in t.bases:
            bname = re.sub(r"<.*>", "", b).split(".")[-1]
            if bname in self.types and self.types[bname].kind == kind:
                project_base = self.types[bname]
                base_cls = project_base.cpp_name
                if project_base.header and project_base.header != plan.header_rel:
                    includes.add(project_base.header)
        includes.update(CLASS_INCLUDES.get(kind, []))
        public, private = self._fields_block(t, cpp, includes, forwards, field_map, statics, struct=(kind == "struct"))
        plan.field_maps[t.name] = field_map
        self._members = set(field_map.values()) | {to_pascal(p.name) for p in t.properties}
        self._ufuncs = set()
        # Miembros y métodos heredados de clases base del proyecto: UHT tampoco permite
        # ocultarlos con parámetros ni redeclarar UFUNCTION con el mismo nombre.
        base, seen = project_base, set()
        while base is not None and base.cs_type is not None and base.cpp_name not in seen:
            seen.add(base.cpp_name)
            bt = base.cs_type
            self._members |= {cpp_property_name(f.name) for f in bt.fields} | {to_pascal(p.name) for p in bt.properties}
            self._ufuncs |= {to_pascal(m.name) for m in bt.methods if not m.is_constructor}
            base = next((self.types[re.sub(r"<.*>", "", b).split(".")[-1]] for b in bt.bases
                         if re.sub(r"<.*>", "", b).split(".")[-1] in self.types), None)

        if kind == "struct":
            out = [f"USTRUCT(BlueprintType)\nstruct {cpp}\n{{\n\tGENERATED_BODY()\n"]
            out += public + private
            for m in t.methods:
                if m.is_constructor:
                    continue
                decl, sig, note = self._method_decl(m, kind, False, False)
                out.append(decl.replace('\tUFUNCTION(BlueprintCallable, Category = "Unity")\n', ""))
                cpp_defs.append(self._method_body(m, sig, cpp, note))
            out.append("};\n")
            return "\n".join(out)

        if kind == "interface":
            icpp = "I" + cpp[1:]
            out = [f"UINTERFACE(MinimalAPI, Blueprintable)\nclass {cpp} : public UInterface\n{{\n\tGENERATED_BODY()\n}};\n",
                   f"class {self.api} {icpp}\n{{\n\tGENERATED_BODY()\n\npublic:"]
            for m in t.methods:
                decl, _, _ = self._method_decl(m, kind, False, False)
                out.append(decl)
            out.append("};\n")
            return "\n".join(out)

        specs = {
            "component": 'ClassGroup = (Unity), meta = (BlueprintSpawnableComponent), Blueprintable',
            "data_asset": "BlueprintType",
            "object": "BlueprintType, Blueprintable",
            "library": "",
        }[kind]
        out = [f"UCLASS({specs})", f"class {self.api} {cpp} : public {base_cls}", "{", "\tGENERATED_BODY()", "", "public:"]
        msgs = [m for m in t.methods if kind == "component" and m.name in UNITY_MESSAGES]
        if kind == "component":
            out.append(f"\t{cpp}();\n")
            ticks = any(m.name in ("Update", "LateUpdate", "FixedUpdate", "OnTriggerStay", "OnTriggerStay2D") for m in msgs)
            cpp_defs.insert(0, f"{cpp}::{cpp}()\n{{\n\tPrimaryComponentTick.bCanEverTick = {'true' if ticks else 'false'};\n}}")
        out += public
        method_lines: list[str] = []
        msg_lines: list[str] = []
        for m in t.methods:
            if m.is_constructor:
                method_lines.append(f"\t// TODO(unity2ue): constructor C# {m.name}({m.params}) -> usar inicialización de UPROPERTY/PostInitProperties")
                continue
            if kind == "component" and m.name in UNSUPPORTED_MESSAGES:
                method_lines.append(f"\t// TODO(unity2ue): {m.name} -> {UNSUPPORTED_MESSAGES[m.name]}")
                method_lines.append(_comment_block(m.body))
                continue
            decl, sig, note = self._method_decl(m, kind, project_base is not None, kind == "library")
            (msg_lines if (kind == "component" and m.name in UNITY_MESSAGES) else method_lines).append(decl)
            if sig:
                cpp_defs.append(self._method_body(m, sig, cpp, note))
        for p in t.properties:
            if not _AUTO_PROP.search(p.source) or "=>" in p.source.split("{")[0]:
                ct = self.mapper.map(p.type, p.name)
                name = to_pascal(p.name)
                cpp_defs.append(
                    f"{_by_value(ct.param)} {cpp}::Get{name}() const\n{{\n\t// TODO(unity2ue): traducir propiedad C#:\n"
                    f"{_comment_block(p.source.strip())}\n\treturn {{}};\n}}"
                )
        if method_lines:
            out.append("")
            out += method_lines
        if msg_lines:
            out.append("\nprotected:\n\t// Mensajes de Unity (invocados por UUnityBehaviour)")
            out += msg_lines
        if private:
            out.append("\nprivate:")
            out += private
        out.append("};\n")
        cpp_defs[0:0] = statics
        return "\n".join(out)

    # ----------------------------------------------------------- fichero
    def generate(self, plan: ScriptPlan) -> tuple[str, str]:
        """Devuelve (contenido .h, contenido .cpp)."""
        includes: set[str] = set()
        forwards: set[str] = set()
        self._includes, self._forwards = includes, forwards
        sections: list[str] = []
        cpp_defs: list[str] = []
        file_types = plan.file.all_types()
        # Orden: enums, structs, interfaces, clases
        order = {"enum": 0, "struct": 1, "interface": 2}
        typed = []
        for t in file_types:
            pt = self.types.get(t.name)
            if pt is None:
                continue
            typed.append((order.get(pt.kind, 3), t, pt))
        typed.sort(key=lambda x: x[0])
        for _, t, pt in typed:
            if pt.kind == "enum":
                sections.append(self._enum(t, pt.cpp_name))
            else:
                sections.append(self._class(t, pt.kind, pt.cpp_name, plan, includes, forwards, cpp_defs))

        header_name = PurePosixPath(plan.header_rel).stem
        own_includes = sorted(i for i in includes if i and i != plan.header_rel)
        own_forwards = sorted(f for f in forwards if f not in {pt.cpp_name for _, _, pt in typed})
        h = [
            f"// Generado por unity2ue desde: {plan.unity_path}",
            f"// {STATUS_STUB}",
            "// Los métodos contienen el C# original comentado. Tradúcelos con el agente",
            "// `csharp-to-cpp` de Claude Code y cambia el estado a TRANSLATED.",
            "#pragma once",
            "",
            '#include "CoreMinimal.h"',
            *[f'#include "{i}"' for i in own_includes],
            f'#include "{header_name}.generated.h"',
            "",
        ]
        if own_forwards:
            h += [f"class {f};" for f in own_forwards] + [""]
        h += sections
        c = [
            f"// Generado por unity2ue desde: {plan.unity_path}",
            f"// {STATUS_STUB}",
            f'#include "{plan.header_rel}"',
            "",
        ]
        c += [d + "\n" for d in cpp_defs]
        return "\n".join(h).rstrip() + "\n", "\n".join(c).rstrip() + "\n"
