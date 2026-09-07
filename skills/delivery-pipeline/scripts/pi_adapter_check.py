#!/usr/bin/env python3
"""Pi TUI adapter 的隔离回归检查，不触达真实 Herdr session。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile

import pi_adapter as adapter


FAKE_HERDR = '''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

session = Path(os.environ["PI_FAKE_SESSION"])
worktree = os.environ["PI_FAKE_WORKTREE"]
pending = Path(os.environ["PI_FAKE_PENDING"])
args = sys.argv[1:]
if args[:2] == ["agent", "get"]:
    print(json.dumps({"result": {"agent": {
        "agent": "pi", "agent_status": "done", "cwd": worktree,
        "agent_session": {"kind": "path", "value": str(session)},
    }}}))
elif args[:2] == ["pane", "send-text"]:
    text = args[3]
    if not (text.startswith("/model ") or text.startswith("/thinking ")):
        raise SystemExit("unsupported fake TUI command")
    pending.write_text(json.dumps({"text": text, "returns": 0}), encoding="utf-8")
    print("{}")
elif args[:2] == ["pane", "send-keys"]:
    state = json.loads(pending.read_text(encoding="utf-8"))
    state["returns"] += 1
    if state["returns"] >= 2:
        text = state["text"]
        if text.startswith("/model "):
            provider, model_id = text[7:].split("/", 1)
            entry = {"type": "model_change", "provider": provider, "modelId": model_id}
        else:
            entry = {"type": "thinking_level_change", "thinkingLevel": text[10:]}
        with session.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\\n")
        pending.unlink()
    else:
        pending.write_text(json.dumps(state), encoding="utf-8")
    print("{}")
else:
    raise SystemExit("unsupported fake Herdr command: " + " ".join(args))
'''


def request(model: str = "openai-codex/gpt-6-astra", effort: str = "max") -> dict:
    intent = "a" * 64
    return {"request_id": f"request-{intent}", "intent_sha256": intent,
            "target_request": {"model": model, "effort": effort}}


def rejects(callable_, *args, **kwargs) -> None:
    try:
        callable_(*args, **kwargs)
    except adapter.PiAdapterError:
        return
    raise AssertionError(f"expected {callable_.__name__} to fail closed")


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="pi-adapter-") as directory:
        root = Path(directory)
        session = root / "session.jsonl"
        session.write_text(json.dumps({"type": "session", "id": "session-1", "cwd": str(root)}) + "\n",
                           encoding="utf-8")
        fake = root / "herdr"
        fake.write_text(FAKE_HERDR, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        os.environ["PI_FAKE_SESSION"] = str(session)
        os.environ["PI_FAKE_WORKTREE"] = str(root)
        os.environ["PI_FAKE_PENDING"] = str(root / "pending.json")
        result = adapter.apply_tui_switch(
            request(), pane_id="w1:p1", worktree=str(root), session_id="session-1",
            herdr=str(fake), timeout=1,
        )
        assert result["native_seam"] == "pi-tui"
        assert result["actual_model"] == "openai-codex/gpt-6-astra"
        assert result["actual_effort"] == "max"
        assert len(result["commands"]) == 2
        rejects(adapter.apply_tui_switch, request(), pane_id="w1:p1", worktree=str(root),
                session_id="other", herdr=str(fake), timeout=0.1)
        rejects(adapter.apply_tui_switch, request("openai-codex/gpt-6-astra\n/exit"),
                pane_id="w1:p1", worktree=str(root), session_id="session-1", herdr=str(fake))


if __name__ == "__main__":
    check()
    print("pi-adapter-check: pass")
