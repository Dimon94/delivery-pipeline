#!/usr/bin/env python3
"""从看板 CLI 验收 Herdr 现场探针（S20）。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


SNAPSHOT = Path(__file__).resolve().parents[2] / "delivery-pipeline/scripts/board_snapshot.py"
FAKE_HERDR = """
import json
import os
from pathlib import Path
import sys
from time import sleep

with Path(os.environ["PROBE_CALLS"]).open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
assert sys.argv[1:] == ["agent", "list"]
case = os.environ["PROBE_CASE"]
if case == "timeout":
    sleep(5)
if case == "failed":
    sys.exit("fixture: socket unavailable")
agents = [{"pane_id": "pane-1", "name": "worker", "agent_status": case}]
if case == "missing":
    agents = [{"pane_id": "pane-2", "name": "worker", "agent_status": "working"},
              {"pane_id": "pane-1", "name": "other", "agent_status": "working"}]
print(json.dumps({"result": {"agents": agents}}))
"""


def write_map(root, name, runtime, pane, nested=False):
    folder = root / name
    folder.mkdir()
    (folder / "driver.json").write_text(json.dumps({"plan": {"tickets": [{"id": "A"}]}}))
    overlay = (f"herdr:\n  pane_id: {pane}\n  agent_name: worker" if nested else
               "herdr: " + json.dumps({"pane_id": pane, "agent_name": "worker"}))
    (folder / "registry.md").write_text(
        "<!-- wayfinder-lane-registry:v2 -->\n```yaml\n"
        f"lane_id: A\nwork_item: A\nrole: backend\nstate: running\nruntime: {runtime}\n{overlay}\n```\n")


def main():
    with TemporaryDirectory(prefix="board-probe-") as temp:
        directory = Path(temp)
        fake = directory / "herdr"
        fake.write_text(f"#!{sys.executable}\n" + FAKE_HERDR)
        fake.chmod(0o755)
        calls = directory / "calls.jsonl"
        root = directory / "lanes"
        root.mkdir()
        write_map(root, "primary", "herdr-codex-pane", "pane-1")

        def observe(case):
            calls.write_text("")
            env = {**os.environ, "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}",
                   "PROBE_CALLS": str(calls), "PROBE_CASE": case}
            run = subprocess.run([sys.executable, str(SNAPSHOT), "--lanes-root", str(root)],
                                 env=env, capture_output=True, text=True, timeout=8)
            assert run.returncode == 0, run.stderr
            assert [json.loads(line) for line in calls.read_text().splitlines()] == [["agent", "list"]]
            return json.loads(run.stdout)

        for case, state, status, reason in [
            ("working", "working", "ok", None),
            ("idle", "not_working", "ok", None),
            ("missing", "unknown", "missing", "未匹配"),
            ("failed", "unknown", "failed", "socket unavailable"),
            ("timeout", "unknown", "failed", "超时"),
        ]:
            snapshot = observe(case)
            [mmf] = snapshot["inbox"]
            [ticket] = mmf["tickets"]
            assert (ticket["lane"]["live"], ticket["executing"], mmf["executing"]) == (
                state, state == "working", False), case
            [probe] = snapshot["probes"]
            assert (probe["runtime"], probe["status"]) == ("herdr", status), (case, probe)
            assert reason in probe["reason"] if reason else probe["reason"] is None, (case, probe)

        # 不同 map 可复用同一 lane ID。一个批次内同时覆盖旧多行段与未注册 runtime。
        write_map(root, "other-map", "herdr-pi-pane", "pane-2", nested=True)
        write_map(root, "legacy-match", "herdr-pi-pane", "pane-1", nested=True)
        write_map(root, "unregistered", "fixture-task", "pane-1")
        snapshot = observe("working")
        assert {m["map"]: m["tickets"][0]["lane"]["live"] for m in snapshot["inbox"]} == {
            "primary": "working", "other-map": "unknown", "legacy-match": "working", "unregistered": "unknown"}

    print("看板现场探针 S20 通过（工作、空闲、失配、失败、超时，单次只读查询）")


if __name__ == "__main__":
    main()
