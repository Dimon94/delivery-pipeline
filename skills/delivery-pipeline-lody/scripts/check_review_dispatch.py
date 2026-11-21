"""DD518：真实 Registry/预算与 Lody 公开 I/O 边界，预期来自 DD508 R5–R17。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline-setup/scripts'))
import model_config as mc
import native_review as adapter


def check():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        config=mc.migrate_document(mc.valid_fixture())[0]
        config['review']['whole-change']['spec']['effort']='low'
        calls=[]
        options={'current':{'sessionId':'caller','workspaceId':'workspace','machineId':'machine'},
                 'agentConfigs':[{'id':'config','machineId':'machine','agentType':'pi',
                    'runConfig':{'models':[{'id':'provider/model','reasoningEffortValues':['high','low']}]}}]}
        def io(name,args):
            calls.append((name,deepcopy(args)))
            if name=='lody_session_create_options': return deepcopy(options)
            if name=='lody_session_create': return {'id':'adopted','state':'active'}
            raise AssertionError(name)
        binding={'sessionId':'caller','workspaceId':'workspace','machineId':'machine','projectId':'project','sourceRepo':tmp}
        # 真实 Git 临时 fixture；不建 checkout，不启动原生进程。
        import subprocess
        subprocess.run(['git','init','-q',tmp],check=True)
        subprocess.run(['git','-C',tmp,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-qm','base'],check=True)
        base=subprocess.check_output(['git','-C',tmp,'rev-parse','HEAD'],text=True).strip()
        options['current']['workContext']={'kind':'local','projectId':'project','rootPath':tmp}
        options['machines']=[{'id':'machine','online':True,'canUse':True}]
        options['localProjects']=[{'id':'project','machineId':'machine','rootPath':tmp,'isGit':True}]
        sources=root/'sources.md'
        adapter.registry.write(sources,{'lane_id':'map','role':'map','base_commit':base,'work_item':'map'})
        request={'action':'dispatch','registry':str(root/'review.md'),'lane':'review','request_id':'r1',
                 'config':config,'implementation_registries':[str(sources)],'fixed_point':base,
                 'head':base,'required_axes':['standards','spec'],'ledger':str(root/'ledger.json'),
                 'row':{'work_item':'DD518','worktree':tmp,'base_commit':base},'binding':binding,
                 'owner':{'name':'code-review','path':'/resolved/code-review/SKILL.md','invocation':'code-review'},
                 'prompt':'只读 whole-change review'}
        try: value=adapter.handle(request,io)
        except ValueError as error: raise AssertionError('合法 R1 必须按冻结双轴派发') from error
        assert value['action']=='recover_original', '冻结计划应创建并保存唯一原 session receipt'
        assert [x[0] for x in calls].count('lody_session_create')==1, '首次仅创建一个 session'
        row=value['row']; packet=value['review_packet']
        assert row['lody']['receipt']['id']=='adopted'
        sent=next(a for n,a in calls if n=='lody_session_create')
        assert sent['modelId']=='provider/model' and sent['reasoningEffort']=='high'
        assert [(x['axis'],x['requested']['effort']) for x in packet['owner_calls']]==[('standards','high'),('spec','low')]
        assert len(value['execution_evidence'])==2 and all(x['status']=='unknown' and x['executed'] is None for x in value['execution_evidence']), '无原生独立证据必须逐轴 Unknown'
        before=len(calls)
        retry={k:request[k] for k in ('registry','lane','request_id','binding')};retry['action']='recover'
        assert adapter.handle(retry,io)['row']==row and len(calls)==before, '重放不读配置不调用 native'
        # 取消必须 stop，不重发。
        row['state']='cancelled';adapter.registry.write(Path(request['registry']),row)
        assert adapter.handle(retry,io)['action']=='stop' and len(calls)==before, '取消后必须 stop 且零原生重发'
        # gate 必须保留 findings；部分 known 冲突也阻断。
        from review_gate import run
        axes={a:{'verdict':'PASS','counts':{'P0':0,'P1':0,'P2':0,'P3':0},'findings':['完整 finding '+a]} for a in ('standards','spec')}
        data={'round':1,'axes':axes,'review_packet':packet,'native_readbacks':{}}
        assert run(data,str(root/'unknown.json'))=='PASS', 'Unknown 不单独阻断'
        data['native_readbacks']={'spec':{'source':'native_readback','identity':{'model':'conflict'}}}
        assert run(data,str(root/'mismatch.json'))=='REVIEW_BLOCKED', '部分 known 冲突必须阻断'
        saved=json.loads((root/'mismatch.json').read_text())
        assert saved['rounds'][-1]['axes']==axes, '完整 findings 不得丢失'
        # 任何缺失、池外、required axes 漂移都必须在 create/Registry 前失败。
        def reject(label,change,reason=None):
            bad=deepcopy(request);bad['lane']=label;bad['request_id']=label;bad['registry']=str(root/(label+'.md'))
            change(bad)
            before=sum(n=='lody_session_create' for n,_ in calls)
            try: adapter.handle(bad,io)
            except ValueError as error:
                assert reason is None or reason in str(error), label+' 缺证据不能被当正面 unavailable'
            else: raise AssertionError(label+' 必须阻断')
            assert sum(n=='lody_session_create' for n,_ in calls)==before and not Path(bad['registry']).exists(), label+' 必须零副作用'
        old=deepcopy(options)
        options['agentConfigs'][0]['runConfig']['models'][0].pop('reasoningEffortValues')
        reject('missing-evidence',lambda b:None)
        options.clear();options.update(deepcopy(old))
        options['agentConfigs'][0]['runConfig']['models']=[]
        reject('empty-native-cache',lambda b:None,'review_capability_evidence_required')
        options.clear();options.update(deepcopy(old))
        reject('outside-pool',lambda b:b['config']['review']['whole-change']['standards'].update(model='outside'))
        reject('wrong-axes',lambda b:b.update(required_axes=['spec']))
        # 正面 unavailable 跳过，重复候选保序；spec-only 后轮由 canonical prepare_round 决定。
        c=deepcopy(config);c['review']['whole-change']['standards']['candidates']=[{'agent':'pi','model':'second','effort':'high'}]
        options['agentConfigs'][0]['runConfig']['models'].append({'id':'second','reasoningEffortValues':['high']})
        options['agentConfigs'][0]['runConfig']['models'][0]['reasoningEffortValues']=['low']
        bad=deepcopy(request);bad.update(lane='candidate',request_id='candidate',registry=str(root/'candidate.md'),config=c)
        chosen=adapter.handle(bad,io)
        assert chosen['row']['review_plan']['lane']['selected']['model']=='second', '正面不支持 high 应跳过主项'
        # ADR-0027 一轮制：FIX 需带反例；原轮取消或仍有效都不能开 R2。
        options.clear();options.update(deepcopy(old))
        fix_axes=deepcopy(axes);fix_axes['spec'].update(verdict='BLOCK',counts={'P0':0,'P1':1,'P2':0,'P3':0})
        fix_data={'round':1,'axes':fix_axes,'review_packet':packet,'native_readbacks':{},'repros':['node --test spec.test.js']}
        ledger=root/'fix.json'
        assert run(fix_data,str(ledger))=='FIX'
        adapter.registry.write(sources,{'lane_id':'repair','role':'backend','map':'map','output_mode':'commit',
              'integrated_commit':'repair-head','agent':'codex','model':'repair-model','effort':'high','work_item':'repair'})
        r2=deepcopy(request);r2.update(lane='r2',request_id='r2',registry=str(root/'r2.md'),round=2,
                    ledger=str(ledger),previous_review_registry=request['registry'],head='repair-head',required_axes=['spec'])
        for state in (None,'created'):
            if state: row['state']=state;adapter.registry.write(Path(request['registry']),row)
            try: adapter.handle(r2,io)
            except ValueError: continue
            raise AssertionError('FIX 之后不能开 R2')
        before=len(calls)
        reuse=deepcopy(request);reuse.update(lane='reuse',request_id='reuse',registry=str(root/'reuse.md'),ledger=str(ledger))
        reused=adapter.handle(reuse,io)
        assert reused['action']=='reuse' and reused['result']['axes']==fix_axes and len(calls)==before, '相同 base/head 只复用完整结论'
        # 真实 JSON-lines 子进程协议；替身仅在公开 native I/O。
        protocol=deepcopy(request);protocol.update(action='preflight',lane='protocol',request_id='protocol',registry=str(root/'protocol.md'))
        proc=subprocess.Popen([sys.executable,str(Path(adapter.__file__))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        proc.stdin.write(json.dumps(protocol)+'\n');proc.stdin.flush()
        while True:
            message=json.loads(proc.stdout.readline())
            if 'result' in message:
                assert message['result']['action']=='preflight_ready', message
                break
            assert message['tool']!='lody_session_create', 'preflight 不得创建 session'
            proc.stdin.write(json.dumps({'result':io(message['tool'],message['arguments'])})+'\n');proc.stdin.flush()
        assert proc.wait(timeout=10)==0, proc.stderr.read()
        assert not Path(protocol['registry']).exists(), 'preflight 不得写 Registry'
        # 两个真实进程共享唯一 Registry；create 边界只允许一次。
        import multiprocessing
        concurrent=deepcopy(request);concurrent.update(lane='race',request_id='race',registry=str(root/'race.md'))
        marker=root/'creates'
        def worker():
            def race_io(n,a):
                if n=='lody_session_create':
                    with marker.open('a') as f:f.write('create\n')
                    return {'id':'race-receipt'}
                return io(n,a)
            try: adapter.handle(concurrent,race_io)
            except ValueError: pass
        ctx=multiprocessing.get_context('fork')
        workers=[ctx.Process(target=worker) for _ in range(2)]
        for w in workers:w.start()
        for w in workers:w.join(15);assert w.exitcode==0, '并发调用必须结束'
        assert marker.read_text().splitlines()==['create'], '并发同 request 不得重复 native create'
        # response lost 留 launching；恢复绝不重发。
        options.clear();options.update(old)
        lost=deepcopy(request);lost.update(lane='lost',request_id='lost',registry=str(root/'lost.md'))
        def lost_io(n,a):
            if n=='lody_session_create': raise ValueError('response lost')
            return io(n,a)
        try: adapter.handle(lost,lost_io)
        except ValueError: pass
        else: raise AssertionError('response lost must surface')
        before=len(calls)
        assert adapter.handle(lost,io)['action']=='inspect_original' and len(calls)==before
        assert run(data,request['ledger'])=='REVIEW_BLOCKED'
        recovered=adapter.handle(retry,io)
        assert recovered['execution_evidence'][1]['status']=='mismatch' and recovered['recorded_rounds'][-1]['axes']==axes, '恢复须保留原 known 冲突与完整 findings'
    print('native-unknown: pass (Lody I/O fixture; actual session/model/effort Unknown)')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=['native-unknown'],required=True);parser.parse_args();check()
