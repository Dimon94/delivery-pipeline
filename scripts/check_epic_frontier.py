#!/usr/bin/env python3
"""通过共享入口验证 Epic 开工、上线与续接。"""
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/delivery-pipeline/scripts/epic_frontier.py"
EPIC = "https://github.com/example/project/issues/30"
MAP_A = "https://github.com/example/project/issues/31"
SPEC_A = "https://github.com/example/project/issues/32"
SPEC_D = "https://github.com/example/project/issues/33"


def run(items, *, mmf=None, failure=None):
    result = subprocess.run(
        [sys.executable, str(HELPER)],
        input=json.dumps({"epic": EPIC, "items": items, "mmf": mmf}),
        capture_output=True,
        text=True,
    )
    if failure:
        assert result.returncode != 0 and failure in result.stderr, result
        assert not result.stdout, result
        return None
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def dependency(source, gate, requires, evidence=None):
    return {"source": source, "gate": gate, "requires": requires, "evidence": evidence}


def main():
    # #30 的依赖形状：A 每日核价、B 官方测试入口、C 三网实测、
    # D 目录扩充、G 退款。D 可在 Interface 对齐后开发，真实上线等 A。
    a = {"id": "A", "state": "development", "dependencies": []}
    b = {"id": "B", "state": "development", "dependencies": [
        dependency("A", "development", "evidence"),
    ]}
    c = {"id": "C", "state": "development", "dependencies": [
        dependency("B", "development", "evidence"),
        dependency("external:probe-sites", "development", "evidence"),
    ]}
    d = {"id": "D", "state": "development", "dependencies": [
        dependency("A", "development", "evidence"),
        dependency("A", "release", "accepted"),
    ]}
    g = {"id": "G", "state": "development", "dependencies": []}

    first = run([a, b, c, d, g])
    assert first["development"] == [{"id": "A"}, {"id": "G"}], first
    assert set(first["waiting"]) == {"B", "C", "D"} and not first["release"], first

    # 已有 writer 时只续接该 lane，其他 MMF 继续。Interface 读回即可解锁 B、D。
    a.update(state="active", map=MAP_A, spec=SPEC_A)
    b["dependencies"][0]["evidence"] = MAP_A + "#issuecomment-1"
    d["dependencies"][0]["evidence"] = MAP_A + "#issuecomment-1"
    in_progress = run([a, b, c, d, g])
    assert in_progress["active"] == [{"id": "A", "map": MAP_A, "spec": SPEC_A}], in_progress
    assert in_progress["development"] == [{"id": "B"}, {"id": "D"}, {"id": "G"}], in_progress
    assert set(in_progress["waiting"]) == {"C"}, in_progress
    c["dependencies"][0]["evidence"] = EPIC + "#issuecomment-3"
    assert "C" in run([a, b, c, d, g])["waiting"]
    c["dependencies"][1]["evidence"] = EPIC + "#issuecomment-4"
    assert {"id": "C"} in run([a, b, c, d, g])["development"]

    # 新进程从相同 Issue 与现场读回重建，续接已有 Map/Spec。
    a["state"] = "development"
    d.update(state="release", spec=SPEC_D)
    resumed = run([a, b, c, d, g])
    assert resumed == run([a, b, c, d, g]), resumed
    assert resumed["development"][0] == {"id": "A", "map": MAP_A, "spec": SPEC_A}, resumed
    assert not resumed["release"] and resumed["waiting"]["D"]["dependencies"] == [
        {"source": "A", "gate": "release", "requires": "accepted"},
    ], resumed

    a.update(state="accepted", acceptance=SPEC_A + "#issuecomment-2")
    next_wave = run([a, b, c, d, g])
    assert next_wave["release"] == [{"id": "D", "spec": SPEC_D}], next_wave
    assert next_wave["accepted"] == ["A"] and not next_wave["done"], next_wave
    scoped = run([a, b, c, d, g], mmf="D")
    assert scoped["release"] == next_wave["release"] and not scoped["development"], scoped
    assert not scoped["done"] and scoped["accepted"] == ["A"], scoped
    run([a], mmf="missing", failure="未知 MMF")
    assert run([a])["done"]
    candidate = {"id": "H", "state": "candidate", "dependencies": []}
    assert run([a, candidate])["waiting"] == {"H": {"state": "candidate"}}

    run([a, {**b, "spec": SPEC_A}], failure="重复坐标")
    run([a, {**b, "dependencies": [dependency("missing", "release", "accepted")]}],
        failure="未知 MMF")
    run([{**a, "acceptance": "Unknown"}], failure="acceptance")

    a = {"id": "A", "state": "development", "dependencies": [
        dependency("B", "release", "accepted"),
    ]}
    b = {"id": "B", "state": "development", "dependencies": [
        dependency("A", "release", "accepted"),
    ]}
    cycle = run([a, b, g])
    assert cycle["cycle"] and cycle["development"] == [{"id": "A"}, {"id": "B"}, {"id": "G"}], cycle
    print("epic frontier: pass")


if __name__ == "__main__":
    main()
