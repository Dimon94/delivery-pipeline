#!/usr/bin/env python3
"""隔离 HOME，通过公开 probe 验证 TOML fallback 与可搬迁的应用资源。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--tool', type=Path, default=Path(__file__).resolve().parents[1] / 'skills/delivery-pipeline-setup/scripts/model_config.py')
parser.add_argument('--python', default=sys.executable)
args = parser.parse_args()
# 禁用 site packages，且强制缺少 tomllib；3.11+ CI 也必须走随包 fallback。
runner = '''import sys, runpy, importlib.abc
class NoTomllib(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'tomllib':
            raise ModuleNotFoundError('controlled missing tomllib')
sys.meta_path.insert(0, NoTomllib())
sys.path.insert(0, sys.argv[1])
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name='__main__')
'''
with tempfile.TemporaryDirectory(prefix='config-toml-') as tmp:
    home = Path(tmp)
    (home / '.codex').mkdir()
    binary = home / 'bin'
    binary.mkdir()
    codex = binary / 'codex'
    codex.write_text('#!/bin/sh\n/bin/echo \'{"models": []}\'\n')
    codex.chmod(0o755)
    catalog = home / 'catalog.json'
    catalog.write_text(json.dumps({'models': [{'slug': 'vendor/model@large', 'supported_reasoning_levels': [{'effort': e} for e in ['high', 'xhigh', 'ultra', 'persistent']]}]}))
    config = home / '.codex/config.toml'
    valid = ('model_provider = "local.magpie"\nmodel_catalog_json = ' + json.dumps(str(catalog)) + '\n'
             '# 完整 TOML：带点的 quoted key、inline table、multiline string\n'
             'note = """isolated\nfixture"""\n'
             '[model_providers]\n"local.magpie" = {base_url = "http://127.0.0.1:3425/backend-api/codex"}\n')
    gateway = {'gateway': {'status': 'ok', 'data': [{'id': 'vendor/model@large', 'supported_reasoning_levels': [{'effort': 'low'}, {'effort': 'high'}, {'effort': 'ultra'}]}]}}
    env = {'HOME': str(home), 'PATH': str(binary), 'PYTHONDONTWRITEBYTECODE': '1'}
    def probe():
        p = subprocess.run([args.python, '-S', '-c', runner, str(args.tool.resolve().parent), str(args.tool.resolve()), 'probe', '--request-id', 'toml-contract'], input=json.dumps(gateway), text=True, capture_output=True, cwd=home, env=env)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)
    config.write_text(valid)
    p = probe()
    assert p['capabilities']['codex']['models'] == {'vendor/model@large': ['high']}, '有效 magpie 路由/catalog 应保留 native 身份与 effort 交集'
    assert p['sources']['codex']['status'] == 'ok'
    for invalid in (valid.replace('127.0.0.1:3425', '127.0.0.1:9999'), valid.replace('"local.magpie" =', '"unmapped" ='), 'model_provider = [broken'):
        config.write_text(invalid)
        p = probe()
        assert p['capabilities']['codex']['models'] == {} and p['sources']['codex']['status'] == 'unknown'
    config.write_text(valid)
    catalog.write_text(json.dumps({'models': [{'slug': 'unmapped-native', 'supported_reasoning_levels': [{'effort': 'high'}]}]}))
    p = probe()
    assert p['capabilities']['codex']['models'] == {} and p['sources']['codex']['status'] == 'unknown'
    bundled = {'models': [{'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': e} for e in ['low', 'high', 'xhigh', 'max', 'ultra', 'persistent']]}]}
    codex.write_text('#!/bin/sh\n[ "$*" = "debug models --bundled" ] || exit 1\n/bin/echo ' + "'" + json.dumps(bundled) + "'\n")
    config.write_text('model_catalog_json = ' + json.dumps(str(catalog)) + '\n')
    catalog.write_text('invalid catalog must not be read for direct')
    p = probe()
    assert p['sources']['codex']['route'] == 'direct'
    assert p['sources']['codex']['status'] == 'ok'
    assert '直连 OpenAI' in p['sources']['codex']['origin']
    assert p['capabilities']['codex']['models'] == {'gpt-6.1-sol': ['low', 'high', 'xhigh', 'max']}
    config.unlink()
    p = probe()
    assert p['sources']['codex']['route'] == 'direct', '缺失配置应使用默认直连'
    assert p['sources']['codex']['status'] == 'ok'
    for failed in ('#!/bin/sh\nexit 1\n', '#!/bin/sh\n/bin/echo invalid-json\n'):
        codex.write_text(failed)
        p = probe()
        assert p['sources']['codex']['status'] == 'unknown'
        assert p['capabilities']['codex']['models'] == {}
        assert p['sources']['codex']['route'] == 'direct'
        assert p['sources']['codex']['reason'] == '无法读取 Codex 内置模型清单'
        config.write_text(valid)
        p = probe()
        assert p['sources']['codex']['route'] == 'gateway'
        assert p['sources']['codex']['reason'] == '无法读取 Codex 内置模型清单'
        config.write_text(valid.replace('127.0.0.1:3425', '127.0.0.1:9999'))
        p = probe()
        assert p['sources']['codex']['reason'] == 'Codex 当前指向的地址既不是本机网关也不是 OpenAI 官方，无法确认可用模型'
        config.unlink()
print('TOML public probe: pass (isolated HOME, no site packages, no tomllib)')
