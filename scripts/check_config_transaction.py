#!/usr/bin/env python3
"""通过 setup 公开命令检查临时文件结果，预期来自 DD-377 R1/R3–R6。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/delivery-pipeline-setup/scripts/model_config.py'
spec = importlib.util.spec_from_file_location('config', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


FAULT_RUNNER = """
import importlib.util, os, pathlib, sys, time
spec = importlib.util.spec_from_file_location('config', sys.argv.pop(1))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fault = sys.argv.pop(1)
original = os.replace
def replace(src, dst):
    if fault == 'pre': raise OSError('受控替换前失败')
    if fault == 'delay': time.sleep(0.15)
    original(src, dst)
    if fault == 'post':
        def unreadable(self): raise OSError('受控替换后读回失败')
        pathlib.Path.read_bytes = unreadable
os.replace = replace
if fault == 'temp':
    def fail_temp(*args, **kwargs): raise OSError('受控临时文件失败')
    m.tempfile.mkstemp = fail_temp
sys.exit(m.main())
"""


def command(path, evidence, base=None, fault=None):
    args = [sys.executable, str(SCRIPT)] if fault is None else [sys.executable, '-c', FAULT_RUNNER, str(SCRIPT), fault]
    args += ['configure', str(path), '--request-id', 'test', '--evidence', str(evidence)]
    if base is not None:
        args += ['--base-hash', base]
    return args


def run(path, candidate, evidence, base=None, fault=None):
    args = command(path, evidence, base, fault)
    p = subprocess.run(args, input=json.dumps(candidate), text=True, capture_output=True)
    assert p.stdout.strip(), p.stderr
    return p.returncode, json.loads(p.stdout)


def check():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'config.json'
        ev = Path(directory) / 'evidence.json'
        candidate = m.valid_fixture()
        # 显式 mode 也必须有本轮证据，fixture 的 low/medium/high 均有来源。
        ev.write_text(json.dumps({'request_id': 'test', 'observed_at': '2026-11-12T08:30:00Z', 'sources': {a: {'status': 'ok'} for a in ('pi','codex','claude')}, 'capabilities': {a: {'binary': True, 'models': {'provider/model': ['low', 'medium', 'high']}} for a in ('pi','codex','claude')}}))
        code, result = run(path, candidate, ev)
        assert code == 0 and result['status'] == 'applied', result
        raw = path.read_bytes()
        base = hashlib.sha256(raw).hexdigest()
        assert result['config'] == candidate and result['base_hash'] == base
        code, result = run(path, candidate, ev)
        assert code == 1 and result['error']['code'] == 'base_conflict'
        assert path.read_bytes() == raw
        # 无语义修改保持非标准原始排版及 inode。
        path.write_text(json.dumps(candidate, separators=(',', ':')))
        raw = path.read_bytes()
        base = hashlib.sha256(raw).hexdigest()
        inode = path.stat().st_ino
        code, result = run(path, candidate, ev, base)
        assert code == 0 and result['changed'] is False
        assert path.read_bytes() == raw and path.stat().st_ino == inode
        candidate['work']['planning']['effort'] = 'low'
        code, result = run(path, candidate, ev, 'stale')
        assert code == 1 and result['error']['code'] == 'base_conflict'
        assert path.read_bytes() == raw
        bad = json.loads(ev.read_text()); bad['request_id'] = 'previous'; ev.write_text(json.dumps(bad))
        code, result = run(path, candidate, ev, base)
        assert code == 1 and result['error']['code'] == 'capability_unavailable'
        assert path.read_bytes() == raw
        bad['request_id'] = 'test'; ev.write_text(json.dumps(bad))
        for field, value in (('agent', 'codex'), ('model', 'absent/model'), ('effort', 'absent-effort')):
            invalid = json.loads(json.dumps(candidate))
            invalid['work']['planning'][field] = value
            # codex 来源有效但只有另一个模型，精确模型身份不能借用 pi 证据。
            absent = json.loads(ev.read_text()); absent['capabilities']['codex']['models'] = {}
            ev.write_text(json.dumps(absent))
            code, result = run(path, invalid, ev, base)
            assert code == 1 and result['error']['code'] == 'capability_unavailable'
            assert path.read_bytes() == raw
        ev.write_text(json.dumps(bad))
        invalid = {**candidate, 'version': 4}
        code, result = run(path, invalid, ev, base)
        assert code == 1 and result['error']['code'] == 'invalid_candidate'
        assert path.read_bytes() == raw
        lock = path.with_name(path.name + '.lock'); lock.unlink(); lock.mkdir()
        code, result = run(path, candidate, ev, base)
        assert code == 1 and result['error']['code'] == 'io_error'
        assert path.read_bytes() == raw
        lock.rmdir()
        code, result = run(path, candidate, ev, base, 'temp')
        assert code == 1 and result['status'] == 'rejected'
        assert path.read_bytes() == raw
        code, result = run(path, candidate, ev, base, 'pre')
        assert code == 1 and result['status'] == 'rejected'
        assert path.read_bytes() == raw
        code, result = run(path, candidate, ev, base, 'post')
        assert code == 3 and result['status'] == 'commit_unverified', result
        assert json.loads(path.read_bytes()) == candidate
        assert result['expected_hash'] == hashlib.sha256(path.read_bytes()).hexdigest()
        # 两个真正独立进程；替换边界延迟扩大交错窗口，不替代锁。
        base = hashlib.sha256(path.read_bytes()).hexdigest()
        left = json.loads(json.dumps(candidate)); left['work']['planning']['effort'] = 'medium'
        right = json.loads(json.dumps(candidate)); right['work']['planning']['effort'] = 'high'
        processes = [subprocess.Popen(command(path, ev, base, 'delay'), stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process, value in zip(processes, (left, right)):
            process.stdin.write(json.dumps(value)); process.stdin.close(); process.stdin = None
        outcomes = [json.loads(process.communicate(timeout=10)[0]) for process in processes]
        assert sorted(r['status'] for r in outcomes) == ['applied', 'rejected'], outcomes
        winner = next(r for r in outcomes if r['status'] == 'applied')
        loser = next(r for r in outcomes if r['status'] == 'rejected')
        assert loser['error']['code'] == 'base_conflict'
        assert json.loads(path.read_bytes()) == winner['config']
        # 旧 CLI v2 成功输出合同与转换范围。
        legacy = {'version': 2, 'roles': {key: {'agent': 'pi', 'model': 'old/model', 'effort': 'high'}
                  for key in ('planning','design','frontend','backend','testing','review')}}
        path.write_text(json.dumps(legacy))
        process = subprocess.run([sys.executable, str(SCRIPT), 'migrate', str(path)], capture_output=True, text=True)
        assert process.returncode == 0, process.stdout
        assert json.loads(process.stdout) == {'migrated': str(path), 'transport': 'cli', 'default_mode': None}
        actual = json.loads(path.read_bytes())
        assert actual['version'] == 6 and actual['modes'] == {}
        assert actual['work']['planning'] == {**legacy['roles']['planning'], 'fallbacks': []}
        assert actual['review']['whole-change']['spec'] == {**legacy['roles']['review'], 'candidates': []}
        # migrate 与 configure 共享协议；不是仅同一入口自测。
        path.write_text(json.dumps(legacy))
        legacy_base = hashlib.sha256(path.read_bytes()).hexdigest()
        migrate = subprocess.Popen([sys.executable, '-c', FAULT_RUNNER, str(SCRIPT), 'delay', 'migrate', str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        configure = subprocess.Popen(command(path, ev, legacy_base, 'delay'), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        configure_out = configure.communicate(json.dumps(candidate), timeout=10)[0]
        migrate_out = migrate.communicate(timeout=10)[0]
        assert sorted([configure.returncode, migrate.returncode]) == [0, 1], (configure_out, migrate_out)
        final = json.loads(path.read_bytes())
        assert final == (candidate if configure.returncode == 0 else actual)
        for fault, expected_code in (('pre', 1), ('post', 3)):
            path.write_text(json.dumps(legacy)); before = path.read_bytes()
            process = subprocess.run([sys.executable, '-c', FAULT_RUNNER, str(SCRIPT), fault, 'migrate', str(path)],
                                     capture_output=True, text=True)
            assert process.returncode == expected_code, process.stdout
            if fault == 'pre':
                assert path.read_bytes() == before
            else:
                assert json.loads(process.stdout)['status'] == 'commit_unverified'
                assert json.loads(path.read_bytes()) == actual

    print('配置事务检查通过：创建/hash/no-op/旧证据/提交前后故障/真进程并发/迁移')

if __name__ == '__main__':
    check()
