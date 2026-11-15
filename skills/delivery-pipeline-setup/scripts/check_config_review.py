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
            assert 'candidate selection not available' in str(error)
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

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['single-model-plan', 'candidate-family-transaction'], required=True)
    args = parser.parse_args()
    if args.case == 'single-model-plan':
        for version in (6, 7):
            check_single_model(version)
    else:
        check_candidate_family()
