def apply(state, event):
    if not isinstance(event, dict) or "id" not in event or "kind" not in event:
        raise ValueError("event requires id and kind")

    event_id = event["id"]
    if event_id in state["seen"]:
        return {**state, "seen": [*state["seen"]]}

    kind = event["kind"]
    phase = state["phase"]

    if kind == "start" and phase == "idle":
        return _success(state, event_id, phase="starting")
    if kind == "ready" and phase == "starting":
        checkpoint = event.get("checkpoint")
        if checkpoint:
            return _success(state, event_id, phase="ready", checkpoint=checkpoint)
    if kind == "dispatch" and phase == "ready":
        if "checkpoint" in event and event["checkpoint"] == state["checkpoint"]:
            return _success(state, event_id, phase="switching", pending=event_id)
    if kind == "unknown" and phase == "switching":
        return _success(state, event_id)
    if kind == "ack" and phase == "switching":
        return _success(state, event_id, phase="executing", pending=None)
    if kind == "finish" and phase == "executing":
        return _success(state, event_id, phase="review")
    if kind == "approve" and phase == "review":
        return _success(state, event_id, phase="reviewed")
    if kind == "integrate" and phase == "reviewed":
        return _success(state, event_id, phase="integrated")

    raise ValueError(f"invalid event: {kind}")


def _success(state, event_id, **changes):
    result = {**state, **changes}
    result["seen"] = [*state["seen"], event_id]
    return result
