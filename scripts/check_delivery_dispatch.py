"""临时 Git 仓的命令行验收；假 claude 只校验启动参数与输入，提交由真实 Git 产生。"""
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'skills/delivery-pipeline-setup/scripts'))
from model_config import valid_fixture


def check(root):
    repo = root / 'repo'
    repo.mkdir()
    cfg = root / 'cfg'
    cfg.mkdir()
    normal = {'type': 'command', 'command': 'normal-hook'}
    settings = {'hooks': {'SessionStart': [{'hooks': [normal, {'type': 'command', 'command': '/tmp/bees hook --cli claude'}]}]}}
    personal_gateway = 'http://127.0.0.1:18787'
    settings['env'] = {'ANTHROPIC_BASE_URL': personal_gateway}
    settings['permissions'] = {'deny': ['Read(private.txt)']}
    (cfg / 'settings.json').write_text(json.dumps(settings))
    cli = HERE / 'delivery-dispatch'
    worker = root / 'claude'
    worker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
argv=sys.argv[1:]
worker_home=pathlib.Path(os.environ['CLAUDE_CONFIG_DIR'])
assert worker_home != pathlib.Path(os.environ['ORIGINAL_CLAUDE_DIR'])
assert worker_home.is_dir()
assert '-p' in argv and '--bare' not in argv and '--safe-mode' not in argv
assert argv[argv.index('--model')+1]=='auto/test-model' and argv[argv.index('--effort')+1]=='high'
assert argv[argv.index('--max-turns')+1]=='7'
settings=json.loads(pathlib.Path(argv[argv.index('--settings')+1]).read_text())
assert settings['env']['ANTHROPIC_BASE_URL']=='http://127.0.0.1:3425'
assert settings['permissions']['deny']==['Read(private.txt)']
hooks=settings['hooks']['SessionStart'][0]['hooks']
assert [h['command'] for h in hooks]==['normal-hook']
brief=sys.stdin.read()
name=pathlib.Path.cwd().name
assert 'BRIEF_PRIVATE_SENTINEL' in brief
if name=='retry' and 'git status' not in brief:
    pathlib.Path(name).write_text('保留未提交改动')
    sys.exit(0)
if name=='retry': assert pathlib.Path(name).read_text()=='保留未提交改动'
pathlib.Path(name).write_text('done')
subprocess.run(['git','add','--',name],check=True)
subprocess.run(['git','commit','-qm',name],check=True)
''')
    worker.chmod(0o755)
    env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'], CLAUDE_CONFIG_DIR=str(cfg), ORIGINAL_CLAUDE_DIR=str(cfg), MAGPIE_API_KEY='test-only')

    def run(*args):
        return subprocess.check_output(args, cwd=repo, env=env, text=True).strip()

    run('git', 'init', '-q', '-b', 'main')
    run('git', 'config', 'user.email', 'fixture@example.invalid')
    run('git', 'config', 'user.name', 'fixture')
    (repo / 'guide').write_text('baseline')
    run('git', 'add', 'guide')
    run('git', 'commit', '-qm', 'base')
    base = run('git', 'rev-parse', 'HEAD')
    config = valid_fixture()
    config['work']['backend'].update(agent='pi', model='magpie/auto/test-model', effort='high')
    (root / 'config.json').write_text(json.dumps(config))
    ev = {'capabilities': {'pi': {'binary': True, 'models': {'magpie/auto/test-model': ['high']}}}}
    (root / 'probe.json').write_text(json.dumps(ev))
    args = ['--turns', '7', '--task', 'backend', '--config', root / 'config.json', '--evidence', root / 'probe.json']
    wave = root / 'wave'
    wave.mkdir()
    def contract(name, writable=None, check=None):
        return dict(ticket='TICKET', slice_id=name, scenarios=['S1'], base=base,
                    title='写入结果', goal='BRIEF_PRIVATE_SENTINEL', owns=['R1'], exclusions=[],
                    read_first=['guide'], writable=writable or [name], expected='done',
                    check=check or [sys.executable, '-c',
                        f"from pathlib import Path; assert Path({name!r}).read_text() == 'done'; print('done')"])

    def write_contract(directory, data):
        path = directory / (data['slice_id'] + '.json')
        path.write_text(json.dumps(data))
        return path

    probe = root / 'probe.json'
    no_probe = write_contract(root, contract('no-probe'))
    for invalid in ({}, {'capabilities': None}):
        probe.write_text(json.dumps(invalid))
        rejected = subprocess.run([cli, 'run', 'no-probe', no_probe, *args], cwd=repo, env=env, capture_output=True)
        assert rejected.returncode and b'capabilities' in rejected.stderr
        assert run(cli, 'status') == '[]' and 'brief/no-probe' not in run('git', 'worktree', 'list')
    probe.write_text(json.dumps(ev))
    for n in ['one', 'retry']:
        write_contract(wave, contract(n))
    run(cli, 'batch', wave, '-p', '2', *args)
    states = {r['name']: r for r in json.loads(run(cli, 'status'))}
    assert {n: v['attempts'] for n, v in states.items()} == {'one': 1, 'retry': 2}
    assert all(r['state'] == 'ready' for r in states.values())
    run(cli, 'merge', 'one', 'retry')
    assert [ (repo / n).read_text() for n in ['one','retry'] ] == ['done','done']
    def fresh(data):
        data['base'] = run('git', 'rev-parse', 'HEAD')
        return write_contract(root, data)

    for name, data in [('outside', contract('outside', writable=['approved'])),
                       ('red', contract('red', check=[sys.executable, '-c', 'raise SystemExit(7)']))]:
        path = fresh(data)
        before = run('git', 'rev-parse', 'HEAD')
        result = subprocess.run([cli, 'run', name, path, *args], cwd=repo, env=env, capture_output=True)
        assert result.returncode != 0, name
        assert json.loads(run(cli, 'status'))[0]['state'] == 'failed', name
        assert subprocess.run([cli, 'merge', name], cwd=repo, env=env, capture_output=True).returncode != 0
        assert run('git', 'rev-parse', 'HEAD') == before
        run(cli, 'drop', name)
    run(cli, 'run', 'solo', fresh(contract('solo')), *args)
    run(cli, 'drop', 'solo')
    assert run(cli, 'status') == '[]' and not (repo / 'solo').exists()
    assert json.loads((cfg / 'settings.json').read_text()) == settings
    from unittest.mock import patch
    with patch.dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg)):
        hook_args = runpy.run_path(str(cli))['hook_args']
        with hook_args(repo, env, magpie=False) as (options, native_env):
            native_settings = json.loads(Path(options[options.index('--settings') + 1]).read_text())
            assert native_env is env and native_env['CLAUDE_CONFIG_DIR'] == str(cfg)
            assert native_settings['env']['ANTHROPIC_BASE_URL'] == personal_gateway
    print('PASS run/batch/retry/status/merge/drop + model/effort/turns + selective hooks')


if __name__ == '__main__':
    with TemporaryDirectory() as tmp:
        check(Path(tmp))
