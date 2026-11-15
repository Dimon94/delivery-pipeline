"""T3 whole-change Adapter；唯一计划/预算/Registry 沿 canonical owner。"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline/scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline-setup/scripts'))
import lane_registry as registry
import model_config
from review_gate import prepare_round, read_ledger, run
from native_replacement import NativeReplacement, TARGETS, stdio_call


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class ReviewDispatch:
    def __init__(self, call):
        self.call = call

    def prepare(self, config, context):
        """只读能力发现；完整参与池核验发生在任何 packet/Registry/native mutation 前。"""
        if context.get('action') == 'reuse':
            return context
        axes = list(dict.fromkeys(['standards', *context['required_axes']]))
        capabilities, sources, native, snapshots = {}, {}, {}, []
        for axis in axes:
            cell = config['review']['whole-change'][axis]
            native[axis] = []
            for identity in [model_config.triple(cell), *cell.get('candidates', [])]:
                caps = self.call('orchestrator_capabilities', dict(search=identity['model']))
                provider, option = TARGETS[identity['agent']]
                p = next((p for p in caps.get('providers', []) if p['providerInstanceId'] == provider), None)
                if not p or not caps.get('parentThreadId') or not caps.get('inheritedProviderInstanceId'):
                    raise ValueError('review_capability_evidence_required: provider/context missing')
                models = p.get('models')
                if not isinstance(models, list):
                    raise ValueError('review_capability_evidence_required: model catalog missing')
                model = next((m for m in models if m['id'] == identity['model']), None)
                if model is None and p.get('omittedModels', 0):
                    raise ValueError('review_capability_evidence_required: exact model omitted')
                opt = next((o for o in (model or {}).get('options', []) if o['id'] == option), None)
                cross = provider != caps['inheritedProviderInstanceId']
                if not isinstance(p.get('canRunChildTask'), bool) or (cross and not isinstance(p.get('canRunCrossProviderChildTask'), bool)):
                    raise ValueError('review_capability_evidence_required: native permission missing')
                if model and (opt is None or not isinstance(opt.get('values'), list)):
                    raise ValueError('review_capability_evidence_required: effort options missing')
                available = bool(model and identity['effort'] in opt['values'] and p['canRunChildTask']
                                 and (not cross or p['canRunCrossProviderChildTask']))
                snapshot = dict(identity=identity, capabilities=caps)
                snapshots.append(snapshot)
                capabilities.setdefault(identity['agent'], dict(binary=True, models={}))['models'][identity['model']] = opt['values'] if opt else []
                sources[identity['agent']] = dict(status='ok', source='orchestrator_capabilities')
                native[axis].append(dict(identity=identity, status='runnable' if available else 'unavailable',
                    evidence_id=digest(snapshot), reason=None if available else 'native exact target/effort/permission unavailable'))
        evidence = dict(request_id=context['request_id'], observed_at=datetime.now(timezone.utc).isoformat(),
                        sources=sources, capabilities=capabilities)
        # 单模型仍需真实原生 preflight；不能用仅有 model 目录跳过 permission。
        for axis in axes:
            if not config['review']['whole-change'][axis].get('candidates') and native[axis][0]['status'] != 'runnable':
                raise ValueError('review_no_runnable_candidate: native single-model preflight failed')
        plan = model_config.resolve_review_plan(config, required_axes=context['required_axes'],
            implementations=context['implementations'], evidence=evidence, native_capabilities=native,
            request_id=context['request_id'], round_context=context)
        plan['native_preflight'] = dict(transport='t3code', snapshots=snapshots, evidence=evidence, capabilities=native)
        return dict(review_plan=plan, owner_calls=registry.build_owner_calls(plan))

    def dispatch(self, path, row, packet, owner, task):
        """reserve 为唯一占位点；既有同轮必须 recover，不能再次 delegate。"""
        plan = packet['review_plan']
        registry.verify_review_packet(plan, packet)
        if set(owner) != {'name', 'path', 'invocation_label'} or not Path(owner['path']).is_absolute():
            raise ValueError('resolved owner name/absolute path/invocation_label required')
        selected = plan['lane']['selected']
        caps = self.call('orchestrator_capabilities', dict(search=selected['model']))
        target = NativeReplacement(self.call, caps).target(selected)
        for call in packet['owner_calls']:
            axis_caps = self.call('orchestrator_capabilities', dict(search=call['requested']['model']))
            NativeReplacement(self.call, axis_caps).target(call['requested'])
        arguments = dict(task=task+'\n'+json.dumps(dict(review_packet=packet, owner=owner), ensure_ascii=False),
                         target=target, isolation='worktree', mode='async', role='review', clientRequestId=row['lane_id'])
        request = dict(coordinator_thread_id=caps['parentThreadId'], arguments=arguments)
        row = {**row, **selected, 'role':'review', 'runtime':'t3-task', 'output_mode':'verdict',
               'state':'created', 'review_plan':plan, 't3code':dict(review_packet=packet, owner=owner,
               native_request=request, startup_state='accepted', coordinator_thread_id=caps['parentThreadId'],
               coordinator_provider=caps['inheritedProviderInstanceId'],provider_instance_id=target['providerInstanceId'],
               effort_option=next(iter(target['options'])),client_request_id=row['lane_id'])}
        registry.reserve_review(path, row)
        with registry.lock(path) as locked:
            current = registry.rows(locked)[row['lane_id']]
            current['t3code']['startup_state'] = 'launching'
            registry.persist(locked, [current])
        try:
            receipt = self.call('delegate_task', arguments)
        except (ValueError, OSError) as error:
            receipt = dict(error=str(error))  # Unknown；launching 保留原 request，禁止重发。
        with registry.lock(path) as locked:
            current = registry.rows(locked)[row['lane_id']]
            current['t3code']['receipt'] = receipt
            current['t3code'].update(task_id=receipt.get('taskId'),child_thread_id=receipt.get('childThreadId'),link=receipt.get('link'))
            current['t3code']['startup_state'] = 'received' if receipt.get('taskId') else 'launching'
            current['state'] = 'running'
            registry.persist(locked, [current])
        return self.recover(path, row['lane_id'])

    def recover(self, path, lane):
        row, _ = registry.read(path, lane)
        plan = registry.load_review_plan(path, lane, row['review_plan']['request_id'])
        overlay = row['t3code']
        registry.verify_review_packet(plan, overlay['review_packet'])
        action = 'stop' if row.get('state') in {'cancelled','consumed','closed','failed'} else 'inspect_original'
        return dict(action=action, row=row, review_packet=overlay['review_packet'])

    def fan_in(self, packet, axes, coordinates, ledger, round_no, p2_issues=None):
        """逐轴只读取绑定的 recentRuns；requested/thread.model/options 不证明执行。"""
        plan = packet['review_plan']
        registry.verify_review_packet(plan, packet)
        if set(axes) != set(plan['required_axes']) or set(coordinates) - set(axes):
            raise ValueError('result/coordinates must belong to required axes')
        if len({(c['thread_id'], c['run_id']) for c in coordinates.values()}) != len(coordinates):
            raise ValueError('each axis requires independent native run coordinates')
        readbacks = {}
        for axis, coordinate in coordinates.items():
            read = self.call('t3_thread_read', dict(threadId=coordinate['thread_id'], runLimit=50))
            if read['thread']['threadId'] != coordinate['thread_id']:
                raise ValueError('axis native coordinate mismatch')
            recent = next((r for r in read.get('recentRuns', []) if r['runId'] == coordinate['run_id']), None)
            # 目录 schema 未提供 applied effort；必须保持 Unknown，不读 requested options。
            provider = (recent or {}).get('providerInstanceId')
            agent = next((a for a, (p, _) in TARGETS.items() if p == provider), provider)
            readbacks[axis] = dict(source='native_readback', identity=dict(agent=agent,
                model=(recent or {}).get('executedModel')), applied_effort=None, raw=read,
                coordinate=coordinate)
        return run(dict(round=round_no, axes=axes, review_packet=packet, native_readbacks=readbacks, p2_issues=p2_issues or []), ledger)


def main():
    if sys.stdin.isatty():
        import termios
        settings = termios.tcgetattr(sys.stdin)
        settings[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(sys.stdin, termios.TCSANOW, settings)
    request = json.loads(sys.stdin.readline())
    adapter = ReviewDispatch(stdio_call)
    action = request.pop('action')
    if action == 'prepare':
        context = prepare_round(read_ledger(request.pop('ledger')), **request.pop('round'))
        result = adapter.prepare(request['config'], context)
    elif action in {'dispatch', 'recover', 'fan_in'}:
        result = getattr(adapter, action)(**request)
    else:
        raise ValueError('unknown review action')
    print(json.dumps(dict(result=result)), flush=True)


if __name__ == '__main__':
    main()
