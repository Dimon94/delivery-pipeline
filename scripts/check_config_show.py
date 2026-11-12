#!/usr/bin/env python3
"""DD-378：穿过真实命令的离线读取合同，预期取自 M1 Spec。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile

TOOL = Path(__file__).resolve().parents[1] / 'skills/delivery-pipeline-setup/scripts/model_config.py'


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'settings'
        def read(state, raw=None):
            if raw is not None:
                path.write_bytes(raw)
            before = path.read_bytes() if path.is_file() else None
            command = [sys.executable, str(TOOL), 'show', str(path)]
            if sys.platform == 'darwin' and shutil.which('sandbox-exec'):
                command = ['sandbox-exec', '-p', '(version 1)(allow default)(deny network*)(deny file-write*)', *command]
            result = subprocess.run(command, capture_output=True, text=True, env={**os.environ, 'http_proxy': 'http://127.0.0.1:1', 'https_proxy': 'http://127.0.0.1:1'})
            assert result.returncode == 0, result.stderr
            snapshot = json.loads(result.stdout)
            assert snapshot['api_version'] == 1
            assert snapshot['file_state'] == state, snapshot
            assert snapshot['base_hash'] == (hashlib.sha256(before).hexdigest() if before is not None else None)
            assert (path.read_bytes() if path.is_file() else None) == before
            return snapshot
        assert read('missing')['config'] is None
        assert read('invalid_json', b'{broken')['config'] is None
        assert read('unsupported_version', b'{"version":4}')['validation']['valid'] is False
        read('invalid_schema', b'{"version":6}')
        cell = {'agent': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'}
        config = {'version': 6, 'work': {name: {**cell,"fallbacks":[]} for name in ['planning','design','frontend','backend','testing']}, 'modes': {}, 'review': {scope: {axis: {**cell,"candidates":[]} for axis in ['standards','spec']} for scope in ['implementation','whole-change']}}
        raw = (json.dumps(config, indent=3)+'\n').encode()
        snapshot = read('ready', raw)
        assert snapshot['config'] == config
        assert snapshot['validation'] == {'valid': True, 'errors': []}
        assert len(snapshot['cells']) == 9
        assert all(cell['status'] == 'unknown' for cell in snapshot['cells'].values())
        path.unlink()
        path.mkdir()
        assert read('unreadable')['base_hash'] is None
    print('show: 6 file states, exact bytes/hash, nine Unknown cells PASS')

if __name__ == '__main__':
    main()
