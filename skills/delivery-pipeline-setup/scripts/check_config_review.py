#!/usr/bin/env python3
"""DD-509：Spec PLAN-01/R7/R12/R14 的公开 Interface 检查，配置均为 fixture。"""
import argparse
import copy
import importlib.util
import sys
import subprocess
import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('model_config', HERE/'model_config.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.path.insert(0, str(HERE.parents[1]/'delivery-pipeline/scripts'))
import lane_registry as registry


def check():
    config = m.valid_fixture()
    config['review']['whole-change']['spec']['effort'] = 'low'
    evidence = {'pi': {'binary': True, 'models': {'provider/model': ['high', 'low']}}}
    rows = {'map': {'lane_id': 'map', 'role': 'map', 'base_commit': 'base'},
            'impl': {'lane_id': 'impl', 'map': 'map', 'output_mode': 'commit', 'role': 'backend',
                     'integrated_commit': 'abc', 'agent': 'codex', 'model': 'frozen-model', 'effort': 'high'},
            'test': {'lane_id': 'test', 'map': 'map', 'output_mode': 'checks', 'role': 'testing', 'model': 'ignore'}}
    implementations = registry.collect_implementation_identities(rows, 'base')
    assert implementations == [{'lane_id': 'impl', 'requested': {'agent': 'codex', 'model': 'frozen-model', 'effort': 'high'}, 'executed': None}]
    plan = m.resolve_review_plan(config, required_axes=['standards', 'spec'], implementations=implementations,
                                 evidence=evidence, native_capabilities={}, request_id='round-1')
    assert plan['scope'] == 'whole-change' and plan['required_axes'] == ['standards', 'spec']
    assert plan['lane']['selected'] == {'agent': 'pi', 'model': 'provider/model', 'effort': 'high'}
    assert plan['axes']['spec']['selected'] == {'agent': 'pi', 'model': 'provider/model', 'effort': 'low'}
    assert plan['implementations'] == implementations and len(plan['config_hash']) == 64
    assert plan['lane']['fallback'] == 'single_model' and len(plan['lane']['attempts']) == 1
    calls = registry.build_owner_calls(plan)
    assert [(c['axis'], c['requested']['effort']) for c in calls] == [('standards', 'high'), ('spec', 'low')]
    assert all(c['execution_evidence'] is None for c in calls)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'registry.md'
        registry.write(path, {'lane_id': 'review', 'work_item': 'DD-509', 'role': 'review'})
        registry.freeze_review_plan(path, 'review', plan, 'round-1')
        source = Path(tmp)/'sources.md'
        for r in rows.values():
            registry.write(source, {**r, 'work_item': r['lane_id']})
        config_path, evidence_path = Path(tmp)/'config.json', Path(tmp)/'evidence.json'
        config_path.write_text(json.dumps(config))
        evidence_path.write_text(json.dumps(evidence))
        flags = [str(config_path), 'review', '--review-scope', 'whole-change', '--output-mode', 'verdict',
                 '--required-axes', 'standards', 'spec', '--request-id', 'round-1',
                 '--implementation-registry', str(source), '--fixed-point', 'base', '--evidence', str(evidence_path)]
        for command in ['resolve', 'freeze', 'start']:
            process = subprocess.run([sys.executable, str(HERE/'model_config.py'), command, *flags], capture_output=True, text=True)
            assert process.returncode == 0, process.stdout+process.stderr
            value = json.loads(process.stdout)
            if command == 'start':
                assert value[-4:] == ['--model', 'provider/model', '--thinking', 'high']
            else:
                assert value['review_plan'] == plan

        assert registry.load_review_plan(path, 'review', 'round-1') == plan
        registry.verify_review_packet(plan, {'review_plan': plan, 'owner_calls': calls})
        changed = copy.deepcopy(plan)
        changed['axes']['spec']['selected']['effort'] = 'high'
        for action in [lambda: registry.freeze_review_plan(path, 'review', changed, 'round-1'),
                       lambda: registry.verify_review_packet(plan, {'review_plan': changed, 'owner_calls': calls})]:
            try: action()
            except ValueError: pass
            else: raise AssertionError('immutable plan/packet accepted drift')
    spec_only = m.resolve_review_plan(config, required_axes=['spec'], implementations=[], evidence=evidence,
                                      native_capabilities={}, request_id='round-2')
    assert [c['axis'] for c in registry.build_owner_calls(spec_only)] == ['spec']
    assert spec_only['lane']['selected']['effort'] == 'high'
    assert config['version'] == 6 and 'model_families' not in config
    print('single-model-plan: pass (fixture; no native execution)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['single-model-plan'], required=True)
    parser.parse_args()
    check()
