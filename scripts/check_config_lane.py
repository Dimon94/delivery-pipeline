"""R8：公开保存结果经 canonical resolve/start 消费，显式预设不变。"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from check_config_transaction import m, SCRIPT


def check():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'config.json'
        evidence_path = Path(directory) / 'evidence.json'
        original = m.valid_fixture()
        original['work']['frontend'] = {'agent': 'pi', 'model': 'magpie/codex/gpt-6.1-sol@100k', 'effort': 'high'}
        original['modes']['standard']['agents']['pi']['direct'] = {'model': 'provider/model', 'effort': 'high'}
        path.write_text(json.dumps(original))
        candidate = copy.deepcopy(original)
        candidate['work']['frontend']['effort'] = 'low'
        evidence = {'pi': {'binary': True, 'models': {'magpie/codex/gpt-6.1-sol@100k': ['high', 'low'], 'provider/model': ['high']}}}
        envelope = {'request_id': 'save', 'observed_at': 'now', 'sources': {'pi': {'status': 'ok'}}, 'capabilities': evidence}
        evidence_path.write_text(json.dumps(envelope))
        def run(command, *args, stdin=None):
            result = subprocess.run([sys.executable, str(SCRIPT), command, str(path), *args], input=stdin, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout)
        snapshot = run('show')
        saved = run('apply', '--base-hash', snapshot['base_hash'], '--request-id', 'save', '--evidence', str(evidence_path), stdin=json.dumps(candidate))
        assert saved['config'] == candidate
        assert saved['config']['modes'] == original['modes']
        assert saved['config']['review'] == original['review']
        evidence_path.write_text(json.dumps(evidence))
        common = ['frontend', '--output-mode', 'commit', '--evidence', str(evidence_path)]
        default = run('resolve', *common)
        assert (default['agent'], default['model'], default['effort'], default['phase'], default['mode_name']) == ('pi', 'magpie/codex/gpt-6.1-sol@100k', 'low', 'direct', None), default
        start = run('start', *common, '--worker-name', 'test', '--pane-id', 'isolated')
        assert start == ['herdr', 'agent', 'start', 'test', '--kind', 'pi', '--pane', 'isolated', '--', '--approve', '--model', 'magpie/codex/gpt-6.1-sol@100k', '--thinking', 'low'], start
        for flags, source in [(['--map-mode', 'standard'], 'map'), (['--ticket-mode', 'standard', '--map-mode', 'missing'], 'ticket')]:
            mode = run('resolve', *common, *flags)
            assert (mode['model'], mode['effort'], mode['source'], mode['phase']) == ('provider/model', 'high', source, 'direct'), mode
            mode_start = run('start', *common, *flags)
            assert mode_start[-4:] == ['--model', 'provider/model', '--thinking', 'high'], mode_start
    print('save → resolve/start default and explicit mode: pass')


if __name__ == '__main__':
    check()
