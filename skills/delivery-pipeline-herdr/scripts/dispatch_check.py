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
elif args[:2] in (["agent", "start"], ["agent", "prompt"], ["pane", "rename"], ["pane", "close"], ["workspace", "rename"]):
    out({})
else:
    raise SystemExit(2)
'''


def fixture_config(root: Path) -> tuple[Path, Path]:
    spec = importlib.util.spec_from_file_location(
        "model_config", HERE.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    config = root / ".config/delivery-pipeline/model-roles.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(mc.valid_fixture()))
    evidence = root / "evidence.json"
    evidence.write_text(json.dumps({"pi": {"binary": True, "models": {"provider/model": ["high", "low"]}}}))
    return config, evidence


GOOD_MAP = ("<!-- wayfinder-lane-registry:v2 -->\n```yaml\nlane_id: map-demo\nrole: map\n```\n\n"
            "## Coordinator Recovery\n\nMap/Spec：x\nRegistry：x\nGate/状态：x\n现场：x\n证据：x\n"
            "下一步：fan-in；合同入口: a.md§B\n")


TAB = "#1 实施"


def run(root: Path, lane: str, state: dict, *, env_extra=None, packet="packet", map_text=GOOD_MAP,
        extra=(), config_document=None, probe_evidence=None):
    (root / "state.json").write_text(json.dumps(state))
    (root / "calls.jsonl").write_text("")
    config, evidence = fixture_config(root)
    if config_document is not None:
        config.write_text(json.dumps(config_document))
    if probe_evidence is not None:
        evidence.write_text(json.dumps(probe_evidence))
    (root / "packet.md").write_text(packet)
    registry = root / f"registry-{lane}.md"
    map_registry = root / "registry-map-demo.md"
    map_registry.write_text(map_text)
    env = {**os.environ, "HOME": str(root), "PATH": f"{root}:{os.environ['PATH']}", "HERDR_ENV": "1",
           "HERDR_WORKSPACE_ID": "w1", "HERDR_TAB_ID": "w1:t1", "HERDR_PANE_ID": "w1:p1",
           "DP_LANE_WATCH": str(root / "watch"), **(env_extra or {})}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence", str(evidence),
         "--task", "backend", "--output-mode", "commit", "--lane", lane, "--work-item", "https://x/1",
         "--title", "#1 演示", "--tab-prefix", TAB, "--worktree", str(root), "--branch", "b", "--base", "abc",
         "--packet", str(root / "packet.md"), "--registry", str(registry),
         "--map-registry", str(map_registry), *extra],
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
        sys.path.insert(0,str(HERE.parents[1]/"delivery-pipeline/scripts"))
        import lane_registry
        actual,_ = lane_registry.read(registry,"lane-a")
        if actual.get("state") != "running" or actual.get("herdr",{}).get("pane_id") != "w1:p2" or actual.get("agent") != "pi":
            failures.append("registry missing running state, herdr overlay or frozen plan")
        rev = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True,
                             text=True).stdout.strip() or "Unknown"  # 无 .git（如 pre-commit 导出树）
        if f"contract_rev: {rev}" not in text:
            failures.append("registry missing contract_rev = skill repo HEAD at dispatch")
        if "map: map-demo" not in text:
            failures.append("registry missing map = map registry lane_id")
        if not any(c[:2] == ["tab", "create"] and TAB in c for c in calls):
            failures.append("first lane did not open worker tab #1 实施")
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

        result, registry, calls = run(root, "lane-shadow", base, extra=("--config", str(root / "overlay.json")))
        if result.returncode == 0 or calls or registry.exists() or "requires the setup model-roles.json" not in result.stdout:
            failures.append("map-local work config was not rejected before herdr")

        # 2. 已有 active writer → 拒绝且不调用 herdr。
        result, _, calls = run(root, "lane-a", json.loads(json.dumps(base)))
        if result.returncode == 0 or calls:
            failures.append("active registry writer was not rejected before herdr")

        # 3. worker tab 未满 → split 进同一 tab，不开新 tab。
        state = json.loads(json.dumps(base))
        state["tabs"].append({"tab_id": "w1:t2", "label": TAB, "pane_count": 1, "workspace_id": "w1"})
        state["panes"].append({"pane_id": "w1:p2", "tab_id": "w1:t2", "workspace_id": "w1"})
        result, registry, calls = run(root, "lane-b", state)
        if result.returncode != 0 or any(c[:2] == ["tab", "create"] for c in calls) \
                or not any(c[:2] == ["pane", "split"] and "right" in c for c in calls):
            failures.append("non-full worker tab was not reused via right split")

        # 4. 满 tab → 开 <前缀>-2。
        state = json.loads(json.dumps(base))
        state["tabs"].append({"tab_id": "w1:t2", "label": TAB, "pane_count": 4, "workspace_id": "w1"})
        result, _, calls = run(root, "lane-c", state)
        if not any(c[:2] == ["tab", "create"] and f"{TAB}-2" in c for c in calls):
            failures.append("full worker tab did not overflow to <prefix>-2")

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

        # 7. lane 名超过 Herdr agent 名 32 字符上限 → herdr 调用前拒绝，不写 registry。
        long_lane = "refresh-dd-289-oauth-repair-tickets-r1"
        result, registry, calls = run(root, long_lane, json.loads(json.dumps(base)))
        if result.returncode == 0 or calls or registry.exists() or "32" not in result.stdout:
            failures.append("over-long lane name was not rejected before herdr")

        # 8. packet owner 已移出交付链路（ticket-sizing）→ 无 --off-chain-reason 时拒绝；
        #    给出理由时派发并把理由写入 registry。
        sizing = "Owner：ticket-sizing；/x/skills/ticket-sizing/SKILL.md；pi file-based owner invocation\n"
        result, registry, calls = run(root, "lane-f", json.loads(json.dumps(base)), packet=sizing)
        if result.returncode == 0 or calls or registry.exists():
            failures.append("off-chain owner dispatched without --off-chain-reason")
        result, registry, _ = run(root, "lane-g", json.loads(json.dumps(base)), packet=sizing,
                                  extra=("--off-chain-reason", "用户要求单独校准预算"))
        if result.returncode != 0 or "off_chain_reason: 用户要求单独校准预算" not in registry.read_text():
            failures.append("off-chain owner with reason was not dispatched/recorded")

        # 9. map registry 不合格（模板外章节）→ herdr 调用前拒绝并指向 recovery_record.py。
        bad_map = GOOD_MAP + "\n## 批次 01 结果\n\n- 长篇结果\n"
        result, registry, calls = run(root, "lane-h", json.loads(json.dumps(base)), map_text=bad_map)
        if result.returncode == 0 or calls or registry.exists() or "recovery_record.py" not in result.stdout:
            failures.append("non-conforming map registry did not block dispatch")

        # 10. Antigravity 经 Herdr --kind agy 派发并写入 herdr-agy-pane。
        spec = importlib.util.spec_from_file_location(
            "model_config", HERE.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py")
        mc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mc)
        ag_doc = mc.valid_fixture()
        ag_doc["work"]["backend"] = {"agent": "antigravity", "model": "gemini-4-neon", "effort": "xhigh", "fallbacks": []}
        ag_ev = {"antigravity": {"binary": True, "models": {"gemini-4-neon": ["low", "medium", "high", "xhigh"]}}}
        result, registry, calls = run(root, "lane-agy", json.loads(json.dumps(base)),
                                      config_document=ag_doc, probe_evidence=ag_ev)
        ag_start = next((c for c in calls if c[:2] == ["agent", "start"]), [])
        ag_row, _ = lane_registry.read(registry, "lane-agy") if registry.exists() else ({}, None)
        wt_real = os.path.realpath(str(root))
        expected_ag_settings = json.dumps({"trustedWorkspaces": [wt_real]}, ensure_ascii=False)
        if (result.returncode != 0 or ag_row.get("runtime") != "herdr-agy-pane" or ag_row.get("agent") != "antigravity"
                or ag_start != ["agent", "start", "lane-agy", "--kind", "agy", "--pane", "w1:p2", "--",
                                "--model", "gemini-4-neon", "--effort", "xhigh", "--dangerously-skip-permissions",
                                "--settings", expected_ag_settings]):
            failures.append(f"antigravity herdr dispatch failed: rc={result.returncode} row={ag_row} start={ag_start}")

        # 10b. Claude 派发预写 DP_CLAUDE_CONFIG_PATH 目录信任；Codex 派发注入 projects.<wt>.trust_level。
        cl_doc = mc.valid_fixture()
        cl_doc["work"]["backend"] = {"agent": "claude", "model": "claude-opus-5-5", "effort": "medium", "fallbacks": []}
        cl_ev = {"claude": {"binary": True, "models": {"claude-opus-5-5": ["low", "medium", "high"]}}}
        claude_cfg = root / "claude-trust.json"
        result, _, _ = run(root, "lane-cl", json.loads(json.dumps(base)),
                           config_document=cl_doc, probe_evidence=cl_ev,
                           env_extra={"DP_CLAUDE_CONFIG_PATH": str(claude_cfg)})
        cl_saved = json.loads(claude_cfg.read_text(encoding="utf-8")) if claude_cfg.exists() else {}
        if result.returncode != 0 or cl_saved.get("projects", {}).get(wt_real, {}).get("hasTrustDialogAccepted") is not True:
            failures.append(f"claude herdr dispatch did not pretrust worktree: rc={result.returncode} saved={cl_saved}")

        cx_doc = mc.valid_fixture()
        cx_doc["work"]["backend"] = {"agent": "codex", "model": "gpt-6.2-sol", "effort": "high", "fallbacks": []}
        cx_ev = {"codex": {"binary": True, "models": {"gpt-6.2-sol": ["low", "medium", "high"]}}}
        result, _, calls = run(root, "lane-cx", json.loads(json.dumps(base)),
                               config_document=cx_doc, probe_evidence=cx_ev)
        cx_start = next((c for c in calls if c[:2] == ["agent", "start"]), [])
        if result.returncode != 0 or f'projects.{json.dumps(wt_real)}.trust_level="trusted"' not in cx_start:
            failures.append(f"codex herdr dispatch omitted trust_level override: rc={result.returncode} start={cx_start}")

        # 11. 可视化短命名：自动补齐 Linear Issue 号、同步 workspace rename、超宽在 herdr 调用前拒绝。
        result, registry, calls = run(
            root, "lane-vis", json.loads(json.dumps(base)),
            extra=(
                "--work-item", "https://linear.app/erplus/issue/JB-548/demo",
                "--title", "扩表Job",
                "--tab-prefix", "JB-512 实施",
                "--workspace-label", "JB-512 零停机 M3",
            ),
        )
        if (result.returncode != 0
                or not any(c == ["workspace", "rename", "w1", "JB-512 零停机 M3"] for c in calls)
                or not any(c[:2] == ["tab", "create"] and "JB-512 实施" in c for c in calls)
                or not any(c == ["pane", "rename", "w1:p2", "JB-548 扩表Job"] for c in calls)):
            failures.append(f"visual naming dispatch failed: rc={result.returncode} calls={calls}")
        result, registry, calls = run(
            root, "lane-wide", json.loads(json.dumps(base)),
            extra=("--workspace-label", "JB-512 生产分层零停机发布体系全量方案"),
        )
        if result.returncode == 0 or calls or registry.exists() or "exceeds limit 20" not in result.stdout:
            failures.append(f"over-wide workspace label not rejected before herdr: {result.stdout}")
        # 12. 只有编号、没有中文简写的 tab 前缀与 pane 标题，在 herdr 调用前拒绝。
        for lane, flags in (("lane-bare-tab", ("--tab-prefix", "DD-654")),
                            ("lane-bare-pane", ("--title", "dd-655"))):
            result, registry, calls = run(root, lane, json.loads(json.dumps(base)), extra=flags)
            if result.returncode == 0 or calls or registry.exists() or "中文简写" not in result.stdout:
                failures.append(f"label without CJK short name not rejected before herdr {flags}: {result.stdout}")

    for failure in failures:
        print(f"FAIL {failure}")
    print("dispatch_check: " + ("fail" if failures else "pass"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
