#!/usr/bin/env python3
"""本机构建：绑定解释器，携带同源工具，ad-hoc 签名；`--install` 就地升级同一 bundle id 的旧应用。"""
import argparse
import datetime
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
BUNDLE_ID = 'com.dimon.delivery-pipeline.settings'


def build_info(repo, now=None):
    """构建号三段：提交短哈希、已跟踪文件是否有未提交改动、UTC 构建时间。读不到 git 时 commit='unknown'，不抛异常。"""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    # 钩子等上层会注入 GIT_DIR / GIT_INDEX_FILE，继承会让构建号指向别的仓。
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()

    try:
        commit = git('rev-parse', '--short', 'HEAD') or 'unknown'
        dirty = bool(git('status', '--porcelain', '--untracked-files=no')) if commit != 'unknown' else False
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = 'unknown', False
    return {'commit': commit, 'dirty': dirty, 'built_at': now.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}


def build_label(info):
    """例：'658b108 · 2026-11-16 06:40Z'；有未提交改动时 '658b108+未提交 · …'。Go 的 AppInfo.Build 同格式。"""
    return info['commit'] + ('+未提交' if info['dirty'] else '') + ' · ' + info['built_at'][:16].replace('T', ' ') + 'Z'


def ldflags(python, info):
    """二进制注入：与既有 main.pythonPath 并列。"""
    return ' '.join(['-X main.pythonPath='+str(python), '-X main.buildCommit='+info['commit'],
                     '-X main.buildDirty='+('true' if info['dirty'] else 'false'), '-X main.builtAt='+info['built_at']])


def stamp_bundle(app, info):
    """把构建号写进 Info.plist 的 CFBundleVersion；必须在 codesign 之前，否则签名失效。"""
    path = Path(app) / 'Contents/Info.plist'
    with path.open('rb') as f:
        plist = plistlib.load(f)
    plist['CFBundleVersion'] = build_label(info)
    with path.open('wb') as f:
        plistlib.dump(plist, f)


def summary(app, info):
    return '构建号：'+build_label(info)+'\n路径：'+str(app)


class InstallRefused(Exception):
    """安装被拒；reason 为 running / foreign_bundle / copy_failed，拒绝时目标保持原状。"""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def verify(app):
    """验签新包；失败抛 CalledProcessError / OSError。"""
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)],
                   check=True, capture_output=True)


def _bundle_id(app):
    try:
        with (app / 'Contents/Info.plist').open('rb') as f:
            return plistlib.load(f).get('CFBundleIdentifier')
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def _is_running(destination):
    """有进程的可执行文件位于 destination/Contents/MacOS/ 下。"""
    prefixes = {str(destination / 'Contents/MacOS') + '/',
                str(destination.resolve() / 'Contents/MacOS') + '/'}
    out = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True).stdout
    return any(line.strip().startswith(tuple(prefixes)) for line in out.splitlines())


def _copy_verified(app, temp):
    try:
        shutil.copytree(app, temp, symlinks=True)
        verify(temp)
    except (OSError, shutil.Error, subprocess.CalledProcessError) as error:
        shutil.rmtree(temp, ignore_errors=True)
        raise InstallRefused('copy_failed', '新包复制或验签失败：'+str(error)) from error


def install(app, destination):
    """同级临时目录复制并验签，再与旧包交换；任何拒绝都保持 destination 原状。"""
    app, destination = Path(app), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.parent / ('.'+destination.name+'.new-'+str(os.getpid()))
    backup = destination.parent / ('.'+destination.name+'.old-'+str(os.getpid()))
    if destination.exists():
        if _bundle_id(destination) != BUNDLE_ID:
            raise InstallRefused('foreign_bundle', '目标位置是其他应用，未覆盖：'+str(destination))
        if _is_running(destination):
            raise InstallRefused('running', '应用正在运行，请先退出再安装：'+str(destination))
        _copy_verified(app, temp)
        destination.rename(backup)
        try:
            temp.rename(destination)
        except OSError as error:
            backup.rename(destination)
            shutil.rmtree(temp, ignore_errors=True)
            raise InstallRefused('copy_failed', '替换失败，旧应用已保留：'+str(error)) from error
        shutil.rmtree(backup, ignore_errors=True)
    else:
        _copy_verified(app, temp)
        temp.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    python = Path(args.python).resolve()
    subprocess.run([str(python), '-c', 'import sys; assert sys.version_info >= (3,10), "需要 Python >= 3.10"'], check=True)
    info = build_info(root)
    subprocess.run(['bun', 'run', 'build', '-skip-dmg'], cwd=root, env={**os.environ, 'MYGO_LDFLAGS': ldflags(python, info)}, check=True)
    app = next((root / 'build').glob('darwin-*/*.app'))
    canonical = root.parents[1] / 'skills/delivery-pipeline-setup/scripts'
    resources = app / 'Contents/Resources'
    shutil.copy2(canonical / 'model_config.py', resources / 'model_config.py')
    shutil.copytree(canonical / '_vendor', resources / '_vendor', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # 对最终资源执行隔离 probe，防止源码可用但应用漏带依赖。
    subprocess.run([str(python), str(root.parents[1] / 'scripts/check_config_toml.py'),
                    '--python', str(python), '--tool', str(resources / 'model_config.py')], check=True)
    stamp_bundle(app, info)
    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)], check=True)
    verify(app)
    if args.install:
        destination = Path.home() / 'Applications' / app.name
        try:
            app = install(app, destination)
        except InstallRefused as refused:
            raise SystemExit('安装已停止（'+refused.reason+'），旧应用保持原样：'+str(refused))
    print(summary(app, info))


if __name__ == '__main__':
    main()
