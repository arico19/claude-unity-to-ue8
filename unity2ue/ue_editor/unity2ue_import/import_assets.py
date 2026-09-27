"""Importa texturas, modelos, audio, fuentes y vídeos descritos en ``assets.json``."""

from __future__ import annotations

import os
import shutil

import unreal

from .common import ASSET_TOOLS, LOG, ensure_dir, load, project_dir, save, set_prop

STEP = "assets"


def _task(filename: str, dest: str, name: str, options=None) -> unreal.AssetImportTask:
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", filename)
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    if options is not None:
        task.set_editor_property("options", options)
    return task


def _fbx_options(item: dict):
    opts = unreal.FbxImportUI()
    skeletal = bool(item.get("skeletal"))
    set_prop(opts, "automated_import_should_detect_type", False)
    set_prop(opts, "import_mesh", True)
    set_prop(opts, "import_textures", False)
    set_prop(opts, "import_materials", False)
    set_prop(opts, "import_as_skeletal", skeletal)
    set_prop(opts, "import_animations", bool(item.get("import_animations")))
    set_prop(opts, "create_physics_asset", skeletal)
    set_prop(opts, "mesh_type_to_import",
             unreal.FBXImportType.FBXIT_SKELETAL_MESH if skeletal else unreal.FBXImportType.FBXIT_STATIC_MESH)
    scale = float(item.get("uniform_scale") or 1.0)
    sm = opts.get_editor_property("static_mesh_import_data")
    set_prop(sm, "combine_meshes", bool(item.get("combine_meshes", True)))
    set_prop(sm, "auto_generate_collision", True)
    set_prop(sm, "generate_lightmap_u_vs", True)
    set_prop(sm, "import_uniform_scale", scale)
    sk = opts.get_editor_property("skeletal_mesh_import_data")
    set_prop(sk, "import_uniform_scale", scale)
    set_prop(sk, "import_morph_targets", True)
    return opts


def _find_skeleton(dest: str):
    """Esqueleto ya importado más cercano: misma carpeta de Unity, luego carpetas superiores."""
    folder = dest.rsplit("/", 1)[0]
    while folder.count("/") >= 2:
        for p in unreal.EditorAssetLibrary.list_assets(folder, recursive=True, include_folder=False):
            data = unreal.EditorAssetLibrary.find_asset_data(p)
            if str(data.asset_class_path.asset_name) == "Skeleton":
                return load(p)
        folder = folder.rsplit("/", 1)[0]
    return None


def _retry_model(item: dict, src: str) -> list[str]:
    """Reintenta un FBX esquelético que no produjo nada.

    1. Sólo animación (FBX de Mixamo/Unity sin malla) sobre un esqueleto ya importado.
    2. Malla estática (p.ej. varios huesos raíz, que UE no admite en mallas esqueléticas).
    """
    skeleton = _find_skeleton(item["destination_path"])
    if skeleton is not None and item.get("import_animations"):
        opts = _fbx_options(item)
        set_prop(opts, "import_mesh", False)
        set_prop(opts, "skeleton", skeleton)
        set_prop(opts, "create_physics_asset", False)
        set_prop(opts, "mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
        task = _task(src, item["destination_path"], item["destination_name"], opts)
        ASSET_TOOLS.import_asset_tasks([task])
        paths = list(task.get_editor_property("imported_object_paths") or [])
        if paths:
            LOG.warn(STEP, item["unity_path"], f"Sólo animación: importada sobre el esqueleto {skeleton.get_path_name()} "
                     "(revisa que los huesos coincidan)")
            return paths
    static = dict(item, skeletal=False, import_animations=False)
    task = _task(src, item["destination_path"], item["destination_name"], _fbx_options(static))
    ASSET_TOOLS.import_asset_tasks([task])
    paths = list(task.get_editor_property("imported_object_paths") or [])
    if paths:
        LOG.warn(STEP, item["unity_path"], "No se pudo importar como malla esquelética (p.ej. varios huesos raíz): "
                 "importada como malla estática, sin animación")
    return paths


def _configure_texture(tex, item: dict) -> None:
    name = item["destination_name"]
    if item.get("normal_map"):
        set_prop(tex, "compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP, STEP, name)
        set_prop(tex, "lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD_NORMAL_MAP, STEP, name)
        # Unity usa normales OpenGL (Y+); UE usa DirectX (Y-).
        set_prop(tex, "flip_green_channel", bool(item.get("flip_green_channel", True)), STEP, name)
        set_prop(tex, "srgb", False, STEP, name)
    else:
        set_prop(tex, "srgb", bool(item.get("srgb", True)), STEP, name)
        if not item.get("srgb", True):
            set_prop(tex, "compression_settings", unreal.TextureCompressionSettings.TC_MASKS, STEP, name)
    if item.get("ui") or item.get("sprite"):
        set_prop(tex, "lod_group", unreal.TextureGroup.TEXTUREGROUP_UI, STEP, name)
        set_prop(tex, "mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS, STEP, name)
    elif not item.get("mipmaps", True):
        set_prop(tex, "mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS, STEP, name)
    address = {"Wrap": "TA_WRAP", "Clamp": "TA_CLAMP", "Mirror": "TA_MIRROR"}.get(item.get("wrap", "Wrap"), "TA_WRAP")
    set_prop(tex, "address_x", getattr(unreal.TextureAddress, address))
    set_prop(tex, "address_y", getattr(unreal.TextureAddress, address))
    if item.get("filter") == "Nearest":
        set_prop(tex, "filter", unreal.TextureFilter.TF_NEAREST)
    if item.get("max_size"):
        set_prop(tex, "max_texture_size", int(item["max_size"]))
    save(tex)


def _import_video(item: dict, src: str) -> None:
    movies = os.path.join(project_dir(), "Content", "Movies")
    os.makedirs(movies, exist_ok=True)
    dst = os.path.join(movies, os.path.basename(src))
    shutil.copy2(src, dst)
    factory_cls = getattr(unreal, "FileMediaSourceFactoryNew", None)
    if factory_cls is None:
        LOG.warn(STEP, item["unity_path"], "Vídeo copiado a Content/Movies; crea el FileMediaSource manualmente.")
        return
    ensure_dir(item["destination_path"])
    media = ASSET_TOOLS.create_asset(item["destination_name"], item["destination_path"], unreal.FileMediaSource,
                                     factory_cls())
    media.set_editor_property("file_path", f"./Movies/{os.path.basename(src)}")
    save(media)
    LOG.ok(STEP, item["unity_path"], "FileMediaSource creado")


def _set_legacy_fbx(enabled: bool) -> None:
    # En UE 5.5+ Interchange importa FBX por defecto; forzamos el importador clásico para
    # que se respeten las opciones de FbxImportUI (si el motor aún lo incluye).
    try:
        value = "False" if enabled else "True"
        unreal.SystemLibrary.execute_console_command(None, f"Interchange.FeatureFlags.Import.FBX {value}")
    except Exception:  # noqa: BLE001
        pass


# Tipos que en UE 5.8 necesitan la UI de Slate: importarlos en un commandlet cierra el editor
# (assert CurrentApplication.IsValid()). Se importan después en el editor con UI.
NEEDS_UI = {"font"}


def is_commandlet() -> bool:
    try:
        return "-run=" in unreal.SystemLibrary.get_command_line().lower()
    except Exception:  # noqa: BLE001
        return False


def run(data: dict | None, only: set[str] | None = None) -> None:
    if not data:
        LOG.warn(STEP, "assets.json", "No hay assets que importar")
        return
    items = [i for i in data.get("imports", []) if only is None or i["type"] in only]
    if only is None and is_commandlet():
        deferred = [i for i in items if i["type"] in NEEDS_UI]
        items = [i for i in items if i["type"] not in NEEDS_UI]
        for i in deferred:
            LOG.warn(STEP, i["unity_path"], "Fuente: se importa al abrir el editor con UI (paso de capturas "
                     "o import_assets.run(..., only={'font'}))")
    # Texturas primero (los materiales las necesitan), después modelos, audio, etc.
    order = {"texture": 0, "model": 1, "audio": 2, "font": 3, "video": 4}
    items.sort(key=lambda i: order.get(i["type"], 9))
    _set_legacy_fbx(True)
    batch: list[tuple[dict, unreal.AssetImportTask]] = []
    for item in items:
        src = os.path.join(project_dir(), item["file"])
        if not os.path.exists(src):
            LOG.error(STEP, item["unity_path"], f"No existe {src}")
            continue
        if item["type"] == "video":
            try:
                _import_video(item, src)
            except Exception:  # noqa: BLE001
                LOG.exception(STEP, item["unity_path"])
            continue
        ensure_dir(item["destination_path"])
        opts = _fbx_options(item) if item["type"] == "model" and src.lower().endswith(".fbx") else None
        batch.append((item, _task(src, item["destination_path"], item["destination_name"], opts)))

    # Importar por lotes para dar feedback y no perder todo ante un fallo.
    retry: list[dict] = []
    chunk = 50
    for start in range(0, len(batch), chunk):
        part = batch[start:start + chunk]
        with unreal.ScopedSlowTask(len(part), f"unity2ue: importando assets {start + 1}-{start + len(part)}") as slow:
            slow.make_dialog(True)
            try:
                ASSET_TOOLS.import_asset_tasks([t for _, t in part])
            except Exception:  # noqa: BLE001
                LOG.exception(STEP, f"lote {start}")
            for item, task in part:
                slow.enter_progress_frame(1, item["unity_path"])
                paths = list(task.get_editor_property("imported_object_paths") or [])
                if not paths:
                    if item["type"] == "model" and item.get("skeletal") and item["file"].lower().endswith(".fbx"):
                        retry.append(item)
                    else:
                        LOG.error(STEP, item["unity_path"], "La importación no produjo ningún asset")
                    continue
                if item["type"] == "texture":
                    tex = load(paths[0])
                    if tex is not None:
                        _configure_texture(tex, item)
                LOG.ok(STEP, item["unity_path"], f"-> {', '.join(str(p) for p in paths[:3])}")
    # Reintentos al final, cuando ya existen los esqueletos del resto de modelos.
    for item in retry:
        try:
            paths = _retry_model(item, os.path.join(project_dir(), item["file"]))
            if paths:
                LOG.ok(STEP, item["unity_path"], f"-> {', '.join(str(p) for p in paths[:3])}")
            else:
                LOG.error(STEP, item["unity_path"], "La importación no produjo ningún asset (ni como animación ni estática)")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, item["unity_path"])
    _set_legacy_fbx(False)
