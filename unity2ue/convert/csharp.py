"""Parser ligero de C# orientado a scripts de Unity.

No es un compilador: extrae la *estructura* (tipos, campos serializados, métodos y sus
cuerpos) para generar esqueletos C++ de UE y dar a los agentes de Claude el contexto
necesario para la traducción completa del cuerpo de cada método.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TYPE_KEYWORDS = ("class", "struct", "enum", "interface", "record")
MODIFIERS = {
    "public", "private", "protected", "internal", "static", "readonly", "const", "new", "volatile",
    "override", "virtual", "abstract", "sealed", "extern", "unsafe", "partial", "async", "event",
}

_TYPE_DECL = re.compile(
    r"(?P<mods>(?:\b(?:public|private|protected|internal|static|abstract|sealed|partial|readonly|unsafe|new)\s+)*)"
    r"\b(?P<kind>class|struct|enum|interface|record)\s+(?P<name>\w+)\s*(?P<generic><[^>{]*>)?"
    r"(?:\s*:\s*(?P<bases>[^{]+?))?\s*(?:where\s+[^{]+)?\{",
)
_ATTR_BLOCK = re.compile(r"^\s*(\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]\s*)+")
_ATTR_NAMES = re.compile(r"\[\s*([^\]]*)\]")
_FIELD_DECL = re.compile(r"^(?P<mods>(?:(?:" + "|".join(sorted(MODIFIERS)) + r")\s+)*)(?P<type>.+?)\s+"
                         r"(?P<names>@?\w+(?:\s*,\s*@?\w+)*)$", re.S)
_METHOD_DECL = re.compile(r"^(?P<mods>(?:(?:" + "|".join(sorted(MODIFIERS)) + r")\s+)*)"
                          r"(?:(?P<ret>[\w.<>\[\],\s?]+?)\s+)?(?P<name>~?\w+)\s*(?:<[^>()]*>)?\s*\((?P<params>.*)\)\s*"
                          r"(?::\s*(?:base|this)\s*\(.*\))?\s*(?:where\s+.+)?$", re.S)


@dataclass
class CSField:
    name: str
    type: str
    default: str | None
    modifiers: list[str]
    attributes: list[str]

    @property
    def is_static(self) -> bool:
        return "static" in self.modifiers or "const" in self.modifiers

    @property
    def serialized(self) -> bool:
        attrs = {a.split("(")[0].strip() for a in self.attributes}
        if self.is_static or "readonly" in self.modifiers or {"NonSerialized", "System.NonSerialized"} & attrs:
            return False
        return "public" in self.modifiers or bool({"SerializeField", "SerializeReference"} & attrs)


@dataclass
class CSMethod:
    name: str
    return_type: str
    params: str
    modifiers: list[str]
    attributes: list[str]
    body: str
    is_constructor: bool = False
    expression_bodied: bool = False


@dataclass
class CSProperty:
    name: str
    type: str
    source: str


@dataclass
class CSType:
    name: str
    kind: str  # class | struct | enum | interface | record
    bases: list[str]
    modifiers: list[str]
    attributes: list[str]
    namespace: str | None
    fields: list[CSField] = field(default_factory=list)
    methods: list[CSMethod] = field(default_factory=list)
    properties: list[CSProperty] = field(default_factory=list)
    enum_values: list[str] = field(default_factory=list)
    nested: list["CSType"] = field(default_factory=list)
    outer: str | None = None
    source: str = ""

    @property
    def base(self) -> str | None:
        return self.bases[0] if self.bases else None


@dataclass
class CSFile:
    path: str
    usings: list[str]
    types: list[CSType]
    source: str

    def all_types(self) -> list[CSType]:
        out: list[CSType] = []
        stack = list(self.types)
        while stack:
            t = stack.pop(0)
            out.append(t)
            stack[0:0] = t.nested
        return out


def mask_code(src: str) -> str:
    """Sustituye comentarios, literales y directivas por espacios conservando posiciones."""
    out = list(src)
    i, n = 0, len(src)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    line_start = True
    while i < n:
        c = src[i]
        if line_start and c == "#":
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
            continue
        if c == "\n":
            line_start = True
            i += 1
            continue
        if not c.isspace():
            line_start = False
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
        elif c in "@$" and i + 1 < n and src[i + 1] in "@$\"":
            # @"..." / $"..." / $@"..." / @$"..."
            k = i
            while k < n and src[k] in "@$":
                k += 1
            verbatim = "@" in src[i:k]
            j = _string_end(src, k, verbatim)
            blank(i + (k - i) + 1, j - 1)
            i = j
        elif c == '"':
            j = _string_end(src, i, False)
            blank(i + 1, j - 1)
            i = j
        elif c == "'":
            j = i + 1
            while j < n and src[j] != "'" and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
        else:
            i += 1
    return "".join(out)


def _string_end(src: str, quote_pos: int, verbatim: bool) -> int:
    j = quote_pos + 1
    n = len(src)
    if src.startswith('"""', quote_pos):  # raw string literal (C# 11)
        end = src.find('"""', quote_pos + 3)
        return n if end == -1 else end + 3
    while j < n:
        ch = src[j]
        if verbatim:
            if ch == '"':
                if j + 1 < n and src[j + 1] == '"':
                    j += 2
                    continue
                return j + 1
        else:
            if ch == "\\":
                j += 2
                continue
            if ch == '"' or ch == "\n":
                return j + 1
        j += 1
    return n


def _match_brace(masked: str, open_pos: int) -> int:
    depth = 0
    for k in range(open_pos, len(masked)):
        ch = masked[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(masked) - 1


def _split_attrs(header: str) -> tuple[list[str], str]:
    attrs: list[str] = []
    m = _ATTR_BLOCK.match(header)
    if m:
        for a in _ATTR_NAMES.findall(m.group(0)):
            attrs.extend(x.strip() for x in _split_top(a, ",") if x.strip())
        header = header[m.end():]
    return attrs, header.strip()


def _split_top(text: str, sep: str) -> list[str]:
    """Divide por ``sep`` ignorando separadores dentro de <>, (), [] y {}."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _find_top(text: str, token: str) -> int:
    depth = 0
    for i, ch in enumerate(text):
        if ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        elif depth == 0 and text.startswith(token, i):
            if token == "=" and (text.startswith("==", i) or text.startswith("=>", i) or (i and text[i - 1] in "!<>=")):
                continue
            return i
    return -1


def _parse_members(t: CSType, src: str, masked: str, start: int, end: int, namespace: str | None) -> None:
    """Recorre el cuerpo de un tipo (entre ``start`` y ``end`` exclusivos)."""
    i = start
    seg_start = start
    while i < end:
        ch = masked[i]
        if ch == ";":
            _handle_statement(t, src[seg_start:i], masked[seg_start:i])
            i += 1
            seg_start = i
        elif ch == "{":
            header_masked = masked[seg_start:i]
            header_src = src[seg_start:i]
            close = _match_brace(masked, i)
            tm = _TYPE_DECL.search(masked[seg_start:i + 1])
            if tm and masked[seg_start:i + 1].rstrip().endswith("{") and not re.search(r"[=(]", header_masked[: tm.start()]):
                nested = _parse_type(src, masked, seg_start + tm.start(), namespace, outer=t.name, open_pos=i)
                if nested is not None:
                    t.nested.append(nested)
            else:
                _handle_block(t, header_src, header_masked, src[i + 1:close], masked[i + 1:close])
            i = close + 1
            # Propiedades con inicializador: `{ get; set; } = 5;`
            k = i
            while k < end and masked[k].isspace():
                k += 1
            if k < end and masked[k] == "=" and masked[k:k + 2] != "=>":
                semi = masked.find(";", k)
                i = semi + 1 if semi != -1 else end
                if t.properties and not tm:
                    t.properties[-1].source += " " + src[k:i].strip()
            elif k < end and masked[k] == ";":
                i = k + 1
            seg_start = i
        else:
            i += 1


def _trim_leading(text: str, masked: str) -> tuple[str, str]:
    """Elimina espacios y comentarios iniciales (usando la versión enmascarada)."""
    k = len(masked) - len(masked.lstrip())
    return text[k:], masked[k:]


def _handle_statement(t: CSType, text: str, masked: str) -> None:
    if not masked.strip():
        return
    text, masked = _trim_leading(text, masked)
    attrs, body = _split_attrs(text)
    masked_body = masked.strip()
    m_attr = _ATTR_BLOCK.match(masked_body)
    if m_attr:
        masked_body = masked_body[m_attr.end():].strip()
    arrow = _find_top(masked_body, "=>")
    if arrow != -1:
        head = masked_body[:arrow].strip()
        expr_src = body[body.find("=>") + 2:].strip() if "=>" in body else ""
        if "(" in head:
            m = _METHOD_DECL.match(head)
            if m:
                t.methods.append(
                    CSMethod(m.group("name"), (m.group("ret") or "void").strip(), m.group("params").strip(),
                             m.group("mods").split(), attrs, "return " + expr_src + ";", expression_bodied=True)
                )
                return
        fm = _FIELD_DECL.match(head)
        if fm:
            t.properties.append(CSProperty(fm.group("names"), fm.group("type").strip(), body.strip() + ";"))
        return
    if "(" in masked_body and _find_top(masked_body, "=") == -1:
        # Declaración de método abstracto/extern/interfaz o delegado
        m = _METHOD_DECL.match(masked_body)
        if m and "delegate" not in masked_body.split("(")[0]:
            t.methods.append(CSMethod(m.group("name"), (m.group("ret") or "void").strip(), m.group("params").strip(),
                                      m.group("mods").split(), attrs, ""))
        return
    eq = _find_top(masked_body, "=")
    decl = masked_body if eq == -1 else masked_body[:eq]
    default = None
    if eq != -1:
        # Recuperar el inicializador desde el texto original (con literales).
        body_stripped = body.strip()
        eq_src = _find_top(body_stripped, "=")
        default = body_stripped[eq_src + 1:].strip() if eq_src != -1 else None
    fm = _FIELD_DECL.match(decl.strip())
    if not fm:
        return
    mods = fm.group("mods").split()
    ftype = re.sub(r"\s+", " ", fm.group("type").strip())
    if ftype in MODIFIERS or ftype in ("using", "return", "delegate"):
        return
    names = [n.strip().lstrip("@") for n in fm.group("names").split(",")]
    for name in names:
        t.fields.append(CSField(name, ftype, default if len(names) == 1 else None, mods, attrs))


def _handle_block(t: CSType, header: str, header_masked: str, body: str, body_masked: str) -> None:
    header, header_masked = _trim_leading(header, header_masked)
    attrs, _ = _split_attrs(header)
    _, head = _split_attrs(header_masked)
    head = re.sub(r"\s+", " ", head).strip()
    if not head:
        return
    if t.kind == "enum":
        return
    if "(" in head:
        m = _METHOD_DECL.match(head)
        if not m:
            return
        name = m.group("name")
        ret = (m.group("ret") or "").strip()
        is_ctor = name == t.name and (not ret or ret in MODIFIERS)
        t.methods.append(
            CSMethod(name, ret or ("" if is_ctor else "void"), m.group("params").strip(),
                     m.group("mods").split(), attrs, _dedent(body), is_constructor=is_ctor)
        )
    else:
        fm = _FIELD_DECL.match(head)
        if fm:
            _, header_src = _split_attrs(header)
            t.properties.append(CSProperty(fm.group("names"), fm.group("type").strip(),
                                           header_src.strip() + " {" + body + "}"))


def _dedent(body: str) -> str:
    lines = body.strip("\n").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(ln[cut:] for ln in lines)


def _parse_type(src: str, masked: str, decl_pos: int, namespace: str | None, outer: str | None,
                open_pos: int | None = None) -> CSType | None:
    m = _TYPE_DECL.match(masked, decl_pos)
    if not m:
        return None
    open_pos = m.end() - 1 if open_pos is None else open_pos
    close = _match_brace(masked, open_pos)
    # Atributos inmediatamente anteriores a la declaración.
    before = masked[max(0, decl_pos - 400):decl_pos]
    attrs: list[str] = []
    am = re.search(r"((?:\[[^\[\]]*\]\s*)+)$", before)
    if am:
        for a in _ATTR_NAMES.findall(am.group(1)):
            attrs.extend(x.strip() for x in _split_top(a, ",") if x.strip())
    bases = [b.strip() for b in _split_top(m.group("bases") or "", ",") if b.strip()]
    t = CSType(
        name=m.group("name"),
        kind=m.group("kind"),
        bases=bases,
        modifiers=m.group("mods").split(),
        attributes=attrs,
        namespace=namespace,
        outer=outer,
        source=src[decl_pos:close + 1],
    )
    if t.kind == "enum":
        body = masked[open_pos + 1:close]
        for item in _split_top(body, ","):
            name = item.split("=")[0].strip()
            name = re.sub(r"\[[^\]]*\]", "", name).strip()
            if re.fullmatch(r"\w+", name or ""):
                t.enum_values.append(name)
    else:
        _parse_members(t, src, masked, open_pos + 1, close, namespace)
    return t


def parse_csharp(src: str, path: str = "") -> CSFile:
    masked = mask_code(src)
    usings = re.findall(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", masked, re.M)
    # Namespace con bloque o de ámbito de fichero (C# 10).
    namespaces: list[tuple[int, int, str]] = []
    for nm in re.finditer(r"\bnamespace\s+([\w.]+)\s*([{;])", masked):
        if nm.group(2) == "{":
            open_pos = nm.end() - 1
            namespaces.append((open_pos, _match_brace(masked, open_pos), nm.group(1)))
        else:
            namespaces.append((nm.end(), len(masked), nm.group(1)))

    def ns_at(pos: int) -> str | None:
        best = None
        for a, b, name in namespaces:
            if a <= pos <= b:
                best = name
        return best

    types: list[CSType] = []
    pos = 0
    while True:
        m = _TYPE_DECL.search(masked, pos)
        if not m:
            break
        # Sólo tipos de nivel superior (dentro de namespace o global): profundidad de llaves.
        depth = masked[:m.start()].count("{") - masked[:m.start()].count("}")
        ns = ns_at(m.start())
        ns_depth = sum(1 for a, b, _ in namespaces if a <= m.start() <= b and masked[a] == "{")
        if depth == ns_depth:
            t = _parse_type(src, masked, m.start(), ns, None)
            if t is not None:
                types.append(t)
                pos = m.start() + len(t.source)
                continue
        pos = m.end()
    return CSFile(path=path, usings=usings, types=types, source=src)


def parse_csharp_file(path: str | Path) -> CSFile:
    p = Path(path)
    return parse_csharp(p.read_text("utf-8-sig", errors="replace"), str(p))
