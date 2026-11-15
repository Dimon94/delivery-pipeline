"""同轮只读恢复：唯一 Registry 与原 Review Budget；不启动、不重新选序。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
import lane_registry
from review_gate import read_ledger


def recover(path, lane, request_id, ledger=None):
    row, _ = lane_registry.read(Path(path), lane)
    plan = lane_registry.load_review_plan(Path(path), lane, request_id)
    if row.get('role') != 'review':
        raise ValueError('review lane required')
    packet = dict(review_plan=plan, owner_calls=lane_registry.build_owner_calls(plan))
    # 仅返回原 round：不会把旧轮结果拼成下一轮，也不改 gate 的终态拒绝语义。
    rounds = read_ledger(ledger) if ledger else []
    completed = [r for r in rounds if r.get('review_packet') == packet]
    if ledger and rounds and not completed:
        raise ValueError('original ledger/review packet mismatch')
    native = row.get('herdr', {})
    action = 'recover_original' if native.get('startup_state') == 'completed' else 'inspect_original'
    if row.get('state') in {'cancelled', 'consumed', 'terminal'} or native.get('startup_state') == 'failed':
        action = 'stop'
    if completed and action != 'stop':
        action = 'fan_in_recorded' if completed[-1]['outcome'] == 'FIX' else 'stop'
    return dict(action=action, row=row, review_packet=packet, recorded_rounds=completed,
                execution_readback='Unknown', instruction='保留已有轴结果与 finding；只对账原请求，不重发、不换候选、不补并行')
