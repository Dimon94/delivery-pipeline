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
        assert len([c for c in calls if c[:2] == ['agent', 'start'] and '--help' not in c]) == 1
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


def native_boundary(root):
    """替身只在安装文件与原生进程 I/O；不以此证明 native 接受。"""
    model_path=root/'.pi/agent/models.json'; model_path.parent.mkdir(parents=True); model_path.write_text('{}')
    pkg = root/'pi-package'
    for name in ['dist/bundle/cli.js', 'dist/cli/args.js', 'dist/core/model-config.js',
                 'dist/core/model-resolver.js', 'node_modules/@earendil-works/pi-ai/dist/models.js']:
        path = pkg/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(f'#!{sys.executable}\nprint("1.5.2")\n' if name=='dist/bundle/cli.js' else '// external fixture')
    (pkg/'package.json').write_text(json.dumps({'name':'@earendil-works/pi-coding-agent','version':'1.5.2'}))
    (root/'pi').symlink_to(pkg/'dist/bundle/cli.js'); (pkg/'dist/bundle/cli.js').chmod(0o755)
    (root/'node').write_text(f'#!{sys.executable}\n'+r'''import json,sys
from pathlib import Path
root=Path(__file__).parent
x=json.load(sys.stdin)
statuses=json.loads((root/'native-status.json').read_text()) if (root/'native-status.json').exists() else {}
print(json.dumps([{'identity':i,'status':statuses.get(i['model'],'runnable'),
 'reason':'external native boundary fixture'} for i in x['identities']]))
''')
    (root/'node').chmod(0o755)
    fake = FAKE_HERDR.replace('if args[:2] == ["pane", "current"]:',
        'if args == ["--version"]: print("herdr 0.9.5")\nelif args == ["agent", "start", "--help"]: print("[possible values: pi, codex] -- [AGENT_ARG]")\nelif args[:2] == ["pane", "current"]:')
    (root/'herdr').write_text(f'#!{sys.executable}\n'+fake)
    (root/'herdr').chmod(0o755)


def mutations(calls):
    return [c for c in calls if c[:2] not in [['agent','start']] and c not in [['--version'],['agent','start','--help']]] + [c for c in calls if c[:2]==['agent','start'] and c != ['agent','start','--help']]


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
        native_boundary(root)
        native_path = root/'native.json'; native_path.write_text(json.dumps(native))
        flags = ('--task', 'review', '--output-mode', 'verdict', '--review-scope', 'whole-change',
                 '--required-axes', 'standards', 'spec', '--request-id', 'r1',
                 '--implementation-registry', str(implementation))
        result, path, calls = run(root, 'different', base, packet=packet, map_text=map_text,
            config_document=config, probe_evidence=probe, env_extra={'HOME':str(root)}, extra=flags)
        assert result.returncode == 0, result.stdout+result.stderr
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
        import lane_registry
        row, _ = lane_registry.read(path, 'different')
        plan = row['review_plan']
        assert plan['lane']['selected'] == first and plan['lane'] == plan['axes']['standards'], plan
        assert plan['axes']['spec']['selected'] == later
        assert plan['lane']['comparison_basis'] == 'requested'
        assert len([c for c in calls if c[:2] == ['agent', 'start'] and '--help' not in c]) == 1
        start = next(c for c in calls if c[:2] == ['agent', 'start'] and '--help' not in c)
        assert start[start.index('--model')+1] == 'z-first'
        delivered = (root/'packet.md').read_text()
        payload = json.loads(delivered.split('<!-- DP_REVIEW_PLAN -->')[1].split('```json')[1].split('```')[0])
        assert [c['requested'] for c in payload['owner_calls']] == [first, later]
        assert all(c['execution_evidence'] is None for c in payload['owner_calls'])
        assert 'review_execution.py' in delivered and 'native_readbacks' in delivered
        # 自述文件不再授予能力；当前原生进程 Unknown 时即使文件声称成功也阻断。
        (root/'native-status.json').write_text(json.dumps({'z-first':'unknown'}))
        result, path, calls = run(root, 'missing', base, packet=packet, map_text=map_text,
            config_document=config, probe_evidence=probe, env_extra={'HOME':str(root)}, extra=(*flags,'--native-capabilities',str(native_path)))
        assert result.returncode != 0 and not mutations(calls), '缺证据不得 mutation'
        assert (root/'packet.md').read_text() == packet and not path.exists()
    print('different-family dispatch: pass (fake native I/O; true execution Unknown)')


def check_runnable_fallback():
    """DD513 R10/R14/R17：外部 I/O 替身；真实生产 dispatch/packet/Registry/gate。"""
    import importlib.util
    import subprocess
    spec = importlib.util.spec_from_file_location('mc', Path(__file__).resolve().parents[2]/'delivery-pipeline-setup/scripts/model_config.py')
    mc = importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
    import lane_registry
    primary = {'agent': 'pi', 'model': 'provider/model', 'effort': 'high'}
    first = {**primary, 'model': 'z-first'}
    later = {**primary, 'model': 'a-later'}
    config = mc.migrate_document(mc.valid_fixture())[0]
    for axis in ('standards', 'spec'):
        config['review']['whole-change'][axis]['candidates'] = [first, later, first]
    config['model_families'] = {'pi': {
        primary['model']: {'family': 'blue', 'source': 'user_declared'},
        'impl': {'family': 'red', 'source': 'user_declared'}}}
    probe = {'request_id': 'fallback', 'observed_at': 'fixture', 'sources': {'pi': {'status': 'ok'}},
        'capabilities': {'pi': {'binary': True, 'models': {x['model']: ['high'] for x in (primary, first, later)}}}}
    base = {'tabs': [{'tab_id': 'w1:t1', 'label': 'coord', 'pane_count': 1, 'workspace_id': 'w1'}],
            'panes': [{'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'workspace_id': 'w1'}]}
    for comparison in ('same', 'unknown'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); native_boundary(root)
            (root/'native-status.json').write_text(json.dumps({primary['model']: 'unavailable'}))
            (root/'watch').write_text('#!/bin/sh\nexit 0\n'); (root/'watch').chmod(0o755)
            owner = root/'owner/SKILL.md'; owner.parent.mkdir()
            owner.write_text('---\nname: code-review\n---\nfixture only')
            packet = f'Owner：code-review；{owner}；fixture invocation\n'
            map_text = GOOD_MAP.replace('role: map', 'work_item: DD-508\nrole: map\nbase_commit: abc')
            implementation = root/'impl.md'
            lane_registry.write(implementation, {'lane_id': 'impl', 'work_item': 'DD-513', 'role': 'backend',
                'map': 'map-demo', 'output_mode': 'commit', 'integrated_commit': 'def', **{**primary, 'model': 'impl'}})
            if comparison == 'same':
                config['model_families']['pi']['z-first'] = {'family': 'red', 'source': 'user_declared'}
            else:
                config['model_families']['pi'].pop('z-first', None)
            flags = ('--task', 'review', '--output-mode', 'verdict', '--review-scope', 'whole-change',
                     '--required-axes', 'standards', 'spec', '--request-id', 'fallback',
                     '--implementation-registry', str(implementation))
            result, path, calls = run(root, 'fallback-'+comparison, base, packet=packet, map_text=map_text,
                config_document=config, probe_evidence=probe, env_extra={'HOME': str(root)}, extra=flags)
            assert result.returncode == 0, result.stdout+result.stderr
            plan = lane_registry.read(path, 'fallback-'+comparison)[0]['review_plan']
            for axis in ('standards', 'spec'):
                selected = plan['axes'][axis]
                assert selected['selected'] == first and selected['selected_index'] == 1
                assert selected['comparison'] == comparison
                assert selected['fallback'] == 'no_different_family_candidate'
                attempts = selected['attempts']
                assert [a['identity'] for a in attempts] == [primary, first, later, first]
                assert [a['status'] for a in attempts] == ['unavailable', 'runnable', 'runnable', 'runnable']
                assert attempts[0]['comparison'] == 'different'  # different 但不可运行不能获选。
                assert [a['reason'] for a in attempts] == ['external native boundary fixture', 'selected', 'later_in_user_order', 'later_in_user_order']
            assert plan['lane'] == plan['axes']['standards']
            starts = [c for c in calls if c[:2] == ['agent', 'start'] and '--help' not in c]
            assert len(starts) == 1 and starts[0][starts[0].index('--model')+1] == 'z-first'
            delivered = (root/'packet.md').read_text()
            payload = json.loads(delivered.split('<!-- DP_REVIEW_PLAN -->')[1].split('```json')[1].split('```')[0])
            lane_registry.verify_review_packet(plan, payload)
            assert [c['requested'] for c in payload['owner_calls']] == [first, first]
            assert all(c['execution_evidence'] is None for c in payload['owner_calls'])
            axes = {a: {'verdict': 'PASS', 'counts': {'P0':0,'P1':0,'P2':0,'P3':0}, 'findings': []} for a in ('standards','spec')}
            ledger = root/'ledger.json'
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('review_execution.py')), '--ledger', str(ledger)],
                input=json.dumps({'round': 1, 'axes': axes, 'review_packet': payload, 'native_readbacks': {}}), text=True, capture_output=True)
            assert result.returncode == 0 and result.stdout.strip() == 'PASS', result.stdout+result.stderr
            saved = json.loads(ledger.read_text())['rounds'][0]
            assert [e['status'] for e in saved['execution_evidence']] == ['unknown', 'unknown']
            assert saved['axes'] == axes
    print('runnable-fallback: pass (same/unknown; external I/O fixture; actual execution Unknown)')


def check_capability_safety():
    # 真实生产入口/文件/进程；外部 Herdr、Pi 的 I/O 替身。预期 DD514 R6/R11/R15。
    import importlib.util
    spec = importlib.util.spec_from_file_location('mc', Path(__file__).resolve().parents[2]/'delivery-pipeline-setup/scripts/model_config.py')
    mc=importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
    c=mc.migrate_document(mc.valid_fixture())[0]
    a=mc.triple(c['review']['whole-change']['standards']); b={**a,'model':'second'}
    c['review']['whole-change']['standards']['candidates']=[b,b]
    ev={'request_id':'safe','observed_at':'fixture','sources':{'pi':{'status':'ok'}},
        'capabilities':{'pi':{'binary':True,'models':{a['model']:['high'],'second':['high']}}}}
    base={'tabs':[{'tab_id':'w1:t1','label':'coord','pane_count':1,'workspace_id':'w1'}],
          'panes':[{'pane_id':'w1:p1','tab_id':'w1:t1','workspace_id':'w1'}]}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); native_boundary(root)
        (root/'watch').write_text('#!/bin/sh\nexit 0\n');(root/'watch').chmod(0o755)
        owner=root/'owner/SKILL.md';owner.parent.mkdir();owner.write_text('---\nname: code-review\n---\nfixture')
        packet=f'Owner：code-review；{owner}；fixture invocation\n'
        flags=('--task','review','--output-mode','verdict','--review-scope','whole-change',
               '--required-axes','standards','--request-id','safe')
        map_text=GOOD_MAP.replace('role: map','work_item: DD-508\nrole: map\nbase_commit: base')
        scenarios=[('missing',{b['model']:'unknown'},'review_capability_evidence_required'),
                   ('all',{a['model']:'unavailable',b['model']:'unavailable'},'review_no_runnable_candidate'),
                   ('skip',{a['model']:'unavailable'},None),
                   ('start-failed',{a['model']:'unavailable'},None)]
        for name,statuses,error in scenarios:
            (root/'native-status.json').write_text(json.dumps(statuses))
            state={**base,'working':name!='start-failed'}
            result,path,calls=run(root,name,state,packet=packet,map_text=map_text,config_document=c,probe_evidence=ev,env_extra={'HOME':str(root)},extra=flags)
            if error:
                assert result.returncode!=0 and error in result.stdout,result.stdout+result.stderr
                assert not mutations(calls) and not path.exists() and (root/'packet.md').read_text()==packet
                if name=='all':
                    assert 'second' in result.stdout and 'provider/model' in result.stdout
            else:
                starts=[x for x in calls if x[:2]==['agent','start'] and '--help' not in x]
                assert len(starts)==1 and starts[0][starts[0].index('--model')+1]=='second',(calls,result.stdout,result.stderr)
                assert (result.returncode==0)==(name=='skip')
                if name=='start-failed': assert 'setup_blocked' in path.read_text()
        (root/'native-status.json').write_text('{}')
        result,path,calls=run(root,'readonly',base,packet=packet,map_text=map_text,config_document=c,
            probe_evidence=ev,env_extra={'HOME':str(root)},extra=(*flags,'--preflight-only'))
        assert result.returncode==0 and json.loads(result.stdout)['state']=='preflight_ready',result.stdout+result.stderr
        assert not mutations(calls) and not path.exists() and (root/'packet.md').read_text()==packet
        # 单模型和非参与 implementation 池不应触发候选 native 门槛。
        c['review']['whole-change']['standards']['candidates']=[]
        c['review']['whole-change']['spec']['candidates'] = [{**b, 'model':'nonparticipating-axis'}]
        c['review']['implementation']['spec']['candidates']=[{**b,'model':'unobserved'}]
        (root/'native-status.json').write_text(json.dumps({a['model']:'unknown'}))
        result,path,calls=run(root,'legacy',base,packet=packet,map_text=map_text,config_document=c,probe_evidence=ev,env_extra={'HOME':str(root)},extra=flags)
        assert result.returncode==0,result.stdout+result.stderr
        assert ['--version'] not in calls
    print('capability-safety dispatch: pass (external I/O fixtures; native acceptance Unknown)')



def check_same_round():
    """独立预期 DD515 AC1–6 / R12/R15/R17：原请求只读恢复、零第二副作用。"""
    import os
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
    import lane_registry as registry
    base = {'tabs': [{'tab_id':'w1:t1','label':'coord','pane_count':1,'workspace_id':'w1'}],
            'panes': [{'pane_id':'w1:p1','tab_id':'w1:t1','workspace_id':'w1'}]}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/'herdr').write_text(f'#!{sys.executable}\n'+FAKE_HERDR)
        (root/'watch').write_text('#!/bin/sh\nexit 0\n')
        for name in ('herdr','watch'): (root/name).chmod(0o755)
        owner=root/'owner/SKILL.md'; owner.parent.mkdir(); owner.write_text('---\nname: code-review\n---\nfixture')
        packet=f'Owner：code-review；{owner}；fixture\n'
        flags=('--task','review','--output-mode','verdict','--review-scope','whole-change',
               '--required-axes','standards','spec','--request-id','original')
        map_text=GOOD_MAP.replace('role: map','work_item: DD-508\nrole: map\nbase_commit: base')
        result,path,calls=run(root,'recover',base,packet=packet,map_text=map_text,extra=flags)
        assert result.returncode==0,result.stdout+result.stderr
        original,_=registry.read(path,'recover')
        assert original['herdr']['startup_state']=='completed', '原启动 receipt 未持久化'
        assert original['herdr']['receipt'], '缺原始 receipt'
        starts=sum(c[:2]==['agent','start'] for c in calls); assert starts==1
        frozen=original['review_plan']
        # 配置/catalog 已坏：恢复不得读取它们，不调用原生 IO。
        (root/'model-roles.json').write_text('broken'); (root/'evidence.json').unlink()
        cmd=[sys.executable,str(Path(__file__).with_name('dispatch.py')),'--recover-review',
             '--registry',str(path),'--lane','recover','--request-id','original']
        before=path.read_bytes(); call_bytes=(root/'calls.jsonl').read_bytes()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:subprocess.run(cmd,text=True,capture_output=True),range(2)))
        for r in results:
            assert r.returncode==0,r.stdout+r.stderr
            got=json.loads(r.stdout)
            assert got['review_packet']['review_plan']==frozen
            assert got['row']==original and got['action']=='recover_original'
        assert path.read_bytes()==before and (root/'calls.jsonl').read_bytes()==call_bytes
        # response lost / 取消 / 启动失败均只读原证据，不派下一项。
        for state,startup,action in [('setup_blocked','launching','inspect_original'),
                                     ('cancelled','completed','stop'),('setup_blocked','failed','stop')]:
            row={**original,'state':state,'herdr':{**original['herdr'],'startup_state':startup}}
            registry.write(path,row)
            before=path.read_bytes()
            r=subprocess.run(cmd,text=True,capture_output=True)
            assert r.returncode==0,r.stderr+r.stdout
            got=json.loads(r.stdout); assert got['action']==action and got['row']==row
            assert path.read_bytes()==before and (root/'calls.jsonl').read_bytes()==call_bytes
            _,rev=registry.read(path,'recover')
            try: registry.claim(path,'recover',rev,'no-replacement','tool_or_model',lambda _:dict(writer='exited',identity='match',capability='verified',gate='allowed'))
            except ValueError as error:
                assert 'original plan/receipt' in str(error), '必须返回原 review 恢复合同，不能落入 legacy work 策略'
            else: raise AssertionError('review 进入 work replacement')
            assert path.read_bytes()==before
        # 已完成轴原结果随原 gate 可恢复；终态不重提、不丢 finding，不为并行补跑。
        ledger=root/'review-budget.json'
        packet_data={'review_plan':frozen,'owner_calls':registry.build_owner_calls(frozen)}
        clean={'P0':0,'P1':0,'P2':0,'P3':0}
        axes={axis:{'verdict':'PASS','counts':{**clean,'P3':1},'findings':['原始 finding '+axis]}
              for axis in ('standards','spec')}
        data={'round':1,'axes':axes,'review_packet':packet_data,'native_readbacks':{}}
        gate=[sys.executable,str(Path(__file__).with_name('review_execution.py')),'--ledger',str(ledger)]
        r=subprocess.run(gate,input=json.dumps(data),text=True,capture_output=True)
        assert r.returncode==0 and r.stdout.strip()=='PASS',r.stderr
        before=ledger.read_bytes()
        r=subprocess.run([*cmd,'--review-ledger',str(ledger)],text=True,capture_output=True)
        got=json.loads(r.stdout)
        assert r.returncode==0 and got['action']=='stop'
        assert got['recorded_rounds'][0]['axes']==axes and len(got['recorded_rounds'])==1
        assert [e['status'] for e in got['recorded_rounds'][0]['execution_evidence']]==['unknown','unknown']
        r=subprocess.run(gate,input=json.dumps(data),text=True,capture_output=True)
        assert r.returncode!=0 and ledger.read_bytes()==before
        fix_ledger=root/'fix-budget.json'
        blocked={**axes['standards'],'verdict':'BLOCK','counts':{**clean,'P1':1},'findings':['原始阻断 finding']}
        fix_data={**data,'axes':{**axes,'standards':blocked},'repros':['node --test blocked.test.js']}
        r=subprocess.run([*gate[:-1],str(fix_ledger)],input=json.dumps(fix_data),text=True,capture_output=True)
        assert r.returncode==0 and r.stdout.strip()=='FIX',r.stderr
        r=subprocess.run([*cmd,'--review-ledger',str(fix_ledger)],text=True,capture_output=True)
        got=json.loads(r.stdout)
        assert r.returncode==0 and got['action']=='stop', '取消/失败优先于原 FIX 恢复'
        assert got['recorded_rounds'][0]['axes']['standards']==blocked
        # 相同 intent 换 lane 也不得占第二 lane；真实独立 Python 进程竞争同一文件。
        race=root/'race.md'
        worker="""import sys,json; from pathlib import Path
sys.path.insert(0,sys.argv[1]); import lane_registry as r
row=json.loads(sys.argv[3]); r.reserve_review(Path(sys.argv[2]),row)
"""
        core=str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts')
        def reserve(i):
            row={**original,'lane_id':f'race-{i}','state':'terminal'}
            return subprocess.run([sys.executable,'-c',worker,core,str(race),json.dumps(row)],capture_output=True)
        with ThreadPoolExecutor(2) as pool: reserved=list(pool.map(reserve,range(2)))
        assert sorted(r.returncode for r in reserved)==[0,1]
        assert len(registry.rows(race))==1
        # 原生 IO 已收到 start 后杀死当前 dispatch 进程，真实持久前缀恢复不重发。
        fault = FAKE_HERDR.replace('if args[:2] == ["pane", "current"]:',
            'if args[:2] == ["agent", "start"]:\n    import os,signal\n    (root/"start-accepted").write_text("external fixture only")\n    os.kill(os.getppid(), signal.SIGKILL)\n    raise SystemExit(1)\nelif args[:2] == ["pane", "current"]:')
        (root/'herdr').write_text(f'#!{sys.executable}\n'+fault)
        r,path,calls=run(root,'response-lost',base,packet=packet,map_text=map_text,extra=flags)
        assert r.returncode!=0 and (root/'start-accepted').exists()
        pending,_=registry.read(path,'response-lost')
        assert pending['herdr']['startup_state']=='launching' and 'receipt' not in pending['herdr']
        trace=(root/'calls.jsonl').read_bytes(); before=path.read_bytes()
        r=subprocess.run([sys.executable,str(Path(__file__).with_name('dispatch.py')),
            '--recover-review','--registry',str(path),'--lane','response-lost','--request-id','original'],
            text=True,capture_output=True)
        got=json.loads(r.stdout)
        assert r.returncode==0 and got['action']=='inspect_original' and got['row']==pending
        assert path.read_bytes()==before and (root/'calls.jsonl').read_bytes()==trace
        # exit 0 但响应不可解析也不能伪造 completed receipt。
        malformed=FAKE_HERDR.replace('if args[:2] == ["pane", "current"]:',
            'if args[:2] == ["agent", "start"]:\n    print("response lost")\nelif args[:2] == ["pane", "current"]:')
        (root/'herdr').write_text(f'#!{sys.executable}\n'+malformed)
        r,path,calls=run(root,'malformed-response',base,packet=packet,map_text=map_text,extra=flags)
        saved,_=registry.read(path,'malformed-response')
        assert r.returncode!=0 and saved['herdr']['startup_state']=='launching'
        assert 'receipt' not in saved['herdr'] and sum(c[:2]==['agent','start'] for c in calls)==1
        # 等待 working 超时不是未收到 packet：review 禁止二次 prompt 或关 pane 丢证据。
        (root/'herdr').write_text(f'#!{sys.executable}\n'+FAKE_HERDR)
        r,path,calls=run(root,'working-unknown',{**base,'working':False},packet=packet,map_text=map_text,extra=flags)
        assert r.returncode!=0
        assert sum(c[:2]==['agent','prompt'] for c in calls)==1, 'Unknown working 不得重复投递 review packet'
        assert not any(c[:2]==['pane','close'] for c in calls), '必须保留原 session 证据'
    check_axis_evidence()
    print('same-round-recovery: pass (真实文件/独立进程；native IO 替身，实际执行 Unknown)')


def check_later_round():
    """真实文件/公开派发和 gate；替身仅在 native I/O。预期来自 DD516。"""
    import subprocess
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
    import lane_registry as registry
    from review_gate import read_ledger
    base={'tabs':[{'tab_id':'w1:t1','label':'coord','pane_count':1,'workspace_id':'w1'}],
          'panes':[{'pane_id':'w1:p1','tab_id':'w1:t1','workspace_id':'w1'}]}
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/'herdr').write_text(f'#!{sys.executable}\n'+FAKE_HERDR)
        (root/'watch').write_text('#!/bin/sh\nexit 0\n')
        for name in ('herdr','watch'): (root/name).chmod(0o755)
        owner=root/'owner.md'; owner.write_text('---\nname: code-review\n---\nfixture')
        packet=f'Owner：code-review；{owner}；fixture\n'
        map_text=GOOD_MAP.replace('role: map','work_item: DD-508\nrole: map\nbase_commit: abc')
        ledger=root/'budget.json'
        flags=('--task','review','--output-mode','verdict','--review-scope','whole-change',
               '--required-axes','standards','spec','--review-ledger',str(ledger))
        r,path,calls=run(root,'r1',base,packet=packet,map_text=map_text,extra=(*flags,'--request-id','r1','--review-head','h1'))
        assert r.returncode==0,r.stdout+r.stderr
        row,_=registry.read(path,'r1'); frozen=row['review_plan']
        assert frozen['round_context']['head']=='h1'
        clean=dict(P0=0,P1=0,P2=0,P3=0)
        passing=dict(verdict='PASS',counts=clean,findings=['original'])
        blocking=dict(verdict='BLOCK',counts={**clean,'P1':1},findings=['spec repair'])
        gate=[sys.executable,str(Path(__file__).with_name('review_execution.py')),'--ledger',str(ledger)]
        data=dict(round=1,axes=dict(standards=passing,spec=blocking),review_packet=dict(review_plan=frozen,owner_calls=registry.build_owner_calls(frozen)))
        r=subprocess.run(gate,input=json.dumps(data),text=True,capture_output=True)
        assert r.returncode!=0 and not ledger.exists(), 'P1 without repro accepted'
        data['repros']=['node --test spec.test.js']
        r=subprocess.run(gate,input=json.dumps(data),text=True,capture_output=True)
        assert r.returncode==0 and r.stdout.strip()=='FIX',r.stderr
        row['state']='consumed'; registry.write(path,row)
        budget=ledger.read_bytes()
        # ADR-0027 一轮制：FIX 之后的新 head 不能开 R2，不触发 native，预算字节不变。
        fixer=root/'fixer.md'
        registry.write(fixer,dict(lane_id='fixer',work_item='repair',map='map-demo',role='backend',output_mode='commit',integrated_commit='h2',agent='pi',model='provider/model',effort='high'))
        later=(*flags,'--round','2','--request-id','r2','--review-head','h2','--previous-review-registry',str(path),'--implementation-registry',str(fixer))
        spec_flags=list(later); spec_flags.remove('standards')
        for extra in (later, spec_flags):
            r,path2,calls=run(root,'r2',base,packet=packet,map_text=map_text,extra=extra)
            assert r.returncode!=0 and not calls and not path2.exists(), 'R2 accepted after FIX'
            assert ledger.read_bytes()==budget
        # 原始完整结果复用；新 lane 无写入，无 native 调用，预算字节不变。
        reuse=list(later); reuse[reuse.index('h2')]='h1'
        r,reuse_path,calls=run(root,'reuse',base,packet=packet,map_text=map_text,extra=reuse)
        assert r.returncode==0 and json.loads(r.stdout)['result']==read_ledger(ledger)[0],r.stdout+r.stderr
        assert not calls and not reuse_path.exists() and ledger.read_bytes()==budget
    print('later-round: pass (一轮制：repro 必填、R2 拒绝、同 head 复用；native执行 Unknown)')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--case', choices=['later-round', 'same-round-recovery', 'single-model', 'axis-evidence-mismatch', 'different-family', 'capability-safety', 'runnable-fallback'], required=True)
    args = p.parse_args()
    ({'later-round':check_later_round, 'same-round-recovery':check_same_round, 'runnable-fallback':check_runnable_fallback, 'capability-safety':check_capability_safety, 'axis-evidence-mismatch': check_axis_evidence, 'different-family': check_different_family}.get(args.case, check))()
