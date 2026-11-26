#!/usr/bin/env python3
"""用临时 App 资源运行看板命令，核对随包依赖与 schema 1。"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/delivery-pipeline/scripts'


def read_bundle_snapshot(resources, lanes_root):
    result = subprocess.run(
        [sys.executable, '-E', '-B', '-S', str(resources / 'board_snapshot.py'),
         '--lanes-root', str(lanes_root)],
        cwd=lanes_root.parent, capture_output=True, check=True, timeout=10,
    )
    return json.loads(result.stdout)


def main():
    sys.path.insert(0, str(SCRIPTS))
    from board_snapshot import validate_snapshot

    spec = importlib.util.spec_from_file_location('delivery_config_build', ROOT / 'apps/delivery-config/build.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)

    with tempfile.TemporaryDirectory(prefix='board-bundle-') as tmp:
        directory = Path(tmp).resolve()
        lanes_root = directory / '.config/delivery-pipeline/lanes'
        map_dir = lanes_root / 'bundle-check'
        map_dir.mkdir(parents=True)
        (map_dir / 'registry.md').write_text(
            '<!-- wayfinder-lane-registry:v2 -->\n```yaml\n'
            'lane_id: bundle-check\nwork_item: DEMO-1\nrole: map\nstate: running\n```\n',
            encoding='utf-8',
        )
        (map_dir / 'driver.json').write_text(
            json.dumps({'version': 1, 'map': 'bundle-check', 'plan': {'tickets': []}}), encoding='utf-8',
        )
        resources = directory / 'Board.app/Contents/Resources'
        build.copy_resources(resources)
        try:
            snapshot = validate_snapshot(read_bundle_snapshot(resources, lanes_root))
        except subprocess.CalledProcessError as error:
            raise AssertionError(error.stderr.decode(errors='replace')) from error
        assert snapshot['lanes_root'] == str(lanes_root), '快照应使用传入的 lanes 根'

        # 模拟打包只带入口，漏掉快照命令的所有随包依赖。
        incomplete = directory / 'Incomplete.app/Contents/Resources'
        incomplete.mkdir(parents=True)
        shutil.copy2(resources / 'board_snapshot.py', incomplete / 'board_snapshot.py')
        try:
            read_bundle_snapshot(incomplete, lanes_root)
        except subprocess.CalledProcessError as error:
            assert b'ModuleNotFoundError' in error.stderr or b'FileNotFoundError' in error.stderr, error.stderr
        else:
            raise AssertionError('仅复制快照入口的错误打包应因缺少依赖而失败')

    print('看板打包检查通过（schema 1，漏带依赖的消融已拒绝）')


if __name__ == '__main__':
    main()
