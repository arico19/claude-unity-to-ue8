"""Traducción por reglas de cuerpos de métodos C# (Unity) a C++ (UE 5.8).

Es la parte determinista de la traducción de scripts: cubre los patrones frecuentes de un script
de Unity (transform, Vector3/Quaternion, Mathf, listas, eventos, Instantiate/Destroy, GetComponent,
Debug.Log, Invoke...). Funciona **todo o nada por método**: si un método usa algo que las reglas no
entienden, se deja entero como TODO con el C# original (lo traducirá un agente o el paso por API) y
se anota el motivo, que sirve para medir cobertura y decidir qué regla añadir después.

Convención de espacio: el código traducido trabaja en **unidades y ejes de Unity** (metros, Y arriba),
igual que los datos serializados que vienen del proyecto, y convierte sólo al leer o escribir en el
actor de UE con los ayudantes de ``UUnityCompatLibrary`` (``UnityToUnrealLocation``, ``UnrealToUnityLocation``,
``UnityToUnrealQuat``...). Así ``speed * Time.deltaTime`` y las constantes del inspector siguen valiendo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..naming import cpp_property_name, to_pascal
from .csharp import CSMethod, CSType
from .type_map import CONTAINERS, OBJECT_TYPES, VALUE_TYPES, ProjectType, TypeMapper, _split_generic

COMPAT = "UUnityCompatLibrary"


class Unsupported(Exception):
    """Construcción que las reglas no traducen; el mensaje es el motivo (para estadísticas)."""


# ----------------------------------------------------------------------------------------------
# Tipos (se razonan en términos de C#; se convierten a C++ sólo al emitir declaraciones)
# ----------------------------------------------------------------------------------------------

NUMERIC = {"float", "int", "double", "long", "short", "byte", "uint", "Single", "Int32"}
UNITY_STATIC = {"Mathf", "Vector3", "Vector2", "Quaternion", "Time", "Debug", "Random", "AudioSource", "Camera",
                "GameObject", "Object", "SceneManager", "Color", "string", "String", "Physics", "Input",
                "PlayerPrefs", "Resources", "Application", "Screen", "Gizmos", "Graphics", "Shader", "Array",
                "Matrix4x4", "Enum", "float", "int"}
NUMERIC_CONST = {("float", "MaxValue"): "TNumericLimits<float>::Max()", ("float", "MinValue"): "TNumericLimits<float>::Lowest()",
                 ("float", "Epsilon"): "SMALL_NUMBER", ("float", "PositiveInfinity"): "TNumericLimits<float>::Max()",
                 ("float", "NegativeInfinity"): "TNumericLimits<float>::Lowest()",
                 ("int", "MaxValue"): "TNumericLimits<int32>::Max()", ("int", "MinValue"): "TNumericLimits<int32>::Min()"}
TRANSFORM_LIKE = {"Transform", "RectTransform"}


def _strip(cs: str) -> str:
    t = re.sub(r"\s+", "", cs)
    t = re.sub(r"^(global::)?(UnityEngine|System|System\.Collections\.Generic|TMPro|UnityEngine\.UI)\.", "", t)
    return t


def _element_type(cs: str) -> str | None:
    """Tipo de elemento de ``List<T>``/``T[]``/``IEnumerable<T>``."""
    t = _strip(cs)
    m = re.fullmatch(r"(.+)\[,*\]", t)
    if m:
        return m.group(1)
    m = re.fullmatch(r"([\w.]+)<(.+)>", t)
    if m and m.group(1).split(".")[-1] in CONTAINERS and CONTAINERS[m.group(1).split(".")[-1]] == "TArray":
        args = _split_generic(m.group(2))
        return args[0] if len(args) == 1 else None
    return None


@dataclass
class Ctx:
    """Lo que el traductor sabe del método y de su clase."""
    owner: CSType
    owner_kind: str  # component | data_asset | struct | enum | object | interface | library
    owner_cpp: str
    method: CSMethod
    mapper: TypeMapper
    types: dict[str, ProjectType]
    field_map: dict[str, str]  # nombre C# -> nombre C++ del campo (de la clase propia)
    params: dict[str, tuple[str, str]]  # nombre C# -> (nombre C++, tipo C#)
    delta_name: str | None = None  # Time.deltaTime dentro de Update(float DeltaTime)
    includes: set[str] = field(default_factory=set)
    locals: dict[str, str] = field(default_factory=dict)  # nombre -> tipo C#
    field_types: dict[str, str] = field(default_factory=dict)
    method_returns: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.field_types = {f.name: f.type for f in self.owner.fields}
        for p in self.owner.properties:
            self.field_types[p.name] = p.type
        for m in self.owner.methods:
            if not m.is_constructor:
                self.method_returns[m.name] = m.return_type or "void"
        base = self._project_base(self.owner)
        seen = set()
        while base is not None and base.name not in seen:
            seen.add(base.name)
            for f in base.fields:
                self.field_types.setdefault(f.name, f.type)
                self.field_map.setdefault(f.name, cpp_property_name(f.name))
            for p in base.properties:
                self.field_types.setdefault(p.name, p.type)
            for m in base.methods:
                if not m.is_constructor:
                    self.method_returns.setdefault(m.name, m.return_type or "void")
            base = self._project_base(base)

    def _project_base(self, t: CSType) -> CSType | None:
        for b in t.bases:
            name = re.sub(r"<.*>", "", b).split(".")[-1]
            pt = self.types.get(name)
            if pt is not None and pt.cs_type is not None:
                return pt.cs_type
        return None

    # --- clasificación de tipos ---------------------------------------------------------------
    def kind(self, cs: str | None) -> str:
        if not cs:
            return "unknown"
        t = _strip(cs).rstrip("?")
        if _element_type(t) is not None:
            return "array"
        base = t.split("<")[0].split(".")[-1]
        if base in ("Action", "UnityEvent", "Func"):
            return "event"
        if base in ("Vector3", "Vector2", "Vector4"):
            return "vector"
        if base == "Quaternion":
            return "quat"
        if base in ("Color", "Color32"):
            return "color"
        if base in ("string", "String"):
            return "string"
        if base == "bool" or base == "Boolean":
            return "bool"
        if base in NUMERIC:
            return "number"
        if base == "GameObject":
            return "gameobject"
        if base in TRANSFORM_LIKE:
            return "transform"
        pt = self.types.get(base)
        if pt is not None:
            return {"component": "pcomponent", "struct": "pstruct", "enum": "penum", "data_asset": "pobject",
                    "object": "pobject", "library": "plibrary", "interface": "pobject"}.get(pt.kind, "unknown")
        if base in OBJECT_TYPES:
            cls = OBJECT_TYPES[base][0]
            return "ucomponent" if cls.endswith("Component") or cls.endswith("Widget") else "uasset"
        if base in VALUE_TYPES:
            return "value"
        return "unknown"

    def cpp_local(self, cs: str) -> str:
        """Declaración C++ de una variable local del tipo C# dado."""
        k = self.kind(cs)
        if k in ("gameobject",):
            self.includes.add("GameFramework/Actor.h")
            return "AActor*"
        if k == "transform":
            self.includes.add("Components/SceneComponent.h")
            return "USceneComponent*"
        ct = self.mapper.map(cs)
        if ct.note and ("no mapeado" in ct.note or "genérico" in ct.note):
            raise Unsupported(f"tipo sin equivalente: {cs}")
        self.includes |= ct.includes
        if ct.decl.startswith(("TArray", "TMap", "TSet")):
            return ct.decl
        return ct.param

    def cpp_class(self, cs: str) -> str:
        """Nombre de clase C++ (sin puntero) para GetComponent<T>/Cast."""
        k = self.kind(cs)
        if k == "pcomponent" or k == "pobject":
            return self.types[_strip(cs).split(".")[-1]].cpp_name
        if k == "ucomponent" or k == "uasset":
            cls, inc = OBJECT_TYPES[_strip(cs).split(".")[-1]]
            self.includes.add(inc)
            return cls
        raise Unsupported(f"GetComponent de tipo {cs}")

    def member_type(self, owner_cs: str, member: str) -> str | None:
        """Tipo C# del campo/propiedad/método ``member`` de un tipo del proyecto."""
        pt = self.types.get(_strip(owner_cs).split("<")[0].split(".")[-1])
        t = pt.cs_type if pt is not None else None
        seen = set()
        while t is not None and t.name not in seen:
            seen.add(t.name)
            for f in t.fields:
                if f.name == member:
                    return f.type
            for p in t.properties:
                if p.name == member:
                    return p.type
            for m in t.methods:
                if m.name == member and not m.is_constructor:
                    return m.return_type or "void"
            if member in t.enum_values:
                return t.name
            for n in t.nested:
                if n.name == member:
                    return n.name
            t = self._project_base(t)
        return None

    def member_cpp(self, owner_cs: str, member: str) -> str:
        """Nombre C++ del miembro de un tipo del proyecto (campo, propiedad o método)."""
        pt = self.types.get(_strip(owner_cs).split("<")[0].split(".")[-1])
        t = pt.cs_type if pt is not None else None
        seen = set()
        while t is not None and t.name not in seen:
            seen.add(t.name)
            if member in t.enum_values:
                return member
            for f in t.fields:
                if f.name == member:
                    if t is self.owner:
                        return self.field_map.get(member, cpp_property_name(member))
                    return cpp_property_name(member)
            for p in t.properties:
                if p.name == member:
                    if _AUTO_PROP.search(p.source) and "=>" not in p.source.split("{")[0]:
                        return to_pascal(member)
                    return f"{getter_name(t, member)}()"
            for m in t.methods:
                if m.name == member:
                    return to_pascal(member)
            for n in t.nested:
                if n.name == member:
                    return self.types[n.name].cpp_name if n.name in self.types else n.name
            t = self._project_base(t)
        raise Unsupported(f"miembro desconocido {owner_cs}.{member}")


_AUTO_PROP = re.compile(r"\{\s*(?:(?:public|private|protected|internal)\s+)?get\s*;")


def getter_name(t: CSType, prop_name: str) -> str:
    """``GetFoo()`` para la propiedad con lógica ``Foo``; ``GetFooProperty()`` si ya hay un método ``GetFoo``."""
    name = f"Get{to_pascal(prop_name)}"
    if any(to_pascal(m.name) == name for m in t.methods if not m.is_constructor):
        return name + "Property"
    return name


def property_getter_body(source: str) -> str | None:
    """Cuerpo C# del ``get`` de una propiedad (``=> expr``, ``get => expr;`` o ``get { ... }``); None si no hay."""
    head, _, rest = source.partition("{")
    if "=>" in head:
        expr = head.split("=>", 1)[1].strip()
        return "return " + expr.rstrip(";").strip() + ";"
    m = re.search(r"\bget\s*=>\s*", source)
    if m:
        depth = 0
        for i in range(m.end(), len(source)):
            ch = source[i]
            depth += {"(": 1, ")": -1, "[": 1, "]": -1, "{": 1, "}": -1}.get(ch, 0)
            if ch == ";" and depth == 0:
                return "return " + source[m.end():i].strip() + ";"
        return None
    m = re.search(r"\bget\s*\{", source)
    if m:
        depth = 1
        for i in range(m.end(), len(source)):
            depth += {"{": 1, "}": -1}.get(source[i], 0)
            if depth == 0:
                return source[m.end():i].strip()
    return None


# ----------------------------------------------------------------------------------------------
# Tokenizador
# ----------------------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"(?P<ws>\s+)|(?P<comment>//[^\n]*|/\*.*?\*/)|(?P<str>\$?@?\"(?:\\.|\"\"|[^\"\\])*\")|(?P<chr>'(?:\\.|[^'\\])')"
    r"|(?P<num>\d+\.\d*(?:[eE][+-]?\d+)?[fFdDmM]?|\.\d+(?:[eE][+-]?\d+)?[fFdDmM]?|\d+(?:[eE][+-]?\d+)?[fFdDmMlLuU]*)"
    r"|(?P<id>@?[A-Za-z_]\w*)|(?P<op>\?\?=|\?\.|\?\[|=>|\+\+|--|&&|\|\||==|!=|<=|>=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|::|[-+*/%=<>!&|^~?:;,.(){}\[\]])",
    re.S,
)


@dataclass
class Tok:
    kind: str
    text: str


def tokenize(src: str) -> list[Tok]:
    out: list[Tok] = []
    pos = 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise Unsupported(f"carácter inesperado {src[pos]!r}")
        pos = m.end()
        kind = m.lastgroup or "op"
        if kind == "ws":
            if "\n" in m.group() and (not out or out[-1].kind != "nl"):
                out.append(Tok("nl", "\n"))
            continue
        out.append(Tok(kind, m.group()))
    return out


REJECT_WORDS = {
    "yield": "corrutina (yield)", "await": "async/await", "async": "async/await", "lock": "lock",
    "try": "try/catch", "catch": "try/catch", "finally": "try/catch", "throw": "throw",
    "goto": "goto", "unsafe": "unsafe", "fixed": "fixed", "checked": "checked",
    "is": "operador is", "as": "operador as", "typeof": "typeof", "nameof": "nameof",
    "delegate": "delegate", "event": "event", "out": "parámetro out", "ref": "parámetro ref",
    "params": "params", "using": "using", "StartCoroutine": "corrutina", "StopCoroutine": "corrutina",
    "StopAllCoroutines": "corrutina", "CancelInvoke": "CancelInvoke",
    "Resources": "Resources.Load", "Physics": "Physics", "Input": "Input", "Coroutine": "corrutina",
    "IEnumerator": "corrutina", "Dictionary": "Dictionary", "HashSet": "HashSet", "Queue": "Queue",
    "Stack": "Stack", "Func": "Func", "Gizmos": "Gizmos", "Graphics": "Graphics", "Shader": "Shader",
    "Matrix4x4": "Matrix4x4", "Enum": "Enum", "Application": "Application", "Screen": "Screen",
    "Animator": "Animator", "Rigidbody": "Rigidbody", "Rigidbody2D": "Rigidbody",
    "Array": "Array", "InvokeRepeating": "InvokeRepeating", "LeanTween": "tweening", "DOTween": "tweening",
}
PREFS = {"GetInt": ("PrefsGetInt", "int"), "SetInt": ("PrefsSetInt", "void"), "GetFloat": ("PrefsGetFloat", "float"),
         "SetFloat": ("PrefsSetFloat", "void"), "GetString": ("PrefsGetString", "string"),
         "SetString": ("PrefsSetString", "void"), "HasKey": ("PrefsHasKey", "bool"),
         "DeleteKey": ("PrefsDeleteKey", "void"), "DeleteAll": ("PrefsDeleteAll", "void"), "Save": ("PrefsSave", "void")}
LINQ = {"Select", "Where", "OrderBy", "OrderByDescending", "Any", "All", "First", "FirstOrDefault", "Last",
        "ToList", "ToArray", "Sum", "Min", "Max", "Count", "Aggregate", "Distinct", "Take", "Skip", "Reverse",
        "Find", "FindAll", "FindIndex", "Exists", "ForEach", "Sort", "TrueForAll", "RemoveAll"}
REJECT_OPS = {"??": "operador ??", "??=": "operador ??", "=>": "lambda", "?[": "operador ?[", "::": "::"}

MATHF = {
    "Max": "FMath::Max", "Min": "FMath::Min", "Abs": "FMath::Abs", "Clamp": "FMath::Clamp", "Lerp": "FMath::Lerp",
    "Sqrt": "FMath::Sqrt", "Pow": "FMath::Pow", "Sin": "FMath::Sin", "Cos": "FMath::Cos", "Tan": "FMath::Tan",
    "Atan2": "FMath::Atan2", "Atan": "FMath::Atan", "Asin": "FMath::Asin", "Acos": "FMath::Acos",
    "Floor": "FMath::FloorToFloat", "Ceil": "FMath::CeilToFloat", "Round": "FMath::RoundToFloat",
    "FloorToInt": "FMath::FloorToInt", "CeilToInt": "FMath::CeilToInt", "RoundToInt": "FMath::RoundToInt",
    "Sign": "FMath::Sign", "Exp": "FMath::Exp", "Log": "FMath::Loge", "Log10": "FMath::LogX<10.f>",
    "Approximately": "FMath::IsNearlyEqual", "MoveTowards": f"{COMPAT}::MoveTowards",
    "InverseLerp": "FMath::GetRangePct", "SmoothStep": "FMath::SmoothStep", "Repeat": "FMath::Wrap",
    "LerpAngle": None, "DeltaAngle": None, "PingPong": None, "PerlinNoise": None,
}
MATHF_CONST = {"PI": "PI", "Infinity": "TNumericLimits<float>::Max()", "NegativeInfinity": "TNumericLimits<float>::Lowest()",
               "Deg2Rad": "(PI / 180.f)", "Rad2Deg": "(180.f / PI)", "Epsilon": "SMALL_NUMBER"}
VECTOR_CONST = {"zero": "FVector::ZeroVector", "one": "FVector::OneVector", "up": "FVector(0.f, 1.f, 0.f)",
                "down": "FVector(0.f, -1.f, 0.f)", "forward": "FVector(0.f, 0.f, 1.f)", "back": "FVector(0.f, 0.f, -1.f)",
                "right": "FVector(1.f, 0.f, 0.f)", "left": "FVector(-1.f, 0.f, 0.f)"}
VECTOR2_CONST = {"zero": "FVector2D::ZeroVector", "one": "FVector2D::UnitVector", "up": "FVector2D(0.f, 1.f)",
                 "down": "FVector2D(0.f, -1.f)", "right": "FVector2D(1.f, 0.f)", "left": "FVector2D(-1.f, 0.f)"}
VECTOR_STATIC = {"Lerp": "FMath::Lerp", "Distance": "FVector::Dist", "Dot": "FVector::DotProduct",
                 "Cross": "FVector::CrossProduct", "Min": "FVector::Min", "Max": "FVector::Max",
                 "SqrMagnitude": None, "Angle": None, "Project": None, "Reflect": None, "Normalize": None}
COLOR_CONST = {"white": "FLinearColor::White", "black": "FLinearColor::Black", "red": "FLinearColor::Red",
               "green": "FLinearColor::Green", "blue": "FLinearColor::Blue", "yellow": "FLinearColor::Yellow",
               "clear": "FLinearColor::Transparent", "gray": "FLinearColor::Gray", "grey": "FLinearColor::Gray"}
ARRAY_MEMBERS = {"Count": ".Num()", "Length": ".Num()", "Clear": ".Empty", "IndexOf": ".IndexOfByKey",
                 "Add": ".Add", "Remove": ".Remove", "RemoveAt": ".RemoveAt", "Contains": ".Contains",
                 "Insert": ".Insert", "AddRange": ".Append"}
STRING_MEMBERS = {"Length": ".Len()", "ToUpper": ".ToUpper", "ToLower": ".ToLower", "Contains": ".Contains",
                  "StartsWith": ".StartsWith", "EndsWith": ".EndsWith", "Trim": ".TrimStartAndEnd",
                  "Substring": ".Mid", "Replace": ".Replace", "IsEmpty": ".IsEmpty", "ToString": ""}
VECTOR_MEMBERS = {"x": ".X", "y": ".Y", "z": ".Z", "w": ".W", "magnitude": ".Size()", "sqrMagnitude": ".SizeSquared()",
                  "normalized": ".GetSafeNormal()", "Normalize": ".Normalize"}
COLOR_MEMBERS = {"r": ".R", "g": ".G", "b": ".B", "a": ".A"}
# Mensajes de Unity cuyo parámetro de tiempo se llama distinto en UUnityBehaviour
DELTA_PARAM = {"Update": "DeltaTime", "LateUpdate": "DeltaTime", "FixedUpdate": "InFixedDeltaTime"}


# ----------------------------------------------------------------------------------------------
# Traductor
# ----------------------------------------------------------------------------------------------

class Expr:
    """Resultado de traducir una expresión: código C++ y tipo C# (si se conoce)."""

    __slots__ = ("code", "type", "setter")

    def __init__(self, code: str, type_: str | None = None, setter=None) -> None:
        self.code = code
        self.type = type_
        self.setter = setter  # callable(rhs_code) -> sentencia, para propiedades de Unity (position...)


class RuleTranslator:
    def __init__(self, ctx: Ctx) -> None:
        self.ctx = ctx
        self.toks: list[Tok] = []
        self.i = 0

    # --- utilidades de la lista de tokens -----------------------------------------------------
    def peek(self, k: int = 0) -> Tok | None:
        j = self.i + k
        # salta saltos de línea al mirar hacia delante
        while j < len(self.toks) and self.toks[j].kind == "nl":
            j += 1
            k += 1
        return self.toks[j] if j < len(self.toks) else None

    def next(self) -> Tok:
        while self.i < len(self.toks) and self.toks[self.i].kind == "nl":
            self.i += 1
        if self.i >= len(self.toks):
            raise Unsupported("fin inesperado")
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, text: str) -> None:
        t = self.next()
        if t.text != text:
            raise Unsupported(f"se esperaba {text!r} y hay {t.text!r}")

    def at(self, text: str) -> bool:
        t = self.peek()
        return t is not None and t.text == text

    def collect_until(self, closers: set[str], consume: bool = False) -> list[Tok]:
        """Tokens hasta un cierre a nivel 0 (sin incluirlo)."""
        depth = 0
        out: list[Tok] = []
        while True:
            if self.i >= len(self.toks):
                if closers & {";", "}"}:
                    return out
                raise Unsupported("fin inesperado")
            t = self.toks[self.i]
            if depth == 0 and t.text in closers:
                if consume:
                    self.i += 1
                return out
            if t.text in "([{":
                depth += 1
            elif t.text in ")]}":
                depth -= 1
                if depth < 0:
                    raise Unsupported("paréntesis desparejados")
            out.append(t)
            self.i += 1

    # --- entrada ------------------------------------------------------------------------------
    def translate(self, body: str) -> list[str]:
        self.pre_check(body)
        self.toks = [t for t in tokenize(body) if t.kind != "nl"]
        self.i = 0
        lines: list[str] = []
        while self.i < len(self.toks):
            lines += self.statement()
        return lines

    def pre_check(self, body: str) -> None:
        masked = re.sub(r"\$?@?\"(?:\\.|\"\"|[^\"\\])*\"|'(?:\\.|[^'\\])'", '""', body)
        masked = re.sub(r"//[^\n]*|/\*.*?\*/", "", masked, flags=re.S)
        for w in re.findall(r"@?\b[A-Za-z_]\w*\b", masked):
            if w in REJECT_WORDS:
                raise Unsupported(REJECT_WORDS[w])
        for op, why in REJECT_OPS.items():
            if op in masked:
                raise Unsupported(why)
        if re.search(r"\.(" + "|".join(LINQ) + r")\s*\(", masked):
            raise Unsupported("LINQ/List.Find")
        if re.search(r"\bnew\s+[\w.<>]+\s*\[", masked):
            raise Unsupported("new T[]")
        if re.search(r"\bnew\s*\{", masked):
            raise Unsupported("tipo anónimo")
        if "?." in masked and not re.fullmatch(r"(?s).*", masked):
            raise Unsupported("operador ?.")
        for m in re.finditer(r"\?\.\s*(\w+)", masked):
            if m.group(1) != "Invoke":
                raise Unsupported("operador ?.")
        if self.ctx.owner_kind in ("library", "struct", "enum", "interface", "data_asset", "object"):
            # sólo los usos "propios" (sin ``x.`` delante): ``.transform`` de otro objeto sí vale
            if re.search(r"(?<![.\w])(transform|gameObject|GetComponent|Invoke|enabled)\b", masked):
                raise Unsupported(f"API de MonoBehaviour en {self.ctx.owner_kind}")
            if "static" in self.ctx.method.modifiers and re.search(r"\b(Instantiate|Destroy)\b", masked):
                raise Unsupported("Instantiate/Destroy en método estático")

    # --- sentencias ---------------------------------------------------------------------------
    def statement(self, indent: str = "\t") -> list[str]:
        t = self.peek()
        if t is None:
            return []
        if t.kind == "comment":
            self.next()
            return [indent + t.text.replace("\n", "\n" + indent)]
        if t.text == "{":
            self.next()
            out = [indent + "{"]
            while not self.at("}"):
                out += self.statement(indent + "\t")
            self.next()
            out.append(indent + "}")
            return out
        if t.text == ";":
            self.next()
            return []
        if t.kind == "id":
            w = t.text
            if w == "if":
                self.next()
                self.expect("(")
                cond = self.expr_tokens(self.collect_until({")"}, consume=True))
                out = [f"{indent}if ({self._cond(cond)})"]
                out += self.block_or_statement(indent)
                while self.at("else"):
                    self.next()
                    if self.at("if"):
                        self.next()
                        self.expect("(")
                        cond = self.expr_tokens(self.collect_until({")"}, consume=True))
                        out.append(f"{indent}else if ({self._cond(cond)})")
                    else:
                        out.append(f"{indent}else")
                    out += self.block_or_statement(indent)
                return out
            if w == "while":
                self.next()
                self.expect("(")
                cond = self.expr_tokens(self.collect_until({")"}, consume=True))
                return [f"{indent}while ({self._cond(cond)})"] + self.block_or_statement(indent)
            if w == "do":
                raise Unsupported("do/while")
            if w == "switch":
                return self.switch_statement(indent)
            if w == "for":
                return self.for_statement(indent)
            if w == "foreach":
                return self.foreach_statement(indent)
            if w == "return":
                self.next()
                if self.at(";"):
                    self.next()
                    return [f"{indent}return;"]
                e = self.expr_tokens(self.collect_until({";"}, consume=True))
                return [f"{indent}return {self._coerce(e, self.ctx.method.return_type)};"]
            if w in ("break", "continue"):
                self.next()
                self.expect(";")
                return [f"{indent}{w};"]
            if w == "var" or self.is_declaration():
                return self.declaration(indent)
        toks = self.collect_until({";"}, consume=True)
        return [f"{indent}{self.assignment_or_expr(toks)};"]

    def _cond(self, e: Expr) -> str:
        return e.code

    def _coerce(self, e: Expr, target_cs: str | None) -> str:
        if e.code == "nullptr" or not target_cs:
            return e.code
        return e.code

    def block_or_statement(self, indent: str) -> list[str]:
        if self.at("{"):
            return self.statement(indent)
        return [indent + "{"] + self.statement(indent + "\t") + [indent + "}"]

    def is_declaration(self) -> bool:
        """``Tipo nombre =`` / ``Tipo nombre;`` / ``Tipo[] nombre`` / ``List<T> nombre``."""
        j = self.i
        n = len(self.toks)
        if j >= n or self.toks[j].kind != "id":
            return False
        j += 1
        while j < n and self.toks[j].text == "." and j + 1 < n and self.toks[j + 1].kind == "id":
            j += 2
        if j < n and self.toks[j].text == "<":
            depth = 0
            while j < n:
                if self.toks[j].text == "<":
                    depth += 1
                elif self.toks[j].text == ">":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                elif self.toks[j].text in (";", "(", ")", "=", "{"):
                    return False
                j += 1
        if j + 1 < n and self.toks[j].text == "[" and self.toks[j + 1].text == "]":
            j += 2
        if j < n and self.toks[j].text == "?":
            j += 1
        return j + 1 < n and self.toks[j].kind == "id" and self.toks[j + 1].text in ("=", ";", ",")

    def read_type(self) -> str:
        parts = [self.next().text]
        while self.at(".") and (self.peek(1) or Tok("", "")).kind == "id":
            self.next()
            parts.append("." + self.next().text)
        if self.at("<"):
            depth = 0
            while True:
                t = self.next()
                parts.append(t.text)
                if t.text == "<":
                    depth += 1
                elif t.text == ">":
                    depth -= 1
                    if depth == 0:
                        break
        if self.at("[") and (self.peek(1) or Tok("", "")).text == "]":
            self.next()
            self.next()
            parts.append("[]")
        if self.at("?"):
            self.next()
            parts.append("?")
        return "".join(parts)

    def declaration(self, indent: str) -> list[str]:
        cs_type = self.read_type()
        out: list[str] = []
        while True:
            name = self.next()
            if name.kind != "id":
                raise Unsupported("declaración rara")
            if self.at("="):
                self.next()
                rhs_toks = self.collect_until({";", ","})
                rhs = self.expr_tokens(rhs_toks, expected=None if cs_type == "var" else cs_type)
                actual = rhs.type if cs_type == "var" else cs_type
                if cs_type == "var" and actual is None:
                    raise Unsupported("var sin tipo deducible")
                self.ctx.locals[name.text] = actual or cs_type
                decl = "auto" if cs_type == "var" else self.ctx.cpp_local(cs_type)
                if cs_type == "var" and self.ctx.kind(actual) in ("array",):
                    decl = self.ctx.cpp_local(actual)  # copia de TArray: mejor explícita
                rhs_code = rhs.code
                if self.ctx.kind(cs_type) == "string" and rhs_code.startswith("TEXT("):
                    rhs_code = f"FString({rhs_code})"
                out.append(f"{indent}{decl} {name.text} = {rhs_code};")
            else:
                if cs_type == "var":
                    raise Unsupported("var sin inicializar")
                self.ctx.locals[name.text] = cs_type
                decl = self.ctx.cpp_local(cs_type)
                init = " = nullptr" if decl.endswith("*") else (" = 0" if self.ctx.kind(cs_type) in ("number",) else
                                                                 (" = false" if self.ctx.kind(cs_type) == "bool" else ""))
                out.append(f"{indent}{decl} {name.text}{init};")
            t = self.next()
            if t.text == ";":
                return out
            if t.text != ",":
                raise Unsupported("declaración rara")

    def switch_statement(self, indent: str) -> list[str]:
        """``switch (x) { case A: ... break; default: ... }`` con etiquetas constantes/enum."""
        self.next()
        self.expect("(")
        subject = self.expr_tokens(self.collect_until({")"}, consume=True))
        self.expect("{")
        out = [f"{indent}switch ({subject.code})", f"{indent}{{"]
        while not self.at("}"):
            t = self.next()
            if t.text == "case":
                label_toks = self.collect_until({":"}, consume=True)
                if any(x.text == "when" for x in label_toks):
                    raise Unsupported("case con when")
                label = self.expr_tokens(label_toks)
                out.append(f"{indent}\tcase {label.code}:")
            elif t.text == "default":
                self.expect(":")
                out.append(f"{indent}\tdefault:")
            else:
                raise Unsupported("switch con patrones")
            # sentencias hasta la siguiente etiqueta o el cierre
            while not self.at("}") and not self.at("case") and not self.at("default"):
                out += self.statement(indent + "\t\t")
        self.next()
        out.append(f"{indent}}}")
        return out

    def for_statement(self, indent: str) -> list[str]:
        self.next()
        self.expect("(")
        init_toks = self.collect_until({";"}, consume=True)
        cond_toks = self.collect_until({";"}, consume=True)
        step_toks = self.collect_until({")"}, consume=True)
        init = ""
        if init_toks:
            sub = RuleTranslator(self.ctx)
            sub.toks = init_toks + [Tok("op", ";")]
            if sub.is_declaration() or (init_toks and init_toks[0].text == "var"):
                init = sub.declaration("")[0].rstrip(";")
            else:
                init = self.assignment_or_expr(init_toks)
        cond = self.expr_tokens(cond_toks).code if cond_toks else ""
        step = self.assignment_or_expr(step_toks) if step_toks else ""
        return [f"{indent}for ({init}; {cond}; {step})"] + self.block_or_statement(indent)

    def foreach_statement(self, indent: str) -> list[str]:
        self.next()
        self.expect("(")
        cs_type = self.read_type()
        name = self.next().text
        self.expect("in")
        coll = self.expr_tokens(self.collect_until({")"}, consume=True))
        elem = _element_type(coll.type) if coll.type else None
        if cs_type == "var":
            if elem is None:
                raise Unsupported("foreach var sobre colección de tipo desconocido")
            cs_type = elem
        self.ctx.locals[name] = cs_type
        decl = self.ctx.cpp_local(cs_type)
        if not decl.endswith("*") and self.ctx.kind(cs_type) not in ("number", "bool", "penum"):
            decl = f"const {decl}&"
        return [f"{indent}for ({decl} {name} : {coll.code})"] + self.block_or_statement(indent)

    # --- expresiones --------------------------------------------------------------------------
    ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="}

    def assignment_or_expr(self, toks: list[Tok]) -> str:
        """Sentencia de expresión: asignación (con setters de Unity) o llamada."""
        depth = 0
        for k, t in enumerate(toks):
            if t.text in "([":
                depth += 1
            elif t.text in ")]":
                depth -= 1
            elif depth == 0 and t.kind == "op" and t.text in self.ASSIGN_OPS:
                lhs = self.expr_tokens(toks[:k])
                if self.ctx.kind(lhs.type) == "event":
                    return self.event_subscription(lhs, t.text, toks[k + 1:])
                rhs = self.expr_tokens(toks[k + 1:], expected=lhs.type)
                rhs_code = rhs.code
                if self.ctx.kind(lhs.type) == "string" and rhs_code.startswith("TEXT("):
                    rhs_code = f"FString({rhs_code})"
                if lhs.setter is None and lhs.code.endswith("()"):
                    raise Unsupported("asignación a propiedad con lógica")
                if lhs.setter is not None:
                    if t.text == "=":
                        return lhs.setter(rhs_code)
                    return lhs.setter(f"{lhs.code} {t.text[0]} ({rhs_code})")
                return f"{lhs.code} {t.text} {rhs_code}"
        return self.expr_tokens(toks).code

    def event_subscription(self, lhs: Expr, op: str, rhs_toks: list[Tok]) -> str:
        """``evento += Metodo`` / ``-=`` con un método propio sin parámetros -> AddDynamic/RemoveDynamic."""
        if op not in ("+=", "-=") or len(rhs_toks) != 1 or rhs_toks[0].kind != "id":
            raise Unsupported("suscripción a evento con lambda o método ajeno")
        handler = rhs_toks[0].text
        n_params = len(_split_generic(_strip(lhs.type).split("<", 1)[1][:-1])) if "<" in _strip(lhs.type) else 0
        if n_params and self.ctx.mapper.map(lhs.type).decl == "FUnityEvent":
            raise Unsupported("evento con parámetros sin delegate")
        m = next((m for m in self.ctx.owner.methods if m.name == handler and not m.is_constructor), None)
        if m is None or "static" in m.modifiers:
            raise Unsupported("manejador de evento ajeno o estático")
        if len([p for p in m.params.split(",") if p.strip()]) != n_params:
            raise Unsupported("manejador con parámetros distintos a los del evento")
        fn = "AddDynamic" if op == "+=" else "RemoveDynamic"
        return f"{lhs.code}.{fn}(this, &{self.ctx.owner_cpp}::{to_pascal(handler)})"

    def expr_tokens(self, toks: list[Tok], expected: str | None = None) -> Expr:
        sub = RuleTranslator(self.ctx)
        sub.toks = toks
        sub.i = 0
        return sub.expression(expected)

    def expression(self, expected: str | None = None) -> Expr:
        """Traduce todos los tokens restantes como una expresión (operadores pasan tal cual)."""
        parts: list[str] = []
        last_type: str | None = None
        setter = None
        types_seen: list[str | None] = []
        while self.i < len(self.toks):
            t = self.peek()
            if t is None:
                break
            if t.kind == "comment":
                self.next()
                continue
            if t.kind == "str":
                self.next()
                parts.append(self.string_literal(t.text))
                last_type = "string"
                types_seen.append("string")
            elif t.kind == "chr":
                self.next()
                parts.append("TEXT(" + t.text + ")")
                last_type = "char"
            elif t.kind == "num":
                self.next()
                parts.append(self.number(t.text))
                last_type = "float" if re.search(r"[.fFdDeE]", t.text) else "int"
                types_seen.append(last_type)
            elif t.kind == "id":
                if t.text == "new":
                    e = self.new_expr()
                elif t.text in ("true", "false"):
                    self.next()
                    e = Expr(t.text, "bool")
                elif t.text == "null":
                    self.next()
                    e = Expr("nullptr", None)
                else:
                    e = self.chain(expected)
                parts.append(e.code)
                last_type = e.type
                setter = e.setter
                types_seen.append(e.type)
            elif t.text == "(":
                # cast "(float) x" o paréntesis
                if self.is_cast():
                    self.next()
                    cs = self.read_type()
                    self.expect(")")
                    inner = self.unary(cs)
                    k = self.ctx.kind(cs)
                    if k in ("number",):
                        parts.append(f"static_cast<{self.ctx.cpp_local(cs)}>({inner.code})")
                    elif k in ("pcomponent", "ucomponent", "pobject", "uasset"):
                        parts.append(f"Cast<{self.ctx.cpp_class(cs)}>({inner.code})")
                    elif k == "penum":
                        parts.append(f"static_cast<{self.ctx.cpp_local(cs)}>({inner.code})")
                    else:
                        raise Unsupported(f"cast a {cs}")
                    last_type = cs
                    types_seen.append(cs)
                else:
                    self.next()
                    inner = self.expr_tokens(self.collect_until({")"}, consume=True))
                    code = f"({inner.code})"
                    last_type = inner.type
                    setter = None
                    # postfijos tras paréntesis: (a).x
                    e = self.postfix(Expr(code, inner.type))
                    parts.append(e.code)
                    last_type = e.type
                    types_seen.append(last_type)
            elif t.kind == "op":
                self.next()
                if t.text in ("?.",):
                    raise Unsupported("operador ?.")
                if t.text == "+" and "string" in types_seen:
                    raise Unsupported("concatenación de cadenas")
                parts.append(t.text)
                if t.text in ("?", ":"):
                    pass
            else:
                raise Unsupported(f"token {t.text!r}")
        code = self._join(parts)
        # el tipo de una expresión con operadores: el del primer operando conocido
        typ = next((x for x in types_seen if x), None) if len(types_seen) > 1 else last_type
        if len(parts) > 1:
            setter = None
            if "?" in parts and ":" in parts:
                typ = next((x for x in types_seen[1:] if x), typ)
            elif any(p in ("==", "!=", "<", ">", "<=", ">=", "&&", "||", "!") for p in parts):
                typ = "bool"
        return Expr(code, typ, setter)

    @staticmethod
    def _join(parts: list[str]) -> str:
        """Une operandos y operadores con espacios de estilo C++ (``a - b``, ``-a``, ``f(x)``, ``a[i]``)."""
        binary = {"+", "-", "*", "/", "%", "=", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "&", "|", "^",
                  "<<", ">>", "?", ":", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="}
        out = ""
        prev = ""
        for p in parts:
            if not out:
                out = p
            elif p in (",", ";", ")", "]", "++", "--"):
                out += p
            elif prev in ("(", "[") or prev in ("!", "~") or (prev in ("-", "+") and (
                    not out[:-len(prev)].rstrip() or out[:-len(prev)].rstrip()[-1] in "(,=<>!&|?:+-*/%[")):
                out += p  # tras '(' / '[' / operador unario
            elif p in ("(", "[") and (prev[-1].isalnum() or prev[-1] in ")]_>"):
                out += p
            elif p in binary or prev in binary:
                out += " " + p
            else:
                out += " " + p
            prev = p
        return out

    def is_cast(self) -> bool:
        t1, t2, t3 = self.peek(1), self.peek(2), self.peek(3)
        if t1 is None or t1.kind != "id":
            return False
        cs = t1.text
        if t2 is None or t2.text != ")":
            return False
        if cs not in NUMERIC and cs not in ("bool", "string") and cs not in self.ctx.types and cs not in OBJECT_TYPES:
            return False
        return t3 is not None and (t3.kind in ("id", "num") or t3.text == "(")

    def unary(self, _cs: str) -> Expr:
        t = self.peek()
        if t is not None and t.text == "(":
            self.next()
            inner = self.expr_tokens(self.collect_until({")"}, consume=True))
            return Expr(f"({inner.code})", inner.type)
        if t is not None and t.kind == "num":
            self.next()
            return Expr(self.number(t.text), "float")
        if t is not None and t.kind == "id":
            return self.chain(None)
        raise Unsupported("cast raro")

    def number(self, text: str) -> str:
        m = re.fullmatch(r"(\d+)[fF]", text)
        if m:
            return f"{m.group(1)}.f"
        m = re.fullmatch(r"(\d+\.\d*)[fF]", text)
        if m:
            return f"{m.group(1)}f"
        m = re.fullmatch(r"(\d+\.?\d*)[dDmM]", text)
        if m:
            return m.group(1) if "." in m.group(1) else m.group(1) + ".0"
        if re.fullmatch(r"\d+[lLuU]+", text):
            return re.sub(r"[lLuU]+$", "", text)
        return text

    def string_literal(self, text: str) -> str:
        if text.startswith("$"):
            return self.interpolated(text[1:])
        if text.startswith("@"):
            raise Unsupported("cadena literal @")
        return f"TEXT({text})"

    def interpolated(self, text: str) -> str:
        """``$"Nivel {n} de {total}"`` -> ``FString::Printf(TEXT("Nivel %d de %d"), n, total)``."""
        if text.startswith("@"):
            raise Unsupported("cadena interpolada literal $@")
        inner = text[1:-1]
        fmt: list[str] = []
        args: list[str] = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "{" and inner[i + 1:i + 2] == "{":
                fmt.append("{")
                i += 2
            elif ch == "}" and inner[i + 1:i + 2] == "}":
                fmt.append("}")
                i += 2
            elif ch == "{":
                depth, j = 1, i + 1
                while j < len(inner) and depth:
                    depth += {"{": 1, "}": -1}.get(inner[j], 0)
                    j += 1
                hole = inner[i + 1:j - 1]
                if ":" in hole or "," in hole:
                    raise Unsupported("cadena interpolada con formato")
                e = self.expr_tokens([t for t in tokenize(hole) if t.kind != "nl"])
                k = self.ctx.kind(e.type)
                if k == "string":
                    fmt.append("%s")
                    args.append(f"*({e.code})")
                elif e.type == "int":
                    fmt.append("%d")
                    args.append(e.code)
                elif k == "number":
                    fmt.append("%g")
                    args.append(f"static_cast<double>({e.code})")
                elif k == "bool":
                    fmt.append("%s")
                    args.append(f"(({e.code}) ? TEXT(\"True\") : TEXT(\"False\"))")
                else:
                    raise Unsupported(f"cadena interpolada con {e.type or 'tipo desconocido'}")
                i = j
            elif ch == "%":
                fmt.append("%%")
                i += 1
            else:
                fmt.append(ch)
                i += 1
        return f"FString::Printf(TEXT(\"{''.join(fmt)}\"), {', '.join(args)})" if args else f"TEXT(\"{''.join(fmt)}\")"

    # --- new ----------------------------------------------------------------------------------
    def new_expr(self) -> Expr:
        self.next()  # new
        cs = self.read_type()
        self.expect("(")
        args = self.args_until_close()
        k = self.ctx.kind(cs)
        base = _strip(cs).split("<")[0].split(".")[-1]
        if k == "vector":
            cpp = {"Vector3": "FVector", "Vector2": "FVector2D", "Vector4": "FVector4"}[base]
            return Expr(f"{cpp}({', '.join(self._float(a) for a in args)})" if args else f"{cpp}::ZeroVector", cs)
        if k == "quat":
            return Expr(f"FQuat({', '.join(self._float(a) for a in args)})" if args else "FQuat::Identity", cs)
        if k == "color":
            return Expr(f"FLinearColor({', '.join(self._float(a) for a in args)})", "Color")
        if k == "array":
            if args:
                raise Unsupported("new List con argumentos")
            return Expr(f"{self.ctx.cpp_local(cs)}()", cs)
        if k == "pstruct":
            return Expr(f"{self.ctx.types[base].cpp_name}({', '.join(a.code for a in args)})", cs)
        if k == "gameobject":
            if len(args) == 1 and self.ctx.kind(args[0].type) == "string":
                return Expr(f"{COMPAT}::NewGameObject(this, {args[0].code})", "GameObject")
            if not args:
                return Expr(f"{COMPAT}::NewGameObject(this, TEXT(\"GameObject\"))", "GameObject")
        if k == "pobject" and self.ctx.types[base].kind == "object":
            return Expr(f"NewObject<{self.ctx.types[base].cpp_name}>(this)", cs)
        raise Unsupported(f"new {cs}")

    @staticmethod
    def _float(a: Expr) -> str:
        return a.code

    def args_until_close(self) -> list[Expr]:
        toks = self.collect_until({")"}, consume=True)
        if not toks:
            return []
        groups: list[list[Tok]] = [[]]
        depth = 0
        for t in toks:
            if t.text in "([":
                depth += 1
            elif t.text in ")]":
                depth -= 1
            if depth == 0 and t.text == ",":
                groups.append([])
            else:
                groups[-1].append(t)
        return [self.expr_tokens(g) for g in groups]

    # --- cadenas de acceso: ident(.member | (args) | [idx])* ------------------------------------
    def chain(self, expected: str | None) -> Expr:
        t = self.next()
        name = t.text.lstrip("@")
        ctx = self.ctx
        e: Expr
        if name == "this":
            e = Expr("this", ctx.owner.name)
        elif name == "base":
            self.expect(".")
            m = self.next().text
            e = Expr(f"Super::{to_pascal(m)}", ctx.method_returns.get(m))
        elif name in ("transform", "gameObject") and ctx.owner_kind == "component":
            if name == "transform" and self.at(".") and (self.peek(1) or Tok("", "")).text == "gameObject":
                self.next()
                self.next()
                e = Expr("GetOwner()", "GameObject")
            elif name == "transform":
                e = Expr("GetOwner()->GetRootComponent()", "Transform")
            else:
                e = Expr("GetOwner()", "GameObject")
        elif name == "enabled" and ctx.owner_kind == "component":
            e = Expr("IsEnabled()", "bool", setter=lambda rhs: f"SetEnabled({rhs})")
        elif name == "name" and ctx.owner_kind == "component":
            e = Expr("GetOwner()->GetName()", "string")
        elif name in ctx.locals:
            e = Expr(name, ctx.locals[name])
        elif name in ctx.params:
            cpp, cs = ctx.params[name]
            e = Expr(cpp, cs)
        elif name in ctx.field_types:
            e = Expr(ctx.member_cpp(ctx.owner.name, name), ctx.field_types[name])
        elif name in ctx.method_returns or name in ("Invoke", "Instantiate", "Destroy", "GetComponent",
                                                     "GetComponents", "GetComponentInChildren", "print"):
            e = self.own_call(name)
        elif name in ctx.types:
            e = self.project_static(name)
        elif name in UNITY_STATIC:
            e = self.unity_static(name)
        else:
            raise Unsupported(f"identificador desconocido: {name}")
        return self.postfix(e)

    def postfix(self, e: Expr) -> Expr:
        while True:
            t = self.peek()
            if t is None:
                return e
            if t.text == ".":
                self.next()
                member = self.next().text
                e = self.member(e, member)
            elif t.text == "?.":
                self.next()
                member = self.next().text
                if member != "Invoke" or self.ctx.kind(e.type) != "event":
                    raise Unsupported("operador ?.")
                e = self.member(e, member)
            elif t.text == "[":
                self.next()
                idx = self.expr_tokens(self.collect_until({"]"}, consume=True))
                k = self.ctx.kind(e.type)
                if k != "array":
                    raise Unsupported(f"indexación de {e.type}")
                e = Expr(f"{e.code}[{idx.code}]", _element_type(e.type))
            elif t.text in ("++", "--"):
                self.next()
                e = Expr(f"{e.code}{t.text}", e.type)
            else:
                return e

    def call_args(self) -> list[Expr]:
        self.expect("(")
        return self.args_until_close()

    def generic_arg(self) -> str:
        self.expect("<")
        cs = self.read_type()
        self.expect(">")
        return cs

    # --- llamadas a métodos propios y a la API de MonoBehaviour --------------------------------
    def own_call(self, name: str) -> Expr:
        ctx = self.ctx
        if name == "Invoke":
            args = self.call_args()
            if len(args) != 2 or not args[0].code.startswith("TEXT("):
                raise Unsupported("Invoke con argumentos raros")
            method = args[0].code[6:-2]
            return Expr(f"InvokeAfter({args[1].code}, [this]() {{ {to_pascal(method)}(); }})", "void")
        if name == "GetComponent":
            cs = self.generic_arg()
            self.call_args()
            return Expr(f"GetComponent<{ctx.cpp_class(cs)}>()", cs)
        if name == "GetComponentInChildren":
            cs = self.generic_arg()
            self.call_args()
            return Expr(f"GetComponent<{ctx.cpp_class(cs)}>()", cs)
        if name in ("GetComponents", "GetComponentsInChildren"):
            cs = self.generic_arg()
            self.call_args()
            return Expr(f"GetComponents<{ctx.cpp_class(cs)}>()", f"List<{cs}>")
        if name == "Instantiate":
            return self.instantiate(self.call_args())
        if name == "Destroy":
            return self.destroy(self.call_args())
        if name == "print":
            return self.debug_log("Log", self.call_args())
        if not self.at("("):
            raise Unsupported(f"referencia a método {name} sin llamar")
        args = self.call_args()
        cpp = to_pascal(name)
        return Expr(f"{cpp}({', '.join(a.code for a in args)})", ctx.method_returns.get(name, "void"))

    def _parent_actor(self, e: Expr) -> str:
        k = self.ctx.kind(e.type)
        if k == "gameobject":
            return e.code
        if k == "transform":
            return f"{e.code}->GetOwner()"
        raise Unsupported("Instantiate con padre que no es Transform")

    def instantiate(self, args: list[Expr]) -> Expr:
        if not args:
            raise Unsupported("Instantiate sin argumentos")
        prefab = args[0]
        pk = self.ctx.kind(prefab.type)
        fn = "Instantiate(" if self.ctx.owner_kind == "component" else f"{COMPAT}::InstantiatePrefab(this, "
        if len(args) == 1:
            call = f"{fn}{prefab.code}, FVector::ZeroVector, FRotator::ZeroRotator)"
        elif len(args) == 2:
            call = f"{COMPAT}::InstantiatePrefab(this, {prefab.code}, FVector::ZeroVector, FRotator::ZeroRotator, {self._parent_actor(args[1])})"
        elif len(args) in (3, 4) and self.ctx.kind(args[1].type) == "vector" and self.ctx.kind(args[2].type) == "quat":
            parent = f", {self._parent_actor(args[3])}" if len(args) == 4 else ""
            fn = fn if not parent else f"{COMPAT}::InstantiatePrefab(this, "
            call = (f"{fn}{prefab.code}, {COMPAT}::UnityToUnrealLocation({args[1].code}), "
                    f"{COMPAT}::UnityToUnrealQuat({args[2].code}).Rotator(){parent})")
        else:
            raise Unsupported("Instantiate con otros argumentos")
        if pk in ("pcomponent", "ucomponent"):
            cls = self.ctx.cpp_class(prefab.type)
            return Expr(f"{call}->FindComponentByClass<{cls}>()", prefab.type)
        if pk in ("gameobject", "transform", "unknown"):
            return Expr(call, "GameObject")
        raise Unsupported(f"Instantiate de {prefab.type}")

    def destroy(self, args: list[Expr]) -> Expr:
        if not args:
            raise Unsupported("Destroy sin argumentos")
        target = args[0]
        k = self.ctx.kind(target.type)
        delay = f", {args[1].code}" if len(args) > 1 else ""
        if k == "gameobject":
            if self.ctx.owner_kind == "component":
                return Expr(f"DestroyActor({target.code}{delay})", "void")
            if delay:
                return Expr(f"{target.code}->SetLifeSpan({args[1].code})", "void")
            return Expr(f"{target.code}->Destroy()", "void")
        if k in ("pcomponent", "ucomponent") and not delay:
            return Expr(f"{target.code}->DestroyComponent()", "void")
        raise Unsupported(f"Destroy de {target.type}")

    def debug_log(self, level: str, args: list[Expr]) -> Expr:
        if len(args) == 2 and args[1].code in ("this", "GetOwner()"):
            args = args[:1]
        if len(args) != 1:
            raise Unsupported("Debug.Log con contexto")
        a = args[0]
        macro = {"Log": "UNITY_LOG", "Warning": "UNITY_LOG_WARNING", "Error": "UNITY_LOG_ERROR"}[level]
        if a.code.startswith("TEXT(") and a.code.endswith(")"):
            lit = a.code[5:-1].replace("%", "%%")
            return Expr(f"{macro}({lit})", "void")
        if self.ctx.kind(a.type) == "string":
            return Expr(f'{macro}("%s", *({a.code}))', "void")
        raise Unsupported("Debug.Log de algo que no es cadena")

    # --- clases estáticas del proyecto --------------------------------------------------------
    def project_static(self, name: str) -> Expr:
        pt = self.ctx.types[name]
        if not self.at("."):
            raise Unsupported(f"tipo {name} usado como valor")
        self.next()
        member = self.next().text
        mtype = self.ctx.member_type(name, member)
        if pt.kind == "enum":
            return Expr(f"{pt.cpp_name}::{member}", name)
        cpp_member = self.ctx.member_cpp(name, member)
        if mtype is None:
            raise Unsupported(f"miembro estático desconocido {name}.{member}")
        if self.at("("):
            args = self.call_args()
            return Expr(f"{pt.cpp_name}::{cpp_member}({', '.join(a.code for a in args)})", mtype)
        if member in (pt.cs_type.enum_values if pt.cs_type else []):
            return Expr(f"{pt.cpp_name}::{member}", name)
        nested = self.ctx.types.get(mtype) if mtype == member else None
        if nested is not None and nested.kind == "enum":
            # Clase.EnumAnidado.Valor
            self.expect(".")
            value = self.next().text
            return Expr(f"{nested.cpp_name}::{value}", mtype)
        return Expr(f"{pt.cpp_name}::{cpp_member}", mtype)

    # --- API estática de Unity ----------------------------------------------------------------
    def unity_static(self, name: str) -> Expr:
        ctx = self.ctx
        self.expect(".")
        member = self.next().text
        if name in ("float", "int"):
            if (name, member) in NUMERIC_CONST:
                return Expr(NUMERIC_CONST[(name, member)], name)
            raise Unsupported(f"{name}.{member}")
        if name == "Mathf":
            if member in MATHF_CONST:
                return Expr(MATHF_CONST[member], "float")
            fn = MATHF.get(member)
            if fn is None:
                raise Unsupported(f"Mathf.{member}")
            args = self.call_args()
            if member == "Clamp01":
                return Expr(f"FMath::Clamp({args[0].code}, 0.f, 1.f)", "float")
            if member == "Approximately":
                return Expr(f"FMath::IsNearlyEqual({args[0].code}, {args[1].code})", "bool")
            if member == "Repeat":
                return Expr(f"FMath::Wrap({args[0].code}, 0.f, {args[1].code})", "float")
            ret = "int" if member.endswith("ToInt") else ("bool" if member == "Approximately" else "float")
            if member in ("Max", "Min", "Abs", "Clamp", "Sign") and all(a.type == "int" for a in args):
                ret = "int"
            return Expr(f"{fn}({', '.join(a.code for a in args)})", ret)
        if name in ("Vector3", "Vector2"):
            consts = VECTOR_CONST if name == "Vector3" else VECTOR2_CONST
            if member in consts:
                return Expr(consts[member], name)
            if member == "MoveTowards":
                args = self.call_args()
                return Expr(f"FMath::VInterpConstantTo({args[0].code}, {args[1].code}, 1.f, {args[2].code})", name)
            if member == "Angle":
                args = self.call_args()
                return Expr(f"FMath::RadiansToDegrees(FMath::Acos(FVector::DotProduct({args[0].code}.GetSafeNormal(), "
                            f"{args[1].code}.GetSafeNormal())))", "float")
            fn = VECTOR_STATIC.get(member)
            if fn is None:
                raise Unsupported(f"{name}.{member}")
            args = self.call_args()
            if name == "Vector2":
                fn = fn.replace("FVector::", "FVector2D::")
            ret = "float" if member in ("Distance", "Dot") else name
            return Expr(f"{fn}({', '.join(a.code for a in args)})", ret)
        if name == "Quaternion":
            if member == "identity":
                return Expr("FQuat::Identity", "Quaternion")
            args = self.call_args() if self.at("(") else None
            if args is None:
                raise Unsupported(f"Quaternion.{member}")
            if member in ("Lerp", "Slerp"):
                return Expr(f"FQuat::Slerp({args[0].code}, {args[1].code}, {args[2].code})", "Quaternion")
            if member == "LookRotation" and len(args) == 1:
                return Expr(f"{COMPAT}::LookRotation({args[0].code})", "Quaternion")
            if member == "LookRotation" and len(args) == 2:
                return Expr(f"{COMPAT}::LookRotation({args[0].code}, {args[1].code})", "Quaternion")
            if member == "AngleAxis":
                return Expr(f"FQuat(({args[1].code}).GetSafeNormal(), FMath::DegreesToRadians({args[0].code}))", "Quaternion")
            if member == "Inverse":
                return Expr(f"({args[0].code}).Inverse()", "Quaternion")
            if member == "Angle":
                return Expr(f"FMath::RadiansToDegrees(({args[0].code}).AngularDistance({args[1].code}))", "float")
            raise Unsupported(f"Quaternion.{member}")
        if name == "Time":
            if member == "deltaTime":
                if ctx.delta_name:
                    return Expr(ctx.delta_name, "float")
                if ctx.owner_kind == "component":
                    return Expr("GetWorld()->GetDeltaSeconds()", "float")
                raise Unsupported("Time.deltaTime fuera de un componente")
            if member == "fixedDeltaTime" and ctx.owner_kind == "component":
                return Expr(ctx.delta_name or "GetWorld()->GetDeltaSeconds()", "float")
            if member == "time" and ctx.owner_kind == "component":
                return Expr(f"{COMPAT}::GetTime(this)", "float")
            raise Unsupported(f"Time.{member}")
        if name == "Debug":
            if member in ("Log", "LogWarning", "LogError"):
                return self.debug_log(member[3:] or "Log", self.call_args())
            raise Unsupported(f"Debug.{member}")
        if name == "Random":
            if member == "value":
                return Expr("FMath::FRand()", "float")
            if member == "Range":
                args = self.call_args()
                if all(a.type == "int" for a in args):
                    return Expr(f"{COMPAT}::RandomRangeInt({args[0].code}, {args[1].code})", "int")
                return Expr(f"{COMPAT}::RandomRange({args[0].code}, {args[1].code})", "float")
            raise Unsupported(f"Random.{member}")
        if name == "AudioSource" and member == "PlayClipAtPoint":
            args = self.call_args()
            if len(args) < 2:
                raise Unsupported("PlayClipAtPoint")
            ctx.includes.add("Kismet/GameplayStatics.h")
            vol = f", {args[2].code}" if len(args) > 2 else ""
            return Expr(f"UGameplayStatics::PlaySoundAtLocation(this, {args[0].code}, "
                        f"{COMPAT}::UnityToUnrealLocation({args[1].code}){vol})", "void")
        if name == "Color":
            if member in COLOR_CONST:
                return Expr(COLOR_CONST[member], "Color")
            if member == "Lerp":
                args = self.call_args()
                return Expr(f"FLinearColor::LerpUsingHSV({args[0].code}, {args[1].code}, {args[2].code})", "Color")
            raise Unsupported(f"Color.{member}")
        if name in ("string", "String"):
            if member == "IsNullOrEmpty":
                args = self.call_args()
                return Expr(f"({args[0].code}).IsEmpty()", "bool")
            if member == "Empty":
                return Expr("FString()", "string")
            raise Unsupported(f"string.{member}")
        if name in ("GameObject", "Object"):
            if member == "Find":
                args = self.call_args()
                return Expr(f"{COMPAT}::FindByName(this, {args[0].code})", "GameObject")
            if member == "FindWithTag" or member == "FindGameObjectWithTag":
                args = self.call_args()
                return Expr(f"{COMPAT}::FindWithTag(this, FName({args[0].code}))", "GameObject")
            if member == "FindGameObjectsWithTag":
                args = self.call_args()
                return Expr(f"{COMPAT}::FindGameObjectsWithTag(this, FName({args[0].code}))", "List<GameObject>")
            if member == "Destroy":
                return self.destroy(self.call_args())
            if member == "Instantiate":
                return self.instantiate(self.call_args())
            raise Unsupported(f"{name}.{member}")
        if name == "SceneManager" and member == "LoadScene":
            args = self.call_args()
            if self.ctx.kind(args[0].type) != "string":
                raise Unsupported("LoadScene por índice")
            return Expr(f"{COMPAT}::LoadScene(this, FName(*({args[0].code})))", "void")
        if name == "Camera" and member == "main":
            return Expr(f"{COMPAT}::GetMainCamera(this)", "Camera")
        if name == "PlayerPrefs":
            if member not in PREFS:
                raise Unsupported(f"PlayerPrefs.{member}")
            fn, ret = PREFS[member]
            args = self.call_args()
            return Expr(f"{COMPAT}::{fn}({', '.join(a.code for a in args)})", ret)
        raise Unsupported(f"{name}.{member}")

    # --- miembros de instancias ---------------------------------------------------------------
    def member(self, e: Expr, member: str) -> Expr:
        ctx = self.ctx
        k = ctx.kind(e.type)
        code = e.code
        if k == "transform":
            return self.transform_member(e, member)
        if k == "gameobject":
            if member == "transform":
                return Expr(f"{code}->GetRootComponent()", "Transform")
            if member == "gameObject":
                return e
            if member == "SetActive":
                args = self.call_args()
                return Expr(f"{COMPAT}::SetActive({code}, {args[0].code})", "void")
            if member == "activeSelf" or member == "activeInHierarchy":
                return Expr(f"!{code}->IsHidden()", "bool")
            if member == "name":
                return Expr(f"{code}->GetName()", "string")
            if member in ("GetComponent", "GetComponentInChildren"):
                cs = self.generic_arg()
                self.call_args()
                return Expr(f"{code}->FindComponentByClass<{ctx.cpp_class(cs)}>()", cs)
            if member == "AddComponent":
                cs = self.generic_arg()
                self.call_args()
                return Expr(f"{COMPAT}::AddComponent<{ctx.cpp_class(cs)}>({code})", cs)
            if member == "tag":
                return Expr(f"({code}->Tags.Num() ? {code}->Tags[0].ToString() : FString())", "string")
            if member == "CompareTag":
                args = self.call_args()
                return Expr(f"{code}->ActorHasTag(FName({args[0].code}))", "bool")
            raise Unsupported(f"GameObject.{member}")
        if k in ("pcomponent", "ucomponent", "pobject", "uasset"):
            if member in ("transform", "gameObject") and k in ("pcomponent", "ucomponent"):
                owner = Expr(f"{code}->GetOwner()", "GameObject")
                return owner if member == "gameObject" else Expr(f"{code}->GetOwner()->GetRootComponent()", "Transform")
            if member == "enabled" and k == "pcomponent":
                return Expr(f"{code}->IsEnabled()", "bool", setter=lambda rhs: f"{code}->SetEnabled({rhs})")
            if member == "enabled" and k == "ucomponent":
                return Expr(f"{code}->IsActive()", "bool", setter=lambda rhs: f"{code}->SetActive({rhs})")
            if member == "name":
                return Expr(f"{code}->GetName()", "string")
            if k in ("pcomponent", "pobject"):
                mtype = ctx.member_type(e.type, member)
                if mtype is None:
                    raise Unsupported(f"miembro {e.type}.{member}")
                cpp_member = ctx.member_cpp(e.type, member)
                if self.at("("):
                    args = self.call_args()
                    return Expr(f"{code}->{cpp_member}({', '.join(a.code for a in args)})", mtype)
                return Expr(f"{code}->{cpp_member}", mtype)
            return self.unity_component_member(e, member)
        if k == "vector":
            if member in VECTOR_MEMBERS:
                m = VECTOR_MEMBERS[member]
                if member == "Normalize":
                    self.call_args()
                    return Expr(f"{code}.Normalize()", "void")
                return Expr(f"{code}{m}", "float" if member in "xyzw" or member in ("magnitude", "sqrMagnitude") else e.type)
            raise Unsupported(f"Vector.{member}")
        if k == "quat":
            if member == "eulerAngles":
                raise Unsupported("Quaternion.eulerAngles")
            if member in ("x", "y", "z", "w"):
                return Expr(f"{code}.{member.upper()}", "float")
            raise Unsupported(f"Quaternion.{member}")
        if k == "color":
            if member in COLOR_MEMBERS:
                return Expr(f"{code}{COLOR_MEMBERS[member]}", "float")
            raise Unsupported(f"Color.{member}")
        if k == "array":
            if member in ARRAY_MEMBERS:
                m = ARRAY_MEMBERS[member]
                if m.endswith(")"):
                    return Expr(f"{code}{m}", "int")
                args = self.call_args()
                ret = {"IndexOf": "int", "Contains": "bool"}.get(member, "void")
                return Expr(f"{code}{m}({', '.join(a.code for a in args)})", ret)
            raise Unsupported(f"List.{member}")
        if k == "string":
            if member in STRING_MEMBERS:
                m = STRING_MEMBERS[member]
                if m.endswith(")"):
                    return Expr(f"{code}{m}", "int")
                if member == "ToString":
                    self.call_args()
                    return e
                args = self.call_args()
                ret = {"Contains": "bool", "StartsWith": "bool", "EndsWith": "bool", "IsEmpty": "bool"}.get(member, "string")
                return Expr(f"{code}{m}({', '.join(a.code for a in args)})", ret)
            raise Unsupported(f"string.{member}")
        if k in ("number", "bool"):
            if member == "ToString":
                self.call_args()
                return Expr(f"LexToString({code})", "string")
            raise Unsupported(f"{e.type}.{member}")
        if k == "penum":
            if member == "ToString":
                self.call_args()
                raise Unsupported("enum.ToString")
            raise Unsupported(f"enum.{member}")
        if k == "pstruct":
            mtype = ctx.member_type(e.type, member)
            if mtype is None:
                raise Unsupported(f"miembro {e.type}.{member}")
            cpp_member = ctx.member_cpp(e.type, member)
            if self.at("("):
                args = self.call_args()
                return Expr(f"{code}.{cpp_member}({', '.join(a.code for a in args)})", mtype)
            return Expr(f"{code}.{cpp_member}", mtype)
        if k == "event":
            if member == "Invoke":
                args = self.call_args()
                n_params = len(_split_generic(_strip(e.type).split("<", 1)[1][:-1])) if "<" in _strip(e.type) else 0
                if len(args) != n_params:
                    raise Unsupported("Invoke con un número de argumentos distinto al del evento")
                if n_params and self.ctx.mapper.map(e.type).decl == "FUnityEvent":
                    raise Unsupported("evento con parámetros sin delegate")
                return Expr(f"{code}.Broadcast({', '.join(a.code for a in args)})", "void")
            raise Unsupported(f"evento.{member}")
        if k == "plibrary":
            raise Unsupported("clase estática como valor")
        raise Unsupported(f"miembro .{member} de tipo {e.type or 'desconocido'}")

    def transform_member(self, e: Expr, member: str) -> Expr:
        code = e.code
        if member == "position":
            return Expr(f"{COMPAT}::UnrealToUnityLocation({code}->GetComponentLocation())", "Vector3",
                        setter=lambda rhs: f"{code}->SetWorldLocation({COMPAT}::UnityToUnrealLocation({rhs}))")
        if member == "localPosition":
            return Expr(f"{COMPAT}::UnrealToUnityLocation({code}->GetRelativeLocation())", "Vector3",
                        setter=lambda rhs: f"{code}->SetRelativeLocation({COMPAT}::UnityToUnrealLocation({rhs}))")
        if member == "rotation":
            return Expr(f"{COMPAT}::UnrealToUnityQuat({code}->GetComponentQuat())", "Quaternion",
                        setter=lambda rhs: f"{code}->SetWorldRotation({COMPAT}::UnityToUnrealQuat({rhs}))")
        if member == "localRotation":
            return Expr(f"{COMPAT}::UnrealToUnityQuat({code}->GetRelativeRotation().Quaternion())", "Quaternion",
                        setter=lambda rhs: f"{code}->SetRelativeRotation({COMPAT}::UnityToUnrealQuat({rhs}))")
        if member == "localScale":
            return Expr(f"{COMPAT}::UnrealToUnityScale({code}->GetRelativeScale3D())", "Vector3",
                        setter=lambda rhs: f"{code}->SetRelativeScale3D({COMPAT}::UnityToUnrealScale({rhs}))")
        if member in ("forward", "up", "right"):
            fn = {"forward": "GetForwardVector", "up": "GetUpVector", "right": "GetRightVector"}[member]
            return Expr(f"{COMPAT}::UnrealToUnityDirection({code}->{fn}())", "Vector3")
        if member == "gameObject":
            return Expr(f"{code}->GetOwner()", "GameObject")
        if member == "transform":
            return e
        if member == "parent":
            return Expr(f"{code}->GetAttachParent()", "Transform")
        if member == "name":
            return Expr(f"{code}->GetOwner()->GetName()", "string")
        if member == "SetParent":
            args = self.call_args()
            if self.ctx.kind(args[0].type) != "transform":
                raise Unsupported("SetParent con algo que no es Transform")
            rules = "KeepRelativeTransform" if len(args) > 1 and args[1].code == "false" else "KeepWorldTransform"
            return Expr(f"{code}->AttachToComponent({args[0].code}, FAttachmentTransformRules::{rules})", "void")
        if member == "Translate":
            args = self.call_args()
            if len(args) != 1:
                raise Unsupported("Translate con Space")
            return Expr(f"{code}->AddLocalOffset({COMPAT}::UnityToUnrealLocation({args[0].code}))", "void")
        if member == "Rotate":
            args = self.call_args()
            if len(args) == 2:
                return Expr(f"{code}->AddLocalRotation({COMPAT}::UnityToUnrealQuat(FQuat(({args[0].code}).GetSafeNormal(), "
                            f"FMath::DegreesToRadians({args[1].code}))))", "void")
            raise Unsupported("Rotate con euler")
        if member == "LookAt":
            args = self.call_args()
            if len(args) != 1 or self.ctx.kind(args[0].type) not in ("transform", "vector"):
                raise Unsupported("LookAt raro")
            target = (f"{args[0].code}->GetComponentLocation()" if self.ctx.kind(args[0].type) == "transform"
                      else f"{COMPAT}::UnityToUnrealLocation({args[0].code})")
            self.ctx.includes.add("Kismet/KismetMathLibrary.h")
            return Expr(f"{code}->SetWorldRotation(UKismetMathLibrary::FindLookAtRotation({code}->GetComponentLocation(), {target}))", "void")
        if member in ("GetComponent", "GetComponentInChildren"):
            cs = self.generic_arg()
            self.call_args()
            return Expr(f"{code}->GetOwner()->FindComponentByClass<{self.ctx.cpp_class(cs)}>()", cs)
        if member == "childCount":
            return Expr(f"{code}->GetNumChildrenComponents()", "int")
        if member == "GetChild":
            args = self.call_args()
            return Expr(f"{code}->GetChildComponent({args[0].code})", "Transform")
        raise Unsupported(f"Transform.{member}")

    def unity_component_member(self, e: Expr, member: str) -> Expr:
        base = _strip(e.type).split(".")[-1]
        code = e.code
        if base == "AudioSource":
            if member in ("Play", "Stop"):
                self.call_args()
                return Expr(f"{code}->{member}()", "void")
            if member == "PlayOneShot":
                args = self.call_args()
                return Expr(f"{code}->SetSound({args[0].code}); {code}->Play()", "void")
            if member == "clip":
                return Expr(f"{code}->Sound", "AudioClip", setter=lambda rhs: f"{code}->SetSound({rhs})")
            if member == "volume":
                return Expr(f"{code}->VolumeMultiplier", "float", setter=lambda rhs: f"{code}->SetVolumeMultiplier({rhs})")
            if member == "isPlaying":
                return Expr(f"{code}->IsPlaying()", "bool")
        if base == "ParticleSystem":
            if member == "Play":
                self.call_args()
                return Expr(f"{code}->Activate(true)", "void")
            if member == "Stop":
                self.call_args()
                return Expr(f"{code}->Deactivate()", "void")
        if base in ("Text", "TMP_Text", "TextMeshProUGUI", "TextMeshPro") and member == "text":
            return Expr(f"{code}->GetText().ToString()", "string",
                        setter=lambda rhs: f"{code}->SetText(FText::FromString({rhs}))")
        if base in ("Image", "RawImage") and member == "color":
            return Expr(f"{code}->GetColorAndOpacity()", "Color", setter=lambda rhs: f"{code}->SetColorAndOpacity({rhs})")
        if base in ("Image", "RawImage") and member == "fillAmount":
            raise Unsupported("Image.fillAmount")
        if base in ("MeshRenderer", "Renderer", "SkinnedMeshRenderer") and member == "enabled":
            return Expr(f"{code}->IsVisible()", "bool", setter=lambda rhs: f"{code}->SetVisibility({rhs})")
        if base in ("Collider", "BoxCollider", "SphereCollider", "CapsuleCollider") and member == "enabled":
            return Expr(f"{code}->IsCollisionEnabled()", "bool",
                        setter=lambda rhs: f"{code}->SetCollisionEnabled(({rhs}) ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision)")
        if base == "Camera" and member == "transform":
            return Expr(f"{code}->GetRootComponent()", "Transform")
        raise Unsupported(f"{base}.{member}")


# ----------------------------------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------------------------------

@dataclass
class RuleResult:
    lines: list[str] | None
    reason: str | None
    includes: set[str]

    @property
    def ok(self) -> bool:
        return self.lines is not None


def translate_property(owner: CSType, owner_kind: str, owner_cpp: str, prop, mapper: TypeMapper,
                       types: dict[str, ProjectType], field_map: dict[str, str]) -> RuleResult:
    """Traduce el ``get`` de una propiedad con lógica como si fuera un método sin parámetros."""
    body = property_getter_body(prop.source)
    if body is None:
        return RuleResult(None, "propiedad sin get", set())
    fake = CSMethod(prop.name, prop.type, "", ["static"] if "static" in prop.source.split("{")[0].split() else [],
                    [], body)
    return translate_method(owner, owner_kind, owner_cpp, fake, mapper, types, field_map, {})


def translate_method(owner: CSType, owner_kind: str, owner_cpp: str, method: CSMethod, mapper: TypeMapper,
                     types: dict[str, ProjectType], field_map: dict[str, str],
                     params: dict[str, tuple[str, str]]) -> RuleResult:
    """Traduce el cuerpo de ``method``; ``lines`` es None (con ``reason``) si las reglas no lo cubren."""
    if method.is_constructor:
        return RuleResult(None, "constructor", set())
    if method.return_type.split("<")[0] in ("IEnumerator", "IEnumerable"):
        return RuleResult(None, "corrutina", set())
    body = method.body
    if method.expression_bodied and (method.return_type or "void") == "void" and body.lstrip().startswith("return "):
        body = body.lstrip()[len("return "):]  # ``void Foo() => Bar();`` -> ``Bar();``
    ctx = Ctx(owner, owner_kind, owner_cpp, method, mapper, types, dict(field_map), params,
              delta_name=DELTA_PARAM.get(method.name) if owner_kind == "component" else None)
    try:
        lines = RuleTranslator(ctx).translate(body)
    except Unsupported as e:
        return RuleResult(None, str(e), set())
    except (IndexError, KeyError, ValueError, AttributeError) as e:  # defensa: nunca romper la generación
        return RuleResult(None, f"error interno del traductor: {type(e).__name__}", set())
    return RuleResult(lines, None, ctx.includes)
