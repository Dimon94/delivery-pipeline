#!/usr/bin/env python3
"""Herdr driver_run：fake dispatch.py 下验证派发执行器、静默退出码与交回。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
RUN = HERE / "driver_run.py"
sys.path.insert(0, str(HERE.parents[1] / "delivery-pipeline" / "scripts"))
import driver  # noqa: E402

FAKE = '''import json, sys
args = sys.argv[1:]
v = lambda k: args[args.index(k) + 1]
assert "--config" not in args, f"map-local config reached dispatch: {args}"
open(v("--registry") + ".args", "w").write(json.dumps(args))
open(v("--registry"), "w").write("""<!-- wayfinder-lane-registry:v2 -->
```yaml
lane_id: %s
work_item: %s
role: backend
output_mode: commit
state: running
```
""" % (v("--lane"), v("--work-item")))
print(json.dumps({"lane_id": v("--lane"), "state": "running"}))
'''


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


FAKE_HERDR = '''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_HERDR_STATE"]))
open(os.environ["FAKE_HERDR_STATE"] + ".log", "a").write(" ".join(sys.argv[1:]) + "\\n")
kind = sys.argv[1:3]
if kind == ["pane", "list"]:
    print(json.dumps({"result": {"panes": [{"pane_id": p} for p in state["panes"]]}}))
elif kind == ["agent", "list"]:
    print(json.dumps({"result": {"agents": [{"name": n, "pane_id": p} for p, n in state["agents"].items()]}}))
elif kind == ["pane", "close"]:
    print(json.dumps({"result": {}}))
'''


def check_closeout(root: Path):
    """lane 收口后 Driver 关掉它的 pane；pane 换了 agent 时不关。"""
    import driver_run
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "herdr").write_text(FAKE_HERDR)
    (bin_dir / "herdr").chmod(0o755)
    state_file = root / "herdr.json"
    os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
    os.environ["FAKE_HERDR_STATE"] = str(state_file)
    driver_run.driver.exec_closeout = lambda *_: {"result": "closed"}
    row = {"lane_id": "T1", "herdr": json.dumps({"pane_id": "w:p2", "agent_name": "t1"})}
    state, action = {"lanes": {"T1": row}}, {"args": {"lane_id": "T1"}}

    def closeout(panes, agents):
        state_file.write_text(json.dumps({"panes": panes, "agents": agents}))
        log = Path(str(state_file) + ".log")
        log.unlink(missing_ok=True)
        receipt = driver_run.EXECUTORS["closeout"](root, state, action)
        return receipt, "pane close w:p2" in log.read_text()

    assert closeout(["w:p2"], {"w:p2": "t1"}) == ({"result": "closed"}, True)
    receipt, closed = closeout(["w:p2"], {"w:p2": "other"})
    assert receipt["result"] == "close_pending" and not closed, receipt
    assert closeout([], {}) == ({"result": "closed"}, False)  # 已不在：幂等


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        integ = root / "integ"
        integ.mkdir()
        git(integ, "init", "-q", "-b", "map")
        git(integ, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
        md = root / "map"
        md.mkdir()
        plan = {"tickets": [{"id": "T1", "wave": 1, "task": "backend", "deps": [],
                             "owner": {"name": "implement", "path": "/abs/SKILL.md", "label": "implement"}}]}
        sha = driver.plan_sha(plan)
        contract = {"ticket": "T1", "slice_id": "all", "writable": ["a.txt"], "read_first": ["README.md"],
                    "check": ["true"], "expected": "退出 0"}
        base = {"version": 1, "map": "m1", "gates": {"discovery": 1, "spec": 1, "tickets": 1}, "plan": plan,
                "plan_check": "pass", "grant": {"plan_sha": sha}, "published": "p"}
        driver.write_json(md / "driver.json", base)
        driver.persist_lanes(md, [{"lane_id": "m1", "work_item": "m1", "role": "map", "output_mode": "none",
                                   "state": "running", "integration_worktree_path": str(integ),
                                   "integration_branch": "map", "_file": str(md / "registry.md")}])
        # 没有派发合同：先要合同，不派发（ADR-0028）
        out = subprocess.run([sys.executable, str(RUN), "run", str(md)], capture_output=True, text=True)
        assert out.returncode == 10 and json.loads(out.stdout)["id"] == "contract:T1", (out.returncode, out.stdout, out.stderr)
        base["contracts"] = {"T1": contract}
        driver.write_json(md / "driver.json", base)
        fake = root / "dispatch.py"
        fake.write_text(FAKE)
        env = {**os.environ, "DP_DISPATCH": str(fake)}
        # 缺 dispatch / transport.herdr：交回 coordinator，退出 10
        out = subprocess.run([sys.executable, str(RUN), "run", str(md)], capture_output=True, text=True, env=env)
        action = json.loads(out.stdout)
        assert out.returncode == 10 and action["id"] == "dispatch:T1", (out.returncode, out.stdout, out.stderr)
        # transport 没给这张票的中文短名：不拿 lane 编号凑名字，交回 coordinator。
        dispatch_cfg = {"config": "/map-local.json", "evidence": "/e.json"}
        herdr_cfg = {"worktrees_root": str(root / "wt"), "tab_prefix": "M1 实施"}
        driver.write_json(md / "driver.json", {**base, "dispatch": dispatch_cfg, "transport": {"herdr": herdr_cfg}})
        out = subprocess.run([sys.executable, str(RUN), "run", str(md)], capture_output=True, text=True, env=env)
        assert out.returncode == 10 and json.loads(out.stdout)["id"] == "dispatch:T1", (out.returncode, out.stdout, out.stderr)
        assert not (md / "registry-T1.md.args").exists(), "dispatch ran without a 中文短名"
        # 旧 map 带自选配置路径时，程序只传 evidence，结果 wait；pane 标题取 transport.herdr.labels。
        herdr_cfg["labels"] = {"T1": "上传接口"}
        driver.write_json(md / "driver.json", {**base, "dispatch": dispatch_cfg, "transport": {"herdr": herdr_cfg}})
        out = subprocess.run([sys.executable, str(RUN), "run", str(md)], capture_output=True, text=True, env=env)
        assert out.returncode == 0 and json.loads(out.stdout)["action"] == "wait", (out.returncode, out.stdout, out.stderr)
        sent = json.loads((md / "registry-T1.md.args").read_text())
        assert sent[sent.index("--title") + 1] == "上传接口" and sent[sent.index("--tab-prefix") + 1] == "M1 实施", sent
        packet = (md / "packets" / "T1.md").read_text()
        assert "Owner：implement; /abs/SKILL.md; implement" in packet and "HERDR_ROLE_DISPATCH_PACKET.md" in packet, packet
        assert "范围：只改 a.txt" in packet and "输入：先读 README.md" in packet, packet  # packet 由合同生成
        assert (root / "wt" / "T1").is_dir()
        # watch：终态行交回后 Driver 自己 fan_in（fake commit 非法 → 合同无法核对 → blocked → 验收诊断，需唤醒）
        out = subprocess.run([sys.executable, str(RUN), "watch", str(md), "LANE_DONE T1 deadbeef"],
                             capture_output=True, text=True, env={**env, "DP_DISPATCH": "/nonexistent"})
        action = json.loads(out.stdout)
        assert out.returncode == 10 and action["id"] == "judge:diagnose:T1:1", (out.returncode, out.stdout, out.stderr)
        check_closeout(root)
    print("driver_run check: pass")


if __name__ == "__main__":
    main()
