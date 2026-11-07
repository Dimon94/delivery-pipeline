#!/usr/bin/env python3
"""Review 预算 gate：由 P0/P1 计数推导结论，并用账本强制每个 scope 最多三轮。

输入（JSON stdin）：
  {"round": 1,
   "axes": {"standards": {"verdict": "PASS", "counts": {"P0": 0, "P1": 0, "P2": 1, "P3": 0}},
            "spec": {"verdict": "NO_SPEC"}},
   "p2_issues": ["<Issue 坐标>"]}
输出：PASS | FIX | REVIEW_EXHAUSTED。输入非法或超预算时非零退出。
账本只记录已产生有效 verdict 的轮次及其 P0-P3 合计；中断的审查不进账本，因此不占预算。
只有 FIX 能续轮：PASS 与 REVIEW_EXHAUSTED 是终态，之后再写入一律拒绝。
"""
import argparse
import json
import os
import sys
import tempfile

MAX_ROUNDS = 3
SEVERITIES = ("P0", "P1", "P2", "P3")


# ---- 结论推导 ---------------------------------------------------------------
def axis_counts(name, axis):
    verdict = axis.get("verdict")
    if name == "spec" and verdict == "NO_SPEC":
        return {severity: 0 for severity in SEVERITIES}
    if verdict not in ("PASS", "BLOCK"):
        raise ValueError(f"{name}: verdict 只能是 PASS 或 BLOCK")
    counts = axis.get("counts")
    if not isinstance(counts, dict):
        raise ValueError(f"{name}: 缺少 counts")
    for severity in SEVERITIES:
        value = counts.get(severity)
        if type(value) is not int or value < 0:
            raise ValueError(f"{name}: {severity} 必须是非负整数")
    expected = "BLOCK" if counts["P0"] + counts["P1"] else "PASS"
    if verdict != expected:
        raise ValueError(f"{name}: verdict={verdict} 与 P0/P1 计数矛盾，应为 {expected}")
    return counts


def evaluate(data):
    if not isinstance(data, dict):
        raise ValueError("输入必须是 JSON object")
    round_no = data.get("round")
    if type(round_no) is not int or round_no < 1:
        raise ValueError("round 必须是正整数")
    if round_no > MAX_ROUNDS:
        raise ValueError(f"超出 Review 预算：第 {round_no} 轮，上限 {MAX_ROUNDS} 轮")
    axes = data.get("axes")
    if not isinstance(axes, dict) or not axes:
        raise ValueError("缺少 axes")
    if round_no == 1 and not {"standards", "spec"} <= axes.keys():
        raise ValueError("第 1 轮必须同时有 standards 与 spec；无 Spec 时写 NO_SPEC")
    counts = [axis_counts(name, axis) for name, axis in axes.items()]
    if sum(item["P0"] + item["P1"] for item in counts):
        return "FIX" if round_no < MAX_ROUNDS else "REVIEW_EXHAUSTED"
    issues = data.get("p2_issues", [])
    if not isinstance(issues, list) or not all(isinstance(i, str) and i.strip() for i in issues):
        raise ValueError("p2_issues 必须是 Issue 坐标列表")
    p2_total = sum(item["P2"] for item in counts)
    if len(issues) != p2_total:
        raise ValueError(f"{p2_total} 条 P2 需要 {p2_total} 个 Issue 坐标，实际 {len(issues)}")
    return "PASS"


# ---- 账本 -------------------------------------------------------------------
def read_ledger(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["rounds"]


def write_ledger(path, rounds):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"rounds": rounds}, handle, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def run(data, ledger):
    outcome = evaluate(data)
    rounds = read_ledger(ledger)
    if rounds and rounds[-1]["outcome"] != "FIX":
        raise ValueError(f"账本已终结于 {rounds[-1]['outcome']}，只有 FIX 之后才能开下一轮")
    expected = len(rounds) + 1
    if data["round"] != expected:
        raise ValueError(f"账本要求下一轮为 {expected}，输入为 {data['round']}")
    totals = {severity: 0 for severity in SEVERITIES}
    for name, axis in data["axes"].items():
        for severity, value in axis_counts(name, axis).items():
            totals[severity] += value
    entry = {"round": data["round"], "outcome": outcome, "counts": totals}
    write_ledger(ledger, rounds + [entry])
    return outcome


# ---- 自检 -------------------------------------------------------------------
def self_test():
    clean = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    p1 = {**clean, "P1": 1}
    p2 = {**clean, "P2": 1}

    def payload(round_no, standards, spec=None, issues=None):
        axes = {"standards": standards, "spec": spec or {"verdict": "PASS", "counts": clean}}
        return {"round": round_no, "axes": axes, "p2_issues": issues or []}

    passing = {"verdict": "PASS", "counts": clean}
    blocking = {"verdict": "BLOCK", "counts": p1}
    assert evaluate(payload(1, passing)) == "PASS"
    assert evaluate(payload(2, blocking)) == "FIX"
    assert evaluate(payload(3, blocking)) == "REVIEW_EXHAUSTED"
    assert evaluate(payload(1, {"verdict": "PASS", "counts": p2}, issues=["DD-1"])) == "PASS"
    assert evaluate(payload(1, passing, spec={"verdict": "NO_SPEC"})) == "PASS"
    rejected = (
        payload(1, {"verdict": "BLOCK", "counts": clean}),  # 零 finding 不得 BLOCK
        payload(1, {"verdict": "BLOCK", "counts": p2}, issues=["DD-1"]),  # P2 不阻断
        payload(1, {"verdict": "PASS", "counts": p1}),  # P1 不得 PASS
        payload(1, {"verdict": "PASS", "counts": p2}),  # P2 未登记
        payload(4, passing),  # 超预算
        {"round": 1, "axes": {"standards": passing}},  # 第 1 轮缺轴
    )
    for item in rejected:
        try:
            evaluate(item)
        except ValueError:
            continue
        raise AssertionError(f"应被拒绝: {item}")
    with tempfile.TemporaryDirectory() as root:
        ledger = os.path.join(root, "nested", "ledger.json")
        assert run(payload(1, blocking), ledger) == "FIX"
        for stale in (payload(1, blocking), payload(3, blocking)):  # 重复或跳号都拒绝
            try:
                run(stale, ledger)
            except ValueError:
                continue
            raise AssertionError("账本应拒绝非连续轮次")
        assert run(payload(2, blocking), ledger) == "FIX"
        assert run(payload(3, blocking), ledger) == "REVIEW_EXHAUSTED"
        assert len(read_ledger(ledger)) == 3
        closed = os.path.join(root, "closed.json")
        assert run(payload(1, passing), closed) == "PASS"
        try:  # PASS 后的改动不再开轮
            run(payload(2, blocking), closed)
        except ValueError:
            pass
        else:
            raise AssertionError("PASS 后账本应拒绝新一轮")
        assert read_ledger(closed)[0]["counts"]["P1"] == 0
    print("review gate self-test: pass")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", help="本 scope 的 Review 账本路径")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.ledger:
        parser.error("缺少 --ledger")
    try:
        print(run(json.load(sys.stdin), args.ledger))
    except (ValueError, KeyError, OSError) as error:
        print(f"review gate: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
