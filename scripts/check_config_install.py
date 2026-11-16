#!/usr/bin/env python3
"""用临时目录里的假 .app 穿过构建脚本公开的 install，覆盖 Spec DD-581 的 T1–T7、R1、R2、R6。

每条 R 另有消融：把 build.py 改成错误实现，同一套检查必须失败；
任何错误实现仍通过，本脚本即失败。
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'apps/delivery-config/build.py'
MYGO = ROOT / 'apps/delivery-config/mygo.config.ts'
NAME = 'Delivery Pipeline Settings.app'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 假 .app 没有真实签名：以“Contents/MacOS 下有可执行文件”代替 codesign，失败点与真实验签相同。
    def fake_verify(app):
        exe = Path(app) / 'Contents/MacOS'
        if not exe.is_dir() or not any(p.is_file() and os.access(p, os.X_OK) for p in exe.iterdir()):
            raise subprocess.CalledProcessError(1, 'codesign')
    mod.verify = fake_verify
    return mod


def make_app(path, bundle_id, payload, executable=True):
    macos = path / 'Contents/MacOS'
    macos.mkdir(parents=True)
    with (path / 'Contents/Info.plist').open('wb') as f:
        plistlib.dump({'CFBundleIdentifier': bundle_id, 'CFBundleVersion': payload}, f)
    (path / 'Contents/Resources').mkdir()
    (path / 'Contents/Resources/payload.txt').write_text(payload)
    if executable:
        exe = macos / 'settings'
        exe.write_text('#!/bin/sh\n')
        exe.chmod(0o755)
    return path


def snapshot(path):
    """目录树的逐字节指纹：相对路径、类型、权限、文件内容。"""
    out = {}
    for p in sorted([path, *path.rglob('*')]):
        rel = str(p.relative_to(path))
        if p.is_symlink():
            out[rel] = ('link', os.readlink(p))
        elif p.is_dir():
            out[rel] = ('dir', p.stat().st_mode)
        else:
            out[rel] = ('file', p.stat().st_mode, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def entries(parent):
    return sorted(p.name for p in parent.iterdir())


def refused(mod, app, dest, reason):
    before = snapshot(dest) if dest.exists() else None
    parent_before = entries(dest.parent)
    try:
        mod.install(app, dest)
    except mod.InstallRefused as error:
        assert error.reason == reason, f'期望 {reason}，实际 {error.reason}'
    else:
        raise AssertionError(f'期望拒绝 {reason}，但安装成功')
    assert entries(dest.parent) == parent_before, '拒绝后目录里出现了临时件或备份：'+str(entries(dest.parent))
    if before is not None:
        assert snapshot(dest) == before, '拒绝后旧包不是逐字节不变'


def run_checks(mod, source):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        new = make_app(tmp / 'src/new.app', mod.BUNDLE_ID, 'new')
        def fresh(name):
            parent = tmp / name
            parent.mkdir()
            return parent, parent / NAME

        # T1：目标不存在，首次安装
        parent, dest = fresh('t1')
        assert mod.install(new, dest) == dest
        assert snapshot(dest) == snapshot(new) and entries(parent) == [NAME], 'T1 内容或残件'

        # T2、R1：覆盖升级，只剩一个 .app 且无备份或临时件
        parent, dest = fresh('t2')
        make_app(dest, mod.BUNDLE_ID, 'old')
        mod.install(new, dest)
        assert snapshot(dest) == snapshot(new), 'T2 内容应等于新包'
        assert entries(parent) == [NAME], 'R1 目录里只能剩一个 .app：'+str(entries(parent))

        # T3、T7：运行中被拒，结束进程后重新安装成功
        parent, dest = fresh('t3')
        make_app(dest, mod.BUNDLE_ID, 'old')
        sleeper = dest / 'Contents/MacOS/sleep'
        shutil.copyfile('/bin/sleep', sleeper)
        sleeper.chmod(0o755)
        subprocess.run(['codesign', '--force', '--sign', '-', str(sleeper)], check=True, capture_output=True)  # 复制的系统二进制会被内核拒绝，需重签
        proc = subprocess.Popen([str(sleeper), '60'])
        try:
            for _ in range(50):
                if str(sleeper) in subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True).stdout:
                    break
                time.sleep(0.1)
            assert proc.poll() is None, '假运行进程没有启动'
            refused(mod, new, dest, 'running')
        finally:
            proc.kill()
            proc.wait()
        mod.install(new, dest)
        assert snapshot(dest) == snapshot(new) and entries(parent) == [NAME], 'T7 解除原因后应升级成功'

        # T4：目标是其他 bundle id
        parent, dest = fresh('t4')
        make_app(dest, 'com.example.other', 'foreign')
        refused(mod, new, dest, 'foreign_bundle')

        # T5、R2：新包验签失败，旧包逐字节不变且无临时件
        broken = make_app(tmp / 'src/broken.app', mod.BUNDLE_ID, 'broken', executable=False)
        parent, dest = fresh('t5')
        make_app(dest, mod.BUNDLE_ID, 'old')
        refused(mod, broken, dest, 'copy_failed')

        # T6：目标不存在且新包验签失败，目录保持为空
        parent, dest = fresh('t6')
        refused(mod, broken, dest, 'copy_failed')
        assert entries(parent) == [], 'T6 不应留下残件'

        # R6：构建只有一个 bundle id，等于 MyGo 配置，且没有修改它的参数
        identifier = re.search(r'identifier:\s*"([^"]+)"', MYGO.read_text()).group(1)
        assert mod.BUNDLE_ID == identifier, f'R6 BUNDLE_ID {mod.BUNDLE_ID} != MyGo identifier {identifier}'
        flags = re.findall(r"add_argument\(\s*'(--[\w-]+)'", source)
        assert sorted(flags) == ['--install', '--python'], 'R6 构建脚本不应有改 bundle id 的参数：'+str(flags)


# 错误实现：(消融名, 被替换的片段, 替换成)
MUTANTS = [
    ('T2/R1 交换后不删除备份',
     "        shutil.rmtree(backup, ignore_errors=True)\n    else:", "        pass\n    else:"),
    ('T3 去掉运行检查', "if _is_running(destination):", "if False:"),
    ('T4 去掉 bundle id 检查', "if _bundle_id(destination) != BUNDLE_ID:", "if False:"),
    ('R2 先删旧包再复制',
     "        _copy_verified(app, temp)\n        destination.rename(backup)",
     "        shutil.rmtree(destination)\n        _copy_verified(app, temp)\n        destination.mkdir()\n        destination.rename(backup)"),
    ('T5/T6 失败不清理临时件',
     "        shutil.rmtree(temp, ignore_errors=True)\n        raise InstallRefused('copy_failed', '新包复制或验签失败：'",
     "        raise InstallRefused('copy_failed', '新包复制或验签失败：'"),
    ('T5 验签失败当作成功', "        verify(temp)\n", "        pass\n"),
    ('T7 运行检查永远拒绝', "if _is_running(destination):", "if True:"),
    ('R6 BUNDLE_ID 与 MyGo 不一致',
     "BUNDLE_ID = 'com.dimon.delivery-pipeline.settings'", "BUNDLE_ID = 'com.dimon.delivery-pipeline.settings.test'"),
    ('R6 增加改 bundle id 的参数',
     "    parser.add_argument('--install', action='store_true')\n",
     "    parser.add_argument('--install', action='store_true')\n    parser.add_argument('--bundle-id')\n"),
]


def main():
    source = BUILD.read_text()
    run_checks(load(BUILD, 'build_real'), source)
    print('install contract: pass')
    with tempfile.TemporaryDirectory() as tmp:
        for index, (name, old, new) in enumerate(MUTANTS):
            assert source.count(old) == 1, f'消融片段失效（build.py 已变）：{name}'
            mutant = Path(tmp) / f'build_mutant_{index}.py'
            mutant.write_text(source.replace(old, new))
            mod = load(mutant, f'build_mutant_{index}')
            try:
                run_checks(mod, mutant.read_text())
            except Exception as error:
                print(f'  killed {name}：{type(error).__name__}: {str(error)[:60]}')
                continue
            sys.exit(f'消融未被发现：{name}')
    print(f'install ablations: {len(MUTANTS)} killed')


if __name__ == '__main__':
    main()
