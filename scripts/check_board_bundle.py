#!/usr/bin/env python3
"""用临时 App 资源运行看板命令，核对随包依赖与 schema 1。"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/delivery-pipeline/scripts'


def read_bundle_snapshot(resources, lanes_root, env):
    result = subprocess.run(
        [sys.executable, '-E', '-B', '-S', str(resources / 'board_snapshot.py'),
         '--lanes-root', str(lanes_root)],
        cwd=lanes_root.parent, env=env, capture_output=True, check=True, timeout=5,
    )
    return json.loads(result.stdout)


def refresh_bundle_linear(resources, lanes_root, env):
    result = subprocess.run(
        [sys.executable, '-E', '-B', '-S', str(resources / 'board_snapshot.py'),
         '--lanes-root', str(lanes_root), '--refresh-linear'],
        cwd=lanes_root.parent, env=env, capture_output=True, check=True, timeout=10,
    )
    return json.loads(result.stdout)


def main():
    sys.path.insert(0, str(SCRIPTS))
    from board_snapshot import validate_snapshot

    spec = importlib.util.spec_from_file_location('delivery_config_build', ROOT / 'apps/delivery-config/build.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)

    # 核对 build.ldflags 对 mcporter 与 node 路径的绑定（有值注入，空值不注入）。
    info = {'commit': 'deadbee', 'dirty': False, 'built_at': '2026-11-27T00:00:00Z'}
    bound = build.ldflags('/usr/bin/python3', info, mcporter='/opt/bin/mcporter', node='/opt/node/bin/node').split()
    assert '-X' in bound and 'main.mcporterPath=/opt/bin/mcporter' in bound, f'ldflags 应绑定 mcporterPath：{bound}'
    assert 'main.nodePath=/opt/node/bin/node' in bound, f'ldflags 应绑定 nodePath：{bound}'
    unbound = build.ldflags('/usr/bin/python3', info, mcporter='', node='').split()
    assert all(not flag.startswith('main.mcporterPath=') for flag in unbound), f'空 mcporter 不应注入：{unbound}'
    assert all(not flag.startswith('main.nodePath=') for flag in unbound), f'空 node 不应注入：{unbound}'

    with tempfile.TemporaryDirectory(prefix='board-bundle-') as tmp:
        directory = Path(tmp).resolve()
        fake = directory / 'herdr'
        fake.write_text(
            '#!/bin/sh\n'
            '[ "$#" -eq 2 ] && [ "$1" = agent ] && [ "$2" = list ] || exit 1\n'
            'echo \'{"result":{"agents":[{"pane_id":"test-pane","name":"test-agent","agent_status":"working"}]}}\'\n',
            encoding='utf-8',
        )
        fake.chmod(0o755)
        env = {**os.environ, 'PATH': f"{directory}{os.pathsep}{os.environ['PATH']}"}
        lanes_root = directory / '.config/delivery-pipeline/lanes'
        map_dir = lanes_root / 'bundle-check'
        map_dir.mkdir(parents=True)
        (map_dir / 'registry.md').write_text(
            '<!-- wayfinder-lane-registry:v2 -->\n```yaml\n'
            'lane_id: bundle-check\nwork_item: DEMO-1\nrole: map\nstate: running\n```\n'
            '<!-- wayfinder-lane-registry:v2 -->\n```yaml\n'
            'lane_id: check\nwork_item: DEMO-2\nrole: review\nstate: running\nruntime: herdr-codex-pane\n'
            'herdr: {"pane_id":"test-pane","agent_name":"test-agent"}\n```\n',
            encoding='utf-8',
        )
        (map_dir / 'driver.json').write_text(
            json.dumps({'version': 1, 'map': 'bundle-check', 'plan': {'tickets': []}}), encoding='utf-8',
        )
        resources = directory / 'Board.app/Contents/Resources'
        build.copy_resources(resources)
        try:
            snapshot = validate_snapshot(read_bundle_snapshot(resources, lanes_root, env))
        except subprocess.CalledProcessError as error:
            raise AssertionError(error.stderr.decode(errors='replace')) from error
        assert snapshot['lanes_root'] == str(lanes_root), '快照应使用传入的 lanes 根'
        [mmf] = snapshot['inbox']
        assert mmf['executing'] and mmf['direct_lanes'][0]['live'] == 'working', '随包探针应被快照实际加载'

        # 核对随包资源的 --refresh-linear：在隔离 PATH 下用假 mcporter 写出并合并缓存。
        fake_mcporter = directory / 'mcporter'
        fake_mcporter.write_text(
            '#!/bin/sh\n'
            'echo \'{"id":"DEMO-1","title":"随包 Linear 标题","status":"In Progress","statusType":"started","parentId":null,"issues":[],"hasNextPage":false}\'\n',
            encoding='utf-8',
        )
        fake_mcporter.chmod(0o755)
        summary = refresh_bundle_linear(resources, lanes_root, env)
        assert summary['status'] == 'ok', f'随包 --refresh-linear 应成功：{summary}'
        merged = validate_snapshot(read_bundle_snapshot(resources, lanes_root, env))
        assert merged.get('linear', {}).get('status') == 'ok', f'随包快照应合并 Linear 缓存：{merged.get("linear")}'

        # 模拟打包只带入口，漏掉快照命令的所有随包依赖。
        incomplete = directory / 'Incomplete.app/Contents/Resources'
        incomplete.mkdir(parents=True)
        shutil.copy2(resources / 'board_snapshot.py', incomplete / 'board_snapshot.py')
        try:
            read_bundle_snapshot(incomplete, lanes_root, env)
        except subprocess.CalledProcessError as error:
            assert b'ModuleNotFoundError' in error.stderr or b'FileNotFoundError' in error.stderr, error.stderr
        else:
            raise AssertionError('仅复制快照入口的错误打包应因缺少依赖而失败')

    print('看板打包检查通过（schema 1，随包探针确认 working，漏带依赖的消融已拒绝）')


if __name__ == '__main__':
    main()
