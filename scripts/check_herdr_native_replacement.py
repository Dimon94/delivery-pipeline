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
    assert native.reconcile(claimed)['status']=='unknown', 'absent agent is not negative request receipt'
    busy=True
    agents.append(dict(name='r-test',pane_id='w1:p2',kind='pi',status='idle'))
    assert native.reconcile(claimed)['status']=='completed'
    agents[0]['name']='other'
    assert native.reconcile(claimed)['status']=='unknown'
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
