#!/usr/bin/env python3
"""DD-509：经生产 dispatch.py CLI 的 fake Herdr 外部 seam，非真实执行。"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from dispatch_check import run, FAKE_HERDR, GOOD_MAP


def check():
    base = {'tabs': [{'tab_id': 'w1:t1', 'label': 'coord', 'pane_count': 1, 'workspace_id': 'w1'}],
            'panes': [{'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'workspace_id': 'w1'}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'herdr').write_text(f'#!{sys.executable}\n'+FAKE_HERDR)
        (root/'watch').write_text('#!/bin/sh\nexit 0\n')
        for name in ['herdr', 'watch']: (root/name).chmod(0o755)
        owner = root/'owner/SKILL.md'
        owner.parent.mkdir()
        owner.write_text('---\nname: code-review\n---\nfixture owner; does not execute a model\n')
        packet = f'Owner：code-review；{owner}；fixture file invocation\n'
        flags = ('--task', 'review', '--output-mode', 'verdict', '--review-scope', 'whole-change',
                 '--required-axes', 'standards', 'spec', '--request-id', 'round-1')
        map_text = GOOD_MAP.replace('role: map', 'work_item: DD-508\nrole: map\nbase_commit: abc')
        result, path, calls = run(root, 'review-single', base, packet=packet, map_text=map_text, extra=flags)
        assert result.returncode == 0, result.stdout+result.stderr
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
        import lane_registry
        row,_ = lane_registry.read(path, 'review-single')
        assert row['review_plan']['required_axes'] == ['standards', 'spec']
        assert row['review_plan']['lane']['selected']['model'] == 'provider/model'
        assert len([c for c in calls if c[:2] == ['agent', 'start']]) == 1
        delivered = (root/'packet.md').read_text()
        assert 'DP_REVIEW_PLAN' in delivered and '"execution_evidence": null' in delivered
        assert '"axis": "standards"' in delivered and '"axis": "spec"' in delivered
        assert '逐轴' in delivered and '不得重新读取配置' in delivered
        # 相同 lane 已终态也不能再创建第二个原生 pane/请求。
        row['state'] = 'terminal'
        lane_registry.write(path, row)
        result, _, calls = run(root, 'review-single', base, packet=packet, map_text=map_text, extra=flags)
        assert result.returncode != 0 and not calls, 'completed review lane redispatched'

        result, _, calls = run(root, 'bad-scope', base, packet=packet, map_text=map_text,
                               extra=(*flags, '--review-scope', 'implementation'))
        assert result.returncode != 0 and not calls
        result, _, calls = run(root, 'bad-owner', base, packet='Owner：other；/missing；fixture',
                               map_text=map_text, extra=flags)
        assert result.returncode != 0 and not calls
    print('single-model dispatch: pass (fake Herdr; native execution Unknown)')


def check_axis_evidence():
    """独立预期：DD-508 R17 / DD-510；模拟 readback，绝非真实 Herdr。"""
    import copy
    import subprocess
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
    import lane_registry
    requested = {'agent': 'pi', 'model': 'provider/model', 'effort': 'high'}
    selection = {'selected': requested}
    plan = {'scope': 'whole-change', 'request_id': 'r1', 'required_axes': ['standards', 'spec'],
            'lane': selection, 'axes': {'standards': selection, 'spec': selection}}
    packet = {'review_plan': plan, 'owner_calls': lane_registry.build_owner_calls(plan)}
    clean = {'P0': 0, 'P1': 0, 'P2': 0, 'P3': 0}
    axes = {'standards': {'verdict': 'PASS', 'counts': clean, 'findings': []},
            'spec': {'verdict': 'PASS', 'counts': {**clean, 'P3': 1}, 'findings': ['保留完整 finding']}}
    payload = {'round': 1, 'axes': axes, 'review_packet': packet,
               'native_readbacks': {'standards': {'source': 'native_readback',
                  'identity': {'agent': 'pi', 'model': 'wrong-model'}, 'applied_effort': 'high'}}}
    script = Path(__file__).with_name('review_execution.py')
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp)/'ledger.json'
        result = subprocess.run([sys.executable, str(script), '--ledger', str(ledger)],
                                input=json.dumps(payload), text=True, capture_output=True)
        assert result.returncode == 0, result.stdout+result.stderr
        assert result.stdout.strip() == 'REVIEW_BLOCKED', 'known mismatch released'
        saved = json.loads(ledger.read_text())['rounds'][0]
        assert saved['axes'] == axes, 'findings lost'
        assert saved['release_blockers'] == ['reviewer_execution_mismatch']
        assert [e['status'] for e in saved['execution_evidence']] == ['mismatch', 'unknown']
        assert saved['execution_evidence'][1]['executed'] is None
        before = ledger.read_bytes()
        again = subprocess.run([sys.executable, str(script), '--ledger', str(ledger)],
                               input=json.dumps(payload), text=True, capture_output=True)
        assert again.returncode != 0 and ledger.read_bytes() == before, 'blocked round rerun'
    # R17 决策表：部分冲突优先于缺失；无冲突缺字段只能 Unknown。
    from review_execution import record_axis_execution, round_release_blockers
    native = {'source': 'native_readback', 'identity': {'agent': 'pi', 'model': 'provider/model'},
              'applied_effort': 'high', 'evidence_id': 'adapter-fixture-only'}
    cases = [(native, 'matched'), (None, 'unknown')]
    for field in ('agent', 'model', 'effort'):
        partial = copy.deepcopy(native)
        if field == 'effort':
            del partial['applied_effort']
            partial['identity']['effort'] = 'high'  # requested/argv effort 不是 applied。
        else:
            del partial['identity'][field]
        cases.append((partial, 'unknown'))
        wrong = copy.deepcopy(native)
        if field == 'effort': wrong['applied_effort'] = 'low'
        else: wrong['identity'][field] = 'other'
        cases.append((wrong, 'mismatch'))
    cases.append(({'source': 'native_readback', 'identity': {'model': 'other'}}, 'mismatch'))
    for source in ('pane', 'lane', 'argv', None):
        cases.append(({**native, 'source': source}, 'unknown'))
    for raw, expected in cases:
        observed = record_axis_execution('standards', requested, raw)
        assert observed['status'] == expected, (raw, observed)
        assert observed['requested'] == requested
        assert round_release_blockers([observed]) == (
            ['reviewer_execution_mismatch'] if expected == 'mismatch' else [])
        if raw is None or raw.get('source') != 'native_readback':
            assert observed['executed'] is None
        elif 'applied_effort' not in raw and observed['executed']:
            assert observed['executed']['effort'] is None
    # 用真实 CLI/文件读回 Unknown、matched、不完整输入；不调用 Herdr 或读取配置。
    with tempfile.TemporaryDirectory() as tmp:
        for name, readbacks, expected in (
            ('unknown', {}, 'PASS'),
            ('matched', {axis: native for axis in axes}, 'PASS'),
            ('partial', {'standards': native}, 'PASS')):
            data = {**payload, 'native_readbacks': readbacks}
            ledger = Path(tmp)/f'{name}.json'
            result = subprocess.run([sys.executable, str(script), '--ledger', str(ledger)],
                                    input=json.dumps(data), text=True, capture_output=True)
            assert result.returncode == 0 and result.stdout.strip() == expected, result.stderr
            saved = json.loads(ledger.read_text())['rounds'][0]
            assert saved['axes'] == axes and saved['release_blockers'] == []
            assert [e['status'] for e in saved['execution_evidence']] == {
                'unknown': ['unknown', 'unknown'], 'matched': ['matched', 'matched'],
                'partial': ['matched', 'unknown']}[name]
        for name, data in (
            ('missing-packet', {k: v for k, v in payload.items() if k != 'review_packet'}),
            ('missing-axis', {**payload, 'axes': {'spec': axes['spec']}}),
            ('drift', {**payload, 'review_packet': {**packet, 'owner_calls': []}})):
            ledger = Path(tmp)/f'{name}.json'
            result = subprocess.run([sys.executable, str(script), '--ledger', str(ledger)],
                                    input=json.dumps(data), text=True, capture_output=True)
            assert result.returncode != 0 and not ledger.exists(), name
    print('axis-evidence-mismatch: pass (adapter simulation; native model/effort Unknown)')


def check_different_family():
    # 公开生产 dispatch CLI，替身仅位于 Herdr I/O；不调用真实 lane。
    import importlib.util
    module_path = Path(__file__).resolve().parents[2]/'delivery-pipeline-setup/scripts/model_config.py'
    spec = importlib.util.spec_from_file_location('review_mc', module_path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    primary = {'agent': 'pi', 'model': 'provider/model', 'effort': 'high'}
    first = {**primary, 'model': 'z-first'}
    later = {**primary, 'model': 'a-later'}
    config = m.migrate_document(m.valid_fixture())[0]
    for axis, candidate in [('standards', first), ('spec', later)]:
        config['review']['whole-change'][axis]['candidates'] = [candidate]
    config['model_families'] = {'pi': {model: {'family': family, 'source': 'user_declared'}
        for model, family in [('provider/model', 'impl'), ('z-first', 'other'), ('a-later', 'other')]}}
    probe = {'request_id': 'r1', 'observed_at': 'fixture-only', 'sources': {'pi': {'status': 'ok'}},
        'capabilities': {'pi': {'binary': True, 'models': {x: ['high'] for x in ['provider/model', 'z-first', 'a-later']}}}}
    native = {'request_id': 'r1', 'observed_at': 'fixture-only', 'capabilities': {
        axis: [{'identity': x, 'status': 'runnable', 'reason': None, 'evidence_id': f'fixture-{axis}-{i}'}
               for i, x in enumerate([primary, candidate])]
        for axis, candidate in [('standards', first), ('spec', later)]}}
    base = {'tabs': [{'tab_id': 'w1:t1', 'label': 'coord', 'pane_count': 1, 'workspace_id': 'w1'}],
            'panes': [{'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'workspace_id': 'w1'}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'herdr').write_text(f'#!{sys.executable}\n'+FAKE_HERDR)
        (root/'watch').write_text('#!/bin/sh\nexit 0\n')
        for name in ['herdr', 'watch']: (root/name).chmod(0o755)
        owner = root/'owner/SKILL.md'; owner.parent.mkdir()
        owner.write_text('---\nname: code-review\n---\nfixture only\n')
        packet = f'Owner：code-review；{owner}；fixture file invocation\n'
        map_text = GOOD_MAP.replace('role: map', 'work_item: DD-508\nrole: map\nbase_commit: abc')
        implementation = root/'impl.md'
        implementation.write_text('<!-- wayfinder-lane-registry:v2 -->\n```yaml\nlane_id: impl\nwork_item: DD-512\nrole: backend\noutput_mode: commit\nmap: map-demo\nintegrated_commit: def\nagent: pi\nmodel: provider/model\neffort: high\n```\n')
        native_path = root/'native.json'; native_path.write_text(json.dumps(native))
        flags = ('--task', 'review', '--output-mode', 'verdict', '--review-scope', 'whole-change',
                 '--required-axes', 'standards', 'spec', '--request-id', 'r1',
                 '--implementation-registry', str(implementation))
        result, path, calls = run(root, 'different', base, packet=packet, map_text=map_text,
            config_document=config, probe_evidence=probe, extra=(*flags, '--native-capabilities', str(native_path)))
        assert result.returncode == 0, result.stdout+result.stderr
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
        import lane_registry
        row, _ = lane_registry.read(path, 'different')
        plan = row['review_plan']
        assert plan['lane']['selected'] == first and plan['lane'] == plan['axes']['standards'], plan
        assert plan['axes']['spec']['selected'] == later
        assert plan['lane']['comparison_basis'] == 'requested'
        assert len([c for c in calls if c[:2] == ['agent', 'start']]) == 1
        start = next(c for c in calls if c[:2] == ['agent', 'start'])
        assert start[start.index('--model')+1] == 'z-first'
        delivered = (root/'packet.md').read_text()
        payload = json.loads(delivered.split('<!-- DP_REVIEW_PLAN -->')[1].split('```json')[1].split('```')[0])
        assert [c['requested'] for c in payload['owner_calls']] == [first, later]
        assert all(c['execution_evidence'] is None for c in payload['owner_calls'])
        assert 'review_execution.py' in delivered and 'native_readbacks' in delivered
        for name, extra in [('missing', flags), ('stale', (*flags, '--native-capabilities', str(native_path)))]:
            native_path.write_text(json.dumps({**native, 'request_id': 'stale'}))
            result, path, calls = run(root, name, base, packet=packet, map_text=map_text,
                config_document=config, probe_evidence=probe, extra=extra)
            assert result.returncode != 0 and not calls, '缺证据不得 mutation'
            assert (root/'packet.md').read_text() == packet and not path.exists()
    print('different-family dispatch: pass (fake native I/O; true execution Unknown)')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--case', choices=['single-model', 'axis-evidence-mismatch', 'different-family'], required=True)
    args = p.parse_args()
    ({'axis-evidence-mismatch': check_axis_evidence, 'different-family': check_different_family}.get(args.case, check))()
