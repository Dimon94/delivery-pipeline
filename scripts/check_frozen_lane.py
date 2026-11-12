"""DD413 T12：公开冻结、真实 Registry 格式和恢复；预期来自票据。"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from check_config_transaction import m, SCRIPT, ROOT
import importlib.util


def check():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'config.json'
        registry = Path(directory) / 'registry-test.md'
        doc = m.valid_fixture()
        a = {'agent': 'pi', 'model': 'provider/model', 'effort': 'high'}
        b = {**a, 'effort': 'low'}
        for task in m.CLI_REQUIRED_WORK:
            doc['work'][task] = copy.deepcopy({**a, 'fallbacks': [b, a, b]})
        path.write_text(json.dumps(doc))
        def run(command, file, *args, ok=True):
            p = subprocess.run([sys.executable, str(SCRIPT), command, str(file), *args], capture_output=True, text=True)
            assert (p.returncode == 0) == ok, p.stdout + p.stderr
            return json.loads(p.stdout)
        for task in sorted(m.CLI_REQUIRED_WORK):
            frozen = run('freeze', path, task, '--output-mode', 'checks')
            assert frozen['recovery_plan'] == {'plan_version': 1, 'source': 'work', 'primary': a, 'fallbacks': [b, a, b]}
            assert frozen['recovery_progress'] == {'current_index': None, 'next_cursor': 0}
        plan = m.resolve_plan(doc, 'frontend', output_mode='commit')
        overlay = m.freeze_overlay(plan)
        doc['work']['frontend']['fallbacks'][0]['effort'] = 'high'
        assert overlay['recovery_plan']['fallbacks'] == [b, a, b]
        m.verify_overlay(plan, overlay)
        spec = importlib.util.spec_from_file_location('dispatch', ROOT / 'skills/delivery-pipeline-herdr/scripts/dispatch.py')
        dispatch = importlib.util.module_from_spec(spec); spec.loader.exec_module(dispatch)
        row = {'lane_id': 'dd413-fixture', 'work_item': 'DD-413', 'role': 'frontend', 'output_mode': 'commit', 'runtime': 't3-task', **overlay}
        dispatch.write_registry(registry, row)
        expected = run('recover', registry)
        assert expected['status'] == 'frozen' and expected['recovery_plan'] == overlay['recovery_plan']
        path.unlink()  # 恢复不依赖配置存在
        assert run('recover', registry) == expected
        for change in [ {'recovery_plan': {**overlay['recovery_plan'], 'plan_version': 2}}, {'recovery_progress': {'current_index': 0, 'next_cursor': 4}}, {'recovery_progress': {'current_index': 2, 'next_cursor': 0}}, {'model': 'wrong/model'}, {'recovery_progress': None}, {'recovery_progress': {'current_index': 0, 'next_cursor': 0}} ]:
            dispatch.write_registry(registry, {**row, **change})
            run('recover', registry, ok=False)
        # 备用下标1与primary值相同，位置身份仍须保留。
        positioned = {**row, 'recovery_progress': {'current_index': 1, 'next_cursor': 2}}
        dispatch.write_registry(registry, positioned)
        assert run('recover', registry)['recovery_progress']['current_index'] == 1
        legacy = {k: v for k, v in row.items() if not k.startswith('recovery_')}
        dispatch.write_registry(registry, legacy)
        assert run('recover', registry)['status'] == 'legacy'
        path.write_text(json.dumps(doc))
        for flags in [ ['--map-mode', 'standard'], ['--ticket-mode', 'standard', '--map-mode', 'missing'] ]:
            result = run('freeze', path, 'frontend', '--output-mode', 'commit', *flags)
            assert result['recovery_plan']['source'] == 'explicit_mode'
            assert result['recovery_plan']['fallbacks'] == []
            assert result['recovery_plan']['primary'] == {k: result[k] for k in a}
        result = run('freeze', path, 'frontend', '--output-mode', 'checks', '--ticket-mode', 'missing')
        assert result['recovery_plan']['source'] == 'work'
    print('DD413 frozen lane public contract: pass')

if __name__ == '__main__':
    check()
