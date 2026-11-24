"""T3 生产 Adapter；工具 I/O 由当前原生宿主经 JSON lines 转发。

唯一 intent/receipt 归 canonical Registry。无原回执时不重发 delegate。
"""
import json
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline/scripts'))
import lane_registry as registry

TARGETS = {
    'codex': ('codex', 'reasoningEffort'),
    'claude': ('claudeAgent', 'effort'),
    'pi': ('pi', 'thinking'),
    'antigravity': ('antigravity', 'thought_level'),
}
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted', 'rolled_back'}


class NativeReplacement:
    def __init__(self, call_tool, capabilities):
        self.call = call_tool
        self.capabilities = capabilities

    def target(self, row):
        provider, option = TARGETS[row['agent']]
        caps = self.capabilities
        p = next((p for p in caps['providers'] if p['providerInstanceId'] == provider), {})
        model = next((m for m in p.get('models', []) if m['id'] == row['model']), {})
        opt = next((o for o in model.get('options', []) if o['id'] == option), {})
        if (not p.get('canRunChildTask') or row['effort'] not in opt.get('values', [])
                or (provider != caps['inheritedProviderInstanceId'] and not p.get('canRunCrossProviderChildTask'))):
            raise ValueError('Unknown: exact native target unavailable')
        return dict(providerInstanceId=provider, model=row['model'], options={option: row['effort']})

    def observe(self, source):
        self.target(source['_selected'])
        overlay = source.get('t3code', {})
        receipt = source.get('replacement_intent', {}).get('receipt', {}).get('native', {})
        task_id = receipt.get('taskId') or overlay.get('task_id')
        thread_id = receipt.get('childThreadId') or overlay.get('child_thread_id')
        if not task_id or not thread_id:
            raise ValueError('Unknown: source native task/thread identity missing')
        task = self.call('task_status', dict(taskId=task_id))
        thread = self.call('t3_thread_read', dict(threadId=thread_id, limit=1))['thread']
        if (task.get('childThreadId') != thread_id or task.get('taskId') != task_id
                or thread.get('threadId') != thread_id
                or thread.get('parentThreadId') != self.capabilities['parentThreadId']
                or thread.get('relationshipToParent') != 'subagent'
                or task.get('providerInstanceId') != TARGETS[source['agent']][0]
                or thread.get('providerInstanceId') != TARGETS[source['agent']][0]
                or task.get('model') != source['model'] or thread.get('model') != source['model']
                or task.get('status') not in TERMINAL or task.get('hasPendingChildRuns') is not False
                or thread.get('activeRunId') is not None or thread.get('status') not in TERMINAL):
            raise ValueError('Unknown: original writer/identity/native gate unresolved')
        return dict(writer='exited', identity='match', capability='verified', gate='allowed')

    @staticmethod
    def common_dir(path):
        result = subprocess.run(['git', '-C', str(path), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                capture_output=True, text=True, check=True)
        return Path(result.stdout.strip()).resolve()

    def reconcile(self, row):
        intent = row['replacement_intent']
        request = intent['native_request']
        saved = intent.get('receipt', {})
        if (request.get('coordinator_thread_id') != self.capabilities['parentThreadId']
                or saved.get('request_id') != row['lane_id'] or saved.get('native_request') != request):
            return dict(status='unknown', gap='Unknown: original receipt/request binding missing; no replay')
        native = saved.get('native', {})
        if not native.get('childThreadId') or not native.get('taskId'):
            return dict(status='unknown', receipt=saved, gap='Unknown: original native coordinates missing')
        read = self.call('t3_thread_read', dict(threadId=native['childThreadId'], limit=5))
        thread = read['thread']
        target = request['arguments']['target']
        if (thread.get('threadId') != native['childThreadId']
                or thread.get('parentThreadId') != request['coordinator_thread_id']
                or thread.get('relationshipToParent') != 'subagent'
                or thread.get('providerInstanceId') != target['providerInstanceId']
                or thread.get('model') != target['model'] or not thread.get('worktreePath')):
            return dict(status='unknown', receipt=saved, gap='Unknown: native startup identity mismatch')
        try:
            if self.common_dir(thread['worktreePath']) != self.common_dir(Path.cwd()):
                return dict(status='unknown', receipt=saved, gap='Unknown: worktree repository mismatch')
        except (OSError, subprocess.CalledProcessError):
            return dict(status='unknown', receipt=saved, gap='Unknown: worktree repository unavailable')
        # 配置 model 与独立 executedModel 分开；不从 options 倒推 applied effort。
        saved.update(startup_readback=read, executedModel=next((r.get('executedModel') for r in reversed(read.get('recentRuns', [])) if r.get('executedModel')), 'Unknown'),
                     runtime_thinking='Unknown', applied_effort='Unknown')
        if saved['executedModel'] not in {'Unknown', target['model']}:
            return dict(status='unknown', receipt=saved, gap='independent executed model mismatch')
        return dict(status='completed', receipt=saved)

    def publish_startup(self, path, row):
        """将同一 receipt 投影到既有 lifecycle 字段；重放只补投影，不重复启动。"""
        intent = row['replacement_intent']
        receipt = intent.get('receipt', {})
        if intent['status'] != 'completed' or not receipt.get('startup_readback'):
            return row
        thread = receipt['startup_readback']['thread']
        native = receipt['native']
        target = intent['native_request']['arguments']['target']
        row.update(worktree=thread['worktreePath'], t3code=dict(
            coordinator_thread_id=intent['native_request']['coordinator_thread_id'],
            coordinator_provider=self.capabilities['inheritedProviderInstanceId'],
            provider_instance_id=target['providerInstanceId'], effort_option=next(iter(target['options'])),
            client_request_id=row['lane_id'], task_id=native['taskId'], child_thread_id=native['childThreadId'],
            link=native.get('link'), t3_branch=thread.get('branch'), executed_model=receipt['executedModel']))
        previous, _ = registry.read(path, row['lane_id'])
        if previous != row:
            registry.write(path, row)
        return registry.read(path, row['lane_id'])[0]

    def execute(self, path, lane, task):
        row, _ = registry.read(path, lane)
        if row.get('runtime') != 't3-task':
            raise ValueError('native transport identity mismatch')
        intent = row['replacement_intent']
        if intent['status'] == 'launching':
            return self.publish_startup(path, registry.recover_launch(path, lane, self.reconcile))
        if intent['status'] != 'accepted':
            return self.publish_startup(path, row)
        request = dict(coordinator_thread_id=self.capabilities['parentThreadId'], arguments=dict(
            task=task, target=self.target(row), isolation='worktree', clientRequestId=lane,
            mode='async', role={'checks': 'test', 'commit': 'implementation', 'integration': 'implementation',
                                'verdict': 'review', 'artifact': 'research'}[row['output_mode']]))
        registry.bind_request(path, lane, request, self.observe)
        def start(claimed):
            # launching 在 I/O 前持久化；响应丢失保留原请求，不盲重放。
            try:
                native = self.call('delegate_task', request['arguments'])
            except (ValueError, OSError) as error:
                return dict(status='unknown', receipt=dict(request_id=lane, native_request=request,
                            requested=request['arguments']['target'], error=str(error)))
            saved = dict(request_id=lane, native_request=request, requested=request['arguments']['target'], native=native)
            claimed['replacement_intent']['receipt'] = saved
            # async next 先交还宿主，完成唤醒后再独立读回，不轮询。
            if native.get('next'):
                return dict(status='unknown', receipt=saved)
            try:
                return self.reconcile(claimed)
            except (ValueError, OSError, KeyError) as error:
                return dict(status='unknown', receipt=saved, gap=str(error))
        return self.publish_startup(path, registry.launch(path, lane, self.observe, start))


def stdio_call(name, arguments):
    print(json.dumps(dict(tool=name, arguments=arguments)), flush=True)
    reply = json.loads(sys.stdin.readline())
    if 'error' in reply:
        raise ValueError(reply['error'])
    return reply['result']


def main():
    if sys.stdin.isatty():
        import termios
        settings = termios.tcgetattr(sys.stdin)
        settings[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(sys.stdin, termios.TCSANOW, settings)
    request = json.loads(sys.stdin.readline())
    adapter = NativeReplacement(stdio_call, request['capabilities'])
    path = Path(request['registry'])
    if request['action'] == 'claim':
        result = registry.claim(path, request['source'], request['revision'], request['failure_id'], request['category'], adapter.observe)
    else:
        result = adapter.execute(path, request['lane'], request.get('task', ''))
    print(json.dumps(dict(result=result)), flush=True)


if __name__ == '__main__':
    main()
