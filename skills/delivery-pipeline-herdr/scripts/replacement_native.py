#!/usr/bin/env python3
"""受管 pane 的分阶段公开入口；不创建 pane、不挂 watcher、不自动重发。"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('herdr_replacement',HERE/'replacement.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
r=m.lane_registry


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['probe','init','primary','claim','execute','reconcile','nonce','fault','sample'])
    for name in ('registry','config','evidence','output','target','terminal','target-cwd','caller','workspace','tab'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--lane',default='dd414-primary')
    p.add_argument('--task',default='frontend')
    p.add_argument('--source')
    p.add_argument('--failure-id')
    p.add_argument('--category',choices=['tool_or_model','startup_failed','unknown','connection_interrupted','outcome_unknown','cancelled','context_exhausted'])
    args=p.parse_args()
    # 必须先验证真正的受管 caller；在此之前不读配置或写任何产物。
    coord=m.dispatch.coordinator()
    if coord!=dict(workspace_id=args.workspace,tab_id=args.tab,pane_id=args.caller) or args.caller==args.target:
        raise ValueError('caller/target scope mismatch')
    output=Path(args.output).resolve()
    config=Path(args.config).resolve()
    registry=Path(args.registry).resolve()
    if not output.is_dir() or not all(x.is_relative_to(output) for x in (config,registry)):
        raise ValueError('config/registry must be task-isolated files inside output')
    scope=dict(workspace_id=args.workspace,tab_id=args.tab,pane_id=args.target,
               terminal_id=args.terminal,cwd=args.target_cwd)
    evidence=json.loads(Path(args.evidence).read_text())
    evidence=evidence.get('capabilities',evidence)
    native=m.NativeReplacement(scope,evidence)
    sample=native.sample(scope)
    result={}
    if args.stage=='probe':
        # 供 root 校准尚未采集的 agent 字段；本阶段完全只读。
        result=dict(pane=sample[0],process_info=sample[1],agents=sample[2],
                    schema=native.read_cli('api','schema','--json'),version=native.read_cli('--version'))
    elif args.stage=='init':
        if registry.exists():
            raise ValueError('registry already exists; inspect rather than reinitialize')
        plan=m.mc.resolve_plan(m.mc.load_document(config),args.task,evidence=evidence,output_mode='checks')
        row=dict(lane_id=args.lane,work_item='DD414-accept-'+str(output),role=args.task,
                 runtime=m.dispatch.RUNTIME[plan['agent']],state='created',output_mode='checks',
                 **m.mc.freeze_overlay(plan),herdr={**scope,'agent_name':args.lane})
        r.write(registry,row)
        result=row
    elif args.stage=='primary':
        row,_=r.read(registry,args.lane)
        if row.get('replacement_of') or row['herdr'].get('startup_state'):
            raise ValueError('primary already attempted; sample original request')
        native.verify_target(args.target,row)
        errors=m.mc.capability_errors(row['agent'],row['model'],row['effort'],evidence)
        if errors: raise ValueError('; '.join(errors))
        argv=m.mc.startup_request({**row,'mode':row.get('mode') or 'none','capability':'verified'},worker_name=args.lane,pane_id=args.target)
        row['herdr'].update(startup_state='launching',argv=argv)
        r.write(registry,row)
        response=subprocess.run(argv,capture_output=True,text=True,timeout=45)
        row['herdr']['start_reply']=m.start_result(response.returncode,response.stdout,response.stderr)
        synthetic={**row,'replacement_intent':dict(native_request=dict(scope=scope,agent_name=args.lane))}
        accepted=native.reconcile(synthetic)
        if accepted['status']=='completed':
            row['herdr'].update(startup_state='completed',writer_pids=accepted['receipt']['writer_pids'],receipt=accepted['receipt'])
            row['state']='running'
        r.write(registry,row)
        result=dict(row=row,executedModel='Unknown',effort='Unknown')
    elif args.stage=='claim':
        if not all((args.source,args.failure_id,args.category)):
            raise ValueError('claim requires source, stable failure-id and coordinator-classified category')
        source,rev=r.read(registry,args.source)
        # 已接受 replacement 的启动失败必须先获得正面原请求拒绝回执。
        if args.category=='startup_failed' and source.get('replacement_intent',{}).get('status')!='failed':
            raise ValueError('blocked: no positive original startup rejection; shell absence is insufficient')
        result=r.claim(registry,args.source,rev,args.failure_id,args.category,native.observe)
    elif args.stage in {'execute','reconcile'}:
        row,_=r.read(registry,args.lane)
        if args.stage=='reconcile' and not row.get('replacement_of'):
            # 主 lane 的响应丢失也只读回原 name/terminal，不再发起 start。
            request=dict(scope={k:row['herdr'][k] for k in scope},agent_name=row['herdr']['agent_name'])
            accepted=native.reconcile({**row,'replacement_intent':dict(native_request=request)})
            if accepted['status']=='completed':
                row['herdr'].update(startup_state='completed',writer_pids=accepted['receipt']['writer_pids'],receipt=accepted['receipt'])
                row['state']='running'
                r.write(registry,row)
            result=dict(row=row,reconciliation=accepted)
        else:
            result=(native.execute(registry,args.lane) if args.stage=='execute'
                    else r.recover_launch(registry,args.lane,native.reconcile))
    elif args.stage in {'nonce','fault'}:
        row,_=r.read(registry,args.lane)
        request=row.get('replacement_intent',{}).get('native_request') or dict(
            scope=row['herdr'],agent_name=row['herdr']['agent_name'])
        # primary scope overlay 含额外字段，校验仍使用精确授权坐标。
        original_scope=request['scope']
        synthetic={**row,'replacement_intent':dict(native_request={**request,'scope':{k:original_scope[k] for k in scope}})}
        if native.reconcile(synthetic)['status']!='completed':
            raise ValueError('agent identity/ready Unknown; no prompt sent')
        nonce='DD414-'+uuid.uuid4().hex
        if args.stage=='nonce':
            prompt='只回复这个 nonce：'+nonce+'。不运行工具、不写文件、不访问网络。'
        else:
            prompt=('只做一次只读检查：读取 /tmp/'+nonce+'-intentionally-absent。不要创建它。'
                    '读失败后回复工具错误和 nonce '+nonce+'，随后等待；不写文件、不访问网络。')
        # prompt 回执不算实际响应；sample 独立采集输出供 root 判读。
        result=dict(nonce=nonce,prompt=prompt,response=native.read_cli('agent','prompt',request['agent_name'],prompt),
                    requested={k:row[k] for k in ('agent','model','effort')},
                    executedModel='Unknown',effort='Unknown')
    elif args.stage=='sample':
        result=dict(pane=sample[0],process_info=sample[1],agents=sample[2],
                    output=native.read_cli('pane','read',args.target,'--source','recent-unwrapped','--lines','160'),
                    executedModel='Unknown',effort='Unknown')
    dest=output/(args.stage+'-'+uuid.uuid4().hex+'.json')
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status='recorded',artifact=str(dest)),ensure_ascii=False))

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,OSError,subprocess.TimeoutExpired) as error:
        print(json.dumps(dict(status='blocked',error=str(error)),ensure_ascii=False))
        sys.exit(1)
