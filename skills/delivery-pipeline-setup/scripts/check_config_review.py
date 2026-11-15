#!/usr/bin/env python3
"""DD-509/DD-511：单模型冻结计划与候选/家族事务的公开检查，无原生执行。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_config_transaction import m, SCRIPT, FAULT_RUNNER
sys.path.insert(0, str(HERE.parents[1] / 'delivery-pipeline/scripts'))
import lane_registry as registry


def check_single_model(version):
    config = m.valid_fixture()
    if version == 7:
        config = m.migrate_document(config)[0]
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
    assert config['version'] == version
    assert ('model_families' in config) == (version == 7)
    print('single-model-plan: pass (fixture; no native execution)')


def check_candidate_family():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'config.json'
        evpath = Path(tmp)/'evidence.json'
        a = {'agent':'pi','model':'provider/model','effort':'high'}
        b = {**a,'effort':'low'}
        old = m.valid_fixture()
        old['version'] = 6
        old.pop('model_families', None)
        path.write_text(json.dumps(old))
        def cli(command, candidate=None, base=None, fault=None):
            args = [sys.executable,str(SCRIPT)] if fault is None else [sys.executable,'-c',FAULT_RUNNER,str(SCRIPT),fault]
            args += [command,str(path)]
            if candidate is not None:
                args += ['--base-hash',base or hashlib.sha256(path.read_bytes()).hexdigest(),'--request-id','save','--evidence',str(evpath)]
            p = subprocess.run(args,input=json.dumps(candidate) if candidate is not None else None,text=True,capture_output=True)
            assert p.stdout, p.stderr
            return p.returncode,json.loads(p.stdout)
        raw=path.read_bytes()
        assert cli('show')[1]['file_state']=='ready' and path.read_bytes()==raw
        assert cli('migrate')[0]==0
        expected={**old,'version':7,'model_families':{}}
        assert json.loads(path.read_text())==expected, '显式 v6→v7 只能补空声明'
        assert m.resolve_plan(old,'planning')==m.resolve_plan(expected,'planning')
        ev={'request_id':'save','observed_at':'now','sources':{'pi':{'status':'ok'}},'capabilities':{'pi':{'binary':True,'models':{'provider/model':['high','low']}}}}
        evpath.write_text(json.dumps(ev))
        candidate=copy.deepcopy(expected)
        for axes in candidate['review'].values():
            for c in axes.values(): c['candidates']=[b,a,b]
        candidate['model_families']={'pi':{'provider/model':{'family':'example-family','source':'user_declared'}}}
        code,result=cli('apply',candidate);assert code==0,result
        assert result['config']==candidate and json.loads(path.read_text())==candidate
        frozen_candidate = copy.deepcopy(candidate)
        try:
            m.resolve_review_plan(candidate, required_axes=['standards', 'spec'], implementations=[],
                                  evidence=ev['capabilities'], native_capabilities={}, request_id='candidate-round')
        except ValueError as error:
            assert 'review_capability_evidence_required' in str(error)
        else:
            raise AssertionError('非空候选不得绕过后续选序门槛')
        assert candidate == frozen_candidate
        for model in ('provider','model','provider/model-other','display label','route/provider/model'):
            assert m.family_declaration(candidate,'pi',model) is None
        assert m.family_declaration(candidate,'codex','provider/model') is None
        assert m.family_declaration(candidate,'pi','provider/model')=={'family':'example-family','source':'user_declared'}
        for model in ('provider','model','display label','route/provider/model'):
            bad=copy.deepcopy(candidate)
            bad['model_families']['pi'][model]={'family':'injected','source':'user_declared'}
            raw=path.read_bytes()
            assert cli('apply',bad)[0]==1 and path.read_bytes()==raw, '清单外声明不得注入'
        # 排序和删除不用新的能力，重复计数增加必须重新核验。
        ev['sources']['pi']['status']='unknown';evpath.write_text(json.dumps(ev))
        reordered=copy.deepcopy(candidate)
        for axes in reordered['review'].values():
            for c in axes.values(): c['candidates']=[a,b,b]
        assert cli('apply',reordered)[0]==0
        raw=path.read_bytes()
        bad=copy.deepcopy(reordered);bad['review']['whole-change']['spec']['candidates'].append(b)
        assert cli('apply',bad)[0]==1 and path.read_bytes()==raw
        for model in ('provider','model','display label','route/provider/model'):
            bad=copy.deepcopy(reordered);bad['review']['whole-change']['spec']['candidates'].append({**a,'model':model})
            assert cli('apply',bad)[0]==1 and path.read_bytes()==raw
        removed=copy.deepcopy(reordered)
        for axes in removed['review'].values():
            for c in axes.values(): c['candidates']=[]
        removed['model_families']['pi']['provider/model']['family']='another-family'
        assert cli('apply',removed)[0]==0
        assert json.loads(path.read_text())['model_families']==removed['model_families']
        raw=path.read_bytes();stat=path.stat()
        assert cli('apply',removed)[1]['changed'] is False
        assert path.read_bytes()==raw and path.stat().st_ino==stat.st_ino
        assert cli('apply',removed,base='stale')[1]['error']['code']=='base_conflict'
        for field in ('work','modes'):
            bad=copy.deepcopy(removed)
            if field=='work': bad['work']['research'] = a
            else: bad['modes']={}
            if bad!=removed: assert cli('apply',bad)[0]==1 and path.read_bytes()==raw
        changed=copy.deepcopy(removed);changed['model_families']={}
        assert cli('apply',changed,fault='pre')[0]==1 and path.read_bytes()==raw
        assert cli('apply',changed,fault='post')[1]['status']=='commit_unverified'
        assert json.loads(path.read_text())==changed
        # 同基线独立进程仅一人成功。
        base=hashlib.sha256(path.read_bytes()).hexdigest()
        args=[sys.executable,str(SCRIPT),'apply',str(path),'--base-hash',base,'--request-id','save','--evidence',str(evpath)]
        processes=[subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) for _ in range(2)]
        outputs=[p.communicate(json.dumps(removed),timeout=10)[0] for p in processes]
        assert sorted(json.loads(v)['status'] for v in outputs)==['applied','rejected']
        assert json.loads(path.read_text())==removed
        app=m.valid_app_fixture();assert m.migrate_document(app)==(app,'app')
    print('candidate-family-transaction: pass (CLI/files/processes; native execution Unknown)')

def check_different_family():
    """DD-508 R4/R9：Unknown 后的首个 different，不能优先主项或字典排序。"""
    config = m.migrate_document(m.valid_fixture())[0]
    primary = {'agent': 'pi', 'model': 'provider/model', 'effort': 'high'}
    unknown = {**primary, 'model': 'undeclared-route'}
    first = {**primary, 'model': 'z-first'}
    later = {**primary, 'model': 'a-later'}
    config['review']['whole-change']['standards']['candidates'] = [unknown, first, later, first]
    config['review']['whole-change']['spec']['candidates'] = [later, first]
    config['model_families'] = {'pi': {name: {'family': family, 'source': 'user_declared'}
        for name, family in [('provider/model', 'impl'), ('z-first', 'other'), ('a-later', 'third')]}}
    pools = {axis: [m.triple(cell), *cell['candidates']]
             for axis, cell in config['review']['whole-change'].items()}
    probe = {'request_id': 'r1', 'observed_at': 'fixture-only', 'sources': {'pi': {'status': 'ok'}},
             'capabilities': {'pi': {'binary': True, 'models': {x['model']: ['high'] for x in pools['standards']}}}}
    native = {axis: [{'identity': x, 'status': 'runnable', 'reason': None,
                     'evidence_id': f'fixture-{axis}-{i}'} for i, x in enumerate(pool)] for axis, pool in pools.items()}
    impl = [{'lane_id': 'impl', 'requested': primary, 'executed': primary}]
    def resolve(implementations=impl, evidence=probe, capabilities=native):
        return m.resolve_review_plan(config, required_axes=['standards', 'spec'], implementations=implementations,
            evidence=evidence, native_capabilities=capabilities, request_id='r1')
    plan = resolve()
    assert plan['lane'] == plan['axes']['standards']
    assert plan['lane']['selected'] == first, '必须首个 runnable+different，不能主项/字典排序/Unknown'
    assert plan['axes']['spec']['selected'] == later, '逐轴独立选序'
    assert [a['identity'] for a in plan['lane']['attempts']] == pools['standards'], '用户顺序及重复不可丢'
    assert [a['comparison'] for a in plan['lane']['attempts']] == ['same', 'unknown', 'different', 'different', 'different']
    assert plan['lane']['comparison_basis'] == 'executed'
    assert plan['lane']['fallback'] == 'none'
    assert plan['family_evidence'] and all(f['source'] == 'declared_at_review' for f in plan['family_evidence'])
    requested = resolve([{**impl[0], 'executed': None}])
    assert requested['lane']['comparison_basis'] == 'requested'
    mixed = resolve([impl[0], {**impl[0], 'lane_id': 'legacy', 'executed': None}])
    assert mixed['lane']['comparison_basis'] == 'mixed'
    unknown_impl = resolve([{**impl[0], 'executed': unknown}])
    assert unknown_impl['lane']['comparison'] == 'unknown'
    assert unknown_impl['lane']['selected'] == primary and unknown_impl['lane']['fallback'] == 'no_different_family_candidate'
    for ev, cap in [(None, native), ({**probe, 'request_id': 'stale'}, native), (probe, {})]:
        try: resolve(evidence=ev, capabilities=cap)
        except ValueError as error: assert 'review_capability_evidence_required' in str(error)
        else: raise AssertionError('缺当前证据必须阻断')
    calls = registry.build_owner_calls(plan)
    assert [c['requested'] for c in calls] == [first, later]
    registry.verify_review_packet(plan, {'review_plan': plan, 'owner_calls': calls})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, value in [('config', config), ('probe', probe),
                            ('native', {'request_id': 'r1', 'observed_at': 'fixture-only', 'capabilities': native})]:
            (root/f'{name}.json').write_text(json.dumps(value))
        source = root/'registry.md'
        registry.write(source, {'lane_id': 'map', 'work_item': 'DD-508', 'role': 'map', 'base_commit': 'base'})
        registry.write(source, {'lane_id': 'impl', 'work_item': 'DD-512', 'role': 'backend', 'map': 'map',
            'output_mode': 'commit', 'integrated_commit': 'head', **primary,
            'implementation_execution': {'source': 'native_readback', 'identity': primary}})
        result = subprocess.run([sys.executable, str(SCRIPT), 'resolve', str(root/'config.json'), 'review',
            '--review-scope', 'whole-change', '--output-mode', 'verdict', '--required-axes', 'standards', 'spec',
            '--request-id', 'r1', '--fixed-point', 'base', '--implementation-registry', str(source),
            '--evidence', str(root/'probe.json'), '--native-capabilities', str(root/'native.json')], text=True, capture_output=True)
        assert result.returncode == 0, result.stdout+result.stderr
        assert json.loads(result.stdout)['review_plan'] == plan
    print('different-family-plan: pass (public resolver; fixture capability, native execution Unknown)')


def check_multi_implementer():
    """DD513/R7-R10：手列三值决策表，穿过真实 Registry 收集和公开 resolver。"""
    from itertools import product, permutations
    config = m.migrate_document(m.valid_fixture())[0]
    reviewer = {'agent': 'pi', 'model': 'reviewer', 'effort': 'high'}
    config['review']['whole-change']['standards'] = {**reviewer, 'candidates': [reviewer]}
    config['model_families'] = {'pi': {
        name: {'family': family, 'source': 'user_declared'}
        for name, family in [('reviewer', 'red'), ('red-impl', 'red'), ('blue-impl', 'blue')]}}
    probe = {'request_id': 'multi', 'observed_at': 'fixture', 'sources': {'pi': {'status': 'ok'}},
             'capabilities': {'pi': {'binary': True, 'models': {'reviewer': ['high']}}}}
    caps = {'standards': [{'identity': reviewer, 'status': 'runnable', 'reason': None,
                           'evidence_id': f'fixture-{i}'} for i in range(2)]}
    # 相对 red 审查者：S=red, D=blue, U=未声明。预期直接来自 R8，非调用被测比较器。
    table = {'': 'unknown', 'S': 'same', 'D': 'different', 'U': 'unknown',
             'SS': 'same', 'SD': 'same', 'SU': 'same', 'DD': 'different',
             'DU': 'unknown', 'UU': 'unknown', 'SSS': 'same', 'SSD': 'same',
             'SSU': 'same', 'SDD': 'same', 'SDU': 'same', 'SUU': 'same',
             'DDD': 'different', 'DDU': 'unknown', 'DUU': 'unknown', 'UUU': 'unknown'}
    count = 0
    for key, expected in table.items():
        for sequence in sorted(set(permutations(key))):
            for sources in product(('requested', 'executed'), repeat=len(sequence)):
                rows = {'map': {'lane_id': 'map', 'role': 'map', 'base_commit': 'base'}}
                expected_evidence = []
                for i, (symbol, source) in enumerate(zip(sequence, sources)):
                    identity = {**reviewer, 'model': {'S': 'red-impl', 'D': 'blue-impl', 'U': 'unknown-impl'}[symbol]}
                    # executed 未声明时 requested 仍有 red 声明，必须禁止回退。
                    requested = identity if source == 'requested' else {**reviewer, 'model': 'red-impl'}
                    executed = identity if source == 'executed' else None
                    lane = f'impl-{i}'
                    rows[lane] = {'lane_id': lane, 'map': 'map', 'role': 'backend',
                        'output_mode': 'commit', 'integrated_commit': f'commit-{i}', **requested,
                        'implementation_execution': {'source': 'native_readback', 'identity': executed}}
                    declaration = None if symbol == 'U' else {
                        'family': {'S': 'red', 'D': 'blue'}[symbol], 'source': 'user_declared'}
                    expected_evidence.append({'lane_id': lane, 'requested': requested, 'executed': executed,
                        'identity': identity, 'basis': source, 'declaration': declaration,
                        'source': 'declared_at_review'})
                implementations = registry.collect_implementation_identities(rows, 'base')
                plan = m.resolve_review_plan(config, required_axes=['standards'], implementations=implementations,
                    evidence=probe, native_capabilities=caps, request_id='multi')
                assert plan['lane']['comparison'] == expected, (sequence, sources, plan)
                basis = 'unknown' if not sources else sources[0] if len(set(sources)) == 1 else 'mixed'
                assert plan['lane']['comparison_basis'] == basis
                assert plan.get('implementation_evidence') == expected_evidence, '缺逐实现者来源/声明审计证据'
                assert plan['implementations'] == implementations
                assert [a['comparison'] for a in plan['lane']['attempts']] == [expected, expected]
                assert plan['lane']['fallback'] == ('none' if expected == 'different' else 'no_different_family_candidate')
                assert plan['lane']['selected_index'] == 0
                count += 1
    # 候选自身缺声明时，即使实现集合完整也只能 Unknown。
    del config['model_families']['pi']['reviewer']
    plan = m.resolve_review_plan(config, required_axes=['standards'],
        implementations=[{'lane_id': 'known', 'requested': {**reviewer, 'model': 'blue-impl'}, 'executed': None}],
        evidence=probe, native_capabilities=caps, request_id='multi')
    assert plan['lane']['comparison'] == 'unknown'
    assert plan['lane']['fallback'] == 'no_different_family_candidate'
    for executed in (None, {}, {'model': 'unknown-impl'}):
        plan = m.resolve_review_plan(config, required_axes=['standards'],
            implementations=[{'lane_id': 'partial', 'requested': None, 'executed': executed}],
            evidence=probe, native_capabilities=caps, request_id='multi')
        item = plan['implementation_evidence'][0]
        assert item['identity'] == executed and item['declaration'] is None
        assert item['basis'] == ('requested' if executed is None else 'executed')
        assert plan['lane']['comparison'] == 'unknown'
    print(f'multi-implementer-fallback: pass ({count} Registry/resolver cases; native execution Unknown)')


def check_capability_safety():
    """独立预期：DD514 AC / DD508 R5/R6/R11；公开 resolver。"""
    import copy
    c = m.migrate_document(m.valid_fixture())[0]
    a = m.triple(c['review']['whole-change']['standards'])
    b = {**a, 'model': 'second'}
    c['review']['whole-change']['standards']['candidates'] = [b, b]
    c['review']['whole-change']['spec']['candidates'] = [{**b, 'model':'nonparticipating-axis'}]
    c['review']['implementation']['spec']['candidates'] = [{**b, 'model': 'nonparticipant'}]
    ev = {'request_id': 'safe', 'observed_at': 'fixture', 'sources': {'pi': {'status': 'ok'}},
          'capabilities': {'pi': {'binary': True, 'models': {a['model']: ['high'], 'second': ['high']}}}}
    pool = [a, b, b]
    native = {'standards': [{'identity': x, 'status': 'runnable', 'reason': None,
                            'evidence_id': f'boundary-{i}'} for i,x in enumerate(pool)]}
    def resolve(caps=native, probe=ev):
        return m.resolve_review_plan(c, required_axes=['standards'], implementations=[], evidence=probe,
                                     native_capabilities=caps, request_id='safe')
    def blocked(caps, code='review_capability_evidence_required', probe=ev):
        try: resolve(caps, probe)
        except ValueError as e:
            assert code in str(e), str(e)
            return str(e)
        raise AssertionError('缺证据/全不可运行必须阻断')
    for status in [None, 'unknown']:
        bad = copy.deepcopy(native); bad['standards'][1]['status'] = status
        blocked(bad)
    bad = copy.deepcopy(native); bad['standards'][1]['evidence_id'] = None; blocked(bad)
    bad = copy.deepcopy(native); bad['standards'].pop(); blocked(bad)
    bad = copy.deepcopy(native); bad['standards'][1]['identity'] = a; blocked(bad)
    for status in ['runnable', 'unavailable']:
        bad = copy.deepcopy(native); bad['standards'][1].update(status=status, reason='claimed', evidence_id=None)
        blocked(bad)
    bad = copy.deepcopy(native); bad['standards'][0].update(status='unavailable', reason='native rejection')
    plan = resolve(bad)
    assert plan['lane']['selected'] == b and plan['lane']['selected_index'] == 1
    assert [x['identity'] for x in plan['lane']['attempts']] == pool
    for item in bad['standards']: item.update(status='unavailable', reason='native rejection')
    message = blocked(bad, 'review_no_runnable_candidate')
    attempts = json.loads(message.split(': ', 1)[1])
    assert [x['identity'] for x in attempts] == pool and all(x['reason']=='native rejection' for x in attempts)
    # 有 native 自述也不能掩盖 probe 中缺完整 agent/model/effort 证据。
    missing = copy.deepcopy(ev); del missing['capabilities']['pi']['models']
    blocked(bad, probe=missing)
    for raw in [None, [], {}]:
        blocked(bad, probe={**ev, 'capabilities':raw})
    c['review']['whole-change']['standards']['candidates'] = []
    assert resolve({})['lane']['selected'] == a  # 非参与池、空池无新增门槛。
    print('capability-safety: pass (public resolver; native execution Unknown)')


def check_later_round():
    """独立预期：DD516 / gate-state-machine R2/R3、R16，不执行 native。"""
    from review_gate import prepare_round, run, read_ledger
    clean = dict(P0=0, P1=0, P2=0, P3=0)
    impl = dict(lane_id='impl', requested=dict(agent='pi', model='provider/model', effort='high'), executed=None)
    fixer = dict(lane_id='fixer', requested=impl['requested'], executed=dict(agent='codex', model='undeclared', effort='high'))
    config = m.valid_fixture()
    ev = {'pi': {'binary': True, 'models': {'provider/model': ['high']}}}
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp)/'budget.json'
        context = prepare_round([], round_no=1, base='base', head='h1', request_id='r1', implementations=[impl])
        assert context['required_axes'] == ['standards', 'spec']
        plan = m.resolve_review_plan(config, required_axes=context['required_axes'], implementations=context['implementations'], evidence=ev, native_capabilities={}, request_id='r1', round_context=context)
        packet = dict(review_plan=plan, owner_calls=registry.build_owner_calls(plan))
        passing = dict(verdict='PASS', counts=clean, findings=['original'])
        blocking = dict(verdict='BLOCK', counts={**clean, 'P1':1}, findings=['repair spec'])
        assert run(dict(round=1, axes=dict(standards=passing, spec=blocking), review_packet=packet), ledger) == 'FIX'
        rounds = read_ledger(ledger); before=ledger.read_bytes()
        reuse = prepare_round(rounds, round_no=2, base='base', head='h1', request_id='r2', implementations=[impl])
        assert reuse['action']=='reuse' and reuse['result']==rounds[0]
        assert ledger.read_bytes()==before
        try: run(dict(round=1, axes=dict(standards=passing,spec=blocking), review_packet=packet),ledger)
        except ValueError: pass
        else: raise AssertionError('same head reran gate')
        assert ledger.read_bytes()==before
        context = prepare_round(rounds, round_no=2, base='base', head='h2', request_id='r2', implementations=[impl,fixer])
        assert context['required_axes']==['spec'] and context['implementations']==[impl,fixer]
        plan2 = m.resolve_review_plan(config, required_axes=['spec'], implementations=context['implementations'], evidence=ev, native_capabilities={}, request_id='r2', round_context=context)
        assert [x['axis'] for x in registry.build_owner_calls(plan2)]==['spec']
        assert plan2['lane']['selected']==plan['lane']['selected']
        assert plan2['implementation_evidence'][1]['basis']=='executed'
        assert plan2['implementation_evidence'][1]['declaration'] is None
        for flag in ('interface_changed','dependencies_changed'):
            assert prepare_round(rounds, round_no=2, base='base', head='h2', request_id='r2', implementations=[impl,fixer], **{flag:True})['required_axes']==['standards','spec']
        def rejected(**changes):
            args=dict(round_no=2, base='base', head='h2', request_id='r2', implementations=[impl,fixer]); args.update(changes)
            try: prepare_round(rounds, **args)
            except ValueError: return
            raise AssertionError('invalid new round accepted: '+str(changes))
        rejected(implementations=[impl]); rejected(request_id='r1'); rejected(round_no=4)
        for outcome in ('PASS','REVIEW_BLOCKED','REVIEW_EXHAUSTED'):
            previous=rounds; rounds=[{**previous[0], 'outcome':outcome}]
            rejected()
            rounds=previous
        packet2=dict(review_plan=plan2, owner_calls=registry.build_owner_calls(plan2))
        assert run(dict(round=2,axes=dict(spec=blocking),review_packet=packet2),ledger)=='FIX'
        context3=prepare_round(read_ledger(ledger),round_no=3,base='base',head='h3',request_id='r3',implementations=[impl,fixer,{**impl,'lane_id':'fixer3'}])
        assert context3['required_axes']==['spec']
        plan3=m.resolve_review_plan(config,required_axes=['spec'],implementations=context3['implementations'],evidence=ev,native_capabilities={},request_id='r3',round_context=context3)
        assert run(dict(round=3,axes=dict(spec=blocking),review_packet=dict(review_plan=plan3,owner_calls=registry.build_owner_calls(plan3))),ledger)=='REVIEW_EXHAUSTED'
        assert len(read_ledger(ledger))==3
    print('later-round-plan: pass (R2/R3, fixer, reuse; native Unknown)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['orca-review-plan', 't3-review-plan', 'later-round-plan', 'single-model-plan', 'candidate-family-transaction', 'different-family-plan', 'capability-safety', 'multi-implementer-fallback'], required=True)
    args = parser.parse_args()
    if args.case == 'orca-review-plan':
        subprocess.run([sys.executable, str(HERE.parents[1]/'delivery-pipeline-orca/scripts/check_review_dispatch.py'), '--case', 'native-unknown'], check=True)
    elif args.case == 't3-review-plan':
        subprocess.run([sys.executable, str(ROOT / 'skills/delivery-pipeline-t3code/scripts/check_review_dispatch.py'), '--case', 'native-evidence'], check=True)
    elif args.case == 'later-round-plan':
        check_later_round()
    elif args.case == 'multi-implementer-fallback':
        check_multi_implementer()
    elif args.case == 'capability-safety':
        check_capability_safety()
    elif args.case == 'single-model-plan':
        for version in (6, 7):
            check_single_model(version)
    elif args.case == 'different-family-plan':
        check_different_family()
    else:
        check_candidate_family()
