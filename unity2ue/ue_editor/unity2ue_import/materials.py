"""Crea los materiales maestros ``M_UnityLit``/``M_UnityUnlit`` y una Material Instance por .mat."""

from __future__ import annotations

import os
import struct
import zlib

import unreal

from .common import (
    ASSET_TOOLS,
    LOG,
    content_root,
    create_or_load,
    data_dir,
    ensure_dir,
    linear_color,
    load,
    save,
    set_prop,
)

STEP = "materials"
MEL = unreal.MaterialEditingLibrary

WHITE = "/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture"
FLAT_NORMAL = "/Engine/EngineMaterials/DefaultNormal.DefaultNormal"


# Versión de los materiales maestros: si cambia su construcción, se rehacen al reimportar.
MASTER_VERSION = "4"


def master_folder() -> str:
    return f"{content_root()}/_Master"


def _png_white(path: str) -> None:
    """PNG 4x4 blanco (RGBA) sin dependencias."""
    raw = b"".join(bytes([0]) + bytes([255]) * 16 for _ in range(4))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    png = (signature + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)


def _linear_white() -> str:
    """Textura blanca en espacio lineal: valor por defecto de los mapas de datos (metálico, AO).

    Un sampler "Linear Color" con una textura sRGB (como WhiteSquareTexture del motor) hace que el
    material maestro no compile en SM5 y UE usa el material por defecto (todo gris cuadriculado).
    """
    path = f"{master_folder()}/T_LinearWhite"
    tex = load(path)
    if tex is None:
        src = os.path.join(data_dir(), "T_LinearWhite.png")
        _png_white(src)
        task = unreal.AssetImportTask()
        for k, v in (("filename", src), ("destination_path", master_folder()), ("destination_name", "T_LinearWhite"),
                     ("automated", True), ("replace_existing", True), ("save", True)):
            task.set_editor_property(k, v)
        ASSET_TOOLS.import_asset_tasks([task])
        tex = load(path)
    if tex is not None:
        set_prop(tex, "srgb", False)
        # Compresión normal sin sRGB = sampler "Linear Color" (como las texturas de datos importadas).
        set_prop(tex, "compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
        save(tex)
    return f"{path}.T_LinearWhite"


def _expr(mat, cls, x: int, y: int):
    return MEL.create_material_expression(mat, cls, x, y)


def _scalar(mat, name: str, default: float, x: int, y: int):
    e = _expr(mat, unreal.MaterialExpressionScalarParameter, x, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("default_value", default)
    return e


def _vector(mat, name: str, default, x: int, y: int):
    e = _expr(mat, unreal.MaterialExpressionVectorParameter, x, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("default_value", unreal.LinearColor(*default))
    return e


def _texture(mat, name: str, default_path: str, sampler, x: int, y: int, uv=None):
    e = _expr(mat, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    e.set_editor_property("parameter_name", name)
    e.set_editor_property("texture", unreal.load_asset(default_path))
    e.set_editor_property("sampler_type", sampler)
    if uv is not None:
        MEL.connect_material_expressions(uv, "", e, "UVs")
    return e


def _mul(mat, a, a_out: str, b, b_out: str, x: int, y: int):
    e = _expr(mat, unreal.MaterialExpressionMultiply, x, y)
    MEL.connect_material_expressions(a, a_out, e, "A")
    MEL.connect_material_expressions(b, b_out, e, "B")
    return e


def _uv_node(mat):
    """UV = TexCoord * UVTiling.rg + UVOffset.rg (el primer pin de un VectorParameter es RGB)."""
    tc = _expr(mat, unreal.MaterialExpressionTextureCoordinate, -1600, 0)
    tiling_param = _vector(mat, "UVTiling", (1.0, 1.0, 0.0, 0.0), -1600, 150)
    offset_param = _vector(mat, "UVOffset", (0.0, 0.0, 0.0, 0.0), -1600, 300)
    masks = []
    for i, param in enumerate((tiling_param, offset_param)):
        mask = _expr(mat, unreal.MaterialExpressionComponentMask, -1400, 150 + 150 * i)
        mask.set_editor_property("r", True)
        mask.set_editor_property("g", True)
        MEL.connect_material_expressions(param, "", mask, "")
        masks.append(mask)
    scaled = _mul(mat, tc, "", masks[0], "", -1250, 50)
    add = _expr(mat, unreal.MaterialExpressionAdd, -1100, 50)
    MEL.connect_material_expressions(scaled, "", add, "A")
    MEL.connect_material_expressions(masks[1], "", add, "B")
    return add


def _build_master(name: str, unlit: bool):
    mat, created = create_or_load(name, master_folder(), unreal.Material, unreal.MaterialFactoryNew())
    if not created:
        if unreal.EditorAssetLibrary.get_metadata_tag(mat, "unity2ue_version") == MASTER_VERSION:
            LOG.ok(STEP, name, "ya existe (reutilizado)")
            return mat
        MEL.delete_all_material_expressions(mat)  # versión anterior: se reconstruye en el mismo asset
        LOG.ok(STEP, name, f"se reconstruye (versión {MASTER_VERSION})")
    linear_white = _linear_white()
    S = unreal.MaterialSamplerType
    uv = _uv_node(mat)
    base_tex = _texture(mat, "BaseColorMap", WHITE, S.SAMPLERTYPE_COLOR, -900, -400, uv)
    tint = _vector(mat, "BaseColorTint", (1, 1, 1, 1), -900, -150)
    base = _mul(mat, base_tex, "RGB", tint, "", -500, -350)
    opacity = _mul(mat, base_tex, "A", tint, "A", -500, -200)

    emis_tex = _texture(mat, "EmissiveMap", WHITE, S.SAMPLERTYPE_COLOR, -900, 900, uv)
    emis_col = _vector(mat, "EmissiveColor", (0, 0, 0, 1), -900, 1150)
    emissive = _mul(mat, emis_tex, "RGB", emis_col, "", -500, 950)

    if unlit:
        mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
        add = _expr(mat, unreal.MaterialExpressionAdd, -250, 300)
        MEL.connect_material_expressions(base, "", add, "A")
        MEL.connect_material_expressions(emissive, "", add, "B")
        MEL.connect_material_property(add, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    else:
        MEL.connect_material_property(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
        MEL.connect_material_property(emissive, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

        # Normal = lerp((0,0,1), NormalMap, NormalStrength)
        normal_tex = _texture(mat, "NormalMap", FLAT_NORMAL, S.SAMPLERTYPE_NORMAL, -900, 0, uv)
        flat = _expr(mat, unreal.MaterialExpressionConstant3Vector, -700, 150)
        flat.set_editor_property("constant", unreal.LinearColor(0, 0, 1, 1))
        strength = _scalar(mat, "NormalStrength", 1.0, -700, 250)
        nlerp = _expr(mat, unreal.MaterialExpressionLinearInterpolate, -400, 50)
        MEL.connect_material_expressions(flat, "", nlerp, "A")
        MEL.connect_material_expressions(normal_tex, "RGB", nlerp, "B")
        MEL.connect_material_expressions(strength, "", nlerp, "Alpha")
        MEL.connect_material_property(nlerp, "", unreal.MaterialProperty.MP_NORMAL)

        # Metallic = Metallic * MS.R ; Roughness = 1 - Smoothness * MS.A
        ms_tex = _texture(mat, "MetallicSmoothnessMap", linear_white, S.SAMPLERTYPE_LINEAR_COLOR, -900, 350, uv)
        metallic = _mul(mat, _scalar(mat, "Metallic", 0.0, -700, 350), "", ms_tex, "R", -400, 350)
        smooth = _mul(mat, _scalar(mat, "Smoothness", 0.5, -700, 500), "", ms_tex, "A", -400, 500)
        rough = _expr(mat, unreal.MaterialExpressionOneMinus, -250, 500)
        MEL.connect_material_expressions(smooth, "", rough, "")
        MEL.connect_material_property(metallic, "", unreal.MaterialProperty.MP_METALLIC)
        MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)

        # AO = lerp(1, Occlusion.G, OcclusionStrength)
        ao_tex = _texture(mat, "OcclusionMap", linear_white, S.SAMPLERTYPE_LINEAR_COLOR, -900, 650, uv)
        one = _expr(mat, unreal.MaterialExpressionConstant, -700, 650)
        one.set_editor_property("r", 1.0)
        ao_strength = _scalar(mat, "OcclusionStrength", 1.0, -700, 750)
        ao = _expr(mat, unreal.MaterialExpressionLinearInterpolate, -400, 700)
        MEL.connect_material_expressions(one, "", ao, "A")
        MEL.connect_material_expressions(ao_tex, "G", ao, "B")
        MEL.connect_material_expressions(ao_strength, "", ao, "Alpha")
        MEL.connect_material_property(ao, "", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)

    MEL.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)
    MEL.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY_MASK)
    MEL.layout_material_expressions(mat)
    # Usos: sin "Used with Skeletal Mesh" UE pinta los personajes con el material por defecto.
    for usage in ("used_with_skeletal_mesh", "used_with_morph_targets", "used_with_instanced_static_meshes",
                  "used_with_niagara_sprites", "used_with_niagara_meshes", "used_with_particle_sprites"):
        set_prop(mat, usage, True)
    MEL.recompile_material(mat)
    unreal.EditorAssetLibrary.set_metadata_tag(mat, "unity2ue_version", MASTER_VERSION)
    save(mat)
    LOG.ok(STEP, name, "material maestro creado")
    return mat


BLEND = {
    "Opaque": "BLEND_OPAQUE",
    "Masked": "BLEND_MASKED",
    "Translucent": "BLEND_TRANSLUCENT",
    "Additive": "BLEND_ADDITIVE",
}


def _instance(mdata: dict, masters: dict) -> None:
    pkg = mdata["ue_path"]
    folder, name = pkg.rsplit("/", 1)
    ensure_dir(folder)
    mi, _ = create_or_load(name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    parent = masters.get(mdata.get("parent", "M_UnityLit")) or masters["M_UnityLit"]
    MEL.set_material_instance_parent(mi, parent)

    for param, tex in (mdata.get("textures") or {}).items():
        texture = load((tex.get("texture") or {}).get("ue_path"))
        if texture is None:
            LOG.warn(STEP, name, f"Textura no encontrada para {param}")
            continue
        MEL.set_material_instance_texture_parameter_value(mi, param, texture)
    for param, value in (mdata.get("scalars") or {}).items():
        if param in ("OpacityMaskClip", "SmoothnessMapScale", "HeightScale"):
            continue
        MEL.set_material_instance_scalar_parameter_value(mi, param, float(value))
    for param, value in (mdata.get("vectors") or {}).items():
        MEL.set_material_instance_vector_parameter_value(mi, param, linear_color(value))
    uv = mdata.get("uv") or {}
    tiling = uv.get("tiling", [1, 1])
    offset = uv.get("offset", [0, 0])
    MEL.set_material_instance_vector_parameter_value(mi, "UVTiling", unreal.LinearColor(tiling[0], tiling[1], 0, 0))
    # El origen UV de Unity está abajo a la izquierda; el de UE arriba a la izquierda.
    MEL.set_material_instance_vector_parameter_value(mi, "UVOffset", unreal.LinearColor(offset[0], -offset[1], 0, 0))

    overrides = mi.get_editor_property("base_property_overrides")
    blend = mdata.get("blend_mode", "Opaque")
    if blend != "Opaque":
        set_prop(overrides, "override_blend_mode", True)
        set_prop(overrides, "blend_mode", getattr(unreal.BlendMode, BLEND.get(blend, "BLEND_OPAQUE")))
    if blend == "Masked":
        clip = (mdata.get("scalars") or {}).get("OpacityMaskClip", 0.5)
        set_prop(overrides, "override_opacity_mask_clip_value", True)
        set_prop(overrides, "opacity_mask_clip_value", float(clip))
    if mdata.get("two_sided"):
        set_prop(overrides, "override_two_sided", True)
        set_prop(overrides, "two_sided", True)
    mi.set_editor_property("base_property_overrides", overrides)
    MEL.update_material_instance(mi)
    save(mi)
    LOG.ok(STEP, mdata["unity_path"], f"-> {pkg} ({blend})")


def run(data: dict | None) -> None:
    ensure_dir(master_folder())
    masters = {
        "M_UnityLit": _build_master("M_UnityLit", unlit=False),
        "M_UnityUnlit": _build_master("M_UnityUnlit", unlit=True),
    }
    if not data:
        return
    mats = data.get("materials", [])
    with unreal.ScopedSlowTask(len(mats), "unity2ue: materiales") as slow:
        slow.make_dialog(True)
        for m in mats:
            slow.enter_progress_frame(1, m.get("unity_path", ""))
            try:
                _instance(m, masters)
            except Exception:  # noqa: BLE001
                LOG.exception(STEP, m.get("unity_path", "?"))
