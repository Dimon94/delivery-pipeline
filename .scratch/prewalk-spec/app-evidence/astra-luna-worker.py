def advance(phase, event):
    if phase == "idle" and event == "start":
        return "ready"
    if phase == "ready" and event == "finish":
        return "done"
    if phase == "done" and event == "reset":
        return "idle"
    raise ValueError((phase, event))


if __name__ == "__main__":
    assert advance("idle", "start") == "ready"
    assert advance("ready", "finish") == "done"
    assert advance("done", "reset") == "idle"
    for phase, event in (("idle", "finish"), ("ready", "start"), ("done", "finish"), ("ready", "reset")):
        try:
            advance(phase, event)
        except ValueError:
            pass
        else:
            raise AssertionError((phase, event))
