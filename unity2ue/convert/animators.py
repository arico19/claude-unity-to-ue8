"""Exporta Animator Controllers (.controller) a JSON para recrearlos como Animation Blueprints."""

from __future__ import annotations

from typing import Any

from ..unity.yaml_parser import ref_file_id
from .context import ConversionContext

PARAM_TYPES = {1: "Float", 3: "Int", 4: "Bool", 9: "Trigger"}
CONDITION_MODES = {1: "If", 2: "IfNot", 3: "Greater", 4: "Less", 6: "Equals", 7: "NotEqual"}


def convert_animator(ctx: ConversionContext, unity_path: str) -> dict[str, Any]:
    doc = ctx.project.load(unity_path)
    controller = next((o for o in doc if o.type_name == "AnimatorController"), None)
    out: dict[str, Any] = {
        "unity_path": unity_path,
        "name": ctx.naming.imported_name(unity_path),
        "ue_anim_blueprint_path": ctx.naming.asset_path(unity_path, prefix="ABP_"),
        "parameters": [],
        "layers": [],
    }
    if controller is None:
        return out
    for p in controller.get("m_AnimatorParameters") or []:
        out["parameters"].append({
            "name": p.get("m_Name"),
            "type": PARAM_TYPES.get(int(p.get("m_Type", 0) or 0), "Unknown"),
            "default": p.get("m_DefaultFloat", p.get("m_DefaultInt", p.get("m_DefaultBool"))),
        })

    def state_machine(fid: int, depth: int = 0) -> dict[str, Any]:
        sm = doc.get(fid)
        if sm is None or depth > 8:
            return {}
        states = []
        for cs in sm.get("m_ChildStates") or []:
            st = doc.get(ref_file_id(cs.get("m_State")))
            if st is None:
                continue
            motion = ctx.asset_ref(st.get("m_Motion"), unity_path)
            blend = None
            if motion and motion.get("kind") == "local":
                bt = doc.get(motion["fileID"])
                if bt is not None and bt.type_name == "BlendTree":
                    blend = {
                        "parameter": bt.get("m_BlendParameter"),
                        "parameter_y": bt.get("m_BlendParameterY"),
                        "type": bt.get("m_BlendType"),
                        "children": [
                            {"motion": ctx.asset_ref(c.get("m_Motion"), unity_path), "threshold": c.get("m_Threshold"),
                             "position": c.get("m_Position")}
                            for c in bt.get("m_Childs") or []
                        ],
                    }
                    motion = None
            transitions = []
            for tr_ref in st.get("m_Transitions") or []:
                tr = doc.get(ref_file_id(tr_ref))
                if tr is None:
                    continue
                dst = doc.get(ref_file_id(tr.get("m_DstState")))
                transitions.append({
                    "to": dst.get("m_Name") if dst is not None else ("Exit" if tr.get("m_IsExit") else None),
                    "has_exit_time": bool(int(tr.get("m_HasExitTime", 0) or 0)),
                    "exit_time": tr.get("m_ExitTime"),
                    "duration": tr.get("m_TransitionDuration"),
                    "conditions": [
                        {"mode": CONDITION_MODES.get(int(c.get("m_ConditionMode", 0) or 0), c.get("m_ConditionMode")),
                         "parameter": c.get("m_ConditionEvent"), "threshold": c.get("m_EventTreshold")}
                        for c in tr.get("m_Conditions") or []
                    ],
                })
            states.append({
                "name": st.get("m_Name"),
                "motion": motion,
                "blend_tree": blend,
                "speed": st.get("m_Speed", 1),
                "loop_hint": st.get("m_WriteDefaultValues"),
                "transitions": transitions,
            })
        default = doc.get(ref_file_id(sm.get("m_DefaultState")))
        any_transitions = []
        for tr_ref in sm.get("m_AnyStateTransitions") or []:
            tr = doc.get(ref_file_id(tr_ref))
            if tr is not None:
                dst = doc.get(ref_file_id(tr.get("m_DstState")))
                any_transitions.append({"to": dst.get("m_Name") if dst is not None else None,
                                        "conditions": [{"parameter": c.get("m_ConditionEvent"),
                                                        "mode": CONDITION_MODES.get(int(c.get("m_ConditionMode", 0) or 0))}
                                                       for c in tr.get("m_Conditions") or []]})
        return {
            "name": sm.get("m_Name"),
            "default_state": default.get("m_Name") if default is not None else None,
            "states": states,
            "any_state_transitions": any_transitions,
            "sub_state_machines": [state_machine(ref_file_id(c.get("m_StateMachine")), depth + 1)
                                   for c in sm.get("m_ChildStateMachines") or []],
        }

    for layer in controller.get("m_AnimatorLayers") or []:
        out["layers"].append({
            "name": layer.get("m_Name"),
            "weight": layer.get("m_DefaultWeight", 1),
            "blending": "Additive" if int(layer.get("m_BlendingMode", 0) or 0) == 1 else "Override",
            "mask": ctx.asset_ref(layer.get("m_Mask"), unity_path),
            "state_machine": state_machine(ref_file_id(layer.get("m_StateMachine"))),
        })
    return out
