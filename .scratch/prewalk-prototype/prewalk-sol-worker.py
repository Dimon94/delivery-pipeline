def apply(state, event):
    try:
        event_id = event["id"]
        kind = event["kind"]
        phase = state["phase"]
        seen = state["seen"]
    except (KeyError, TypeError) as exc:
        raise ValueError("state and event are missing required fields") from exc

    if event_id in seen:
        return {**state, "seen": [*seen]}

    next_state = {**state, "seen": [*seen, event_id]}

    if kind == "start" and phase == "idle":
        next_state["phase"] = "starting"
    elif kind == "ready" and phase == "starting":
        checkpoint = event.get("checkpoint")
        if not checkpoint:
            raise ValueError("ready requires a non-empty checkpoint")
        next_state["phase"] = "ready"
        next_state["checkpoint"] = checkpoint
    elif kind == "dispatch" and phase == "ready":
        if event.get("checkpoint") != state.get("checkpoint"):
            raise ValueError("dispatch checkpoint does not match")
        next_state["phase"] = "switching"
        next_state["pending"] = event_id
    elif kind == "unknown" and phase == "switching":
        pass
    elif kind == "ack" and phase == "switching":
        next_state["phase"] = "executing"
        next_state["pending"] = None
    elif kind == "finish" and phase == "executing":
        next_state["phase"] = "review"
    elif kind == "approve" and phase == "review":
        next_state["phase"] = "reviewed"
    elif kind == "integrate" and phase == "reviewed":
        next_state["phase"] = "integrated"
    else:
        raise ValueError(f"invalid {kind!r} event for {phase!r} phase")

    return next_state
