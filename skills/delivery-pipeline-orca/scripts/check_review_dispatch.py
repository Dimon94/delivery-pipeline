#!/usr/bin/env python3
"""DD519：公开 whole-change seam；替身仅位于原生能力 I/O。"""
import argparse
import copy
import json
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
        row=dict(lane_id='review',role='review',work_item='DD519',runtime='orca',state='created',review_plan=packet['review_plan'],orca={'mutation':None})
        registry.reserve_review(path,row)
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
        # R2 spec-only：lane 仍由 standards 选定，owner 仅收到 spec。
        fixing=Path(tmp)/'fix.json'
        axes['spec']=dict(verdict='BLOCK',counts=dict(P0=0,P1=1,P2=0,P3=0),findings=['fix'])
        assert d.finish(dict(round=1,axes=axes,review_packet=packet),fixing)=='FIX'
        registry.write(source,dict(lane_id='fixer',role='backend',work_item='fixer',map='map',output_mode='commit',integrated_commit='h2',**target))
        later=dict(request,round=2,request_id='r2',head='h2',required_axes=['spec'],rounds=read_ledger(fixing))
        later['evidence']={**evidence,'request_id':'r2'}
        spec=d.prepare(later,collect=native)
        assert [x['axis'] for x in spec['owner_calls']]==['spec']
        assert spec['review_plan']['lane']['selected']==target
    print('native-unknown: pass (native I/O substituted; no dispatch/model execution)')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--case',choices=['native-unknown'],required=True); parser.parse_args()
    check()
