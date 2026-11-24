"""回放 JB-476 的 map-local 配置覆盖，并检查 T3 原生边界。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'skills' / name / 'scripts') for name in ('delivery-pipeline', 'delivery-pipeline-setup')]
import driver
import lane_registry
import model_config

BACKEND = dict(agent='pi', model='magpie/auto/gpt-6.2-sol', effort='high')
PLANNING = dict(agent='pi', model='magpie/group/kimi-k3.1-pro', effort='max')
WRONG = dict(agent='codex', model='gpt-6-astra', effort='high')


def fixture(root):
    config = model_config.apply_limits(model_config.valid_fixture(), {'parallel': 4, 'max_turns': 100})
    config['work']['backend'].update(BACKEND)
    config['work']['planning'].update(PLANNING)
    path = root / '.config/delivery-pipeline/model-roles.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config))
    config['work']['backend'].update(WRONG)
    overlay = root / 'map/model-roles.json'
    overlay.parent.mkdir()
    overlay.write_text(json.dumps(config))
    return path, overlay


def check_driver(overlay):
    state = {'driver': {'plan': {'tickets': [{'task': 'backend', 'briefs': [{}]}]},
                        'dispatch': {'config': str(overlay)}}}
    page = driver.preflight_html(driver.brief_preflight(state))
    assert BACKEND['model'] in page and WRONG['model'] not in page, f'JB-476 map-local configuration won: {page}'


def check_plan_gate(root, config):
    plan = {'tickets': [{'id': 'T1', 'task': 'backend', 'briefs': [{'ticket': 'T1', 'slice_id': 'only'}],
                         'scenario_check': ['true']}]}
    d = dict(map='canary', gates={'discovery': 'd', 'spec': 's', 'tickets': 't'}, plan=plan, plan_check='pass')
    old = config.read_text()
    config.unlink()
    for mode in ('legacy', 'auto'):
        md = root / mode
        md.mkdir()
        driver.write_json(md / 'driver.json', {**d, 'planning_mode': mode})
        try:
            action = driver.run(md)
            driver.record(md, action['id'], {'reply': '通过'})
        except ValueError as error:
            assert '预检未通过' in str(error), error
        assert 'grant' not in driver.load(md)['driver']
        assert '无法执行' in (md / 'plan-review.html').read_text()
    config.write_text(old)
    md = root / 'legacy'
    action = driver.run(md)
    try:
        driver.record(md, action['id'], {'reply': '通过'})
    except ValueError as error:
        assert '预检已变化' in str(error), error
    refreshed = driver.run(md)
    assert action['id'] != refreshed['id'] and 'grant' not in driver.load(md)['driver']
    driver.record(md, refreshed['id'], {'reply': '通过'})
    assert driver.run(md)['id'] == 'owner:publish'
    assert driver.run(root / 'auto')['id'] == 'owner:publish'


def invoke(request, replies=()):
    """通过真实 JSON lines 入口记录宿主工具请求，原生响应来自替身。"""
    calls = []
    expected = iter(replies)
    with subprocess.Popen([sys.executable, HERE / 'work_dispatch.py'], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as process:
        def send(value):
            process.stdin.write(json.dumps(value) + '\n')
            process.stdin.flush()

        send(request)
        for line in process.stdout:
            reply = json.loads(line)
            if 'result' in reply:
                break
            name, value = next(expected, (None, None))
            assert reply['tool'] == name, reply
            calls.append(reply['arguments'])
            send({'result': value})
        assert process.wait(timeout=10) == 0 and 'result' in reply
    assert next(expected, None) is None
    return reply['result'], calls


def capabilities(model, efforts):
    return dict(parentThreadId='parent', inheritedProviderInstanceId='codex', providers=[
        dict(providerInstanceId='pi', canRunChildTask=True, canRunCrossProviderChildTask=True,
             models=[dict(id=model, options=[dict(id='thinking', values=efforts)])]),
        dict(providerInstanceId='codex', canRunChildTask=True,
             models=[dict(id=WRONG['model'], options=[dict(id='reasoningEffort', values=['high'])])]),
    ])


def check_native(root, config, overlay):
    subprocess.run(['git', 'init', '-q', root], check=True)
    common = str(root / '.git')
    status = dict(attached=False, projectWorkspaceRoot=str(root))
    for kind, output, triple in [('planning', 'artifact', PLANNING), ('backend', 'commit', BACKEND)]:
        lane = 'JB-478' if kind == 'backend' else 'spec'
        path = str(root / f'registry-{lane}.md')
        row = dict(lane_id=lane, role=kind, output_mode=output, base_commit='a' * 40,
                   map='JB-476', work_item=lane)
        request = dict(action='dispatch', path=path, row=row, task='fixture packet', source=str(root))
        recover = dict(action='recover', path=path, lane=lane)
        cap = capabilities(triple['model'], [triple['effort']])

        for bad in [dict(config=str(overlay)), dict(target=WRONG), dict(row={**row, **WRONG})]:
            result, calls = invoke({**request, **bad})
            assert result['state'] == 'setup_blocked' and not calls and not Path(path).exists(), result
        for model, efforts in [(WRONG['model'], [triple['effort']]), (triple['model'], ['low'])]:
            result, _ = invoke(request, [('orchestrator_capabilities', capabilities(model, efforts))])
            assert result['state'] == 'setup_blocked' and not Path(path).exists(), result

        receipt = dict(taskId='task', childThreadId='child', next='yield')
        result, calls = invoke(request, [('orchestrator_capabilities', cap), ('t3_worktree_status', status),
                                         ('delegate_task', receipt)])
        saved, _ = lane_registry.read(path, lane)
        target = dict(providerInstanceId='pi', model=triple['model'], options={'thinking': triple['effort']})
        assert calls[0]['search'] == triple['model'] and calls[2]['target'] == target, calls
        assert calls[2] == saved['t3code']['native_request'] and result == saved
        assert saved['state'] == 'created' and saved['recovery_plan']['primary'] == triple, saved
        marker = f'LANE_DONE {lane} ' + ('a' * 40 if output == 'commit' else 'spec.md')
        assert driver.signal(root, marker) == {'signal': 'ignored'}, 'unverified startup accepted terminal marker'
        result, calls = invoke(request)
        assert 'lane already exists' in result['reason'] and not calls, result

        child = root / 'child'
        child.mkdir(exist_ok=True)
        (child / '.git').write_text(f'gitdir: {common}\n')
        thread = dict(threadId='child', parentThreadId='parent', relationshipToParent='subagent',
                      providerInstanceId='pi', model=triple['model'], worktreePath=str(child), branch='temp')
        wrong_read = dict(thread=thread, recentRuns=[{'executedModel': WRONG['model']}])
        result, _ = invoke(recover, [('t3_thread_read', wrong_read)])
        assert result['state'] == 'setup_blocked' and 'executed model mismatch' in result['t3code']['startup_gap']
        right_read = dict(thread=thread, recentRuns=[{'executedModel': triple['model']}])
        # 也回放配置缺失的恢复，原生核验沿冻结身份。
        initial = config.read_text()
        config.unlink()
        result, _ = invoke(recover, [('t3_thread_read', right_read)])
        config.write_text(initial)
        assert result['state'] == 'running' and result['worktree'] == str(child), result
        assert result['t3code']['receipt'] == receipt and result['t3code']['executed_model'] == triple['model']
        assert driver.signal(root, marker)['state'] == 'terminal'


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'HOME': tmp, 'MAGPIE_API_KEY': 'fixture-only'}):
        root = Path(tmp).resolve()
        config, overlay = fixture(root)
        check_driver(overlay)
        check_plan_gate(root, config)
        check_native(root, config, overlay)
    print('configured work dispatch: OK')
