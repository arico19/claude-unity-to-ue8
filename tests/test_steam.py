import json
import struct
import zlib
from pathlib import Path

import pytest

from unity2ue.cli import main
from unity2ue.config import ConversionConfig
from unity2ue.pipeline import convert_project
from unity2ue.steam import config as steam_config
from unity2ue.steam.build import archive_dir, buildcookrun_command
from unity2ue.steam.check import STORE_ASSETS, check_achievement_icons, check_store_assets, run_checks
from unity2ue.steam.detect import detect_unity_steam
from unity2ue.steam.images import image_info, png_has_alpha
from unity2ue.steam.init import init_steam
from unity2ue.steam.integrate import integrate, steam_ids_header, upsert_block
from unity2ue.steam.upload import app_build_vdf, steamcmd_command
from unity2ue.steam.vdf import dumps


def _png(path: Path, w: int, h: int, alpha: bool = False) -> Path:
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk)
    return path


def _jpg(path: Path, w: int, h: int) -> Path:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8" + app0 + sof + b"\xff\xd9")
    return path


@pytest.fixture()
def steam_project(tmp_path, sample_project):
    """Proyecto UE convertido + steam init desde Unity + integrate (copia propia, se modifica)."""
    out = tmp_path / "ue"
    convert_project(sample_project, out, ConversionConfig(project_name="Sample Game"), log=lambda _m: None)
    init_steam(out, unity_project=sample_project, log=lambda _m: None)
    integrate(out, log=lambda _m: None)
    return out


def test_detect_steamworks_net(sample_project):
    det = detect_unity_steam(sample_project)
    assert det["sdk"] == "Steamworks.NET"
    assert det["app_id"] == 480
    assert det["achievements"] == ["ACH_WIN_ONE_GAME"]
    assert {s["id"]: s["type"] for s in det["stats"]} == {"NumGames": "int", "FeetTraveled": "float"}
    assert det["leaderboards"] == [{"id": "HighScores", "sort": "descending", "display": "numeric"}]
    assert det["rich_presence_tokens"] == ["#Status_InMenu", "#Status_Victory"]
    assert det["files"] == ["Assets/Scripts/SteamStats.cs"]


def test_conversion_flags_steam(converted):
    assert any(i["source"] == "steam" and i["severity"] == "manual" for i in converted.issues)


def test_init_fills_config_and_refuses_overwrite(steam_project, sample_project):
    cfg = steam_config.load(steam_project)
    assert cfg["app_id"] == 480 and cfg["game_name"] == "Sample Game"
    assert cfg["platforms"] == {"Win64": {"depot_id": 481, "config": "Shipping"}}
    assert cfg["achievements"][0]["id"] == "ACH_WIN_ONE_GAME"
    assert set(cfg["rich_presence"]) == {"english", "spanish"}
    assert (steam_project / "Steam/store/screenshots").is_dir()
    assert (steam_project / "Steam/achievements/LEEME.txt").exists()
    with pytest.raises(FileExistsError):
        init_steam(steam_project)


def test_integrate_project_files(steam_project):
    up = json.loads((steam_project / "SampleGame.uproject").read_text())
    enabled = {p["Name"] for p in up["Plugins"] if p["Enabled"]}
    assert {"OnlineSubsystem", "OnlineSubsystemSteam", "SteamShared", "PythonScriptPlugin"} <= enabled
    assert "SteamSockets" not in enabled
    ini = (steam_project / "Config/DefaultEngine.ini").read_text()
    assert "DefaultPlatformService=Steam" in ini and "SteamDevAppId=480" in ini
    assert "GlobalDefaultGameMode" in ini  # lo generado por convert sigue ahí
    build_cs = (steam_project / "Source/SampleGame/SampleGame.Build.cs").read_text()
    assert '"Steamworks"' in build_cs and "UNITY2UE_WITH_STEAM=1" in build_cs
    assert build_cs.rstrip().endswith("}\n}") or build_cs.rstrip().endswith("}")
    assert build_cs.index("unity2ue steam") < build_cs.rindex("\t}\n}")
    h = (steam_project / "Source/SampleGame/Steam/SteamIntegrationSubsystem.h").read_text()
    cpp = (steam_project / "Source/SampleGame/Steam/SteamIntegrationSubsystem.cpp").read_text()
    assert "SAMPLEGAME_API USteamIntegrationSubsystem" in h and "{{API}}" not in h
    for src in (h, cpp):
        assert src.count("{") == src.count("}")
    assert cpp.count("#if") == cpp.count("#endif")
    ids = (steam_project / "Source/SampleGame/Steam/SteamIds.h").read_text()
    assert 'ACH_WIN_ONE_GAME = TEXT("ACH_WIN_ONE_GAME")' in ids
    assert 'Status_InMenu = TEXT("#Status_InMenu")' in ids
    vdf = (steam_project / "Steam/richpresence/english.vdf").read_text()
    assert '"Language"\t\t"english"' in vdf and '"#Status_Victory"' in vdf


def test_integrate_is_idempotent_and_survives_reconvert(steam_project, sample_project):
    assert integrate(steam_project, log=lambda _m: None) == []
    convert_project(sample_project, steam_project, ConversionConfig(project_name="Sample Game"), log=lambda _m: None)
    ini = (steam_project / "Config/DefaultEngine.ini").read_text()
    assert ini.count(">>> unity2ue steam") == 1 and "SteamDevAppId=480" in ini
    assert (steam_project / "Source/SampleGame/SampleGame.Build.cs").read_text().count(">>> unity2ue steam") == 1
    assert "OnlineSubsystemSteam" in (steam_project / "SampleGame.uproject").read_text()
    assert integrate(steam_project, log=lambda _m: None) == []


def test_networking_uses_steam_sockets(steam_project):
    cfg = steam_config.load(steam_project)
    cfg["networking"] = True
    cfg["app_id"] = 2345670
    integrate(steam_project, cfg, log=lambda _m: None)
    ini = (steam_project / "Config/DefaultEngine.ini").read_text()
    assert "SteamSocketsNetDriver" in ini and "SteamDevAppId=2345670" in ini and "SteamDevAppId=480" not in ini
    assert "SteamSockets" in (steam_project / "SampleGame.uproject").read_text()


def test_upsert_block_replaces_in_place():
    text = "a\n; >>> unity2ue steam\nold\n; <<< unity2ue steam\nb\n"
    new = upsert_block(text, "; >>> unity2ue steam\nnew\n; <<< unity2ue steam\n", ";")
    assert new == "a\n; >>> unity2ue steam\nnew\n; <<< unity2ue steam\nb\n"


def test_validate_rules():
    cfg = steam_config._merge(steam_config.DEFAULTS, {
        "app_id": 1000, "set_live_branch": "default",
        "platforms": {"Win64": {"depot_id": 1001}, "Linux": {"depot_id": 1001}, "PS5": {"depot_id": 1003}},
        "achievements": [{"id": "BAD ID"}, {"id": "OK", "name": "x", "description": "y"},
                         {"id": "OK", "name": "x", "description": "y"}],
        "stats": [{"id": "s", "type": "double"}],
        "leaderboards": [{"id": "lb", "sort": "up"}],
        "rich_presence": {"english": {"Status": "x"}},
        "store": {"short_description": "x" * 301},
    })
    errors = [m for s, m in steam_config.validate(cfg) if s == "error"]
    text = "\n".join(errors)
    for needle in ("'default'", "repetido", "PS5", "BAD ID", "Logro 'OK' repetido", "Estadística 's': type", "sort",
                   "'Status'", "301"):
        assert needle in text, needle
    ok = steam_config._merge(steam_config.DEFAULTS, {"app_id": 1000, "platforms": {"Win64": {"depot_id": 1001}},
                                                     "store": {"short_description": "Un juego."}})
    assert steam_config.validate(ok) == []


def test_vdf_escaping_and_duplicate_keys():
    text = dumps("AppBuild", [("Desc", 'v1 "beta" C:\\x'), ("Depots", [("1", [("FileExclusion", "*.pdb"),
                                                                              ("FileExclusion", "*.sym")])])])
    assert '"Desc"\t\t"v1 \\"beta\\" C:\\\\x"' in text
    assert text.count('"FileExclusion"') == 2
    assert text.count("{") == text.count("}") == 3


def test_image_info(tmp_path):
    assert image_info(_png(tmp_path / "a.png", 920, 430)) == ("png", 920, 430)
    assert image_info(_jpg(tmp_path / "b.jpg", 1920, 1080)) == ("jpg", 1920, 1080)
    assert png_has_alpha(_png(tmp_path / "c.png", 10, 10, alpha=True))
    assert not png_has_alpha(tmp_path / "a.png")
    (tmp_path / "d.png").write_bytes(b"nope")
    assert image_info(tmp_path / "d.png") is None


def test_store_assets(tmp_path):
    store = tmp_path / "store"
    for key, (_d, w, h, required) in STORE_ASSETS.items():
        if required:
            _png(store / f"{key}.png", w, h, alpha=key == "library_logo")
    for i in range(5):
        _jpg(store / "screenshots" / f"shot{i}.jpg", 1920, 1080)
    assert check_store_assets(store) == []
    _png(store / "header_capsule.png", 460, 215)  # tamaño antiguo
    _png(store / "library_logo.png", 1280, 400)  # sin alfa
    (store / "screenshots" / "shot4.jpg").unlink()
    msgs = [m for _s, m in check_store_assets(store)]
    assert any("header_capsule.png: 460x215" in m for m in msgs)
    assert any("transparencia" in m for m in msgs)
    assert any("4 capturas" in m for m in msgs)


def test_achievement_icons(tmp_path):
    ach = [{"id": "ACH_A"}]
    _png(tmp_path / "ACH_A.png", 256, 256)
    _png(tmp_path / "ACH_A_locked.png", 128, 128)
    msgs = [m for _s, m in check_achievement_icons(tmp_path, ach)]
    assert len(msgs) == 1 and "128x128" in msgs[0]


def test_checks_and_checklist(steam_project):
    issues = run_checks(steam_project)
    msgs = "\n".join(m for _s, m in issues)
    assert "Plugins sin activar" not in msgs and "DefaultEngine.ini no tiene" not in msgs
    assert "SteamStats.cpp: aún contiene llamadas de Steamworks.NET" in msgs
    assert main(["steam", "check", str(steam_project)]) == 1
    checklist = (steam_project / "Steam/checklist.md").read_text()
    for needle in ("`ACH_WIN_ONE_GAME`", "`NumGames` | INT", "`HighScores` | descending", "WinAppDataLocal",
                   "SampleGame/Saved/SaveGames", "| Win64 | 481 | windows | `SampleGame.exe` |"):
        assert needle in checklist, needle


def test_buildcookrun_command(tmp_path):
    up = tmp_path / "Game.uproject"
    cmd = buildcookrun_command(Path("/UE"), up, "Win64")
    assert "BuildCookRun" in cmd and "-platform=Win64" in cmd and "-clientconfig=Shipping" in cmd
    assert "-nodebuginfo" in cmd and "-prereqs" in cmd
    assert any(c.startswith("-archivedirectory=") and c.endswith(str(Path("Steam/build/Win64"))) for c in cmd)
    dev = buildcookrun_command(Path("/UE"), up, "Linux", "Development")
    assert "-nodebuginfo" not in dev and "-prereqs" not in dev
    assert archive_dir(tmp_path, "Linux") == tmp_path / "Steam/build/Linux/Linux"


def test_app_build_vdf(steam_project):
    cfg = steam_config.load(steam_project)
    cfg["platforms"]["Linux"] = {"depot_id": 482}
    text = app_build_vdf(steam_project, cfg, description="v1", preview=True)
    assert '"AppID"\t\t"480"' in text and '"SetLive"\t\t"beta"' in text and '"Preview"\t\t"1"' in text
    assert '"LocalPath"\t\t"Win64/Windows/*"' in text and '"LocalPath"\t\t"Linux/Linux/*"' in text
    assert '"481"' in text and '"482"' in text and '"steam_appid.txt"' in text
    with pytest.raises(ValueError):
        app_build_vdf(steam_project, cfg, branch="default")
    cmd = steamcmd_command(Path("steamcmd"), "builder", Path("x.vdf"))
    assert cmd[1:3] == ["+login", "builder"] and cmd[3] == "+run_app_build" and cmd[-1] == "+quit"


def test_upload_requires_build(steam_project, capsys):
    assert main(["steam", "upload", str(steam_project), "--account", "b", "--dry-run"]) == 1
    assert "steam build" in capsys.readouterr().out


def test_steam_ids_header_dlc():
    cfg = steam_config._merge(steam_config.DEFAULTS, {"app_id": 10, "dlc": [{"app_id": 11, "name": "Season Pass"}]})
    assert "inline constexpr int64 Season_Pass = 11;" in steam_ids_header(cfg)
