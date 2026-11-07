#!/usr/bin/env python3
"""用 fake Herdr 复跑 dispatch.py：落位、启动、投递、watcher、registry 状态与失败收口。"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "dispatch.py"

FAKE_HERDR = r'''import json, sys
from pathlib import Path
root = Path(__file__).parent
state = json.loads((root / "state.json").read_text())
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as s:
    s.write(json.dumps(args) + "\n")
def out(v): print(json.dumps({"result": v}))
def save(): (root / "state.json").write_text(json.dumps(state))
W = "w1"
if args[:2] == ["pane", "current"]:
    out({"pane": {"workspace_id": W, "tab_id": "w1:t1", "pane_id": "w1:p1"}})
elif args[:2] == ["tab", "list"]:
    out({"tabs": state["tabs"]})
elif args[:2] == ["pane", "list"]:
    out({"panes": state["panes"]})
elif args[:2] == ["pane", "split"]:
    anchor = next(p for p in state["panes"] if p["pane_id"] == args[3])
    pid = "w1:p%d" % (len(state["panes"]) + 1)
    state["panes"].append({"pane_id": pid, "tab_id": anchor["tab_id"], "workspace_id": W})
    for t in state["tabs"]:
        if t["tab_id"] == anchor["tab_id"]:
            t["pane_count"] += 1
    save(); out({"pane": {"pane_id": pid}})
elif args[:2] == ["tab", "create"]:
    tid = "w1:t%d" % (len(state["tabs"]) + 1)
    pid = "w1:p%d" % (len(state["panes"]) + 1)
    state["tabs"].append({"tab_id": tid, "label": args[args.index("--label") + 1], "pane_count": 1, "workspace_id": W})
    state["panes"].append({"pane_id": pid, "tab_id": tid, "workspace_id": W})
    save(); out({"tab": {"tab_id": tid}, "root_pane": {"pane_id": pid}})
elif args[:2] == ["pane", "get"]:
    out({"pane": next(p for p in state["panes"] if p["pane_id"] == args[2])})
elif args[:2] == ["agent", "wait"]:
    raise SystemExit(0 if state.get("working", True) else 1)
elif args[:2] in (["agent", "start"], ["agent", "prompt"], ["pane", "rename"], ["pane", "close"]):
    out({})
else:
    raise SystemExit(2)
'''


def fixture_config(root: Path) -> tuple[Path, Path]:
    spec = importlib.util.spec_from_file_location(
        "model_config", HERE.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    config = root / "model-roles.json"
    config.write_text(json.dumps(mc.valid_fixture()))
    evidence = root / "evidence.json"
    evidence.write_text(json.dumps({"pi": {"binary": True, "models": {"provider/model": ["high", "low"]}}}))
    return config, evidence


def run(root: Path, lane: str, state: dict, *, env_extra=None):
    (root / "state.json").write_text(json.dumps(state))
    (root / "calls.jsonl").write_text("")
    config, evidence = fixture_config(root)
    (root / "packet.md").write_text("packet")
    registry = root / f"registry-{lane}.md"
    env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}", "HERDR_ENV": "1",
           "HERDR_WORKSPACE_ID": "w1", "HERDR_TAB_ID": "w1:t1", "HERDR_PANE_ID": "w1:p1",
           "DP_LANE_WATCH": str(root / "watch"), **(env_extra or {})}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(config), "--evidence", str(evidence),
         "--task", "backend", "--output-mode", "commit", "--lane", lane, "--work-item", "https://x/1",
         "--title", "#1 demo", "--worktree", str(root), "--branch", "b", "--base", "abc",
         "--packet", str(root / "packet.md"), "--registry", str(registry)],
        env=env, capture_output=True, text=True)
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    return result, registry, calls


def main() -> int:
    failures = []
    base = {"tabs": [{"tab_id": "w1:t1", "label": "coord", "pane_count": 1, "workspace_id": "w1"}],
            "panes": [{"pane_id": "w1:p1", "tab_id": "w1:t1", "workspace_id": "w1"}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "herdr").write_text(f"#!{sys.executable}\n" + FAKE_HERDR)
        (root / "watch").write_text(f"#!/bin/sh\necho \"$@\" > {root}/watch.args\n")
        for name in ("herdr", "watch"):
            (root / name).chmod(0o755)

        # 1. 无 worker tab → 新开 X tab；registry running；watcher 拿到 pane 坐标；stdout 单行 JSON。
        result, registry, calls = run(root, "lane-a", json.loads(json.dumps(base)))
        lines = result.stdout.strip().splitlines()
        out = json.loads(lines[-1]) if lines else {}
        if result.returncode != 0 or len(lines) != 1 or out.get("state") != "running":
            failures.append(f"happy path failed: {result.stdout} {result.stderr}")
        text = registry.read_text() if registry.exists() else ""
        if "state: running" not in text or "  pane_id: w1:p2" not in text or "agent: pi" not in text:
            failures.append("registry missing running state, herdr overlay or frozen plan")
        if not any(c[:2] == ["tab", "create"] and "X" in c for c in calls):
            failures.append("first lane did not open worker tab X")
        start = next((c for c in calls if c[:2] == ["agent", "start"]), [])
        if "--pane" not in start or start[start.index("--pane") + 1] != "w1:p2":
            failures.append("agent start not bound to placed pane")
        import time
        for _ in range(50):
            if (root / "watch.args").exists():
                break
            time.sleep(0.05)
        if not (root / "watch.args").exists() or "w1:p2 w1:p1 lane-a" not in (root / "watch.args").read_text():
            failures.append("watcher not spawned with worker/coordinator pane")

        # 2. 已有 active writer → 拒绝且不调用 herdr。
        result, _, calls = run(root, "lane-a", json.loads(json.dumps(base)))
        if result.returncode == 0 or calls:
            failures.append("active registry writer was not rejected before herdr")

        # 3. X tab 未满 → split 进同一 tab，不开新 tab。
        state = json.loads(json.dumps(base))
        state["tabs"].append({"tab_id": "w1:t2", "label": "X", "pane_count": 1, "workspace_id": "w1"})
        state["panes"].append({"pane_id": "w1:p2", "tab_id": "w1:t2", "workspace_id": "w1"})
        result, registry, calls = run(root, "lane-b", state)
        if result.returncode != 0 or any(c[:2] == ["tab", "create"] for c in calls) \
                or not any(c[:2] == ["pane", "split"] and "right" in c for c in calls):
            failures.append("non-full worker tab was not reused via right split")

        # 4. 满 tab → 开 X-2。
        state = json.loads(json.dumps(base))
        state["tabs"].append({"tab_id": "w1:t2", "label": "X", "pane_count": 4, "workspace_id": "w1"})
        result, _, calls = run(root, "lane-c", state)
        if not any(c[:2] == ["tab", "create"] and "X-2" in c for c in calls):
            failures.append("full worker tab did not overflow to X-2")

        # 5. agent 两次都未进入 working → 关 pane，registry setup_blocked，exit 1。
        state = json.loads(json.dumps(base))
        state["working"] = False
        result, registry, calls = run(root, "lane-d", state)
        prompts = [c for c in calls if c[:2] == ["agent", "prompt"]]
        if result.returncode == 0 or "state: setup_blocked" not in registry.read_text() \
                or len(prompts) != 2 or not any(c[:2] == ["pane", "close"] for c in calls):
            failures.append("non-working agent did not re-prompt once then close and block")

        # 6. 不在 Herdr 内 → 不写 registry。
        result, registry, calls = run(root, "lane-e", json.loads(json.dumps(base)), env_extra={"HERDR_ENV": ""})
        if result.returncode == 0 or registry.exists():
            failures.append("dispatch outside Herdr wrote registry or succeeded")

    for failure in failures:
        print(f"FAIL {failure}")
    print("dispatch_check: " + ("fail" if failures else "pass"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
