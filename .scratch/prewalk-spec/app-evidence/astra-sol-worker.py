def advance(phase, event):
    if phase == "idle" and event == "start":
        return "ready"
    if phase == "ready" and event == "finish":
        return "done"
    raise ValueError((phase, event))


if __name__ == "__main__":
    assert advance("idle", "start") == "ready"
    assert advance("ready", "finish") == "done"
    try:
        advance("idle", "finish")
    except ValueError:
        pass
    else:
        raise AssertionError("非法转换必须抛出 ValueError")
