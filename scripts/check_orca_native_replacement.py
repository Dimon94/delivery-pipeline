"""DD418 T18/R8/R9：真实 Registry 与 Orca I/O 边界；非原生模型执行。"""
import copy
import os
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('orca_native', ROOT/'skills/delivery-pipeline-orca/scripts/native_replacement.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
r = a.registry


def main():
    with tempfile.TemporaryDirectory() as td:
        target = dict(agent='codex', model='B', effort='high')
        request = dict(run_id='run', task_id='task', retry_of='old', execution_host='local', worktree_id='wt', failure_count=1)
        native = dict(state='ready', runId='run', taskId='task', dispatchId='new',
                      mutation=dict(requestId='uuid'), launch=dict(requested=target, effective=target))
        show = dict(dispatch=dict(id='new', runId='run', taskId='task', retryOfDispatchId='old',
                    hostScope=dict(hostId='local'), failureCount=1),
                    worker=dict(dispatchId='new', worktreeId='wt', state='ready', startOptions=dict(launch=dict(requested=target,effective=target))))
        calls=[]
        result=dict(requestId='uuid',state='completed',method='orchestration.workerStart',receipt=native)
        def io(*args):
            calls.append(args)
            value=result if args[1]=='request-show' else show
            return dict(ok=True,result=copy.deepcopy(value),_meta=dict(runtimeId='runtime'))
        adapter=a.NativeReplacement('/fixed/orca','runtime',read_cli=io)
        row=dict(lane_id='replacement',work_item='DD418',runtime='orca',state='created',**target,
                 replacement_of='source',replacement_intent=dict(status='launching',request_id='replacement',
                 native_request=request,receipt=dict(request_id='replacement',native_request_id='uuid',native_request=request)))
        # 独立预期：原生新 Dispatch 保持旧 Task/retry-of；无 model 推理证据不得伪称 actual。
        outcome=adapter.reconcile(copy.deepcopy(row))
        assert outcome['status']=='completed' and outcome['receipt']['actual_model']=='Unknown'
        assert all(x[1] in {'request-show','worker-show'} for x in calls)
        for state in ('pending','absent'):
            result['state']=state;calls.clear()
            value=adapter.reconcile(copy.deepcopy(row))
            assert value['status']=='unknown' and len(calls)==1
        result['state']='completed'
        # 合法 JSON 的错 lineage/选择/计数/请求同样必须拒绝。
        for section,key,value in [('dispatch','retryOfDispatchId','other'),('dispatch','taskId','other'),
                                  ('dispatch','failureCount',0),('worker','worktreeId','other')]:
            original=show[section][key];show[section][key]=value
            try:adapter.reconcile(copy.deepcopy(row))
            except ValueError:pass
            else:raise AssertionError((section,key))
            show[section][key]=original
        original=show['worker']['startOptions']['launch']['effective']
        show['worker']['startOptions']['launch']['effective']={**target,'effort':'low'}
        try:adapter.reconcile(copy.deepcopy(row))
        except ValueError:pass
        else:raise AssertionError('wrong selected accepted')
        show['worker']['startOptions']['launch']['effective']=original
        invalid=copy.deepcopy(row)
        invalid['replacement_intent']['native_request']['failure_count']=-1
        invalid['replacement_intent']['receipt']['native_request']=copy.deepcopy(invalid['replacement_intent']['native_request'])
        show['dispatch']['failureCount']=0
        try:adapter.reconcile(invalid)
        except ValueError:pass
        else:raise AssertionError('negative native failure count accepted')
        show['dispatch']['failureCount']=1
        # 原生未证明当前 caller 时，启动入口必须拒绝而不写 Registry。
        path_unbound=Path(td)/'unbound.md';r.persist(path_unbound,[row]);before_unbound=path_unbound.read_bytes()
        try:adapter.execute(path_unbound,'replacement')
        except ValueError:pass
        else:raise AssertionError('unbound caller allowed')
        assert path_unbound.read_bytes()==before_unbound
        # Registry 恢复只更新同一 intent，不创建 successor 或消费另一位置。
        path=Path(td)/'registry.md';r.persist(path,[row]);before=r.rows(path)
        recovered=adapter.recover(path,'replacement')
        assert recovered['replacement_intent']['status']=='completed' and set(r.rows(path))==set(before)
        calls.clear();assert adapter.recover(path,'replacement')==recovered and not calls
        missing=copy.deepcopy(row);missing['replacement_intent']['receipt'].pop('native_request_id');calls.clear()
        assert adapter.reconcile(missing)['status']=='unknown' and not calls
        bad=a.NativeReplacement('/fixed/orca','other-runtime',read_cli=io)
        try:bad.reconcile(row)
        except ValueError:pass
        else:raise AssertionError('wrong runtime accepted')
    # 生产入口穿过共享 claim/bind/launch；仅原生外部 I/O 使用替身。
    with tempfile.TemporaryDirectory() as td:
        old=dict(agent='codex',model='M',effort='high');selected=dict(old,effort='low')
        source=dict(lane_id='source',work_item='DD418-launch',runtime='orca',state='blocked',
            worktree='/execution',branch='worker',**old,
            orca=dict(run_id='run',task_id='task',dispatch_id='old',terminal_handle='term-old',
                execution_host='local',worktree_selector='id:wt',attempt_index=0,mutation=None),
            recovery_plan=dict(plan_version=1,source='work',primary=old,fallbacks=[selected,old,selected]),
            recovery_progress=dict(current_index=None,next_cursor=0))
        old_show=dict(dispatch=dict(id='old',runId='run',taskId='task',assigneeHandle='term-old',
            hostScope=dict(hostId='local'),failureCount=1,retryOfDispatchId=None),
            worker=dict(dispatchId='old',agentTerminalHandle='term-old',worktreeId='wt',state='failed',
                startOptions=dict(agent='codex',launch=dict(requested=old,effective=old))),
            projection=dict(dispatchId='old',runId='run',taskId='task',host=dict(id='local'),liveness=dict(verdict='exited')),
            terminalResource=dict(terminalHandle='term-old',worktreeId='wt',ownerDispatchId='old'))
        new_show=copy.deepcopy(old_show)
        new_show['dispatch'].update(id='new',assigneeHandle='term-new',retryOfDispatchId='old')
        new_show['worker'].update(dispatchId='new',agentTerminalHandle='term-new',state='ready',
            startOptions=dict(agent='codex',launch=dict(requested=selected,effective=selected)))
        native=dict(state='ready',runId='run',taskId='task',dispatchId='new',mutation=dict(requestId='uuid'),
            launch=dict(requested=selected,effective=selected))
        launches=[];rejected=[False];proof_host=['local'];rogue=[False]
        def external(*args):
            verb=args[:2]
            if verb==('orchestration','run-show'):v=dict(run=dict(id='run',coordinator_handle='coordinator'))
            elif verb==('terminal','show'):v=dict(terminal=dict(handle='coordinator',executionHostId='local',connected=True))
            elif verb==('worktree','show'):v=dict(worktree=dict(id='wt',path='/execution',branch='worker'))
            elif verb==('orchestration','worker-list'):
                v=dict(page=dict(hasMore=False),workers=[dict(dispatchId='old',taskId='task',runId='run',
                    workerState='failed',agentTerminalHandle='term-old',resource=dict(worktreeId='wt',ownerDispatchId='old'),
                    projection=dict(liveness=dict(verdict='exited')))])
                if rogue[0]:
                    other=copy.deepcopy(v['workers'][0]);other['dispatchId']='later-exited';v['workers'].append(other)
            elif verb==('orchestration','worker-show'):
                if args[-1]=='proof':v=dict(dispatch=dict(id='proof',hostScope=dict(hostId=proof_host[0])),worker=dict(dispatchId='proof',stage='settled',startOptions=dict(launch=dict(requested=selected,effective=selected))))
                else:v=old_show if args[-1]=='old' else new_show
            elif verb==('orchestration','worker-start'):
                launches.append(args)
                if rejected[0]:
                    error=ValueError('native rejection')
                    error.envelope=dict(ok=False,error=dict(code='invalid_argument',data=dict(orchestrationRequestId='rejected-uuid')))
                    raise error
                v=native
            elif verb==('orchestration','request-show'):v=dict(requestId='uuid',state='completed',method='orchestration.workerStart',receipt=native)
            else:raise AssertionError(args)
            return dict(ok=True,result=copy.deepcopy(v),_meta=dict(runtimeId='runtime'))
        adapter=a.NativeReplacement('/fixed/orca','runtime',selected_dispatch='proof',read_cli=external)
        previous=os.environ.get('ORCA_TERMINAL_HANDLE')
        try:
            os.environ['ORCA_TERMINAL_HANDLE']='coordinator'  # 仅替身测试；生产不得注入。
            path=Path(td)/'launch.md';r.write(path,source);_,rev=r.read(path,'source')
            next_row=adapter.claim(path,'source',rev,'failure','tool_or_model')
            result=adapter.execute(path,next_row['lane_id'])
            assert result['replacement_intent']['status']=='completed'
            assert result['orca']['attempt_index']==1 and result['orca']['task_id']=='task'
            assert result['recovery_progress']==dict(current_index=0,next_cursor=1)
            assert len(launches)==1 and '--spec' not in launches[0] and launches[0][launches[0].index('--retry-of')+1]=='old'
            assert launches[0][launches[0].index('--effort')+1]=='low'
            adapter.execute(path,next_row['lane_id']);assert len(launches)==1
            # 原 writer 与原生熔断在 claim 前拒绝，原字节和位置不动。
            for field,value in [('writer','live'),('breaker',3),('count',None),('identity','other')]:
                blocked=Path(td)/(field+'.md');r.write(blocked,source);_,revision=r.read(blocked,'source');before=blocked.read_bytes()
                saved=copy.deepcopy(old_show)
                if field=='writer':old_show['projection']['liveness']['verdict']=value
                elif field=='identity':old_show['dispatch']['taskId']=value
                else:old_show['dispatch']['failureCount']=value
                try:adapter.claim(blocked,'source',revision,'failure','tool_or_model')
                except ValueError:pass
                else:raise AssertionError('unsafe claim '+field)
                assert blocked.read_bytes()==before and len(launches)==1
                old_show.clear();old_show.update(saved)
            rogue_path=Path(td)/'rogue.md';r.write(rogue_path,source);_,revision=r.read(rogue_path,'source');before=rogue_path.read_bytes()
            rogue[0]=True
            try:adapter.claim(rogue_path,'source',revision,'rogue','tool_or_model')
            except ValueError:pass
            else:raise AssertionError('stale Task attempt branched around history')
            assert rogue_path.read_bytes()==before
            rogue[0]=False
            remote_path=Path(td)/'remote.md';r.write(remote_path,source);_,revision=r.read(remote_path,'source');before=remote_path.read_bytes()
            proof_host[0]='other-host'
            try:adapter.claim(remote_path,'source',revision,'remote','tool_or_model')
            except ValueError:pass
            else:raise AssertionError('remote capability adopted for local attempt')
            assert remote_path.read_bytes()==before
            proof_host[0]='local'
            rejected[0]=True
            rejected_path=Path(td)/'rejected.md';r.write(rejected_path,source);_,revision=r.read(rejected_path,'source')
            claimed=adapter.claim(rejected_path,'source',revision,'rejected','tool_or_model')
            held=adapter.execute(rejected_path,claimed['lane_id'])
            assert held['replacement_intent']['status']=='launching'
            assert held['replacement_intent']['receipt'].get('native_request_id')=='rejected-uuid', 'lost native rejection UUID'

        finally:
            if previous is None:os.environ.pop('ORCA_TERMINAL_HANDLE',None)
            else:os.environ['ORCA_TERMINAL_HANDLE']=previous
    print('Orca original request Registry reconciliation checks: pass (native I/O substituted)')


if __name__=='__main__':main()
