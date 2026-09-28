import json

from unity2ue.analyze import analyze_project
from unity2ue.convert.hierarchy import iter_nodes


def _load(result, name):
    return json.loads((result.out_dir / "Unity2UE" / name).read_text())


def test_project_files(converted):
    out = converted.out_dir
    up = json.loads(converted.uproject.read_text())
    assert converted.uproject.name == "SampleGame.uproject"
    assert up["EngineAssociation"] == "5.8"
    assert up["Modules"][0]["Name"] == "SampleGame"
    assert any(p["Name"] == "PythonScriptPlugin" for p in up["Plugins"])
    for rel in (
        "Source/SampleGame/SampleGame.Build.cs",
        "Source/SampleGameEditor.Target.cs",
        "Source/SampleGame/UnityCompat/UnityBehaviour.h",
        "Source/SampleGame/Unity/PlayerControllerComponent.h",
        "Source/SampleGame/Unity/RotatorComponent.h",
        "Content/Python/unity2ue_import/run_all.py",
        "Unity2UE/report.md",
        "Unity2UE_Import.bat",
    ):
        assert (out / rel).exists(), rel
    compat = (out / "Source/SampleGame/UnityCompat/UnityBehaviour.h").read_text()
    assert "SAMPLEGAME_API UUnityBehaviour" in compat and "{{API}}" not in compat
    ini = (out / "Config/DefaultEngine.ini").read_text()
    assert "GameDefaultMap=/Game/Unity/Maps/Main" in ini
    assert "DefaultGravityZ=-981.000" in ini
    assert 'Name="Player"' in ini  # capa 8 -> canal de colisión


def test_scene(converted):
    level = _load(converted, "levels/Main.json")
    assert level["ue_level_path"] == "/Game/Unity/Maps/Main"
    roots = {n["name"]: n for n in level["roots"]}
    assert list(roots) == ["Main Camera", "Directional Light", "Player", "Rock", "Crate (1)"]
    player = roots["Player"]
    assert player["transform"]["location"] == [300.0, 200.0, 0.0]
    assert player["transform"]["rotation"][1] == 90.0
    assert [c["name"] for c in player["children"]] == ["Muzzle"]
    types = [c["type"] for c in player["components"]]
    assert types == ["StaticMesh", "CapsuleCollision", "Script"]
    script = player["components"][2]
    assert script["cpp_class"] == "PlayerControllerComponent"
    assert script["properties"]["move_speed"]["value"] == 8
    assert script["properties"]["bullet_prefab"]["value"]["resolved"]["ue_class_path"] == \
        "/Game/Unity/Prefabs/BP_Crate.BP_Crate_C"
    crate = roots["Crate (1)"]
    assert crate["prefab"]["unity_path"] == "Assets/Prefabs/Crate.prefab"
    assert crate["transform"]["location"] == [100.0, 500.0, 50.0]
    assert crate["prefab"]["overrides"][0]["property"] == "m_Intensity"
    assert crate["children"][0]["name"] == "Label" and crate["children"][0]["active"] is False
    rock = roots["Rock"]["components"][0]
    assert rock["mesh"]["ue_folder"] == "/Game/Unity/Models/Rock"
    assert rock["mesh"]["sub_name"] == "Rock_Mesh"
    cam = roots["Main Camera"]["components"][0]
    assert cam["type"] == "Camera" and round(cam["field_of_view"]) == 91
    sun = roots["Directional Light"]
    assert sun["components"][0]["type"] == "DirectionalLight"
    assert sun["transform"]["rotation"][0] == -50.0 or abs(sun["transform"]["rotation"][0] + 50) < 1e-3
    assert level["environment"]["fog"] is True
    assert len(list(iter_nodes(level["roots"]))) == 7


def test_prefab(converted):
    bps = _load(converted, "blueprints.json")
    crate = bps["prefabs"][0]
    assert crate["ue_blueprint_path"] == "/Game/Unity/Prefabs/BP_Crate"
    comps = {c["type"]: c for c in crate["root"]["components"]}
    assert comps["BoxCollision"]["box_extent"] == [150.0, 50.0, 100.0]
    assert comps["Rigidbody"]["lock_rotation"] == {"x": True, "y": True, "z": True}
    assert comps["StaticMesh"]["mesh"]["ue_path"] == "/Engine/BasicShapes/Cube.Cube"
    assert comps["Script"]["cpp_class"] == "RotatorComponent"
    glow = crate["root"]["children"][0]
    assert glow["components"][0]["type"] == "PointLight"
    assert glow["transform"]["location"] == [0.0, 0.0, 100.0]


def test_materials_and_assets(converted):
    mat = _load(converted, "materials.json")["materials"][0]
    assert mat["ue_path"] == "/Game/Unity/Materials/MI_Wood"
    assert mat["shader_family"] == "urp_lit" and mat["blend_mode"] == "Opaque"
    assert mat["textures"]["BaseColorMap"]["texture"]["ue_path"] == "/Game/Unity/Textures/Wood_Albedo.Wood_Albedo"
    assert mat["uv"]["tiling"] == [2.0, 2.0]
    imports = {i["destination_name"]: i for i in _load(converted, "assets.json")["imports"]}
    assert imports["Wood_Normal"]["normal_map"] and imports["Wood_Normal"]["flip_green_channel"]
    assert imports["Wood_Albedo"]["srgb"]
    assert imports["Rock"]["type"] == "model" and not imports["Rock"]["skeletal"]
    assert (converted.out_dir / imports["Wood_Albedo"]["file"]).exists()


def test_settings_and_input(converted):
    settings = _load(converted, "settings.json")
    actions = {a["name"]: a for a in settings["input_actions"]}
    assert actions["Horizontal"]["value_type"] == "Axis1D"
    assert {"key": "A", "negate": True} in actions["Horizontal"]["mappings"]
    assert actions["Jump"]["mappings"] == [{"key": "SpaceBar", "negate": False}]
    assert actions["Mouse X"]["mappings"] == [{"key": "MouseX", "negate": False}]


def test_scripts_queue_and_no_overwrite(converted, sample_project):
    from unity2ue.config import ConversionConfig
    from unity2ue.pipeline import convert_project

    queue = {s["unity_path"]: s for s in _load(converted, "scripts.json")["scripts"]}
    assert queue["Assets/Scripts/PlayerController.cs"]["status"] == "stub"
    assert queue["Assets/Editor/SampleTool.cs"]["kind"] == "editor"
    header = converted.out_dir / queue["Assets/Scripts/Rotator.cs"]["header"]
    translated = header.read_text().replace("UNITY2UE_STATUS: STUB", "UNITY2UE_STATUS: TRANSLATED") + "// mano\n"
    header.write_text(translated)
    convert_project(sample_project, converted.out_dir, ConversionConfig(project_name="Sample Game"), log=lambda _m: None)
    assert header.read_text() == translated
    queue2 = {s["unity_path"]: s for s in _load(converted, "scripts.json")["scripts"]}
    assert queue2["Assets/Scripts/Rotator.cs"]["status"] == "translated"


def test_analyze(sample_project):
    data = analyze_project(sample_project)
    assert data["render_pipeline"] == "URP"
    assert data["unity_version"] == "2022.3.20f1"
    assert data["asset_counts"]["script"] == 4
    assert data["component_usage"]["MeshFilter"] == 4
    assert data["api_usage"]["legacy_input"] == 1


def test_scriptable_object_assets(converted):
    """Los .asset de ScriptableObjects del proyecto se convierten en DataAssets con sus valores."""
    data = _load(converted, "data_assets.json")["data_assets"]
    rifle = next(d for d in data if d["unity_path"] == "Assets/Data/Rifle.asset")
    assert rifle["ue_path"] == "/Game/Unity/Data/DA_Rifle"
    assert rifle["cpp_class"] == "WeaponData"
    assert rifle["properties"]["damage"]["value"] == 35
    assert rifle["properties"]["display_name"]["value"] == "Rifle"
    sound = rifle["properties"]["fire_sound"]["value"]["resolved"]
    assert sound["ue_path"] == "/Game/Unity/Audio/Shot.Shot"


def test_skinned_mesh_ignores_node_rotation_and_prunes_bones(converted):
    """La malla con skin no hereda la corrección de ejes del nodo FBX y los huesos vacíos desaparecen."""
    bps = _load(converted, "blueprints.json")
    hero = next(p for p in bps["prefabs"] if p["unity_path"] == "Assets/Prefabs/Hero.prefab")
    names = {n["name"]: n for n in iter_nodes([hero["root"]])}
    body = names["Body"]
    assert body["skinned_transform_ignored"]
    assert body["transform"]["rotation_quat"] == [0.0, 0.0, 0.0, 1.0]
    assert "Spine" not in names  # hueso sin nada colgado
    assert {"Hips", "Hand", "Gun"} <= set(names)  # la cadena que lleva el arma se conserva


def test_reconvert_keeps_unchanged_files(tmp_path, sample_project):
    """Reconvertir no reescribe ficheros idénticos: si no, UE recompila todo el módulo (~45 min)."""
    import os

    from unity2ue.config import ConversionConfig
    from unity2ue.pipeline import convert_project

    cfg = ConversionConfig(project_name="Sample Game")
    result = convert_project(sample_project, tmp_path, cfg, log=lambda _m: None)
    files = [result.out_dir / "Source/SampleGame/UnityCompat/UnityBehaviour.h",
             result.out_dir / "Source/SampleGame/Unity/RotatorComponent.h"]
    for f in files:
        os.utime(f, (1_000_000_000, 1_000_000_000))
    convert_project(sample_project, tmp_path, cfg, log=lambda _m: None)
    assert all(f.stat().st_mtime == 1_000_000_000 for f in files)


def test_reconvert_keeps_project_extras(tmp_path, sample_project):
    """Las personalizaciones de unity2ue_import/extra/ sobreviven a una reconversión."""
    from unity2ue.config import ConversionConfig
    from unity2ue.pipeline import convert_project

    cfg = ConversionConfig(project_name="Sample Game")
    result = convert_project(sample_project, tmp_path, cfg, log=lambda _m: None)
    custom = result.out_dir / "Content/Python/unity2ue_import/extra/mis_retoques.py"
    custom.write_text("def run():\n    pass\n", encoding="utf-8")
    convert_project(sample_project, tmp_path, cfg, log=lambda _m: None)
    assert custom.exists()


def test_image_size_reads_png_header(tmp_path):
    """Tamaño de sprite en modo Simple = píxeles de la imagen / PixelsPerUnit (no m_Size)."""
    import struct
    import zlib

    from unity2ue.convert.components import _image_size

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (bytes([137, 80, 78, 71, 13, 10, 26, 10]) + chunk(b"IHDR", struct.pack(">IIBBBBB", 300, 150, 8, 6, 0, 0, 0))
           + chunk(b"IEND", b""))
    path = tmp_path / "s.png"
    path.write_bytes(png)
    assert _image_size(path) == (300, 150)
