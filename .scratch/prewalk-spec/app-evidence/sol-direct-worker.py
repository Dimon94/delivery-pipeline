def advance(phase, event):
    if phase == "idle" and event == "start":
        return "ready"
    if phase == "ready" and event == "finish":
        return "done"
    raise ValueError(f"invalid transition: {phase!r} + {event!r}")
