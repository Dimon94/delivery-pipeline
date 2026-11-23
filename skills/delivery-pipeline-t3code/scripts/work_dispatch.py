"""启动 T3 work lane。配置解析、Registry 与原生请求在同一入口。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from native_replacement import NativeReplacement, stdio_call
import lane_registry as registry

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline-setup/scripts'))
import model_config

OUTPUTS = {
    'planning': {'artifact': 'research'},
    'design': {'artifact': 'design', 'commit': 'implementation'},
    'frontend': {'commit': 'implementation'},
    'backend': {'commit': 'implementation'},
    'testing': {'checks': 'test'},
    'integration': {'integration': 'implementation'},
}
ROW_FIELDS = {'lane_id', 'work_item', 'role', 'output_mode', 'base_commit', 'map', 'ticket_url',
              'wave', 'merges', 'off_chain_reason'}
PACKET = Path(__file__).resolve().parent.parent / 'assets/T3CODE_ROLE_DISPATCH_PACKET.md'


class WorkDispatch:
    def __init__(self, call):
        self.call = call

    def dispatch(self, path, row, task, source, *, ticket_mode=None, map_mode=None, target_override=None):
        if set(row) - ROW_FIELDS or not all(row.get(key) for key in (
                'lane_id', 'work_item', 'role', 'output_mode', 'base_commit', 'map')):
            raise ValueError('work dispatch accepts only lane coordinates and work type')
        if not task.strip():
            raise ValueError('worker packet is empty')
        kind, output = row['role'], row['output_mode']
        role = OUTPUTS.get(kind, {}).get(output)
        if role is None:
            raise ValueError('unsupported work type/output mode; formal review uses review_dispatch.py')
        lane = row['lane_id']
        if lane in registry.rows(path):
            raise ValueError('lane already exists; inspect original request')
        config = model_config.load_document(model_config.cli_config_path())
        config_task = 'backend' if kind == 'integration' and kind not in config['work'] else kind
        plan = model_config.resolve_plan(config, config_task, ticket_mode=ticket_mode, map_mode=map_mode,
                                         output_mode=output)
        frozen = model_config.freeze_overlay(plan)
        caps = self.call('orchestrator_capabilities', dict(search=frozen['model']))
        parent = caps['parentThreadId']
        target = NativeReplacement(self.call, caps).target(frozen)
        repo = NativeReplacement.common_dir(source)
        status = self.call('t3_worktree_status', {})
        checkout = status['worktreePath'] if status.get('attached') else status['projectWorkspaceRoot']
        if not parent or any(NativeReplacement.common_dir(path) != repo
                             for path in (status['projectWorkspaceRoot'], checkout)):
            raise ValueError('dispatch unavailable: coordinator and source repository differ')
        branch = f"{frozen['agent']}/issue-{row['work_item']}" if output == 'commit' else None
        option, effort = next(iter(target['options'].items()))
        packet = (f'{task.rstrip()}\nRegistry：{path}\nWorker 合同：{PACKET}，读取 Worker 执行节\n'
                  f'Coordinator thread：{parent}（{caps["inheritedProviderInstanceId"]}）\n'
                  f'Worker target：{target["providerInstanceId"]} / {target["model"]} / {option}={effort}\n'
                  f'Base：{row["base_commit"]}；分支 {branch or "detached"}\n'
                  f'目标仓覆盖：{target_override or "none"}\n'
                  f'冻结执行计划：{json.dumps(frozen, ensure_ascii=False)}\n')
        arguments = dict(task=packet, title=f'map-{row["map"]} {kind} #{row["work_item"]}', target=target,
                         isolation='worktree', mode='async', clientRequestId=lane, role=role)
        overlay = dict(coordinator_thread_id=parent, coordinator_provider=caps['inheritedProviderInstanceId'],
                       provider_instance_id=target['providerInstanceId'], effort_option=option, client_request_id=lane,
                       common_dir=str(repo), native_request=arguments, work_dispatch=True, startup_state='launching',
                       startup_parent_thread_id=parent)
        row = {**row, **frozen, 'runtime': 't3-task', 'worktree': None, 'branch': branch,
               'state': 'created', 'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               't3code': overlay}
        registry.write(path, row, create=True)
        current, _ = registry.read(path, lane)
        model_config.verify_overlay(plan, {k: current[k] for k in frozen})
        if current['t3code'] != overlay:
            raise ValueError('native request readback mismatch')

        try:
            receipt = self.call('delegate_task', current['t3code']['native_request'])
        except (OSError, ValueError) as error:
            return self.update(path, lane, 'setup_blocked', startup_gap=str(error))
        current = self.update(path, lane, 'created', receipt=receipt, task_id=receipt.get('taskId'),
                              child_thread_id=receipt.get('childThreadId'), link=receipt.get('link'))
        if receipt.get('taskId') and receipt.get('childThreadId') is None and 'childThreadId' in receipt:
            current = self.update(path, lane, 'setup_blocked', startup_gap='linked environment outside transport')
            self.call('task_cancel', dict(taskId=receipt['taskId']))
            return current
        if receipt.get('next') and receipt.get('childThreadId'):
            return current
        return self.recover(path, lane)

    @staticmethod
    def update(path, lane, state, *, worktree=None, **overlay):
        with registry.lock(path) as path:
            row = registry.rows(path)[lane]
            if row['state'] not in {'created', 'setup_blocked'}:
                return row
            row['state'] = state
            row['t3code'].update(overlay)
            if worktree:
                row['worktree'] = worktree
            registry.persist(path, [row])
            return registry.read(path, lane)[0]

    def recover(self, path, lane):
        row, _ = registry.read(path, lane)
        t3 = row.get('t3code', {})
        if row.get('runtime') != 't3-task' or not t3.get('work_dispatch'):
            raise ValueError('work dispatch recovery requires its original registry intent')
        if row['state'] not in {'created', 'setup_blocked'}:
            return row
        if not t3.get('task_id') or not t3.get('child_thread_id'):
            return self.update(path, lane, 'setup_blocked', startup_gap='Unknown: original native coordinates missing')
        try:
            reply = self.call('t3_thread_read', dict(threadId=t3['child_thread_id'], limit=1, runLimit=5))
            thread = reply['thread']
            if (thread.get('threadId') != t3['child_thread_id']
                    or thread.get('parentThreadId') != t3['startup_parent_thread_id']
                    or thread.get('relationshipToParent') != 'subagent'
                    or thread.get('providerInstanceId') != t3['provider_instance_id']
                    or thread.get('model') != row['model'] or not thread.get('worktreePath')
                    or str(NativeReplacement.common_dir(thread['worktreePath'])) != t3['common_dir']):
                raise ValueError('native startup identity/worktree mismatch')
            models = {run['executedModel'] for run in reply.get('recentRuns', []) if run.get('executedModel')}
            if models - {row['model']}:
                raise ValueError(f'independent executed model mismatch: {sorted(models)}')
        except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
            return self.update(path, lane, 'setup_blocked', startup_gap=str(error))
        state = 'awaiting_human' if row['role'] == 'design' and row['output_mode'] == 'artifact' else 'running'
        return self.update(path, lane, state, worktree=thread['worktreePath'], startup_state='verified',
                           startup_gap=None, t3_branch=thread.get('branch'), executed_model=next(iter(models), 'Unknown'))


def main():
    if sys.stdin.isatty():
        import termios
        settings = termios.tcgetattr(sys.stdin)
        settings[3] &= ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(sys.stdin, termios.TCSANOW, settings)
    adapter = WorkDispatch(stdio_call)
    try:
        request = json.loads(sys.stdin.readline())
        action = request.pop('action')
        path = Path(request['path']).expanduser()
        if not path.is_absolute():
            raise ValueError('registry path must be absolute')
        request['path'] = path.resolve()
        if action == 'dispatch':
            result = adapter.dispatch(**request)
        elif action == 'recover':
            result = adapter.recover(**request)
        else:
            raise ValueError('unknown work dispatch action')
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        result = dict(state='setup_blocked', reason=str(error))
    print(json.dumps(dict(result=result), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
