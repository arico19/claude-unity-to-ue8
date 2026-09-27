"""Conversión de materiales Unity (.mat) a Material Instances de UE.

Todos los materiales se convierten en instancias de dos materiales maestros que el
script del editor crea (``M_UnityLit`` y ``M_UnityUnlit``). Los parámetros siguen el
flujo *metallic/smoothness* de Unity: roughness = 1 - smoothness se resuelve en el grafo.
"""

from __future__ import annotations

from typing import Any

from ..unity.builtin import BUILTIN_DEFAULT_GUID, BUILTIN_SHADER_FILE_IDS, KNOWN_SHADER_GUIDS
from ..unity.yaml_parser import ref_file_id, ref_guid
from .context import ConversionContext
from .coords import color_to_linear

# Propiedad Unity -> parámetro de textura del material maestro
TEXTURE_MAP = {
    "_MainTex": "BaseColorMap",
    "_BaseMap": "BaseColorMap",
    "_BaseColorMap": "BaseColorMap",
    "_BumpMap": "NormalMap",
    "_NormalMap": "NormalMap",
    "_MetallicGlossMap": "MetallicSmoothnessMap",
    "_MaskMap": "MaskMap",  # HDRP: R metal, G AO, B detail, A smoothness
    "_OcclusionMap": "OcclusionMap",
    "_EmissionMap": "EmissiveMap",
    "_EmissiveColorMap": "EmissiveMap",
    "_SpecGlossMap": "SpecularGlossMap",
    "_ParallaxMap": "HeightMap",
    "_DetailAlbedoMap": "DetailAlbedoMap",
    "_DetailNormalMap": "DetailNormalMap",
}
NORMAL_TEXTURE_PROPS = {"_BumpMap", "_NormalMap", "_DetailNormalMap"}
LINEAR_TEXTURE_PROPS = {"_MetallicGlossMap", "_MaskMap", "_OcclusionMap", "_SpecGlossMap", "_ParallaxMap"}

COLOR_MAP = {"_Color": "BaseColorTint", "_BaseColor": "BaseColorTint", "_EmissionColor": "EmissiveColor",
             "_EmissiveColor": "EmissiveColor", "_SpecColor": "SpecularColor"}
SCALAR_MAP = {
    "_Metallic": "Metallic",
    "_Glossiness": "Smoothness",
    "_Smoothness": "Smoothness",
    "_GlossMapScale": "SmoothnessMapScale",
    "_BumpScale": "NormalStrength",
    "_NormalScale": "NormalStrength",
    "_OcclusionStrength": "OcclusionStrength",
    "_Cutoff": "OpacityMaskClip",
    "_AlphaCutoff": "OpacityMaskClip",
    "_Parallax": "HeightScale",
}
# Propiedades que ya se reflejan en blend_mode/two_sided.
BLEND_STATE_FLOATS = {"_Mode", "_Surface", "_SurfaceType", "_Cull", "_Blend", "_SrcBlend", "_DstBlend", "_ZWrite",
                      "_AlphaClip", "_AlphaCutoffEnable", "_DoubleSidedEnable", "_SmoothnessTextureChannel"}


def _entries(section: Any) -> dict[str, Any]:
    """Normaliza listas ``[{_Prop: val}]`` o ``[{first:{name}, second}]`` a dict."""
    out: dict[str, Any] = {}
    if isinstance(section, dict):
        return dict(section)
    for item in section or []:
        if not isinstance(item, dict):
            continue
        if "first" in item and "second" in item:
            name = (item.get("first") or {}).get("name")
            if name:
                out[str(name)] = item["second"]
        else:
            out.update(item)
    return out


def shader_family(ctx: ConversionContext, shader_ref: Any) -> str:
    guid = ref_guid(shader_ref)
    fid = ref_file_id(shader_ref)
    if guid == BUILTIN_DEFAULT_GUID:
        return BUILTIN_SHADER_FILE_IDS.get(fid, "builtin_other")
    if guid in KNOWN_SHADER_GUIDS:
        return KNOWN_SHADER_GUIDS[guid]
    info = ctx.project.guids.get(guid)
    if info is not None:
        return "custom_shadergraph" if info.path.endswith(".shadergraph") else "custom_shader"
    return "unknown"


def _blend_mode(family: str, floats: dict[str, Any], keywords: list[str]) -> str:
    f = lambda k, d=0.0: float(floats.get(k, d) or 0.0)  # noqa: E731
    if family.startswith("standard") or family == "legacy_diffuse":
        return {0: "Opaque", 1: "Masked", 2: "Translucent", 3: "Translucent"}.get(int(f("_Mode")), "Opaque")
    if family in ("unlit_transparent", "sprites_default", "ui_default"):
        return "Translucent"
    if family == "unlit_cutout":
        return "Masked"
    surface = f("_Surface", f("_SurfaceType"))
    if surface >= 1:
        return "Additive" if int(f("_Blend")) == 2 else "Translucent"
    if f("_AlphaClip") >= 1 or f("_AlphaCutoffEnable") >= 1 or "_ALPHATEST_ON" in keywords:
        return "Masked"
    return "Opaque"


def convert_material(ctx: ConversionContext, unity_path: str) -> dict[str, Any]:
    doc = ctx.project.load(unity_path)
    mat = next((o for o in doc if o.type_name == "Material"), None)
    name = ctx.naming.imported_name(unity_path)
    out: dict[str, Any] = {
        "unity_path": unity_path,
        "name": name,
        "ue_path": ctx.naming.material_path(unity_path),
    }
    if mat is None:
        ctx.error(unity_path, "No se encontró el objeto Material en el fichero.")
        out["parent"] = "M_UnityLit"
        return out

    props = mat.get("m_SavedProperties") or {}
    textures = _entries(props.get("m_TexEnvs"))
    floats = _entries(props.get("m_Floats"))
    colors = _entries(props.get("m_Colors"))
    keywords_raw = mat.get("m_ShaderKeywords") or mat.get("m_ValidKeywords") or ""
    keywords = keywords_raw.split() if isinstance(keywords_raw, str) else [str(k) for k in keywords_raw]

    family = shader_family(ctx, mat.get("m_Shader"))
    unlit = "unlit" in family or family in ("sprites_default", "ui_default")
    out["shader_family"] = family
    out["parent"] = "M_UnityUnlit" if unlit else "M_UnityLit"
    out["blend_mode"] = _blend_mode(family, floats, keywords)
    out["two_sided"] = float(floats.get("_Cull", 2) or 0) == 0 or float(floats.get("_DoubleSidedEnable", 0) or 0) == 1

    tex_params: dict[str, Any] = {}
    unmapped: dict[str, Any] = {}
    tiling = [1.0, 1.0]
    offset = [0.0, 0.0]
    for prop, env in textures.items():
        if not isinstance(env, dict):
            continue
        ref = ctx.asset_ref(env.get("m_Texture"), unity_path)
        if not ref:
            continue
        param = TEXTURE_MAP.get(prop)
        entry = {"texture": ref, "is_normal": prop in NORMAL_TEXTURE_PROPS, "linear": prop in LINEAR_TEXTURE_PROPS}
        if param is None:
            unmapped[prop] = entry
            continue
        tex_params[param] = entry
        if param == "BaseColorMap":
            sc = env.get("m_Scale") or {}
            of = env.get("m_Offset") or {}
            tiling = [float(sc.get("x", 1) or 0), float(sc.get("y", 1) or 0)]
            offset = [float(of.get("x", 0) or 0), float(of.get("y", 0) or 0)]

    scalars: dict[str, float] = {}
    for prop, val in floats.items():
        param = SCALAR_MAP.get(prop)
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if param:
            scalars[param] = fval
        elif prop not in BLEND_STATE_FLOATS:
            unmapped.setdefault(prop, fval)

    vectors: dict[str, list[float]] = {}
    for prop, val in colors.items():
        param = COLOR_MAP.get(prop)
        if param:
            vectors[param] = color_to_linear(val)
        else:
            unmapped.setdefault(prop, color_to_linear(val))

    # --- Reglas del flujo metallic/smoothness de Unity ---
    if "MetallicSmoothnessMap" in tex_params:
        scalars["Metallic"] = 1.0  # Unity ignora _Metallic si hay mapa
        scalars["Smoothness"] = scalars.get("SmoothnessMapScale", 1.0)
    if "MaskMap" in tex_params:  # HDRP
        tex_params["MetallicSmoothnessMap"] = tex_params.pop("MaskMap")
        tex_params.setdefault("OcclusionMap", dict(tex_params["MetallicSmoothnessMap"], channel="G"))
    if float(floats.get("_SmoothnessTextureChannel", 0) or 0) == 1:
        out["smoothness_from_albedo_alpha"] = True
        ctx.info(unity_path, "Smoothness leída del alfa del albedo: revisar el material en UE.")
    emission_on = "_EMISSION" in keywords or "EmissiveMap" in tex_params or family.startswith("hdrp")
    if not emission_on:
        vectors["EmissiveColor"] = [0.0, 0.0, 0.0, 1.0]
    if "SpecularGlossMap" in tex_params or family == "standard_specular":
        ctx.manual(unity_path, "Material en flujo specular: convertido aproximadamente a metallic/roughness.")
    if family in ("custom_shader", "custom_shadergraph", "unknown"):
        ctx.manual(
            unity_path,
            f"Shader personalizado ({family}): se usa M_UnityLit como aproximación. "
            "Recrear el shader como material UE (ver skill materiales-unity-ue).",
        )
    if "HeightMap" in tex_params:
        ctx.info(unity_path, "Parallax/height map ignorado (usar BumpOffset o Nanite displacement en UE).")

    out["textures"] = tex_params
    out["scalars"] = scalars
    out["vectors"] = vectors
    out["uv"] = {"tiling": tiling, "offset": offset}
    out["render_queue"] = mat.get("m_CustomRenderQueue", -1)
    out["unmapped"] = unmapped
    return out
