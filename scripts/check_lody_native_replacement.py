"""DD417：公开 0.112 MCP 形状穿过真实 Registry；边界替身不代表产品验收。"""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lodyreplacement', ROOT/'skills/delivery-pipeline-lody/scripts/native_replacement.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
r = a.registry


def main():
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(['git', 'init', '-q', td], check=True)
        binding = dict(sessionId='requester', workspaceId='workspace', machineId='machine', projectId='project', sourceRepo=td)
        primary = dict(agent='codex', model='A', effort='low')
        fallback = dict(agent='codex', model='B', effort='high')
        source = dict(lane_id='source', work_item='DD417-check', runtime='lody-session', state='blocked',
                      output_mode='checks', **primary, lody=dict(coordinator_session_id='requester',operation_id='original',session_id='old'),
                      recovery_plan=dict(plan_version=1, source='work', primary=primary, fallbacks=[fallback,primary,fallback]),
                      recovery_progress=dict(current_index=None,next_cursor=0))
        calls = []
        current = dict(sessionId='requester',workspaceId='workspace',machineId='machine')
        options = dict(current=current, machines=[dict(id='machine',online=True,canUse=True)],
                       localProjects=[dict(id='project',machineId='machine',rootPath=td,isGit=True)],
                       agentConfigs=[dict(id='config',machineId='machine',agentType='codex',runConfig=dict(models=[dict(id='A',reasoningEffortValues=['low']),dict(id='B',reasoningEffortValues=['high'])],reasoningEffortValues=['low','high']))])
        path = Path(td)/'registry.md'
        lane = [None]
        lost = [False]
        def io(name,args):
            calls.append((name,deepcopy(args)))
            if name == 'lody_session_create_options': return deepcopy(options)
            if name == 'lody_session_status_many':
                return dict(items=[dict(sessionId='old',ok=True,value=dict(summary=dict(id='old',machineId='machine'),
                    execution=dict(executionState='idle',phase='idle',queuedTurnCount=0),
                    machine=dict(state='online'), observation=dict(quality='fresh')))])
            if name == 'lody_session_create':
                row,_=r.read(path,lane[0])
                assert row['replacement_intent']['status']=='launching', 'native I/O preceded durable launching'
                if lost[0]: raise OSError('response lost')
                return dict(id='adopted',kind='session_create',state='active',items=[])
            if args['operationId']=='original':
                return dict(id='original',kind='session_create',state='finished',completion=dict(type='result',value=dict(items=[dict(status='succeeded',target=dict(sessionId='old',userTurnId='turn'))])))
            if lost[0]: raise ValueError('OPERATION_NOT_FOUND')
            return dict(id=args['operationId'],kind='session_create',state='active',items=[])
        adapter=a.NativeReplacement(io,binding)
        def claim():
            r.write(path,source)
            _,rev=r.read(path,'source')
            result=r.claim(path,'source',rev,'failure','tool_or_model',adapter.observe)
            lane[0]=result['lane_id']
            return result
        claim()
        row=adapter.execute(path,lane[0],'readonly nonce')
        requested=[args for name,args in calls if name=='lody_session_create']
        assert requested==[dict(operationId=lane[0],prompt='readonly nonce',machineId='machine',agentConfigId='config',modelId='B',reasoningEffort='high',useCurrentSessionAsParent=False,workContext=dict(kind='local',projectId='project',worktree=True))]
        assert row['replacement_intent']['receipt']['native']['id']=='adopted'
        calls.clear()
        adapter.execute(path,lane[0],'different input')
        assert ('lody_operation_get',dict(operationId='adopted')) in calls
        assert not any(name=='lody_session_create' for name,_ in calls)
        row,_=r.read(path,lane[0]);assert row['replacement_intent']['receipt']['executedModel']=='Unknown'
        assert row['recovery_progress']==dict(current_index=0,next_cursor=1)
        # 丢响应/NOT_FOUND 也只查原 operation，不重发、不重新选序。
        path=Path(td)/'lost.md';claim();lost[0]=True
        adapter.execute(path,lane[0],'nonce');calls.clear()
        row=adapter.execute(path,lane[0],'never retry')
        assert row['replacement_intent']['status']=='launching'
        assert [args for name,args in calls if name=='lody_operation_get']==[dict(operationId=lane[0])]
        assert not any(name=='lody_session_create' for name,_ in calls)
        # 身份或模型能力未知，既有 intent 原字节不变。
        lost[0]=False;path=Path(td)/'blocked.md';claim();before=path.read_bytes()
        for kind in ['requester','model','effort','writer']:
            def bad(name,args):
                value=io(name,args)
                if name=='lody_session_create_options':
                    if kind=='requester':value['current']['sessionId']='other'
                    if kind=='model':value['agentConfigs'][0]['runConfig']['models']=[]
                    if kind=='effort':
                        value['agentConfigs'][0]['runConfig']['models'][1].pop('reasoningEffortValues')
                        value['agentConfigs'][0]['runConfig']['measuredForModelId']='A'
                if name=='lody_session_status_many' and kind=='writer':value['items'][0]['value']['execution']['queuedTurnCount']=1
                return value
            calls.clear()
            try:a.NativeReplacement(bad,binding).execute(path,lane[0],'unsafe')
            except ValueError:pass
            else:raise AssertionError('unsafe native call allowed')
            assert path.read_bytes()==before and not any(name=='lody_session_create' for name,_ in calls)
    print('Lody native Adapter boundary checks: pass (native execution Unknown)')


if __name__=='__main__':main()
