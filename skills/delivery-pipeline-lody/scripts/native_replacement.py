"""Lody 0.112 原生 MCP 调用方；唯一持久状态仍归 canonical Registry。

运行于原 Lody requester 的宿主，JSON lines 只转发公开工具。T3 不可伪装该身份。
"""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline/scripts'))
import lane_registry as registry


def common_dir(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--path-format=absolute',
                                    '--git-common-dir'], text=True).strip()


class NativeReplacement:
    def __init__(self, call_tool, binding):
        self.call = call_tool
        self.binding = binding

    def current(self):
        value = self.call('lody_session_create_options', {})
        current = value['current']
        if any(current.get(k) != self.binding[k] for k in ('sessionId', 'workspaceId', 'machineId')):
            raise ValueError('Unknown: original requester binding mismatch')
        return value

    def target(self, row):
        options = self.current()
        machine = self.binding['machineId']
        project = self.binding['projectId']
        configs = self.call('lody_session_create_options', dict(machineId=machine,
                            agentConfigQuery=row['agent'], localProjectQuery=project))
        if configs['current'] != options['current']:
            raise ValueError('Unknown: requester changed')
        matches = [c for c in configs['agentConfigs'] if c['agentType'] == row['agent']
                   and c['machineId'] == machine and c.get('availability', {}).get('state') != 'unavailable']
        if len(matches) != 1:
            raise ValueError('Unknown: exact agent config ambiguous/unavailable')
        config = matches[0]
        run = config['runConfig']
        model = next((m for m in run.get('models', []) if m['id'] == row['model']), {})
        efforts = model.get('reasoningEffortValues')
        if efforts is None and run.get('measuredForModelId') == row['model']:
            efforts = run.get('reasoningEffortValues', [])
        if not model or row['effort'] not in (efforts or []):
            raise ValueError('Unknown: exact model/effort unsupported')
        projects = [p for p in configs['localProjects'] if p['id'] == project and p['machineId'] == machine and p['isGit'] is True]
        if (len(projects) != 1 or common_dir(projects[0]['rootPath']) != common_dir(self.binding['sourceRepo'])
                or not any(m['id'] == machine and m.get('online') is True and m.get('canUse') is True for m in configs['machines'])):
            raise ValueError('Unknown: local project/machine unavailable')
        return dict(machineId=machine, agentConfigId=config['id'], modelId=row['model'],
                    reasoningEffort=row['effort'], useCurrentSessionAsParent=False,
                    workContext=dict(kind='local', projectId=project, worktree=True))

    def status(self, session):
        items = self.call('lody_session_status_many', dict(sessionIds=[session]))['items']
        if len(items) != 1 or items[0].get('sessionId') != session or items[0].get('ok') is not True:
            raise ValueError('Unknown: session status unavailable')
        return items[0]['value']

    def observe(self, source):
        self.target(source)
        overlay = source['lody']
        if overlay['coordinator_session_id'] != self.binding['sessionId']:
            raise ValueError('Unknown: original operation requester mismatch')
        op = self.call('lody_operation_get', dict(operationId=overlay['operation_id']))
        # 成功完成的目标 turn + fresh 无工作状态，才正面排除 writer。
        # cancelled/error/TARGET_TIMEOUT 绝不由 finished 推导退出。
        items = op.get('completion', {}).get('value', {}).get('items', [])
        if (op.get('id') != overlay['operation_id'] or op.get('state') != 'finished'
                or op.get('completion', {}).get('type') != 'result' or len(items) != 1
                or items[0].get('status') != 'succeeded'
                or items[0].get('target', {}).get('sessionId') != overlay['session_id']):
            raise ValueError('Unknown: positive original turn completion missing')
        value = self.status(overlay['session_id'])
        execution = value['execution']
        if (value['summary']['id'] != overlay['session_id']
                or value['summary']['machineId'] != self.binding['machineId']
                or value['observation']['quality'] != 'fresh' or value['machine']['state'] != 'online'
                or execution.get('executionState') != 'idle' or execution.get('phase') != 'idle'
                or execution.get('activeTurnId') or execution.get('queuedTurnCount') != 0):
            raise ValueError('Unknown: writer exit unproven')
        return dict(writer='exited', identity='match', capability='verified', gate='allowed')

    def reconcile(self, row):
        self.current()
        intent = row['replacement_intent']
        request = intent['native_request']
        if request['binding'] != self.binding:
            raise ValueError('Unknown: recovery requires original requester')
        saved = intent.get('receipt', {})
        # 响应丢失只 inspect 原键；NOT_FOUND/异常保留 launching，不调用 create。
        operation = saved.get('native', {}).get('id', row['lane_id'])
        try:
            snapshot = self.call('lody_operation_get', dict(operationId=operation))
        except (ValueError, OSError) as error:
            return dict(status='unknown', receipt={**saved, 'gap': str(error)})
        if snapshot.get('id') != operation or snapshot.get('kind') != 'session_create':
            return dict(status='unknown', receipt={**saved, 'gap': 'Unknown: operation identity mismatch'})
        saved.update(native=snapshot, requested=request['arguments'], executedModel='Unknown',
                     runtime_thinking='Unknown', applied_effort='Unknown', nonce='Unknown')
        # receipt 保存不等于启动/模型执行验收；以实际 target 绑定 lifecycle。
        items = snapshot.get('items', snapshot.get('completion', {}).get('value', {}).get('items', []))
        if len(items) == 1 and items[0].get('target', {}).get('sessionId'):
            saved['session_id'] = items[0]['target']['sessionId']
        return dict(status='unknown', receipt=saved)

    def execute(self, path, lane, prompt):
        row, _ = registry.read(path, lane)
        if row['runtime'] != 'lody-session':
            raise ValueError('native transport identity mismatch')
        intent = row['replacement_intent']
        if intent['status'] == 'launching':
            return registry.recover_launch(path, lane, self.reconcile)
        if intent['status'] != 'accepted':
            return row
        request = dict(binding=self.binding, arguments=dict(operationId=lane, prompt=prompt, **self.target(row)))
        registry.bind_request(path, lane, request, self.observe)
        def start(claimed):
            saved = dict(requested=request['arguments'])
            try:
                # 原生可采用另一个 operation id，必须立即保留，不能覆盖成 lane_id。
                saved['native'] = self.call('lody_session_create', request['arguments'])
            except (ValueError, OSError) as error:
                saved['gap'] = str(error)
            return dict(status='unknown', receipt=saved)
        return registry.launch(path, lane, self.observe, start)


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
    adapter = NativeReplacement(stdio_call, request['binding'])
    path = Path(request['registry'])
    if request['action'] == 'claim':
        result = registry.claim(path, request['source'], request['revision'], request['failure_id'], request['category'], adapter.observe)
    else:
        result = adapter.execute(path, request['lane'], request.get('prompt', ''))
    print(json.dumps(dict(result=result)), flush=True)


if __name__ == '__main__':
    main()
