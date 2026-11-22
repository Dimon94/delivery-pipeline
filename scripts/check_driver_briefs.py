"""跨仓 TURN-1：从上游 prepare CLI 到 Driver 的真实工作树、提交与场景回读。"""
import json
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'skills' / name / 'scripts') for name in ('delivery-pipeline', 'delivery-pipeline-setup')]
import driver
import model_config
import lane_registry

# 蜂巢执行与 transport 无关：Herdr 壳的 driver_run 与 T3 Code 等壳直接调用的核心 driver.py 都要跑通。
ENTRIES = {'herdr': (ROOT / 'skills/delivery-pipeline-herdr/scripts/driver_run.py', 10, 'watch'),
           'core': (ROOT / 'skills/delivery-pipeline/scripts/driver.py', 0, 'signal')}
CLI = ROOT / 'scripts/delivery-dispatch'
WORKER = '''#!/usr/bin/env python3
import fcntl, json, os, pathlib, subprocess, sys, time
with open(os.environ['STARTS'], 'a') as log:
    # parallel=1；两个 watcher 或两个执行片都不能同时进入。
    fcntl.flock(log, fcntl.LOCK_EX | fcntl.LOCK_NB)
    brief = json.load(sys.stdin)
    assert sys.argv[sys.argv.index('--max-turns') + 1] == '2'
    name = brief['slice_id']
    print(name, file=log, flush=True)
    time.sleep(.05)
    path = pathlib.Path(brief['writable'][0])
    def commit(text):
        path.write_text(text)
        subprocess.run(['git', 'add', '--', str(path)], check=True)
        subprocess.run(['git', 'commit', '-qm', name], check=True)
    if name == 'state':
        commit('// first commit\\n')
        commit("module.exports = () => 'stopped';")
    else:
        # 局部基线仍 running，所以两片都会绿；合在一起才丢结果。
        expr = "require('./status')(turn) === 'stopped' ? [] : turn.results" if os.environ['BAD'] else 'turn.results'
        commit('module.exports = turn => ' + expr + ';')
'''


def output(*cmd, cwd=None, payload=None):
    return subprocess.check_output(cmd, cwd=cwd, input=payload, text=True).strip()


def journey(tmp, upstream, payload, bad, entry):
    run_cli, woke, signal = ENTRIES[entry]
    repo, md = tmp / 'repo', tmp / 'map'
    shutil.copytree(upstream / 'example', repo)
    md.mkdir()
    def git(*args):
        return output('git', *args, cwd=repo)
    git('init', '-qb', 'integration')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    git('add', '--', 'turn.js', 'status.js', 'results.js', 'check.cjs')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    # 示例基线属于上游临时仓库。用当前真实仓库的 HEAD 调用上游的正式 JSON 接口。
    slices = json.loads(output('node', '-e', 'console.log(JSON.stringify(require(process.argv[1])().split))', str(upstream / 'briefs.cjs')))
    prepared = json.loads(output('node', upstream.parents[2] / 'delegate-ticket/scripts/prepare.js', cwd=repo,
                                 payload=json.dumps({**payload, 'base': base, 'site': {'slices': slices}})))
    assert [b['slice_id'] for b in prepared] == ['state', 'results']
    ticket = dict(id='TURN-1', briefs=prepared, scenario_check=['node', 'check.cjs', 'all'])
    plan = {'tickets': [ticket, {'id': 'NEXT', 'deps': ['TURN-1'], 'hitl': True}]}
    config = model_config.apply_limits(model_config.valid_fixture(), {'parallel': 1, 'max_turns': 2})
    config['work']['backend'].update(agent='claude', model='fixture', effort='high')
    cfg = tmp / 'config.json'
    cfg.write_text(json.dumps(config))
    doc = dict(version=1, map='map', plan=plan, grant={'plan_sha': driver.plan_sha(plan)}, published=True,
               dispatch={'config': str(cfg)})
    driver.write_json(md / 'driver.json', doc)
    # Plan Review 预检：展示实际模型与上限；配置解析失败时写明无法执行。
    page = driver.preflight_html(driver.load(md))
    assert 'claude / fixture / high' in page and '每片 ≤2 轮，并发 ≤1' in page, page
    blind = deepcopy(doc)
    blind['dispatch']['config'] = str(tmp / 'missing.json')
    assert '无法执行' in driver.preflight_html({'driver': blind}), blind
    driver.persist_lanes(md, [dict(lane_id='map', role='map', state='running', work_item='map',
                                   integration_worktree_path=str(repo), integration_branch='integration', base_commit=base, _file=None)])
    fake = tmp / 'claude'
    fake.write_text(WORKER)
    fake.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ['PATH'], BAD='bad' if bad else '',
               STARTS=str(tmp / 'starts'), CLAUDE_CONFIG_DIR=str(tmp / 'claude-config'))
    # 模拟批次已经执行完成、Driver 尚未写 dispatch 回执时重启。
    batch = tmp / 'batch.json'
    batch.write_text(json.dumps(prepared))
    marker = 'LANE_DONE TURN-1'
    if bad:
        rows = subprocess.check_output([CLI, 'batch', batch, '--managed', md, '--task', 'backend',
                                       '--config', cfg], cwd=repo, env=env, text=True)
        records = [json.loads(line) for line in rows.splitlines()]
        assert len(records) == 2
        try:
            driver.brief_delivery.verify_rows(prepared, records[:1], md, repo, 'backend', 'map')
        except ValueError as error:
            assert '缺少执行片' in str(error)
        else:
            raise AssertionError('缺片竟能产生整票回执')
        assert subprocess.run([CLI, 'merge', records[0]['name']], cwd=repo, capture_output=True).returncode
        marker = records[0]['marker']
    assert git('rev-parse', 'HEAD') == base
    procs = [subprocess.Popen([sys.executable, run_cli, *cmd], env=env, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) for cmd in (('run', md), (signal, md, marker))]
    for p in procs:
        stdout, stderr = p.communicate(timeout=30)
        assert p.returncode == woke, (stdout, stderr)
        if signal == 'signal' and 'action' not in json.loads(stdout):
            continue  # 核心 signal 只记终态，不打印 Action
        assert json.loads(stdout)['id'] == ('halt:plan_change:scenario:TURN-1' if bad else 'hitl:NEXT'), stdout
    head = git('rev-parse', 'HEAD')
    assert git('rev-list', '--count', '--merges', base + '..HEAD') == '2'
    assert git('rev-list', '--count', '--no-merges', base + '..HEAD') == '3'
    assert sorted((tmp / 'starts').read_text().splitlines()) == ['results', 'state']
    state = driver.load(md)
    proof = state['driver']['receipts'][f'scenario:TURN-1:{head}']
    assert proof['base'] == head and proof['ok'] is (not bad) and proof['check'] == ticket['scenario_check']
    if not bad:
        ids = lane_registry.collect_implementation_identities(state['lanes'], base)
        assert len(ids) == 2 and all(i['requested']['model'] == 'fixture' for i in ids)
        assert json.loads(proof['observed']) == {'status': 'stopped', 'results': ['第一段']}
        lanes = dict(state['lanes'])
        del lanes[next(k for k, r in lanes.items() if r.get('slice_id') == 'state')]
        assert driver.decide({**state, 'lanes': lanes})['action'] == 'dispatch_briefs'
        (repo / 'results.js').write_text('module.exports = () => [];')
        git('commit', '-qam', '集成后回归')
        rerun = subprocess.run([sys.executable, run_cli, 'run', md], env=env, text=True, capture_output=True)
        assert rerun.returncode == woke and json.loads(rerun.stdout)['action'] == 'halt', rerun.stdout
    print('TURN-1', entry, '整票拒绝' if bad else '整票通过', proof['base'], '2 slices, 3 commits, 2 watchers')


if __name__ == '__main__':
    upstream = Path(sys.argv[1]).resolve() / 'skills/to-tickets/references/stop-turn'
    payload = json.loads(output('node', upstream / 'verify-contract.cjs', '--json'))['prepareInput']
    for entry in ENTRIES:
        for bad in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                journey(Path(tmp).resolve(), upstream, payload, bad, entry)
