"""DD407 独立预期：A→B→A；两个通知者最多一个 successor。"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'skills/delivery-pipeline/scripts'
sys.path.insert(0, str(CORE))
try:
    import lane_registry as registry
except ImportError:
    raise AssertionError('DD414 缺少真实 Registry 原子 claim 接口')


def observation(_):
    return dict(writer='exited', identity='match', capability='verified', gate='allowed')


def launch(path,lane,observe,start):
    registry.bind_request(path,lane,{'request_id':lane,'test_adapter':'external seam'},observe)
    return registry.launch(path,lane,observe,start)


def main():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'lane-registry.md'
        a = dict(agent='pi', model='A', effort='high')
        b = dict(agent='pi', model='B', effort='low')
        row = dict(lane_id='initial', work_item='/test/work', role='planning', mode='none',
                   runtime='herdr-pi-pane', state='blocked', **a,
                   recovery_plan=dict(plan_version=1, source='work', primary=a, fallbacks=[b,a,b]),
                   recovery_progress=dict(current_index=None, next_cursor=0))
        registry.write(path, row)
        source, rev = registry.read(path, 'initial')
        before=path.read_bytes()
        try:
            registry.write(path,{**row,**b,'recovery_progress':dict(current_index=0,next_cursor=1)})
        except ValueError:
            pass
        else:
            raise AssertionError('ordinary write advanced frozen position without claim')
        assert path.read_bytes()==before
        code = """import sys,json;from pathlib import Path
sys.path.insert(0,sys.argv[1]);import lane_registry as r
out=r.claim(Path(sys.argv[2]),'initial',sys.argv[3],'failure-1','tool_or_model',lambda _:dict(writer='exited',identity='match',capability='verified',gate='allowed'))
print(json.dumps(out))
"""
        procs = [subprocess.Popen([sys.executable,'-c',code,str(CORE),str(path),rev], stdout=subprocess.PIPE, text=True) for _ in range(2)]
        claims = [json.loads(p.communicate()[0]) for p in procs]
        assert all(p.returncode == 0 for p in procs)
        assert claims[0] == claims[1], claims
        first = claims[0]
        before=path.read_bytes()
        try:
            registry.write(path,{**row,'lane_id':'unclaimed-new-writer','state':'created'})
        except ValueError:
            pass
        else:
            raise AssertionError('normal writer bypassed accepted replacement')
        assert path.read_bytes()==before
        assert first['model'] == 'B' and first['recovery_progress'] == dict(current_index=0,next_cursor=1)
        try:
            registry.claim(path,'initial',rev,'different-failure','tool_or_model',observation)
        except ValueError:
            pass
        else:
            raise AssertionError('different event overwrote successor')
        launched = []
        def start(row):
            launched.append(row['lane_id'])
            return dict(status='failed', receipt={'native':'positive startup failure'})
        launch(path,first['lane_id'],observation,start)
        launch(path,first['lane_id'],observation,start)
        assert launched == [first['lane_id']]
        checkpoint,_=registry.read(path,first['lane_id'])
        registry.write(path,{**checkpoint,'state':'blocked'})
        reread,_=registry.read(path,first['lane_id'])
        assert reread['replacement_intent']==checkpoint['replacement_intent']
        assert reread['state']=='blocked'
        try:
            registry.claim(path,'initial',rev,'second-event-after-failure','tool_or_model',observation)
        except ValueError:
            pass
        else:
            raise AssertionError('same source acquired a second successor after startup failure')
        current, revision = registry.read(path,first['lane_id'])
        second=registry.claim(path,first['lane_id'],revision,'failure-2','startup_failed',observation)
        assert second['model']=='A' and second['recovery_progress']==dict(current_index=1,next_cursor=2)
        def lost(_):
            raise OSError('response lost')
        try:
            launch(path,second['lane_id'],observation,lost)
        except OSError:
            pass
        launch(path,second['lane_id'],observation,start)
        assert len(launched)==1
        unresolved=registry.recover_launch(path,second['lane_id'],lambda _:dict(status='unknown'))
        assert unresolved['replacement_intent']['status']=='launching'
        registry.recover_launch(path,second['lane_id'],lambda _:dict(status='failed',receipt={'native':'original request'}))
        _,revision=registry.read(path,second['lane_id'])
        before=path.read_bytes()
        try:
            registry.claim(path,second['lane_id'],revision,'failure-3','startup_failed',observation)
        except ValueError as e:
            assert 'budget' in str(e)
        else:
            raise AssertionError('third replacement allowed')
        assert path.read_bytes()==before
        assert len(registry.rows(path))==3
        # 活跃 writer、revision 冲突不修改实际文件。
        for obs,revision in [(lambda _:dict(writer='active'),rev),(observation,'stale')]:
            fresh=Path(td)/('active-'+str(len(str(revision)))+'.md')
            registry.write(fresh,row)
            _,valid=registry.read(fresh,'initial')
            before=fresh.read_bytes()
            try:
                registry.claim(fresh,'initial',valid if revision==rev else revision,'f','tool_or_model',obs)
            except ValueError:
                pass
            else:
                raise AssertionError('unsafe claim accepted')
            assert fresh.read_bytes()==before
        # Herdr 外部 I/O seam：独立预期 A→B→C 的精确 argv；不冒充真实 Herdr。
        import os
        spec=importlib.util.spec_from_file_location('herdr_replacement',ROOT/'skills/delivery-pipeline-herdr/scripts/replacement.py')
        adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
        adapter_path=Path(td)/'herdr-adapter.md'
        c={**a,'model':'C'}
        registry.write(adapter_path,{**row,'recovery_plan':{**row['recovery_plan'],'fallbacks':[b,c]}})
        old_env=os.environ.get('HERDR_ENV')
        os.environ['HERDR_ENV']='1'  # 仅外部 seam；不调用真实 Herdr。
        try:
            lane='initial'
            for i,(triple,category) in enumerate([(b,'tool_or_model'),(c,'startup_failed')]):
                _,revision=registry.read(adapter_path,lane)
                nxt=registry.claim(adapter_path,lane,revision,'abc-'+str(i),category,observation)
                seen=[]
                def native(argv,claimed):
                    seen.append(argv)
                    return dict(status='failed' if i==0 else 'completed',receipt={'external_adapter':'test only'})
                def target(pane,claimed):
                    return dict(pane_id=pane,identity='match',shell='available',scope='isolated_lane')
                adapter.execute(adapter_path,nxt['lane_id'],observation,'test-pane',
                                {'pi':{'binary':True,'models':{triple['model']:[triple['effort']]}}},target,native)
                assert seen==[['herdr','agent','start',nxt['lane_id'],'--kind','pi','--pane','test-pane','--','--approve','--model',triple['model'],'--thinking',triple['effort']]]
                lane=nxt['lane_id']
        finally:
            if old_env is None:os.environ.pop('HERDR_ENV',None)
            else:os.environ['HERDR_ENV']=old_env
        concurrent=Path(td)/'launch-race.md'
        registry.write(concurrent,row)
        _,revision=registry.read(concurrent,'initial')
        intent=registry.claim(concurrent,'initial',revision,'launch-race','tool_or_model',observation)
        registry.bind_request(concurrent,intent['lane_id'],{'request_id':intent['lane_id']},observation)
        launchcode="""import sys,json;from pathlib import Path
sys.path.insert(0,sys.argv[1]);import lane_registry as r
def start(row):
 with open(sys.argv[4],'a') as f:f.write(row['lane_id']+'\\n')
 return dict(status='completed',receipt={'native':'original receipt'})
print(json.dumps(r.launch(Path(sys.argv[2]),sys.argv[3],lambda _:dict(writer='exited',identity='match',capability='verified',gate='allowed'),start)))
"""
        events=Path(td)/'native-calls.txt'
        procs=[subprocess.Popen([sys.executable,'-c',launchcode,str(CORE),str(concurrent),intent['lane_id'],str(events)],stdout=subprocess.PIPE,text=True) for _ in range(2)]
        results=[json.loads(p.communicate()[0]) for p in procs]
        assert all(p.returncode==0 for p in procs)
        assert results[0]==results[1]
        assert events.read_text().splitlines()==[intent['lane_id']]
        # 真进程在原生调用中崩溃：launching 已持久，重启只能对账。
        crashpath=Path(td)/'crash.md'
        registry.write(crashpath,row)
        _,revision=registry.read(crashpath,'initial')
        claimed=registry.claim(crashpath,'initial',revision,'crash-f','tool_or_model',observation)
        crashcode="""import sys,os;from pathlib import Path
sys.path.insert(0,sys.argv[1]);import lane_registry as r
r.bind_request(Path(sys.argv[2]),sys.argv[3],dict(request_id=sys.argv[3]),lambda _:dict(writer='exited',identity='match',capability='verified',gate='allowed'))
r.launch(Path(sys.argv[2]),sys.argv[3],lambda _:dict(writer='exited',identity='match',capability='verified',gate='allowed'),lambda _:os._exit(23))
"""
        result=subprocess.run([sys.executable,'-c',crashcode,str(CORE),str(crashpath),claimed['lane_id']])
        assert result.returncode==23
        persisted,_=registry.read(crashpath,claimed['lane_id'])
        assert persisted['replacement_intent']['status']=='launching'
        registry.launch(crashpath,claimed['lane_id'],observation,lambda _:(_ for _ in ()).throw(AssertionError('crash replay relaunched')))
        registry.recover_launch(crashpath,claimed['lane_id'],lambda _:dict(status='completed',receipt={'native':'same request recovered'}))
        # 长度及重复位置的决定由公开 Recovery 和真实 Registry 读回验证。
        for length in range(4):
            for fallbacks in ([a]*length,[b,a,b][:length]):
                bounded=Path(td)/'bounded.md'
                bounded.unlink(missing_ok=True)
                initial={**row,'recovery_plan':{**row['recovery_plan'],'fallbacks':fallbacks}}
                registry.write(bounded,initial)
                lane='initial'
                for i in range(min(length,2)):
                    _,revision=registry.read(bounded,lane)
                    nxt=registry.claim(bounded,lane,revision,'event-'+str(i),'tool_or_model',observation)
                    assert {k:nxt[k] for k in ('agent','model','effort')}==fallbacks[i]
                    assert nxt['recovery_progress']==dict(current_index=i,next_cursor=i+1)
                    launch(bounded,nxt['lane_id'],observation,lambda _:dict(status='failed',receipt={'native':'failed'}))
                    lane=nxt['lane_id']
                _,revision=registry.read(bounded,lane)
                before=bounded.read_bytes()
                try:
                    registry.claim(bounded,lane,revision,'stop','tool_or_model',observation)
                except ValueError as e:
                    assert str(e) in {'budget','exhausted','existing_policy'}
                else:
                    raise AssertionError('out of bounds claim')
                assert bounded.read_bytes()==before
    print('replacement real Registry/process checks: pass')

if __name__=='__main__':
    main()
