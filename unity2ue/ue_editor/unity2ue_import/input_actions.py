"""Crea InputActions + InputMappingContext (Enhanced Input) a partir del InputManager de Unity."""

from __future__ import annotations

import unreal

from .common import LOG, content_root, create_or_load, save, set_prop, settings

STEP = "input"


def _factory(*names):
    for n in names:
        cls = getattr(unreal, n, None)
        if cls is not None:
            return cls()
    return None


def _key(name: str) -> unreal.Key:
    """unreal.Key no expone key_name en Python (UE 5.8): se construye con import_text."""
    key = unreal.Key()
    if not key.import_text(name):
        raise ValueError(f"Tecla desconocida en UE: {name}")
    return key


def _set_negate(imc, action, key_name: str) -> bool:
    """Añade un modificador Negate al mapeo (la API cambió entre versiones de UE5)."""
    negate = unreal.new_object(unreal.InputModifierNegate, outer=imc)
    for prop in ("mappings", "default_key_mappings"):
        try:
            container = imc.get_editor_property(prop)
        except Exception:  # noqa: BLE001
            continue
        mappings = container.get_editor_property("mappings") if hasattr(container, "get_editor_property") \
            and not isinstance(container, (list, unreal.Array)) else container
        changed = False
        for m in mappings:
            if m.get_editor_property("action") == action and m.get_editor_property("key").export_text() == key_name:
                m.set_editor_property("modifiers", [negate])
                changed = True
        if changed:
            if mappings is container:
                imc.set_editor_property(prop, mappings)
            else:
                container.set_editor_property("mappings", mappings)
                imc.set_editor_property(prop, container)
            return True
    return False


def run() -> None:
    actions = settings().get("input_actions") or []
    if not actions:
        return
    folder = f"{content_root()}/Input"
    imc_factory = _factory("InputMappingContext_Factory", "InputMappingContextFactory")
    ia_factory = _factory("InputAction_Factory", "InputActionFactory")
    if imc_factory is None or ia_factory is None:
        LOG.warn(STEP, "EnhancedInput", "Factorías de Enhanced Input no disponibles en Python; crea las acciones a mano")
        return
    imc, _ = create_or_load("IMC_UnityDefault", folder, unreal.InputMappingContext, imc_factory)
    for a in actions:
        name = "IA_" + "".join(ch if ch.isalnum() else "_" for ch in a["name"])
        try:
            ia, _ = create_or_load(name, folder, unreal.InputAction, ia_factory)
            vt = unreal.InputActionValueType.AXIS1D if a["value_type"] == "Axis1D" else unreal.InputActionValueType.BOOLEAN
            set_prop(ia, "value_type", vt, STEP, name)
            save(ia)
            for m in a.get("mappings", []):
                imc.map_key(ia, _key(m["key"]))
                if m.get("negate") and not _set_negate(imc, ia, m["key"]):
                    LOG.warn(STEP, name, f"Añade manualmente el modificador Negate a {m['key']}")
            LOG.ok(STEP, a["name"], f"-> {folder}/{name}")
        except Exception:  # noqa: BLE001
            LOG.exception(STEP, a["name"])
    save(imc)
