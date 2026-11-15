#!/usr/bin/env python3
"""Orca whole-change 的计划/恢复/逐轴 fan-in；原生 mutation 仍归既有入口。"""
import argparse
import hashlib
import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]/'delivery-pipeline-setup/scripts'))
import model_config as m
sys.path.insert(0,str(HERE.parents[1]/'delivery-pipeline/scripts'))
import lane_registry as registry
from review_gate import prepare_round, read_ledger, run
from preflight import resolve_orca_executable
from native_pi_preflight import collect_pi


def collect_native(pools, request_id):
    """读取固定安装的原生参数解析器；不是 executed/applied effort 读回。

    非 App 布局或缺少当前原生模块保持 Unknown，不借用其他 transport。
    """
    result=dict(request_id=request_id,observed_at=datetime.now(timezone.utc).isoformat(),capabilities={},sources=[],ordered_pools=pools)
    reason='native Orca launch parser unavailable'
    rows=[]
    try:
        def capture(argv, payload=None):
            response=subprocess.run(argv,input=payload,capture_output=True,text=True,timeout=30)
            record=dict(argv=argv,exit=response.returncode,stdout=response.stdout,stderr=response.stderr)
            result['sources'].append(record)
            return record
        executable=Path(resolve_orca_executable())
        resources=executable.parent.parent
        out=resources/'app.asar.unpacked/out'
        parser=out/'shared/agent-launch/choices/agent-launch-model-preferences.js'
        catalog=out/'shared/agent-session/options/agent-session-option-catalog.js'
        electron=resources.parent/'MacOS/Orca'
        pi_transport=False
        if any(t['agent']=='pi' for ts in pools.values() for t in ts):
            info=resources.parent/'Info.plist'
            installed=plistlib.loads(info.read_bytes())['CFBundleShortVersionString']
            version=capture([str(executable),'--version'])
            guide=capture([str(executable),'skills','get','orca-cli','--full','--json'])
            worker=capture([str(executable),'orchestration','worker-start','--help'])
            terminal=capture([str(executable),'terminal','send','--help'])
            worktree=capture([str(executable),'worktree','create','--help'])
            g=json.loads(guide['stdout'])
            pi_transport=(installed=='1.4.258' and version['stdout'].strip()==installed
                and all(x['exit']==0 for x in (version,guide,worker,terminal,worktree))
                and g.get('name')=='orca-cli' and g.get('full') is True
                and all(x in g.get('markdown','') for x in ('terminal','worktree','orchestration'))
                and all(x in worker['stdout'] for x in ('--terminal','--worktree','--task'))
                and all(x in terminal['stdout'] for x in ('--terminal','--text','--enter','--wait-submit'))
                and all(x in worktree['stdout'] for x in ('--name','--base-branch')))
            result['sources'].append(dict(path=str(info),sha256=hashlib.sha256(info.read_bytes()).hexdigest()))
            result['sources'].append(dict(path=str(executable),sha256=hashlib.sha256(executable.read_bytes()).hexdigest()))
        # 原生源码只做纯解析；不调用 agent launch / worker-start / session。
        script='''const fs=require('fs'),crypto=require('crypto');
const p=require(process.argv[1]),c=require(process.argv[2]);
const pools=JSON.parse(process.argv[3]);
const cfg=require(process.argv[4]);
const pi_transport=cfg.TUI_AGENT_CONFIG?.pi?.detectCmd==='pi' && cfg.TUI_AGENT_CONFIG?.pi?.promptInjectionMode==='argv';
const rows=Object.fromEntries(Object.entries(pools).map(([a,ts])=>[a,ts.map(t=>{
 const cat=c.getAgentSessionOptionLaunchCatalog(t.agent);
 if(!cat || !cat.supportsWorkerLaunchPreferences || !c.findCatalogModel(cat,t.model)) return {status:'unknown',reason:'exact native model catalog evidence missing'};
 const checked=p.checkAgentLaunchModelPreferences({agent:t.agent,model:t.model,effort:t.effort,createsWorktree:true});
 if(checked.refusal) return {status:'unavailable',reason:checked.refusal.message};
 if(checked.preferences?.model!==t.model || checked.preferences?.effort!==t.effort) return {status:'unknown',reason:'native parser remap/Unknown'};
 return {status:'runnable',reason:'native static launch compatibility; execution Unknown'};
})]));
const sources=Object.keys(require.cache).map(path=>({path,sha256:crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex')}));
process.stdout.write(JSON.stringify({rows,sources,pi_transport}));'''
        env={**os.environ,'ELECTRON_RUN_AS_NODE':'1'}
        env.pop('NODE_OPTIONS',None); env.pop('NODE_REPL_EXTERNAL_MODULE',None)
        response=subprocess.run([str(electron),'-e',script,str(parser),str(catalog),json.dumps(pools),str(out/'shared/agent-launch/catalog/tui-agent-config.js')],env=env,capture_output=True,text=True,timeout=30)
        if response.returncode:
            raise ValueError('native parser failed: '+response.stderr[-1000:])
        decoded=json.loads(response.stdout)
        rows=decoded['rows']; result['sources'].extend(decoded['sources'])
        if pi_transport and decoded.get('pi_transport') is True:
            native=collect_pi([t for ts in pools.values() for t in ts],capture,result['sources'])
            for axis,pool in pools.items():
                for index,target in enumerate(pool):
                    if target['agent']=='pi':
                        rows[axis][index]=native.get(json.dumps(target,sort_keys=True),dict(status='unknown',reason='version-matched Pi parser evidence missing'))
                        rows[axis][index]={k:v for k,v in rows[axis][index].items() if k!='identity'}
        else:
            for axis,pool in pools.items():
                for index,target in enumerate(pool):
                    if target['agent']=='pi':
                        rows[axis][index]=dict(status='unknown',reason='Orca version/guide/native agent-argv transport evidence missing')
        result['executable']=str(executable)
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
        reason=str(error)
    for axis,pool in pools.items():
        result['capabilities'][axis]=[]
        for index,target in enumerate(pool):
            observation=rows[axis][index] if isinstance(rows,dict) else dict(status='unknown',reason=reason)
            record=dict(identity=target,**observation)
            record['evidence_id']=hashlib.sha256(json.dumps([request_id,result['observed_at'],pools,axis,index,record,result['sources']],sort_keys=True).encode()).hexdigest()
            result['capabilities'][axis].append(record)
    return result


def prepare(request, *, collect=collect_native):
    """纯计划 seam。传入 Registry 路径，身份不从当前配置/argv 猜测。"""
    rows={}
    for path in request['implementation_registries']:
        rows.update(registry.rows(Path(path)))
    implementations=registry.collect_implementation_identities(rows,request['fixed_point'])
    rounds=request.get('rounds',[])
    context=prepare_round(rounds,round_no=request['round'],base=request['base'],head=request['head'],
        request_id=request['request_id'],implementations=implementations,
        interface_changed=request.get('interface_changed',False),dependencies_changed=request.get('dependencies_changed',False))
    if context['action']=='reuse':
        return context
    if request['required_axes']!=context['required_axes']:
        raise ValueError('required axes differ from Review Budget')
    document=request['config']
    pools={axis:[m.triple(cell),*cell.get('candidates',[])]
           for axis in dict.fromkeys(['standards',*context['required_axes']])
           for cell in [document['review']['whole-change'][axis]]}
    native=collect(pools,request['request_id'])
    # 单模型也必须通过 Orca 自身 native preflight，不增设家族门槛。
    for axis,pool in pools.items():
        observations=native.get('capabilities',{}).get(axis,[])
        if len(observations)!=len(pool) or any(x.get('identity')!=t or x.get('status') not in ('runnable','unavailable') or not x.get('evidence_id') for x,t in zip(observations,pool)):
            raise ValueError('review_capability_evidence_required: '+json.dumps(native,ensure_ascii=False))
        if len(pool)==1 and observations[0]['status']!='runnable':
            raise ValueError('review_no_runnable_candidate: '+json.dumps(native,ensure_ascii=False))
    plan=m.resolve_review_plan(document,required_axes=context['required_axes'],implementations=context['implementations'],
        evidence=request['evidence'],native_capabilities=native['capabilities'],request_id=request['request_id'],round_context=context)
    plan['native_preflight']=native
    return dict(dispatch='preflight-ready',authority=False,review_plan=plan,owner_calls=registry.build_owner_calls(plan))


def recover(path,lane,request_id,ledger=None):
    row=registry.read(Path(path),lane)[0]
    plan=registry.load_review_plan(Path(path),lane,request_id)
    recorded=[r for r in read_ledger(ledger) if r.get('review_packet',{}).get('review_plan')==plan] if ledger else []
    return dict(action='stop' if row.get('state') in ('cancelled','consumed','closed','setup_blocked') or recorded else 'inspect_original',
                row=row,review_packet=dict(review_plan=plan,owner_calls=registry.build_owner_calls(plan)),recorded_rounds=recorded,
                instruction='只读原 intent/receipt/轴结果；Unknown 不重发、不重选；完成轴只 fan-in')


def finish(data,ledger):
    if not isinstance(data.get('review_packet'),dict):
        raise ValueError('frozen review_packet required')
    return run(data,str(ledger))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','freeze','recover','execution'])
    parser.add_argument('request',help='Root 准备的 JSON；不写配置，不派发')
    args=parser.parse_args()
    try:
        data=json.loads(Path(args.request).read_text())
        if args.action=='recover':
            result=recover(data['registry'],data['lane'],data['request_id'],data.get('ledger'))
        elif args.action=='execution':
            result=finish(data['data'],data['ledger'])
        else:
            # 同轮已冻结优先恢复，绝不读取新配置/能力重选。
            if data.get('registry') and Path(data['registry']).exists():
                existing=registry.rows(Path(data['registry']))
                if data['lane'] in existing or any(r.get('review_plan',{}).get('request_id')==data['request_id'] for r in existing.values()):
                    raise ValueError('review already frozen: recover original plan/receipt')
            request={**data,'config':m.load_document(Path(data['config'])),'evidence':json.loads(Path(data['evidence']).read_text()),
                     'rounds':read_ledger(data['ledger']) if data.get('ledger') else []}
            if request['rounds']:
                previous=registry.rows(Path(data.get('previous_review_registry',data['registry'])))
                old=request['rounds'][-1]['review_packet']['review_plan']
                originals=[r for r in previous.values() if r.get('review_plan')==old]
                if len(originals)!=1 or originals[0].get('state') in ('cancelled','setup_blocked'):
                    raise ValueError('original round missing/cancelled/failed: recover only')
            result=prepare(request)
            if result.get('action')!='reuse':
                from preflight import preflight
                native_request={**data['preflight'],'review_packet':result}
                if Path(native_request['config']).resolve()!=Path(data['config']).resolve() or Path(native_request['model_evidence']).resolve()!=Path(data['evidence']).resolve():
                    raise ValueError('preflight must bind the same config/probe')
                if native_request['owner']['name']!='code-review' or native_request['task']!='review' or native_request['output_mode']!='verdict':
                    raise ValueError('whole-change verdict requires resolved code-review owner')
                checked=preflight(native_request)
                if not checked['ok']:
                    raise ValueError(json.dumps(checked,ensure_ascii=False))
                result['orca_preflight']=checked
                if args.action=='freeze':
                    from registry_overlay import empty_overlay, validate_markers
                    packet=Path(data['packet'])
                    if not packet.is_absolute() or not packet.is_file():
                        raise ValueError('existing absolute dispatch packet required')
                    frozen=checked['worker_policy']['frozen']
                    m.verify_overlay(checked['worker_policy']['plan'],frozen)
                    row=dict(lane_id=data['lane'],work_item=data['work_item'],role='review',runtime='orca',
                        dispatch_runtime='orca',coordinator_runtime='orca-terminal',
                        output_mode='verdict',state='created',updated_at=datetime.now(timezone.utc).isoformat(),base_commit=data['base'],worktree=data['worktree'],
                        branch=data['branch'],map=data['map'],packet=str(packet),orca=empty_overlay(),**frozen)
                    row=validate_markers(row,kind='lane')
                    registry.reserve_review(Path(data['registry']),row)
                    marker='<!-- DP_REVIEW_PLAN -->'
                    packet.write_text(packet.read_text()+'\n'+marker+'\n```json\n'+json.dumps(result,ensure_ascii=False)+'\n```\n')
                    result['instruction']='Registry 已占位；Root 核验 provenance 后沿既有 Orca overlay 写原生 intent。任何不确定仅 recover，不再 freeze/dispatch。'
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps(dict(status='blocked',authority=False,error=str(error)),ensure_ascii=False))
        return 1

if __name__=='__main__':
    raise SystemExit(main())
