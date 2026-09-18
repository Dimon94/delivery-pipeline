from copy import deepcopy


def apply(state, event):
    """Apply *event* to *state* without mutating either argument."""
    try:
        event_id = event["id"]
        kind = event["kind"]
        phase = state["phase"]
        seen = state["seen"]
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid state or event") from exc

    if event_id in seen:
        return deepcopy(state)

    next_phase = None
    updates = {}

    if kind == "start" and phase == "idle":
        next_phase = "starting"
    elif kind == "ready" and phase == "starting":
        checkpoint = event.get("checkpoint")
        if not checkpoint:
            raise ValueError("ready requires a non-empty checkpoint")
        next_phase = "ready"
        updates["checkpoint"] = checkpoint
    elif kind == "dispatch" and phase == "ready":
        if event.get("checkpoint") != state.get("checkpoint"):
            raise ValueError("dispatch checkpoint does not match")
        next_phase = "switching"
        updates["pending"] = event_id
    elif kind == "unknown" and phase == "switching":
        next_phase = "switching"
    elif kind == "ack" and phase == "switching":
        next_phase = "executing"
        updates["pending"] = None
    elif kind == "finish" and phase == "executing":
        next_phase = "review"
    elif kind == "approve" and phase == "review":
        next_phase = "reviewed"
    elif kind == "integrate" and phase == "reviewed":
        next_phase = "integrated"
    else:
        raise ValueError(f"invalid {kind!r} event in {phase!r} phase")

    result = deepcopy(state)
    result["phase"] = next_phase
    result.update(deepcopy(updates))
    result["seen"] = deepcopy(seen)
    result["seen"].append(deepcopy(event_id))
    return result
