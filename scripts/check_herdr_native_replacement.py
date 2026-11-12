"""外部 CLI 边界合同；不是原生验收。独立预期来自 DD414 response-lost 规则。"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hr', ROOT/'skills/delivery-pipeline-herdr/scripts/replacement.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def check():
    # 当前实现把 CLI JSON {result: ...} 的成功误当 Unknown。
    result = m.start_result(0, '{"result":{"type":"agent_started","agent":{"name":"r-test","pane_id":"w1:p2"}}}', '')
    assert result['status']=='unknown', '启动返回不能替代独立身份读回'
    for code, out, err in [(1,'','agent_not_ready'), (2,'','syntax'), (0,'{}','')]:
        assert m.start_result(code,out,err)['status']=='unknown'
    scope=dict(workspace_id='w1',tab_id='w1:t1',pane_id='w1:p2',terminal_id='term-test',cwd='/test')
    evidence={'pi':{'binary':True,'models':{'A':['high']}}}
    import subprocess
    retired=subprocess.Popen([sys.executable,'-c','pass'])
    retired.wait()
    commands=[]
    busy=False
    agents=[]
    def cli(*args):
        commands.append(args)
        if args[:2]==('pane','get'):
            return {'result':{'pane':scope}}
        if args[:2]==('pane','process-info'):
            return {'result':{'process_info':dict(pane_id='w1:p2',shell_pid=1,foreground_processes=[dict(pid=2 if busy else 1,name='zsh')])}}
        if args==('--version',):
            return 'herdr 0.9.5'
        if args==('agent','list'):
            return {'result':{'agents':agents}}
        raise AssertionError(args)
    native=m.NativeReplacement(scope,evidence,read_cli=cli)
    row=dict(lane_id='initial',agent='pi',model='A',effort='high',herdr={**scope,'agent_name':'initial','writer_pids':[retired.pid]})
    assert native.observe(row)['writer']=='exited'
    busy=True
    try: native.observe(row)
    except ValueError: pass
    else: raise AssertionError('foreground child treated as exited writer')
    busy=False
    request=dict(argv=['herdr','agent','start'],pane_id='w1:p2',agent_name='r-test',scope=scope)
    claimed={**row,'lane_id':'r-test','replacement_intent':dict(native_request=request)}
    import json
    from copy import deepcopy
    request['argv']=['herdr','agent','start','r-test','--kind','pi','--pane','w1:p2','--']
    raw=json.dumps(dict(id='cli:agent:start',error=dict(code='agent_start_failed',
                        message='agent process exited before becoming interactive')))
    def reply(out=raw, version='herdr 0.9.5', req=request, code=1):
        return m.start_result(code,'',out,version=version,request=req,request_id='r-test')
    positive=reply()
    assert positive['status']=='failed', '精确原请求退出回执必须支持正面失败'
    failed={**claimed,'replacement_intent':dict(status='failed',native_request=request,receipt=positive['receipt'])}
    failed['herdr']={**scope,'agent_name':'r-test'} # 从未成为 writer，没有 PID
    assert native.observe(failed)['writer']=='exited'
    busy=True
    try: native.observe(failed)
    except ValueError: pass
    else: raise AssertionError('failed receipt bypassed live writer')
    busy=False
    for bad in [reply(out=raw.replace('agent process exited before becoming interactive','agent start response did not include terminal_id')),
                reply(out=raw.replace('agent_start_failed','timeout')),reply(version='Unknown'),
                reply(version='herdr 0.9.6'),reply(code=0)]:
        assert bad['status']=='unknown'
    for key,value in [('agent_name','other'),('pane_id','w1:p3')]:
        bad=deepcopy(request);bad[key]=value
        assert reply(req=bad)['status']=='unknown'
    for key,value in [('agent_name','other'),('scope',{**scope,'terminal_id':'other'})]:
        bad=deepcopy(failed);bad['replacement_intent']['native_request'][key]=value
        try: native.observe(bad)
        except ValueError: pass
        else: raise AssertionError('receipt identity mismatch accepted')
    bad=deepcopy(failed)
    bad['replacement_intent']['receipt']['native_request']=deepcopy(request)
    bad['replacement_intent']['receipt']['native_request']['scope']['terminal_id']='another-terminal'
    try: native.observe(bad)
    except ValueError: pass
    else: raise AssertionError('receipt for another terminal accepted')
    completed=deepcopy(failed);completed['replacement_intent']['status']='completed'
    try: native.observe(completed)
    except ValueError: pass
    else: raise AssertionError('completed startup relabeled failed')

    assert native.reconcile(claimed)['status']=='unknown', 'absent agent is not negative request receipt'
    busy=True
    # 来自 Herdr 0.9.5 api schema 的 AgentInfo 字段，不能用自造 kind/status。
    agents.append(dict(name='r-test',pane_id='w1:p2',agent='pi',agent_status='idle',
                       interactive_ready=True,terminal_id=scope['terminal_id']))
    assert native.reconcile(claimed)['status']=='completed'
    agents[0]['terminal_id']='other'
    assert native.reconcile(claimed)['status']=='unknown'
    agents[0]['terminal_id']=scope['terminal_id']
    agents[0]['name']='other'
    assert native.reconcile(claimed)['status']=='unknown'
    # 真 Registry + 生产 execute；仅替换 CLI I/O，不另建预算或资格 owner。
    agents.clear();busy=False
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'registry.md'
        triple=dict(agent='pi',model='A',effort='high')
        primary={**row,'lane_id':'a','state':'blocked','runtime':'herdr-pi-pane','work_item':'startup-case',
                 'recovery_plan':dict(plan_version=1,source='work',primary=triple,fallbacks=[triple,triple]),
                 'recovery_progress':dict(current_index=None,next_cursor=0)}
        m.lane_registry.write(path,primary)
        _,rev=m.lane_registry.read(path,'a')
        b=m.lane_registry.claim(path,'a',rev,'a-tool-error','tool_or_model',native.observe)
        with patch.dict(os.environ,{'HERDR_ENV':'1'}), patch.object(m.subprocess,'run',
                return_value=subprocess.CompletedProcess([],1,'',raw)) as start:
            failed=native.execute(path,b['lane_id'])
            assert failed['replacement_intent']['status']=='failed'
            assert native.execute(path,b['lane_id'])==failed and start.call_count==1
        _,rev=m.lane_registry.read(path,b['lane_id'])
        c=m.lane_registry.claim(path,b['lane_id'],rev,'b-start-failed','startup_failed',native.observe)
        assert c['recovery_progress']==dict(current_index=1,next_cursor=2)
        assert m.lane_registry.claim(path,b['lane_id'],rev,'b-start-failed','startup_failed',native.observe)==c
        # 没有原始回执的 launching：缺席不倒推，原请求不重发。
        m.lane_registry.bind_request(path,c['lane_id'],dict(request,agent_name=c['lane_id']),native.observe)
        def lost(_): raise OSError('response lost before durable receipt')
        try: m.lane_registry.launch(path,c['lane_id'],native.observe,lost)
        except OSError: pass
        pending=m.lane_registry.recover_launch(path,c['lane_id'],native.reconcile)
        assert pending['replacement_intent']['status']=='launching'
        assert 'receipt' not in pending['replacement_intent']
        # Unknown 原始回执可以留证；仍不得被缺席变成 failed。
        unknown=m.start_result(1,'','timeout')
        pending=m.lane_registry.recover_launch(path,c['lane_id'],lambda _:unknown)
        assert pending['replacement_intent']['receipt']['start_reply']['stderr']=='timeout'
        assert m.lane_registry.recover_launch(path,c['lane_id'],native.reconcile)['replacement_intent']['status']=='launching'
    # 正面 startup_failed 不能消费已成功启动的 intent（独立预期：用户任务第2项）。
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'registry.md'
        triple=dict(agent='pi',model='A',effort='high')
        primary=dict(lane_id='a',work_item='w',role='frontend',runtime='herdr-pi-pane',state='blocked',mode=None,
                     **triple,recovery_plan=dict(plan_version=1,source='work',primary=triple,fallbacks=[triple,triple]),
                     recovery_progress=dict(current_index=None,next_cursor=0))
        obs=lambda _:dict(writer='exited',identity='match',capability='verified',gate='allowed')
        m.lane_registry.write(path,primary)
        _,rev=m.lane_registry.read(path,'a')
        b=m.lane_registry.claim(path,'a',rev,'f1','tool_or_model',obs)
        m.lane_registry.bind_request(path,b['lane_id'],{'test':'external boundary'},obs)
        m.lane_registry.launch(path,b['lane_id'],obs,lambda _:dict(status='completed',receipt={'native':'accepted'}))
        _,rev=m.lane_registry.read(path,b['lane_id'])
        before=path.read_bytes()
        try: m.lane_registry.claim(path,b['lane_id'],rev,'f2','startup_failed',obs)
        except ValueError: pass
        else: raise AssertionError('successful startup misclassified as positive startup failure')
        assert before==path.read_bytes()
    # 不依赖外部 HERDR_ENV，所有 CLI 都是边界替身，不控制真实宿主。
    print('Herdr native boundary contract: pass (external CLI substitute only)')

if __name__=='__main__': check()
