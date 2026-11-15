"""同轮只读恢复：唯一 Registry 与原 Review Budget；不启动、不重新选序。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
import lane_registry
from review_gate import read_ledger, prepare_round


def recover(path, lane, request_id, ledger=None, previous_registry=None):
    row, _ = lane_registry.read(Path(path), lane)
    plan = lane_registry.load_review_plan(Path(path), lane, request_id)
    if row.get('role') != 'review':
        raise ValueError('review lane required')
    packet = dict(review_plan=plan, owner_calls=lane_registry.build_owner_calls(plan))
    # 仅返回原 round：不会把旧轮结果拼成下一轮，也不改 gate 的终态拒绝语义。
    rounds = read_ledger(ledger) if ledger else []
    completed = [r for r in rounds if r.get('review_packet') == packet]
    if ledger and not completed and (rounds or plan.get('round_context', {}).get('round', 1) > 1):
        context = plan.get('round_context', {})
        # 已入账但 packet 不同仍是 mismatch；仅允许原预算决定的下一轮等待 fan-in。
        if ([r.get('round') for r in rounds] != list(range(1, len(rounds)+1))
                or any(r.get('review_packet', {}).get('review_plan', {}).get(
                    'round_context', {}).get('base') != row.get('base_commit') for r in rounds)):
            raise ValueError('original ledger/review packet mismatch')
        expected = prepare_round(rounds, round_no=context.get('round'), base=context.get('base'),
            head=context.get('head'), request_id=request_id, implementations=plan['implementations'],
            interface_changed=context.get('interface_changed'),
            dependencies_changed=context.get('dependencies_changed'))
        if (expected.get('action') != 'plan' or expected != context
                or context['base'] != row.get('base_commit')
                or plan['required_axes'] != expected['required_axes']):
            raise ValueError('original ledger/review packet mismatch')
        # 与派发相同的原计划/原状态证据；不能只凭账本 FIX 复活取消或失败轮。
        prior_rows = lane_registry.rows(Path(previous_registry)) if previous_registry else lane_registry.rows(Path(path))
        verify_previous_round(prior_rows, rounds)
    native = row.get('herdr', {})
    action = 'recover_original' if native.get('startup_state') == 'completed' else 'inspect_original'
    if row.get('state') in {'cancelled', 'consumed', 'terminal'} or native.get('startup_state') == 'failed':
        action = 'stop'
    if completed and action != 'stop':
        action = 'fan_in_recorded' if completed[-1]['outcome'] == 'FIX' else 'stop'
    return dict(action=action, row=row, review_packet=packet, recorded_rounds=completed,
                execution_readback='Unknown', instruction='保留已有轴结果与 finding；只对账原请求，不重发、不换候选、不补并行')


def verify_previous_round(prior_rows, rounds):
    """派发与恢复共用原轮计划/状态核验；账本 FIX 不能替代原 Registry。"""
    originals = [r for r in prior_rows.values()
                 if r.get('review_plan') == rounds[-1]['review_packet']['review_plan']]
    if (len(originals) != 1 or originals[0].get('state') in
            {'cancelled', 'setup_blocked', 'failed'}
            or originals[0].get('herdr', {}).get('startup_state') == 'failed'):
        raise ValueError('original round missing/cancelled/failed: recover original, no new FIX')
