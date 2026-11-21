#!/usr/bin/env python3
"""DD519：公开 whole-change seam；替身仅位于原生能力 I/O。"""
import argparse
import copy
import json
import io
import os
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'delivery-pipeline-setup/scripts'))
import model_config as m
sys.path.insert(0, str(HERE.parents[1] / 'delivery-pipeline/scripts'))
import lane_registry as registry
from review_gate import run, read_ledger
import review_dispatch as d


def check():
    config = m.valid_fixture()
    target = dict(agent='pi', model='provider/model', effort='high')
    other = dict(target, effort='low')
    config['review']['whole-change']['standards']['candidates'] = [other]
    config['review']['whole-change']['spec']['candidates'] = [other]
    evidence = dict(request_id='r1', observed_at='now', sources={'pi': {'status':'ok'}},
                    capabilities={'pi':dict(binary=True, models={'provider/model':['high','low']})})
    def native(pools, request_id):
        return dict(request_id=request_id, capabilities={axis:[dict(identity=t, status='runnable', evidence_id='native-test') for t in pool] for axis,pool in pools.items()})
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp)/'impl.md'
        registry.write(source, dict(lane_id='map',role='map',work_item='map',base_commit='base'))
        registry.write(source, dict(lane_id='impl',role='backend',work_item='impl',map='map',output_mode='commit',integrated_commit='head',**target))
        request = dict(config=config, evidence=evidence, implementation_registries=[str(source)],
                       fixed_point='base', base='base', head='h1', round=1, request_id='r1', required_axes=['standards','spec'])
        def missing(pools, request_id):
            result=native(pools, request_id)
            result['capabilities']['spec'][1]['status']='unknown'
            return result
        try: d.prepare(request, collect=missing)
        except ValueError as e: assert 'review_capability_evidence_required' in str(e)
        else: raise AssertionError('missing native evidence authorized review packet')
        packet=d.prepare(request, collect=native)
        assert packet['authority'] is False and packet['dispatch']=='preflight-ready'
        assert packet['review_plan']['required_axes']==['standards','spec']
        assert packet['review_plan']['lane']['selected']==target
        assert [x['axis'] for x in packet['owner_calls']]==['standards','spec']
        # 真实本壳 preflight caller 消费冻结计划，不重新读取主配置选序。
        from preflight import _model_command
        config_path=Path(tmp)/'config.json'; config_path.write_text(json.dumps(config))
        evidence_path=Path(tmp)/'evidence.json'; evidence_path.write_text(json.dumps(evidence))
        preflight_request=dict(config=str(config_path),model_evidence=str(evidence_path),task='review',output_mode='verdict',review_packet=packet)
        resolved,_,_=_model_command(preflight_request,'resolve')
        assert resolved['review_plan']==packet['review_plan']
        frozen,_,_=_model_command(preflight_request,'freeze')
        assert frozen['review_plan']==packet['review_plan'] and frozen['agent']==target['agent']
        def outside(pools, request_id):
            result=native(pools,request_id); result['capabilities']['standards'][0]['identity']={**target,'model':'outside'}
            return result
        try: d.prepare(request,collect=outside)
        except ValueError: pass
        else: raise AssertionError('outside-pool native target accepted')
        wrong=dict(request,required_axes=['spec'])
        try: d.prepare(wrong,collect=native)
        except ValueError: pass
        else: raise AssertionError('wrong required axes accepted')
        path=Path(tmp)/'review.md'
        # 独立预期：DD508 R14 / DD519 AC2 的 selected 身份；Base Schema 的无命名 mode；
        # Orca overlay 合同要求新 freeze 可直接写 task-create intent，不靠 caller 补 row。
        import preflight as pf
        from registry_overlay import apply_request, persist_overlay
        owner=Path(tmp)/'code-review'/'SKILL.md'
        owner.parent.mkdir(); owner.write_text('---\nname: code-review\n---\n')
        agent_source=Path(tmp)/'agent.json'; agent_source.write_text('{}')
        packet_path=Path(tmp)/'packet.md'; packet_path.write_text('# dispatch')
        host=dict(target=dict(kind='local'),runtimeId='test-runtime')
        def native_read(executable, *args, **kwargs):
            if args==('--version',): return 'test-version'
            if args[:2]==('skills','get'):
                return dict(name=args[2],full=True,markdown='# guide')
            if args==('agent-context',): return dict(commands=[])
            if args==('status',):
                return dict(ok=True,result=dict(target=host['target'],runtime=dict(
                    state='ready',reachable=True,connectionState='connected',
                    runtimeId=host['runtimeId'],capabilities=[])))
            if args==('skills','installed'):
                return dict(result=dict(skills=[dict(id='test-skill',name='delivery-pipeline-orca',
                    providers=['agent-skills'],sourceKind='test',sourceLabel='fixture')]))
            if args[:2]==('terminal','show'):
                return dict(ok=True,result=dict(terminal=dict(handle='test-terminal')))
            raise AssertionError('unexpected native I/O: '+str(args))
        freeze_request=dict(request,config=str(config_path),evidence=str(evidence_path),
            registry=str(path),lane='review',work_item='DD519',worktree=tmp,
            branch='fixture-review',map='map',packet=str(packet_path),preflight=dict(
                operation='task-create',skill_name='delivery-pipeline-orca',references=[],
                required_commands=[],required_capabilities=[],config=str(config_path),
                model_evidence=str(evidence_path),task='review',output_mode='verdict',
                target_host=host,owner=dict(name='code-review',skill_path=str(owner),
                invocation_label='/skill:code-review'),agent_readback=dict(
                status='ready',**target,source=str(agent_source))))
        request_path=Path(tmp)/'freeze.json'; request_path.write_text(json.dumps(freeze_request))
        with patch.object(d.prepare,'__kwdefaults__',dict(collect=native)), \
             patch.object(pf,'_run',side_effect=native_read), \
             patch.object(pf,'resolve_orca_executable',return_value='/fixture/orca'), \
             patch.dict(os.environ,ORCA_TERMINAL_HANDLE='test-terminal'), \
             patch.object(sys,'argv',['review_dispatch.py','freeze',str(request_path)]):
            output=io.StringIO()
            with redirect_stdout(output): status=d.main()
        assert status==0, output.getvalue()
        row=registry.read(path,'review')[0]
        intent=apply_request(dict(action='record_mutation',kind='lane',row=row,
                                 arguments=dict(operation='task-create')))
        assert {k:row.get(k) for k in target}==target, 'freeze lost/rewrote lane selected identity'
        assert 'mode' in row and row['mode'] is None, 'review inherited an unrelated named mode'
        assert all(k in row for k in ('updated_at','base_commit','worktree','branch','output_mode'))
        assert row['review_plan']==packet['review_plan']
        intent=persist_overlay(row,intent,readback=lambda:registry.read(path,'review')[0],
                               write=lambda value:registry.write(path,value))
        assert registry.read(path,'review')[0]['orca']['mutation']==dict(
            operation='task-create',request_id=None,receipt_reference=None)
        row=intent
        for state in ('created','cancelled'):
            registry.write(path,dict(row,state=state))
            before=path.read_bytes()
            recovered=d.recover(path,'review','r1')
            assert recovered['action']==('stop' if state=='cancelled' else 'inspect_original'), 'duplicate/cancelled request attempted native redispatch'
            assert recovered['review_packet']['review_plan']==packet['review_plan']
            assert path.read_bytes()==before
            try: registry.reserve_review(path,row)
            except ValueError: pass
            else: raise AssertionError('duplicate or cancelled request authorized new native dispatch')
        axes={a:dict(verdict='PASS',counts=dict(P0=0,P1=0,P2=0,P3=0),findings=['retain '+a]) for a in ('standards','spec')}
        ledger=Path(tmp)/'budget.json'
        assert d.finish(dict(round=1,axes=axes,review_packet=packet),ledger)=='PASS'
        entry=read_ledger(ledger)[0]
        assert all(x['status']=='unknown' and x['executed'] is None for x in entry['execution_evidence']), 'requested/preflight falsely promoted to executed matched'
        assert entry['axes']['standards'].get('findings')==['retain standards'] and entry['axes']['spec'].get('findings')==['retain spec'], 'findings lost'
        mismatch=Path(tmp)/'mismatch.json'
        data=dict(round=1,axes=axes,review_packet=packet,native_readbacks={'spec':dict(source='native_readback',identity=dict(model='outside'),applied_effort=None)})
        assert d.finish(data,mismatch)=='REVIEW_BLOCKED'
        assert read_ledger(mismatch)[0]['axes']==axes
        # 一轮制（ADR-0027）：FIX 需带反例，之后不再开 R2。
        fixing=Path(tmp)/'fix.json'
        axes['spec']=dict(verdict='BLOCK',counts=dict(P0=0,P1=1,P2=0,P3=0),findings=['fix'])
        assert d.finish(dict(round=1,axes=axes,review_packet=packet,repros=['node --test fix.test.js']),fixing)=='FIX'
        later=dict(request,round=2,request_id='r2',head='h2',required_axes=['spec'],rounds=read_ledger(fixing))
        later['evidence']={**evidence,'request_id':'r2'}
        try: d.prepare(later,collect=native)
        except ValueError: pass
        else: raise AssertionError('R2 must be rejected')
    print('native-unknown: pass (native I/O substituted; no dispatch/model execution)')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--case',choices=['native-unknown'],required=True); parser.parse_args()
    check()
