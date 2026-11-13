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

    def base_branch(self, row):
        # canonical claim 继承 worktree/base_commit，但删除原生 overlay。
        # 公开 local 合同只承诺 branch；不把 SHA 或显示名当作可用 base。
        try:
            worktree = row['worktree']
            base = row['base_commit']
            if not base or common_dir(worktree) != common_dir(self.binding['sourceRepo']):
                raise ValueError('source common dir/base missing')
            def git(*args):
                return subprocess.check_output(['git', '-C', worktree, *args], text=True,
                                               stderr=subprocess.PIPE).strip()
            branch = git('symbolic-ref', '--quiet', '--short', 'HEAD')
            head = git('rev-parse', '--verify', 'HEAD^{commit}')
            resolved = git('rev-parse', '--verify', 'refs/heads/' + branch + '^{commit}')
            if head != base or resolved != base:
                raise ValueError('source branch no longer equals frozen commit')
            return branch
        except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
            raise ValueError('Unknown: frozen base branch unverified') from error

    def target(self, row):
        branch = self.base_branch(row)
        options = self.current()
        context = options['current'].get('workContext', {})
        if (context.get('kind') != 'local' or context.get('projectId') != self.binding['projectId']
                or common_dir(context.get('rootPath', '')) != common_dir(self.binding['sourceRepo'])):
            raise ValueError('Unknown: requester source project mismatch')
        machine = self.binding['machineId']
        project = self.binding['projectId']
        configs = self.call('lody_session_create_options', dict(machineId=machine,
                            agentConfigQuery=row['agent'], localProjectQuery=project))
        if configs['current'] != options['current']:
            raise ValueError('Unknown: requester changed')
        # 0.112 create_options 的正常 discovery summary 省略 availability；
        # 显式状态仍须 available，不能将 unknown/quota 当作可启动。
        matches = [c for c in configs['agentConfigs'] if c['agentType'] == row['agent']
                   and c['machineId'] == machine
                   and ('availability' not in c or c['availability'].get('state') == 'available')]
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
                    workContext=dict(kind='local', projectId=project, worktree=True, branch=branch))

    def status(self, session):
        items = self.call('lody_session_status_many', dict(sessionIds=[session]))['items']
        if len(items) != 1 or items[0].get('sessionId') != session or items[0].get('ok') is not True:
            raise ValueError('Unknown: session status unavailable')
        return items[0]['value']

    def observe(self, source):
        self.target(source['_selected'])
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
        # receipt/配置请求不等于模型执行；public history 仅为响应证据。
        try:
            items = (snapshot.get('completion', {}).get('value', {}).get('items', [])
                     if snapshot.get('state') == 'finished' else snapshot.get('items', []))
            if len(items) != 1:
                raise ValueError('Unknown: unique native target missing')
            item = items[0]
            target = item.get('target', {})
            session = target.get('sessionId')
            if not session or not target.get('userTurnId'):
                raise ValueError('Unknown: native target turn missing')
            saved['session_id'] = session
            value = self.status(session)
            saved['startup'] = value
            summary = value['summary']
            expected = request['arguments']
            context = summary.get('executionContext', {})
            if (summary.get('id') != session or summary.get('machineId') != expected['machineId']
                    or summary.get('agentConfigId') != expected['agentConfigId']
                    or summary.get('openedBySessionId') != self.binding['sessionId']
                    or context.get('kind') != 'local' or context.get('projectId') != self.binding['projectId']
                    or context.get('worktree') is not True or summary.get('parentSessionId')
                    or value['machine']['state'] != 'online' or value['observation']['quality'] != 'fresh'):
                raise ValueError('Unknown: startup identity/worktree/freshness mismatch')
            worktrees = subprocess.check_output(['git', '-C', self.binding['sourceRepo'],
                                                'worktree', 'list', '--porcelain'], text=True)
            matches = []
            for block in worktrees.strip().split('\n\n'):
                fields = dict(line.split(' ', 1) for line in block.splitlines() if ' ' in line)
                if fields.get('branch') == 'refs/heads/' + summary.get('branch', ''):
                    matches.append(fields['worktree'])
            if len(matches) != 1 or common_dir(matches[0]) != common_dir(self.binding['sourceRepo']):
                raise ValueError('Unknown: native branch worktree unavailable')
            if Path(matches[0]).resolve() == Path(self.binding['sourceRepo']).resolve():
                raise ValueError('Unknown: target shares source directory')
            base = row.get('base_commit')
            if not base or subprocess.run(['git', '-C', matches[0], 'merge-base', '--is-ancestor', base, 'HEAD'],
                                         capture_output=True).returncode:
                raise ValueError('Unknown: frozen base unverified')
            saved['worktree'] = matches[0]
            saved.pop('gap', None)
            execution = value['execution']
            if execution.get('executionState') == 'busy' and execution.get('activeTurnId') == target['userTurnId']:
                return dict(status='completed', receipt=saved)
            if (snapshot.get('state') != 'finished' or snapshot.get('completion', {}).get('type') != 'result'
                    or item.get('status') != 'succeeded' or not item.get('assistantTurnId')
                    or execution.get('executionState') != 'idle' or execution.get('phase') != 'idle'
                    or execution.get('activeTurnId') or execution.get('queuedTurnCount') != 0):
                raise ValueError('Unknown: target startup/outcome unresolved')
            history = self.call('lody_session_history', dict(sessionId=session))
            saved['history'] = history
            if (history.get('sessionId') != session or not any(
                    e.get('id') == item['assistantTurnId'] and e.get('role') == 'assistant'
                    and not e.get('isError') and not e.get('truncated')
                    for e in history.get('items', []))):
                raise ValueError('Unknown: exact completed assistant turn unavailable')
            return dict(status='completed', receipt=saved)
        except (ValueError, OSError, KeyError) as error:
            saved['gap'] = str(error)
            return dict(status='unknown', receipt=saved)

    def project(self, path, row):
        # canonical finish 已提交状态；投影可在崩溃后幂等补齐，不再原生 create。
        if row['replacement_intent']['status'] != 'completed':
            return row
        receipt = row['replacement_intent']['receipt']
        request = row['replacement_intent']['native_request']['arguments']
        overlay = dict(workspace_id=self.binding['workspaceId'], machine_id=self.binding['machineId'],
                       project_id=self.binding['projectId'], coordinator_session_id=self.binding['sessionId'],
                       agent_config_id=request['agentConfigId'], operation_id=receipt['native']['id'],
                       session_id=receipt['session_id'],
                       session_link=f"lody://session/{receipt['session_id']}?workspace={self.binding['workspaceId']}",
                       lody_branch=receipt['startup']['summary']['branch'])
        if row.get('lody') != overlay or row.get('worktree') != receipt['worktree']:
            row.update(lody=overlay, worktree=receipt['worktree'])
            registry.write(path, row)
        return registry.read(path, row['lane_id'])[0]

    def execute(self, path, lane, prompt):
        row, _ = registry.read(path, lane)
        if row['runtime'] != 'lody-session':
            raise ValueError('native transport identity mismatch')
        intent = row['replacement_intent']
        if intent.get('native_request', {}).get('binding', self.binding) != self.binding:
            raise ValueError('Unknown: original requester binding mismatch')
        if intent['status'] == 'launching':
            return self.project(path, registry.recover_launch(path, lane, self.reconcile))
        if intent['status'] != 'accepted':
            return self.project(path, row)
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
    request = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) == 3 and sys.argv[1] == '--request' else json.loads(sys.stdin.readline())
    adapter = NativeReplacement(stdio_call, request['binding'])
    path = Path(request['registry']) if 'registry' in request else None
    if request['action'] == 'inspect':
        adapter.current()
        snapshot = adapter.call('lody_operation_get', dict(operationId=request['operationId']))
        items = snapshot.get('completion', {}).get('value', {}).get('items', []) if snapshot.get('state') == 'finished' else snapshot.get('items', [])
        targets = [i['target']['sessionId'] for i in items if i.get('target', {}).get('sessionId')]
        result = dict(operation=snapshot, targets=[dict(status=adapter.status(t), history=adapter.call('lody_session_history', dict(sessionId=t))) for t in targets])
    elif request['action'] == 'claim':
        result = registry.claim(path, request['source'], request['revision'], request['failure_id'], request['category'], adapter.observe)
    else:
        result = adapter.execute(path, request['lane'], request.get('prompt', ''))
    print(json.dumps(dict(result=result)), flush=True)


if __name__ == '__main__':
    main()
