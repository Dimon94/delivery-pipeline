"""Lody whole-change 原 requester 适配；仅由 Root 绑定正式公开工具运行。

沿现有 native_host JSON-lines 协议；不消费外部成功 capabilities、不走 work replacement。
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'delivery-pipeline/scripts'))
sys.path.insert(0, str(ROOT / 'delivery-pipeline-setup/scripts'))
import lane_registry as registry
import model_config as mc
from review_gate import prepare_round, record_axis_execution, read_ledger
from native_replacement import NativeReplacement, common_dir, stdio_call


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def preflight(document, axes, request_id, native):
    """0.112 discovery summary：精确 config/runConfig，missing 与正面不支持分开。"""
    pools = {a: [mc.triple(document['review']['whole-change'][a]),
                  *document['review']['whole-change'][a].get('candidates', [])]
             for a in dict.fromkeys(['standards', *axes])}
    capabilities, snapshots, probe = {}, {}, {}
    for axis, pool in pools.items():
        capabilities[axis] = []
        for identity in pool:
            agent, model, effort = (identity[k] for k in ('agent', 'model', 'effort'))
            if agent not in snapshots:
                snapshots[agent] = native.call('lody_session_create_options',
                    dict(machineId=native.binding['machineId'], agentConfigQuery=agent,
                         localProjectQuery=native.binding['projectId']))
                current = snapshots[agent].get('current', {})
                if any(current.get(k) != native.binding[k] for k in ('sessionId','workspaceId','machineId')):
                    raise ValueError('Unknown: original requester binding mismatch')
            snapshot = snapshots[agent]
            matches = [c for c in snapshot.get('agentConfigs', []) if c.get('agentType') == agent
                       and c.get('machineId') == native.binding['machineId']]
            if len(matches) != 1:
                raise ValueError('review_capability_evidence_required: Unknown exact config '+agent)
            config = matches[0]
            availability = config.get('availability', {}).get('state', 'available')
            run = config.get('runConfig', {})
            models = run.get('models')
            if not isinstance(models, list) or not models:
                raise ValueError('review_capability_evidence_required: Unknown models')
            found = [m for m in models if m.get('id') == model]
            if len(found)>1 or availability not in ('available','unavailable'):
                raise ValueError('review_capability_evidence_required: Unknown config/model')
            efforts = None
            if found:
                efforts = found[0].get('reasoningEffortValues')
                if efforts is None and run.get('measuredForModelId') == model:
                    efforts = run.get('reasoningEffortValues')
                if not isinstance(efforts, list):
                    raise ValueError('review_capability_evidence_required: Unknown exact effort '+model)
            status = 'runnable' if availability=='available' and found and effort in efforts else 'unavailable'
            reason = None if status=='runnable' else ('config unavailable' if availability=='unavailable' else 'exact model/effort unsupported by runConfig')
            item = dict(identity=identity,status=status,reason=reason,
                        evidence_id=digest({'request':request_id,'snapshot':snapshot,'identity':identity}))
            capabilities[axis].append(item)
            evidence = probe.setdefault(agent, {'binary':True,'models':{}})
            if found:
                evidence['models'][model]=efforts
    evidence = dict(request_id=request_id,observed_at=datetime.now(timezone.utc).isoformat(),
                    sources={a:{'status':'ok'} for a in snapshots},capabilities=probe)
    return dict(evidence=evidence,capabilities=capabilities,sources=snapshots)


def recover(request):
    path=Path(request['registry']);row,_=registry.read(path,request['lane'])
    plan=registry.load_review_plan(path,request['lane'],request['request_id'])
    overlay=row['lody']
    if overlay['binding'] != request['binding']:
        raise ValueError('Unknown: original requester required')
    packet=overlay['review_packet'];registry.verify_review_packet(plan,packet)
    action=('stop' if row.get('state') in ('cancelled','closed','blocked','consumed','terminal') else
            'recover_original' if overlay.get('startup_state')=='completed' else 'inspect_original')
    ledger=overlay['ledger']
    if request.get('ledger',ledger)!=ledger:
        raise ValueError('original Review Budget ledger required')
    rounds=read_ledger(ledger) if ledger else []
    recorded=[r for r in rounds if r.get('review_packet')==packet]
    if recorded:
        action='fan_in_recorded' if recorded[-1].get('outcome')=='FIX' else 'stop'
    return dict(action=action,row=row,review_packet=packet,recorded_rounds=recorded,
                execution_evidence=(deepcopy(recorded[-1]['execution_evidence']) if recorded else
                    [record_axis_execution(c['axis'],c['requested'],None) for c in packet['owner_calls']]),
                instruction='只读原 session/轴结果并 fan-in；Unknown 不重发，不换候选')


def handle(request, call):
    path=Path(request['registry'])
    existing=registry.rows(path)
    same=[r for r in existing.values() if r.get('review_plan',{}).get('request_id')==request['request_id']]
    if request.get('action')=='recover' or request['lane'] in existing or same:
        if same and same[0]['lane_id']!=request['lane']:
            raise ValueError('review already frozen: recover original lane')
        return recover(request)
    if request.get('action') not in ('dispatch','preflight'):
        raise ValueError('whole-change dispatch/preflight/recover required')
    owner=request['owner']
    if set(owner)!= {'name','path','invocation'} or not all(owner.values()) or not Path(owner['path']).is_absolute() or not owner['path'].endswith('/SKILL.md'):
        raise ValueError('resolved owner name/absolute SKILL.md path/invocation required')
    document=request['config']
    errors=mc.validate_document(document)
    if errors: raise ValueError('; '.join(errors))
    rounds=read_ledger(request['ledger'])
    contributors={}
    for source in request['implementation_registries']:
        contributors.update(registry.rows(Path(source)))
    implementations=registry.collect_implementation_identities(contributors,request['fixed_point'])
    context=prepare_round(rounds,round_no=request.get('round',1),base=request['fixed_point'],head=request['head'],
                          request_id=request['request_id'],implementations=implementations,
                          interface_changed=request.get('interface_changed',False),
                          dependencies_changed=request.get('dependencies_changed',False))
    if context['action']=='reuse': return context
    if request['required_axes']!=context['required_axes']:
        raise ValueError('required axes differ from Review Budget')
    if rounds:
        prior=registry.rows(Path(request.get('previous_review_registry',request['registry'])))
        originals=[r for r in prior.values() if r.get('review_plan')==rounds[-1]['review_packet']['review_plan']]
        if len(originals)!=1 or originals[0].get('state') in ('cancelled','blocked') or originals[0].get('lody',{}).get('startup_state')!='completed':
            raise ValueError('previous review cancelled/Unknown; inspect original')
    native=NativeReplacement(call,request['binding'])
    collected=preflight(document,request['required_axes'],request['request_id'],native)
    plan=mc.resolve_review_plan(document,required_axes=request['required_axes'],implementations=context['implementations'],
         evidence=collected['evidence'],native_capabilities=collected['capabilities'],request_id=request['request_id'],round_context=context)
    plan['native_preflight']=collected
    packet=dict(review_plan=plan,owner_calls=registry.build_owner_calls(plan))
    # 所选 lane 与每个 required 轴创建前再次精确复核，不重选。
    row=deepcopy(request['row'])
    for identity in [plan['lane']['selected'],*[c['requested'] for c in packet['owner_calls']]]:
        native.target({**row,**identity})
    arguments=native.target({**row,**plan['lane']['selected']})
    prompt=request['prompt']+'\n<!-- DP_REVIEW_PLAN -->\n```json\n'+json.dumps(packet,ensure_ascii=False)+'\n```\n'+json.dumps({'resolved_owner':owner},ensure_ascii=False)+'\n逐轴按 owner_calls requested 调用；只执行 required_axes，禁止重读配置。无独立执行读回写 Unknown；保留完整 findings。沿 canonical review_gate.py fan-in，known mismatch 阻断。已完成轴不重跑；取消/响应丢失只对账原 session，不换候选。'
    arguments.update(operationId=request['lane'],prompt=prompt)
    if request['action']=='preflight': return dict(action='preflight_ready',review_packet=packet,arguments=arguments)
    row.update(lane_id=request['lane'],role='review',runtime='lody-session',output_mode='verdict',state='created',
               review_plan=plan,**plan['lane']['selected'])
    row['lody']=dict(binding=deepcopy(request['binding']),startup_state='launching',arguments=arguments,
                     review_packet=packet,owner=owner,ledger=request['ledger'])
    registry.reserve_review(path,row)
    # reserve 的唯一赢家才调用 create；响应丢失永久保留 launching。
    receipt=call('lody_session_create',arguments)
    if not isinstance(receipt,dict) or not receipt.get('id'):
        raise ValueError('Unknown: native receipt missing; inspect original')
    with registry.lock(path) as locked:
        saved,_=registry.read(locked,request['lane'])
        saved['lody'].update(receipt=receipt,startup_state='completed')
        registry.persist(locked,[saved])
    return recover(request)


def main():
    if sys.stdin.isatty():
        import termios
        settings=termios.tcgetattr(sys.stdin)
        settings[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(sys.stdin,termios.TCSANOW,settings)
    request=json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv)==3 and sys.argv[1]=='--request' else json.loads(sys.stdin.readline())
    try: print(json.dumps({'result':handle(request,stdio_call)},ensure_ascii=False))
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'result':{'action':'blocked','error':str(error)}},ensure_ascii=False));return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
