#!/usr/bin/env python3
"""Review 预算 gate：由 P0/P1 计数推导结论，并用账本强制每个 scope 只审一轮（ADR-0027）。

输入（JSON stdin）：
  {"round": 1,
   "axes": {"standards": {"verdict": "PASS", "counts": {"P0": 0, "P1": 0, "P2": 1, "P3": 0}},
            "spec": {"verdict": "NO_SPEC"}},
   "p2_issues": ["<Issue 坐标>"],
   "repros": ["<每条 P0/P1 的可跑反例：失败测试或命令>"]}
M3 另传 review_packet 和 native_readbacks，逐轴 schema 见 code-review-evidence-preflight.md。
输出：PASS | FIX | REVIEW_BLOCKED。输入非法或超预算时非零退出。
账本只记录已产生有效 verdict 的轮次及其 P0-P3 合计；中断的审查不进账本，因此不占预算。
每条 P0/P1 必须带一个反例；FIX 表示按反例修复，反例变绿加完整测试即关闭，不开复审。
账本写入一轮后即终结，之后再写入一律拒绝。REVIEW_EXHAUSTED 只在旧账本里出现。
"""
from copy import deepcopy
import argparse
import json
import os
import sys
import tempfile

MAX_ROUNDS = 1
SEVERITIES = ("P0", "P1", "P2", "P3")


def record_axis_execution(axis, requested, native_readback):
    """只接受逐轴原生读回；effort 只能取 applied_effort，不能取请求参数。"""
    if axis not in ('standards', 'spec'):
        raise ValueError('unknown review axis')
    if not isinstance(requested, dict) or any(
            not isinstance(requested.get(k), str) or not requested[k].strip()
            for k in ('agent', 'model', 'effort')):
        raise ValueError('requested ModelTriple required')
    raw = native_readback if isinstance(native_readback, dict) else {}
    executed = None
    if raw.get('source') == 'native_readback':
        identity = raw.get('identity') or {}
        observed = {'agent': identity.get('agent'), 'model': identity.get('model'),
                    'effort': raw.get('applied_effort')}
        executed = {key: value if isinstance(value, str) and value.strip() else None
                    for key, value in observed.items()}
        if not any(executed.values()):
            executed = None
    conflicts = [k for k, v in (executed or {}).items() if v is not None and v != requested[k]]
    complete = executed is not None and all(executed.values())
    status = 'mismatch' if conflicts else ('matched' if complete else 'unknown')
    return {'axis': axis, 'requested': deepcopy(requested), 'executed': executed,
            'status': status, 'reason': ','.join(conflicts) if conflicts else
                (None if complete else 'native_readback_incomplete'),
            'native_readback': deepcopy(raw) if raw.get('source') == 'native_readback' else None}


def round_release_blockers(evidence):
    return ['reviewer_execution_mismatch'] if any(e['status'] == 'mismatch' for e in evidence) else []


def execution_evidence(data):
    """由同一冻结 packet 推导 requested；调用方不能提交自评 status。"""
    packet = data.get('review_packet')
    if packet is None:
        return []  # legacy gate；M3 Adapter 强制要求 packet。
    from lane_registry import verify_review_packet
    plan = packet['review_plan']
    verify_review_packet(plan, packet)
    if set(data['axes']) != set(plan['required_axes']):
        raise ValueError('result axes must equal frozen required_axes')
    readbacks = data.get('native_readbacks', {})
    if not isinstance(readbacks, dict) or set(readbacks) - set(plan['required_axes']):
        raise ValueError('native_readbacks must belong to required axes')
    return [record_axis_execution(call['axis'], call['requested'], readbacks.get(call['axis']))
            for call in packet['owner_calls']]


# ---- 结论推导 ---------------------------------------------------------------
def axis_counts(name, axis):
    verdict = axis.get("verdict")
    if name == "spec" and verdict == "NO_SPEC":
        return {severity: 0 for severity in SEVERITIES}
    if name == "standards" and verdict == "SKIPPED":
        if not isinstance(axis.get("reason"), str) or not axis["reason"].strip():
            raise ValueError("standards: SKIPPED 必须写明理由")
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
    if not {"standards", "spec"} <= axes.keys():
        raise ValueError("必须同时有 standards 与 spec；无 Spec 时写 NO_SPEC，Standards 未触发时写 SKIPPED")
    counts = [axis_counts(name, axis) for name, axis in axes.items()]
    if round_release_blockers(execution_evidence(data)):
        return 'REVIEW_BLOCKED'
    blocking = sum(item["P0"] + item["P1"] for item in counts)
    repros = data.get("repros", [])
    if not isinstance(repros, list) or not all(isinstance(r, str) and r.strip() for r in repros):
        raise ValueError("repros 必须是反例命令列表")
    if len(repros) != blocking:
        raise ValueError(f"{blocking} 条 P0/P1 需要 {blocking} 个可跑反例，实际 {len(repros)}；没有反例的降为 P2")
    if blocking:
        return "FIX"
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


def prepare_round(rounds, *, round_no, base, head, request_id, implementations,
                  interface_changed=False, dependencies_changed=False):
    """原 Review Budget 的派发前决定面；不写账本，不创建新 attempt。"""
    if not base or not head or not request_id:
        raise ValueError('new round requires base/head/request_id')
    for entry in reversed(rounds):
        point = entry.get('review_packet', {}).get('review_plan', {}).get('round_context', {})
        if point.get('base') == base and point.get('head') == head:
            return dict(action='reuse', result=deepcopy(entry))
    if type(round_no) is not int or not 1 <= round_no <= MAX_ROUNDS or round_no != len(rounds)+1:
        raise ValueError(f'Review Budget allows {MAX_ROUNDS} round per scope')
    axes = ['standards', 'spec']
    return dict(action='plan', round=round_no, base=base, head=head,
                request_id=request_id, required_axes=axes, implementations=deepcopy(implementations),
                interface_changed=interface_changed, dependencies_changed=dependencies_changed)


def run(data, ledger):
    outcome = evaluate(data)
    rounds = read_ledger(ledger)
    plan = data.get('review_packet', {}).get('review_plan', {})
    context = plan.get('round_context')
    if context:
        expected_plan = prepare_round(rounds, round_no=data['round'], base=context['base'],
            head=context['head'], request_id=plan['request_id'], implementations=plan['implementations'],
            interface_changed=context['interface_changed'], dependencies_changed=context['dependencies_changed'])
        if expected_plan['action'] == 'reuse':
            raise ValueError('same base/head: reuse complete recorded result, do not rerun gate')
        if context != expected_plan or plan['required_axes'] != expected_plan['required_axes']:
            raise ValueError('round plan differs from Review Budget decision')
    if len(rounds) >= MAX_ROUNDS:
        raise ValueError(f"账本已终结于 {rounds[-1]['outcome']}；修复靠反例变绿关闭，不开下一轮")
    expected = len(rounds) + 1
    if data["round"] != expected:
        raise ValueError(f"账本要求下一轮为 {expected}，输入为 {data['round']}")
    totals = {severity: 0 for severity in SEVERITIES}
    for name, axis in data["axes"].items():
        for severity, value in axis_counts(name, axis).items():
            totals[severity] += value
    entry = {"round": data["round"], "outcome": outcome, "counts": totals}
    if data.get('review_packet') is not None:
        evidence = execution_evidence(data)
        entry.update(axes=deepcopy(data['axes']), execution_evidence=evidence,
                     release_blockers=round_release_blockers(evidence),
                     review_packet=deepcopy(data['review_packet']), p2_issues=deepcopy(data.get('p2_issues', [])))
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
    repro = ["node --test tests/x.test.js"]
    assert evaluate(payload(1, passing)) == "PASS"
    assert evaluate({**payload(1, blocking), "repros": repro}) == "FIX"
    assert evaluate(payload(1, {"verdict": "PASS", "counts": p2}, issues=["DD-1"])) == "PASS"
    assert evaluate(payload(1, passing, spec={"verdict": "NO_SPEC"})) == "PASS"
    assert evaluate(payload(1, {"verdict": "SKIPPED", "reason": "无权限或合同改动"})) == "PASS"
    rejected = (
        payload(1, {"verdict": "BLOCK", "counts": clean}),  # 零 finding 不得 BLOCK
        payload(1, {"verdict": "BLOCK", "counts": p2}, issues=["DD-1"]),  # P2 不阻断
        payload(1, {"verdict": "PASS", "counts": p1}),  # P1 不得 PASS
        payload(1, {"verdict": "PASS", "counts": p2}),  # P2 未登记
        payload(1, blocking),  # P1 无反例
        payload(1, {"verdict": "SKIPPED"}),  # 跳过 Standards 无理由
        payload(2, passing),  # 只有一轮
        {"round": 1, "axes": {"standards": passing}},  # 缺轴
    )
    for item in rejected:
        try:
            evaluate(item)
        except ValueError:
            continue
        raise AssertionError(f"应被拒绝: {item}")
    with tempfile.TemporaryDirectory() as root:
        for first in ({**payload(1, blocking), "repros": repro}, payload(1, passing)):
            ledger = os.path.join(root, f"{len(os.listdir(root))}", "ledger.json")
            run(first, ledger)
            for later in (payload(1, passing), payload(2, passing)):  # FIX 与 PASS 之后都不再开轮
                try:
                    run(later, ledger)
                except ValueError:
                    continue
                raise AssertionError("一轮之后账本应拒绝写入")
            assert len(read_ledger(ledger)) == 1
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
