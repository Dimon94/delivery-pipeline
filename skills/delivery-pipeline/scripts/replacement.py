"""Recovery 纯决定面：只消费冻结位置，不读取配置或执行副作用。"""
from copy import deepcopy
import importlib.util
from pathlib import Path

p = Path(__file__).resolve().parents[2] / 'delivery-pipeline-setup/scripts/model_config.py'
spec = importlib.util.spec_from_file_location('replacement_model_config', p)
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)


def decide(row, category, accepted_count):
    frozen = mc.recover_overlay(row)
    if category in {'unknown', 'connection_interrupted'}:
        return {'action': 'inspect'}
    if category == 'cancelled':
        return {'action': 'stop'}
    if category == 'context_exhausted':
        return {'action': 'resplit'}
    if category not in {'tool_or_model', 'startup_failed'}:
        raise ValueError('invalid failure category')
    if accepted_count >= 2:
        return {'action': 'budget'}
    if frozen['status'] == 'legacy':
        return {'action': 'existing_policy'}
    plan = frozen['recovery_plan']
    if plan['source'] != 'work' or not plan['fallbacks']:
        return {'action': 'existing_policy'}
    i = frozen['recovery_progress']['next_cursor']
    if i >= len(plan['fallbacks']):
        return {'action': 'exhausted'}
    return deepcopy({'action': 'replace', **plan['fallbacks'][i], 'recovery_plan': plan,
                     'recovery_progress': {'current_index': i, 'next_cursor': i+1}})
