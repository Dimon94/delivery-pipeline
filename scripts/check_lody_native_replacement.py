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
        subprocess.run(['git', 'init', '-q', '-b', 'main', td], check=True)
        def git(*args):
            return subprocess.check_output(['git','-C',td,*args],text=True).strip()
        git('-c','user.name=check','-c','user.email=check@example.invalid','commit','--allow-empty','-qm','main')
        original = git('rev-parse','HEAD')
        source_tree=Path(td)/'source-tree'
        git('worktree','add','-qb','frozen-source',str(source_tree))
        subprocess.run(['git','-C',str(source_tree),'-c','user.name=check','-c','user.email=check@example.invalid','commit','--allow-empty','-qm','source differs from main'],check=True)
        frozen=subprocess.check_output(['git','-C',str(source_tree),'rev-parse','HEAD'],text=True).strip()
        assert frozen != original
        binding = dict(sessionId='requester', workspaceId='workspace', machineId='machine', projectId='project', sourceRepo=td)
        primary = dict(agent='codex', model='A', effort='low')
        fallback = dict(agent='codex', model='B', effort='high')
        source = dict(lane_id='source', work_item='DD417-check', runtime='lody-session', state='blocked',
                      output_mode='checks', worktree=str(source_tree), base_commit=frozen, branch='display-only-wrong', **primary, lody=dict(coordinator_session_id='requester',operation_id='original',session_id='old'),
                      recovery_plan=dict(plan_version=1, source='work', primary=primary, fallbacks=[fallback,primary,fallback]),
                      recovery_progress=dict(current_index=None,next_cursor=0))
        calls = []
        current = dict(sessionId='requester',workspaceId='workspace',machineId='machine',workContext=dict(kind='local',projectId='project',rootPath=td))
        options = dict(current=current, machines=[dict(id='machine',online=True,canUse=True)],
                       localProjects=[dict(id='project',machineId='machine',rootPath=td,isGit=True)],
                       agentConfigs=[dict(id='config',machineId='machine',agentType='codex',availability=dict(state='available'),runConfig=dict(models=[dict(id='A',reasoningEffortValues=['low']),dict(id='B',reasoningEffortValues=['high'])],reasoningEffortValues=['low','high']))])
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
        successor=claim()
        assert 'lody' not in successor and successor['worktree']==str(source_tree) and successor['base_commit']==frozen
        accepted=path.read_bytes()
        hostpath=Path(td)/'host-registry.md';hostpath.write_bytes(accepted)
        hostfixture=Path(td)/'host.json'
        import json
        hostfixture.write_text(json.dumps(dict(binding=binding,options=options,base=frozen,
            invocation=dict(action='execute',registry=str(hostpath),lane=lane[0],prompt='host nonce',binding=binding))))
        subprocess.run(['node',str(ROOT/'skills/delivery-pipeline-lody/scripts/native_host_check.js'),
                        str(ROOT/'skills/delivery-pipeline-lody/scripts/native_host.js'),str(hostfixture)],check=True)
        # 公开合同的 branch 是 base；实际 Git create 后必须是 source commit，不能是 main。
        args=adapter.target(successor)
        assert args['workContext']['branch']=='frozen-source', args
        child=Path(td)/'child'
        git('worktree','add','-qb','native-child',str(child),args['workContext']['branch'])
        assert subprocess.check_output(['git','-C',str(child),'rev-parse','HEAD'],text=True).strip()==frozen
        accepted=path.read_bytes()
        for fault in ['missing','unknown','moved','foreign','detached']:
            checkpath=Path(td)/(fault+'-base.md');checkpath.write_bytes(accepted)
            badrow,_=r.read(checkpath,lane[0])
            if fault=='missing':badrow.pop('base_commit')
            if fault=='unknown':badrow['base_commit']='f'*40
            if fault=='moved':badrow['base_commit']=original
            if fault=='foreign':
                other=Path(td)/'other';subprocess.run(['git','init','-q',str(other)],check=True)
                badrow['worktree']=str(other)
            if fault=='detached':
                git('worktree','add','--detach',str(Path(td)/'detached'),frozen)
                badrow['worktree']=str(Path(td)/'detached')
            r.write(checkpath,badrow);before=checkpath.read_bytes();calls.clear()
            try:adapter.execute(checkpath,lane[0],'unsafe base')
            except ValueError as error:assert 'Unknown: frozen base' in str(error), error
            else:raise AssertionError(f'unsafe {fault} base allowed')
            assert checkpath.read_bytes()==before and not any(n=='lody_session_create' for n,_ in calls)
        calls.clear()
        row=adapter.execute(path,lane[0],'readonly nonce')
        requested=[args for name,args in calls if name=='lody_session_create']
        assert requested==[dict(operationId=lane[0],prompt='readonly nonce',machineId='machine',agentConfigId='config',modelId='B',reasoningEffort='high',useCurrentSessionAsParent=False,workContext=dict(kind='local',projectId='project',worktree=True,branch='frozen-source'))]
        assert row['replacement_intent']['receipt']['native']['id']=='adopted'
        calls.clear()
        adapter.execute(path,lane[0],'different input')
        assert ('lody_operation_get',dict(operationId='adopted')) in calls
        assert not any(name=='lody_session_create' for name,_ in calls)
        row,_=r.read(path,lane[0]);assert row['replacement_intent']['receipt']['executedModel']=='Unknown'
        assert row['recovery_progress']==dict(current_index=0,next_cursor=1)
        # 独立预期：DD417 startup 绑定原生 target/config/worktree；模型文字不作 actual。
        def startup(name,args):
            if name=='lody_operation_get' and args['operationId']=='adopted':
                return dict(id='adopted',kind='session_create',state='finished',completion=dict(type='result',value=dict(items=[dict(status='succeeded',target=dict(sessionId='child',userTurnId='input'),assistantTurnId='answer')])))
            if name=='lody_session_status_many' and args['sessionIds']==['child']:
                return dict(items=[dict(sessionId='child',ok=True,value=dict(summary=dict(id='child',machineId='machine',agentConfigId='config',openedBySessionId='requester',branch='native-child',executionContext=dict(kind='local',projectId='project',worktree=True)),execution=dict(executionState='idle',phase='idle',queuedTurnCount=0),machine=dict(state='online'),observation=dict(quality='fresh')))])
            if name=='lody_session_history':
                return dict(sessionId='child',items=[dict(id='answer',role='assistant',text='nonce')])
            return io(name,args)
        launching=path.read_bytes()
        row=a.NativeReplacement(startup,binding).execute(path,lane[0],'ignored')
        assert row['state']=='running', row['replacement_intent']['receipt']
        assert row['lody']['session_id']=='child' and row['lody']['operation_id']=='adopted'
        assert Path(row['worktree']).resolve()==child.resolve()
        assert row['replacement_intent']['receipt']['executedModel']=='Unknown'
        assert row['replacement_intent']['receipt']['history']['items'][0]['text']=='nonce'
        calls.clear()
        assert a.NativeReplacement(startup,binding).execute(path,lane[0],'replay')==row
        assert not calls, 'completed replay performed native I/O'
        busy_path=Path(td)/'busy.md';busy_path.write_bytes(launching)
        def busy(name,args):
            value=startup(name,args)
            if name=='lody_session_status_many' and args['sessionIds']==['child']:
                value['items'][0]['value']['execution']=dict(executionState='busy',phase='running',activeTurnId='input',queuedTurnCount=0)
            if name=='lody_session_history':raise AssertionError('busy turn read history')
            return value
        assert a.NativeReplacement(busy,binding).execute(busy_path,lane[0],'ignored')['state']=='running'
        for fault in ['config','stale','branch','history','timeout']:
            checkpath=Path(td)/(fault+'.md');checkpath.write_bytes(launching)
            def mismatch(name,args):
                value=startup(name,args)
                if name=='lody_session_status_many' and args['sessionIds']==['child']:
                    if fault=='config':value['items'][0]['value']['summary']['agentConfigId']='wrong'
                    if fault=='stale':value['items'][0]['value']['observation']['quality']='stale'
                    if fault=='branch':value['items'][0]['value']['summary']['branch']='missing'
                if name=='lody_session_history' and fault=='history':value['items'][0]['id']='different-turn'
                if name=='lody_operation_get' and args['operationId']=='adopted' and fault=='timeout':
                    value['completion']['value']['items'][0]=dict(status='failed',error=dict(code='TARGET_TIMEOUT'))
                return value
            calls.clear()
            badrow=a.NativeReplacement(mismatch,binding).execute(checkpath,lane[0],'never resend')
            assert badrow['replacement_intent']['status']=='launching' and badrow['state']=='created', fault
            assert badrow['recovery_progress']==dict(current_index=0,next_cursor=1)
            assert not any(name=='lody_session_create' for name,_ in calls)
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
    subprocess.run(['node', str(ROOT/'skills/delivery-pipeline-lody/scripts/native_host_check.js')],check=True)
    print('Lody native Adapter boundary checks: pass (native execution Unknown)')


if __name__=='__main__':main()
