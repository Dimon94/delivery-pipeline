#!/usr/bin/env python3
"""DD517：真实文件/gate；替身只在 T3 工具 I/O。独立预期来自 DD508 R5–17。"""
import argparse
import copy
import sys
import tempfile
from pathlib import Path
from review_dispatch import ReviewDispatch, registry
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline-setup/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from check_config_transaction import m

class Native:
    def __init__(self):
        self.calls=[]
        self.caps=dict(parentThreadId='parent', inheritedProviderInstanceId='pi', providers=[dict(
            providerInstanceId='pi', canRunChildTask=True, canRunCrossProviderChildTask=True,
            models=[dict(id='provider/model', options=[dict(id='thinking', values=['high'])])])])
        self.reads={}
    def __call__(self, name, args):
        self.calls.append((name,copy.deepcopy(args)))
        if name=='orchestrator_capabilities': return copy.deepcopy(self.caps)
        if name=='delegate_task': return dict(taskId='task',childThreadId='lane-thread',next='end turn')
        if name=='t3_thread_read': return self.reads[args['threadId']]
        raise AssertionError(name)

def check():
    native=Native(); adapter=ReviewDispatch(native)
    context=dict(action='plan',round=1,base='base',head='head',request_id='r1',required_axes=['standards','spec'],implementations=[],interface_changed=False,dependencies_changed=False)
    config=m.valid_fixture()
    packet=adapter.prepare(config,context)
    assert packet.get('review_plan',{}).get('lane',{}).get('selected')==dict(agent='pi',model='provider/model',effort='high'), '正式入口必须消费冻结 ReviewPlan'
    assert [c['axis'] for c in packet['owner_calls']]==['standards','spec'], 'required axes drift'
    def rejects(fn, message):
        try: fn()
        except ValueError: return
        raise AssertionError(message)
    for mutation in ('provider','model','options','permission'):
        bad=Native()
        if mutation=='provider': bad.caps['providers']=[]
        if mutation=='model':
            bad.caps['providers'][0]['models']=[];bad.caps['providers'][0]['omittedModels']=3
        if mutation=='options': bad.caps['providers'][0]['models'][0]['options']=[]
        if mutation=='permission': del bad.caps['providers'][0]['canRunChildTask']
        rejects(lambda:ReviewDispatch(bad).prepare(config,context),'缺能力证据仍允许创建')
        assert not any(n=='delegate_task' for n,_ in bad.calls), '缺证据有副作用'
    # 用户池外目标被原生正面拒绝，不从目录挑另一个模型。
    outside=copy.deepcopy(config)
    outside['review']['whole-change']['standards']['model']='outside'
    rejects(lambda:adapter.prepare(outside,context),'池外模型替换了用户目标')
    configured=m.migrate_document(config)[0]
    configured['review']['whole-change']['standards']['candidates']=[dict(agent='pi',model='provider/model',effort='high')]
    configured['review']['whole-change']['standards']['effort']='low'
    selected=adapter.prepare(configured,context)
    assert selected['review_plan']['lane']['selected_index']==1, '正面 unavailable 未跳过'
    assert selected['review_plan']['lane']['attempts'][0]['status']=='unavailable'
    spec_context={**context,'round':2,'request_id':'r2','required_axes':['spec']}
    spec=adapter.prepare(config,spec_context)
    assert [c['axis'] for c in spec['owner_calls']]==['spec'], 'spec-only 执行了 standards'
    owner=dict(name='code-review',path='/resolved/code-review/SKILL.md',invocation_label='code-review')
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'registry.md'
        row=dict(lane_id='review',work_item='DD517')
        result=adapter.dispatch(path,row,packet,owner,'read-only whole-change')
        assert result['action']=='inspect_original'
        assert result['row']['review_plan']==packet['review_plan']
        assert result['row']['t3code']['receipt']['childThreadId']=='lane-thread'
        assert result['row']['t3code'].get('child_thread_id')=='lane-thread' and result['row']['t3code'].get('task_id')=='task', '原生命周期缺少 receipt 坐标投影'
        rejects(lambda:adapter.dispatch(path,row,packet,owner,'retry'),'重复 native 创建')
        adapter.recover(path,'review')
        saved=registry.read(path,'review')[0];saved['state']='cancelled';registry.write(path,saved)
        assert adapter.recover(path,'review')['action']=='stop', '取消后重发'
        rejects(lambda:adapter.dispatch(path,row,packet,owner,'retry cancelled'),'取消后再次创建')
        assert len([n for n,_ in native.calls if n=='delegate_task'])==1, '同轮重复 native'
        clean=dict(P0=0,P1=0,P2=0,P3=0)
        axes={a:dict(verdict='PASS',counts=clean,findings=['保留 '+a]) for a in ('standards','spec')}
        for axis in axes:
            native.reads[axis]=dict(thread=dict(threadId=axis,model='REQUESTED-NOT-EVIDENCE'),
                recentRuns=[dict(runId=axis,providerInstanceId='pi',model='REQUESTED-NOT-EVIDENCE',executedModel='provider/model')])
        coords={a:dict(thread_id=a,run_id=a) for a in axes}
        rejects(lambda:adapter.fan_in(packet,axes,{a:coords['standards'] for a in axes},Path(tmp)/'shared.json',1),'lane 身份冒充双轴')
        ledger=Path(tmp)/'unknown.json'
        assert adapter.fan_in(packet,axes,coords,ledger,1)=='PASS'
        import json
        recorded=json.loads(ledger.read_text())['rounds'][0]
        assert all(e['status']=='unknown' and e['executed']['effort'] is None for e in recorded['execution_evidence']), '假 matched/applied effort'
        native.reads['spec']['recentRuns'][0]['executedModel']='WRONG'
        ledger=Path(tmp)/'mismatch.json'
        assert adapter.fan_in(packet,axes,coords,ledger,1)=='REVIEW_BLOCKED', 'known mismatch 未阻断'
        recorded=json.loads(ledger.read_text())['rounds'][0]
        assert recorded['axes']==axes, '丢 findings'
        assert recorded['execution_evidence'][1]['status']=='mismatch'
        rejects(lambda:adapter.fan_in(spec,axes,coords,Path(tmp)/'bad.json',2),'错误 required 轴放行')
    print('t3-review-plan: pass (native I/O fixture; actual execution Unknown)')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['native-evidence'],required=True);parser.parse_args()
    check()
