"""Orca 同 Task replacement Adapter；共享 Registry 是唯一 intent/预算 owner。

仅对本 runtime 已有精确动态 launch 读回的同 agent/model effort 请求开放。
"""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline/scripts'))
import lane_registry as registry
from replacement import decide


class NativeError(ValueError):
    def __init__(self, envelope):
        super().__init__('native request rejected; inspect original request')
        self.envelope = envelope


class NativeReplacement:
    def __init__(self, executable, runtime_id, *, selected_dispatch=None, read_cli=None):
        self.executable = str(Path(executable).resolve())
        self.runtime_id = runtime_id
        self.selected_dispatch = selected_dispatch
        self.read_cli = read_cli or self._cli

    def _cli(self, *args):
        reply = subprocess.run([self.executable, *args, '--json', *(['--full'] if args[0] == 'orchestration' else [])],
                               capture_output=True, text=True, timeout=45)
        # 错误 envelope 也解析；失败不会变成 absent。
        value = json.loads(reply.stdout)
        if reply.returncode or value.get('ok') is not True:
            raise NativeError(value)
        return value

    def read(self, *args):
        value = self.read_cli(*args)
        if (value.get('ok') is not True or value.get('_meta', {}).get('runtimeId') != self.runtime_id
                or not isinstance(value.get('result'), dict)):
            raise ValueError('native runtime/result identity Unknown')
        return value['result']

    def reconcile(self, row):
        intent = row['replacement_intent']
        request = intent.get('native_request', {})
        saved = intent.get('receipt', {})
        # request_id 是 Orca mutation UUID，不能拿共享 lane_id 冒充。
        rid = saved.get('native_request_id')
        if not rid or saved.get('native_request') != request or saved.get('request_id') != row['lane_id']:
            return dict(status='unknown', gap='original native request binding Unknown; no resend')
        observed = self.read('orchestration', 'request-show', '--request', rid)
        if observed.get('requestId') != rid:
            raise ValueError('request identity mismatch')
        receipt = dict(saved, request_show=observed)
        if observed.get('state') in {'pending', 'absent'}:
            # 此入口只对账。pending 的 join 需要原进程退出及精确版本合同，不能猜。
            return dict(status='unknown', receipt=receipt, gap=observed['state']+'; inspect original request')
        if observed.get('state') != 'completed' or observed.get('method') != 'orchestration.workerStart':
            return dict(status='unknown', receipt=receipt, gap='request outcome/method Unknown')
        native = observed.get('receipt', {})
        if (native.get('mutation', {}).get('requestId') != rid
                or native.get('runId') != request.get('run_id')
                or native.get('taskId') != request.get('task_id') or not native.get('dispatchId')):
            raise ValueError('completed receipt lineage mismatch')
        target = {k: row[k] for k in ('agent', 'model', 'effort')}
        show = self.read('orchestration', 'worker-show', '--dispatch', native['dispatchId'])
        dispatch, worker = show['dispatch'], show['worker']
        launch = worker.get('startOptions', {}).get('launch', {})
        old_count = request.get('failure_count')
        count = dispatch.get('failureCount')
        if (dispatch.get('id') != native['dispatchId']
                or dispatch.get('runId') != request['run_id']
                or dispatch.get('taskId') != request['task_id']
                or dispatch.get('retryOfDispatchId') != request.get('retry_of')
                or dispatch.get('hostScope', {}).get('hostId') != request.get('execution_host')
                or worker.get('dispatchId') != dispatch['id']
                or worker.get('worktreeId') != request.get('worktree_id')
                or type(old_count) is not int or not 0 <= old_count < 3
                or type(count) is not int or not old_count <= count <= old_count + 1
                or launch.get('requested') != target or launch.get('effective') != target
                or native.get('launch', {}).get('requested') != target
                or native.get('launch', {}).get('effective') != target):
            raise ValueError('same Task retry/readback/selected lineage mismatch')
        receipt.update(native=native, worker_show=show, requested=target, effective=launch['effective'],
                       actual_model='Unknown', runtime_thinking='Unknown', applied_effort='Unknown')
        # completed request 也可能是明确失败的 worker-start，不能当成功启动。
        state = native.get('state')
        if state == 'failed' and worker.get('state') == 'failed':
            return dict(status='failed', receipt=receipt)
        if state != 'ready':
            return dict(status='unknown', receipt=receipt, gap='startup acceptance Unknown')
        return dict(status='completed', receipt=receipt)

    def coordinator(self, run_id):
        caller = os.environ.get('ORCA_TERMINAL_HANDLE')
        if not caller:
            raise ValueError('native coordinator caller missing; no impersonation')
        run = self.read('orchestration', 'run-show', '--id', run_id)['run']
        terminal = self.read('terminal', 'show', '--terminal', caller)['terminal']
        if (run.get('id') != run_id or run.get('coordinator_handle') != caller
                or terminal.get('handle') != caller or terminal.get('executionHostId') != 'local'
                or terminal.get('connected') is not True):
            raise ValueError('native coordinator identity mismatch')

    def observe(self, source):
        if source.get('runtime') != 'orca':
            raise ValueError('transport identity mismatch')
        identity = source['orca']
        self.coordinator(identity['run_id'])
        if identity.get('mutation') is not None:
            raise ValueError('original mutation unresolved; inspect original request')
        show = self.read('orchestration', 'worker-show', '--dispatch', identity['dispatch_id'])
        fleet = self.read('orchestration', 'worker-list', '--run', identity['run_id'])
        dispatch, worker = show['dispatch'], show['worker']
        wt = self.read('worktree', 'show', '--worktree', identity['worktree_selector'])['worktree']
        resource = show.get('terminalResource', {})
        projection = show['projection']
        old = {k: source[k] for k in ('agent', 'model', 'effort')}
        launch = worker.get('startOptions', {}).get('launch', {})
        count = dispatch.get('failureCount')
        if (dispatch.get('id') != identity['dispatch_id'] or dispatch.get('runId') != identity['run_id']
                or dispatch.get('taskId') != identity['task_id']
                or dispatch.get('assigneeHandle') != identity['terminal_handle']
                or worker.get('dispatchId') != identity['dispatch_id']
                or worker.get('agentTerminalHandle') != identity['terminal_handle']
                or dispatch.get('hostScope', {}).get('hostId') != identity['execution_host']
                or identity['execution_host'] != 'local'
                or worker.get('worktreeId') != wt.get('id')
                or wt.get('path') != source['worktree']
                or wt.get('branch') not in (source['branch'], 'refs/heads/'+source['branch'])
                or worker.get('startOptions', {}).get('agent') != source['agent']
                or launch.get('requested') != old or launch.get('effective') != old
                or projection.get('dispatchId') != identity['dispatch_id']
                or projection.get('runId') != identity['run_id'] or projection.get('taskId') != identity['task_id']
                or projection.get('host', {}).get('id') != identity['execution_host']
                or projection.get('liveness', {}).get('verdict') != 'exited'
                or resource.get('terminalHandle') != identity['terminal_handle']
                or resource.get('worktreeId') != wt['id']
                or resource.get('ownerDispatchId') != identity['dispatch_id']
                or worker.get('state') not in {'failed', 'stopped'}
                or type(count) is not int or not 0 <= count < 3
                or fleet.get('page', {}).get('hasMore') is not False):
            raise ValueError('old identity/writer/native breaker Unknown or blocked')
        matches = [w for w in fleet['workers'] if w.get('dispatchId') == identity['dispatch_id']]
        if (len(matches) != 1 or matches[0].get('workerState') != worker['state']
                or matches[0].get('taskId') != identity['task_id']
                or matches[0].get('agentTerminalHandle') != identity['terminal_handle']
                or matches[0].get('resource', {}).get('ownerDispatchId') != identity['dispatch_id']):
            raise ValueError('fleet source identity mismatch')
        for other in fleet['workers']:
            if other.get('runId') != identity['run_id']:
                raise ValueError('fleet Run mismatch')
            if (other.get('resource', {}).get('worktreeId') == wt['id']
                    and other.get('projection', {}).get('liveness', {}).get('verdict') != 'exited'):
                raise ValueError('Execution Worktree writer active/Unknown')
        # previous native retry 身份必须与持久 attempt 历史一致，不重置计数。
        previous = source.get('replacement_intent', {}).get('native_request', {})
        index = identity.get('attempt_index')
        if (type(index) is not int or index < 0
                or (index == 0 and dispatch.get('retryOfDispatchId') is not None)
                or (index > 0 and (dispatch.get('retryOfDispatchId') != previous.get('retry_of')
                    or previous.get('attempt_index') != index))):
            raise ValueError('previous attempt continuity Unknown')
        ancestors = set()
        parent = dispatch.get('retryOfDispatchId')
        while parent is not None:
            if parent in ancestors or len(ancestors) >= index:
                raise ValueError('native retry history cycle/index conflict')
            ancestors.add(parent)
            older = self.read('orchestration', 'worker-show', '--dispatch', parent)['dispatch']
            if (older.get('id') != parent or older.get('runId') != identity['run_id']
                    or older.get('taskId') != identity['task_id']):
                raise ValueError('native ancestor lineage mismatch')
            parent = older.get('retryOfDispatchId')
        if len(ancestors) != index:
            raise ValueError('native attempt history/index mismatch')
        if any(w.get('taskId') == identity['task_id'] and w.get('dispatchId') not in ancestors | {identity['dispatch_id']}
               for w in fleet['workers']):
            raise ValueError('Task has another attempt; do not branch from stale Dispatch')
        return dict(writer='exited', identity='match', capability='verified', gate='allowed')

    def target(self, source, selected):
        # 当前只放行同 agent/model 的 effort 变化；其他变化保留 blocked。
        if (selected['agent'] != source['agent'] or selected['model'] != source['model']
                or not self.selected_dispatch):
            raise ValueError('selected native support Unknown')
        proof = self.read('orchestration', 'worker-show', '--dispatch', self.selected_dispatch)
        launch = proof['worker'].get('startOptions', {}).get('launch', {})
        if (proof.get('dispatch', {}).get('id') != self.selected_dispatch
                or proof.get('dispatch', {}).get('hostScope', {}).get('hostId') != source['orca']['execution_host']
                or proof['worker'].get('dispatchId') != self.selected_dispatch
                or launch.get('requested') != selected or launch.get('effective') != selected
                or proof['worker'].get('stage') not in {'input_accepted', 'settled'}):
            raise ValueError('selected exact native readback missing')

    def claim(self, path, source_id, revision, failure_id, category):
        source, _ = registry.read(path, source_id)
        choice = decide(source, category, 0)
        if choice.get('action') != 'replace':
            raise ValueError(choice['action'])
        selected = {k: choice[k] for k in ('agent', 'model', 'effort')}
        self.target(source, selected)
        return registry.claim(path, source_id, revision, failure_id, category, self.observe)

    def execute(self, path, lane):
        row, _ = registry.read(path, lane)
        # 身份先从真实原生 caller 核对，外部 T3 不可转发伪 requester。
        if not os.environ.get('ORCA_TERMINAL_HANDLE'):
            raise ValueError('native coordinator caller missing; no impersonation')
        source, _ = registry.read(path, row['replacement_of'])
        self.coordinator(source['orca']['run_id'])
        if row['replacement_intent']['status'] == 'launching':
            return self.recover(path, lane)
        if row['replacement_intent']['status'] != 'accepted':
            return row
        self.observe(source)
        selected = {k: row[k] for k in ('agent', 'model', 'effort')}
        self.target(source, selected)
        identity = source['orca']
        show = self.read('orchestration', 'worker-show', '--dispatch', identity['dispatch_id'])
        request = dict(run_id=identity['run_id'], task_id=identity['task_id'], retry_of=identity['dispatch_id'],
                       execution_host=identity['execution_host'], worktree_id=show['worker']['worktreeId'],
                       worktree_selector=identity['worktree_selector'], failure_count=show['dispatch']['failureCount'],
                       attempt_index=identity['attempt_index']+1, selected=selected)
        registry.bind_request(path, lane, request, self.observe)
        def start(claimed):
            saved = dict(request_id=lane, native_request=request)
            try:
                native = self.read('orchestration', 'worker-start', '--task', request['task_id'],
                    '--run', request['run_id'], '--retry-of', request['retry_of'],
                    '--worktree', request['worktree_selector'], '--agent', selected['agent'],
                    '--model', selected['model'], '--effort', selected['effort'])
                saved['native_request_id'] = native['mutation']['requestId']
                saved['native'] = native
                claimed['replacement_intent']['receipt'] = saved
                return self.reconcile(claimed)
            except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
                envelope = getattr(error, 'envelope', None)
                if envelope:
                    saved['native_error'] = envelope
                    rid = envelope.get('error', {}).get('data', {}).get('orchestrationRequestId')
                    if rid:
                        saved['native_request_id'] = rid
                # 响应 UUID 未返回时保留 launching；不猜 absent，不生成新请求。
                return dict(status='unknown', receipt=saved, gap=str(error))
        row = registry.launch(path, lane, self.observe, start)
        return self.publish(path, row, source)

    def publish(self, path, row, source):
        intent = row['replacement_intent']
        saved = intent.get('receipt', {})
        if intent['status'] not in {'completed', 'failed'} or not saved.get('worker_show'):
            return row
        native = saved['worker_show']
        identity = dict(source['orca'])
        identity.update(dispatch_id=native['dispatch']['id'], terminal_handle=native['worker']['agentTerminalHandle'],
                        attempt_index=intent['native_request']['attempt_index'], mutation=None)
        row['orca'] = identity
        registry.write(path, row)
        return registry.read(path, row['lane_id'])[0]

    def recover(self, path, lane):
        row, _ = registry.read(path, lane)
        if row.get('runtime') != 'orca':
            raise ValueError('transport identity mismatch')
        recovered = registry.recover_launch(path, lane, self.reconcile)
        if 'attempt_index' in recovered['replacement_intent'].get('native_request', {}):
            source, _ = registry.read(path, recovered['replacement_of'])
            return self.publish(path, recovered, source)
        return recovered


def main():
    if len(sys.argv) == 6 and sys.argv[1] == 'recover':
        result = NativeReplacement(sys.argv[4], sys.argv[5]).recover(Path(sys.argv[2]), sys.argv[3])
    elif len(sys.argv) == 2:
        request = json.loads(Path(sys.argv[1]).read_text())
        adapter = NativeReplacement(request['executable'], request['runtime_id'],
                                    selected_dispatch=request.get('selected_dispatch'))
        path = Path(request['registry'])
        if request['action'] == 'claim':
            result = adapter.claim(path, request['source'], request['revision'], request['failure_id'], request['category'])
        elif request['action'] == 'execute':
            result = adapter.execute(path, request['lane'])
        elif request['action'] == 'recover':
            result = adapter.recover(path, request['lane'])
        else:
            raise ValueError('unknown action')
    else:
        raise SystemExit('Usage: native_replacement.py <request.json> | recover <registry> <lane> <executable> <runtime-id>')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
