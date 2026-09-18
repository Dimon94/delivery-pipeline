def apply(state, event):
    if event.get("kind") != "start":
        raise NotImplementedError
    if state.get("phase") != "idle" or "id" not in event:
        raise ValueError("start requires idle phase and an event id")

    return {
        **state,
        "phase": "starting",
        "seen": [*state["seen"], event["id"]],
    }
