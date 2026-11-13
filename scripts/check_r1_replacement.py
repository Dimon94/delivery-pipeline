"""R1 公开行为回归；native I/O 仅用边界替身，不代表原生验收。"""
from pathlib import Path
from copy import deepcopy
import tempfile
import os
import importlib.util
from check_replacement import registry as r, observation, ROOT


def load(name, transport):
    spec=importlib.util.spec_from_file_location(name,ROOT/f'skills/delivery-pipeline-{transport}/scripts/replacement.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def source():
    a=dict(agent='pi',model='A',effort='high')
    b=dict(agent='pi',model='B',effort='low')
    return dict(lane_id='a',work_item='r1',runtime='herdr-pi-pane',state='blocked',output_mode='checks',mode=None,**a,
        recovery_plan=dict(plan_version=1,source='work',primary=a,fallbacks=[b]),
        recovery_progress=dict(current_index=None,next_cursor=0))


def packets():
    with tempfile.TemporaryDirectory() as td:
        for transport,asset in [('t3code','T3CODE'),('lody','LODY')]:
            packet=(ROOT/f'skills/delivery-pipeline-{transport}/assets/{asset}_ROLE_DISPATCH_PACKET.md').read_text()
            packet+='\nCRLF\r\n```\n四反引号````\v\f\x85\u2028\u2029末尾'
            path=Path(td)/(transport+'.md'); row=source();r.write(path,row)
            peer={**row,'lane_id':'peer','work_item':'peer'};r.write(path,peer)
            _,rev=r.read(path,'a');n=r.claim(path,'a',rev,'f','tool_or_model',observation)
            request=dict(task=packet,prompt=packet,history=[dict(text=packet)])
            r.bind_request(path,n['lane_id'],request,observation)
            assert r.read(path,n['lane_id'])[0]['replacement_intent']['native_request']==request
            r.launch(path,n['lane_id'],observation,lambda _:dict(status='unknown',receipt=dict(history=[packet])))
            before=path.read_bytes()
            assert r.claim(path,'a',rev,'f','tool_or_model',observation)['lane_id']==n['lane_id']
            assert path.read_bytes()==before
            out=r.recover_launch(path,n['lane_id'],lambda _:dict(status='completed',receipt=dict(history=[packet])))
            assert out['replacement_intent']['receipt']==dict(history=[packet])
            assert r.read(path,'peer')[0]['work_item']=='peer'
            r.write(path,r.read(path,'peer')[0])
            assert r.read(path,n['lane_id'])[0]==out
    print('R1 packet roundtrip: pass')


def mode():
    h=load('r1herdr','herdr');mc=h.mc
    a=dict(agent='pi',model='A',effort='high')
    doc=dict(version=6,work={k:{**a,'fallbacks':[]} for k in ('planning','design','frontend','backend','testing')},
        modes={'standard':dict(kind='direct',agents={'pi':{stage:dict(model='A',effort='high') for stage in ('starting','execution','direct')}})},
        review={s:{axis:{**a,'candidates':[]} for axis in ('standards','spec')} for s in ('implementation','whole-change')})
    ev={'pi':dict(binary=True,models={'A':['high']})}
    plan=mc.resolve_plan(doc,'frontend',ticket_mode='standard',evidence=ev,output_mode='commit')
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'registry.md';row={**source(),**mc.freeze_overlay(plan)};r.write(path,row)
        _,rev=r.read(path,'a');n=r.claim(path,'a',rev,'f','tool_or_model',observation)
        calls=[];os.environ['HERDR_ENV']='1'
        h.execute(path,n['lane_id'],observation,'pane',ev,
            lambda p,_:dict(pane_id=p,identity='match',shell='available',scope='isolated_lane'),
            lambda argv,_: calls.append(argv) or dict(status='failed',receipt={'native':'test rejection'}))
        assert calls==[['herdr','agent','start',n['lane_id'],'--kind','pi','--pane','pane','--','--approve','--model','A','--thinking','high']]
        out=r.read(path,n['lane_id'])[0]
        assert out['mode']=='standard' and out['recovery_plan']['source']=='explicit_mode' and out['recovery_plan']['fallbacks']==[]
        assert out['recovery_progress']==dict(current_index=None,next_cursor=0)
    print('R1 explicit mode startup seam: pass')


def selected():
    # 真 T3 caller 的能力目录与旧身份读回；无 delegate/native mutation。
    spec=importlib.util.spec_from_file_location('r1t3',ROOT/'skills/delivery-pipeline-t3code/scripts/native_replacement.py')
    t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
    a=dict(agent='codex',model='A',effort='high');b=dict(agent='codex',model='B',effort='low')
    row={**source(),**a,'runtime':'t3-task','mode':None,'t3code':dict(task_id='task',child_thread_id='thread'),
        'recovery_plan':dict(plan_version=1,source='work',primary=a,fallbacks=[b])}
    calls=[]
    def io(name,args):
        calls.append(name)
        if name=='task_status':return dict(taskId='task',childThreadId='thread',status='completed',hasPendingChildRuns=False,providerInstanceId='codex',model='A')
        if name=='t3_thread_read':return dict(thread=dict(threadId='thread',parentThreadId='parent',relationshipToParent='subagent',providerInstanceId='codex',model='A',activeRunId=None,status='completed'))
        raise AssertionError('native mutation')
    def caps(models):return dict(parentThreadId='parent',inheritedProviderInstanceId='codex',providers=[dict(providerInstanceId='codex',canRunChildTask=True,models=models)])
    with tempfile.TemporaryDirectory() as td:
        for i,models in enumerate([[],[dict(id='B',options=[dict(id='reasoningEffort',values=['high'])])], [dict(id='B',options=[dict(id='reasoningEffort',values=['low'])])]]):
            p=Path(td)/f'{i}.md';r.write(p,row);_,rev=r.read(p,'a');before=p.read_bytes()
            adapter=t.NativeReplacement(io,caps(models))
            try:n=r.claim(p,'a',rev,'f','tool_or_model',adapter.observe)
            except ValueError:
                assert i<2 and p.read_bytes()==before
            else:
                assert i==2, 'unsupported selected B was accepted and consumed budget'
                assert n['model']=='B' and n['recovery_progress']==dict(current_index=0,next_cursor=1)
                accepted=p.read_bytes()
                # 已接受 intent 重放不撤销，也不因能力消失重选。
                assert r.claim(p,'a',rev,'f','tool_or_model',t.NativeReplacement(io,caps([])).observe)==n
                assert p.read_bytes()==accepted
    print('R1 selected target gate: pass')

if __name__=='__main__':
    import sys
    for name in sys.argv[1:] or ['packets','mode','selected']:
        globals()[name]()
