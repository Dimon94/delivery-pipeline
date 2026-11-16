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
    """构建号三段：提交短哈希、是否有未提交改动（含未跟踪文件，不含 gitignore 排除的）、UTC 构建时间。读不到 git 时 commit='unknown'，不抛异常。"""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    # 钩子等上层会注入 GIT_DIR / GIT_INDEX_FILE，继承会让构建号指向别的仓。
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()

    try:
        commit = git('rev-parse', '--short', 'HEAD') or 'unknown'
        dirty = bool(git('status', '--porcelain')) if commit != 'unknown' else False
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
    """安装被拒；reason 为 running / foreign_bundle / copy_failed。intact=False 仅表示回滚也失败，旧应用在消息给出的备份路径里。"""

    def __init__(self, reason, message, intact=True):
        super().__init__(message)
        self.reason = reason
        self.intact = intact


class VerifyError(Exception):
    """codesign 验签失败；消息带 codesign 的 stderr。"""


def verify(app):
    """验签新包；失败抛 VerifyError（带 codesign stderr），codesign 不可执行时抛 OSError。"""
    try:
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)],
                       check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise VerifyError('codesign 验签失败（退出码 '+str(error.returncode)+'）：'+(error.stderr or '').strip()) from error


def _bundle_id(app):
    try:
        with (app / 'Contents/Info.plist').open('rb') as f:
            return plistlib.load(f).get('CFBundleIdentifier')
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def _is_running(destination):
    """有进程的可执行文件位于 destination/Contents/MacOS/ 下；ps 失败时无法确认，抛 InstallRefused('running')。"""
    prefixes = {str(destination / 'Contents/MacOS') + '/',
                str(destination.resolve() / 'Contents/MacOS') + '/'}
    try:
        ps = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True)
    except OSError as error:
        raise InstallRefused('running', '无法确认应用是否在运行（ps 无法执行：'+str(error)+'），未安装：'+str(destination)) from error
    if ps.returncode != 0:
        raise InstallRefused('running', '无法确认应用是否在运行（ps 退出码 '+str(ps.returncode)+'），未安装：'+str(destination))
    return any(line.strip().startswith(tuple(prefixes)) for line in ps.stdout.splitlines())


def _copy_verified(app, temp):
    try:
        shutil.copytree(app, temp, symlinks=True)
        verify(temp)
    except (OSError, shutil.Error, subprocess.CalledProcessError, VerifyError) as error:
        shutil.rmtree(temp, ignore_errors=True)
        raise InstallRefused('copy_failed', '新包复制或验签失败：'+str(error)) from error


def _warn(message):
    print('警告：'+message, file=sys.stderr)


def _remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _clean_stale(destination, destination_exists):
    """清掉同目录下本应用遗留的 .<name>.new-* 与 .<name>.old-*（只匹配本应用名前缀）。
    目标不存在时 .old-* 可能是回滚失败后唯一的旧包，保留并警告。"""
    new_prefix, old_prefix = '.'+destination.name+'.new-', '.'+destination.name+'.old-'
    for path in sorted(destination.parent.iterdir()):
        if path.name.startswith(old_prefix) and not destination_exists:
            _warn('目标不存在，保留遗留的旧应用备份（可能是上次回滚失败留下的唯一旧包）：'+str(path))
        elif path.name.startswith((new_prefix, old_prefix)):
            try:
                _remove(path)
            except OSError as error:
                _warn('无法清理上次安装遗留的文件，请手动删除：'+str(path)+'（'+str(error)+'）')


def _swap(temp, destination, backup):
    """destination 与 temp 交换，旧包经 backup；失败时尽力回滚，回滚也失败则报告备份路径。"""
    try:
        destination.rename(backup)
    except OSError as error:
        shutil.rmtree(temp, ignore_errors=True)
        raise InstallRefused('copy_failed', '无法移开旧应用，旧应用保持原样：'+str(error)) from error
    try:
        temp.rename(destination)
    except OSError as error:
        shutil.rmtree(temp, ignore_errors=True)
        try:
            backup.rename(destination)
        except OSError as rollback_error:
            raise InstallRefused('copy_failed', '替换失败且回滚失败（'+str(error)+'；'+str(rollback_error)+'）。旧应用完整保存在备份：'
                                 +str(backup)+'，请手动改回 '+str(destination), intact=False) from rollback_error
        raise InstallRefused('copy_failed', '替换失败，旧应用已保留：'+str(error)) from error
    try:
        shutil.rmtree(backup)
    except OSError as error:
        _warn('安装已完成，但旧应用备份没有删干净，请手动删除：'+str(backup)+'（'+str(error)+'）')


def install(app, destination):
    """同级临时目录复制并验签，再与旧包交换；任何拒绝都保持 destination 原状（回滚也失败时除外，见 InstallRefused.intact）。"""
    app, destination = Path(app), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.parent / ('.'+destination.name+'.new-'+str(os.getpid()))
    backup = destination.parent / ('.'+destination.name+'.old-'+str(os.getpid()))
    if destination.is_symlink():
        raise InstallRefused('foreign_bundle', '目标位置是符号链接，未替换：'+str(destination))
    exists = destination.exists()
    if exists:
        if _bundle_id(destination) != BUNDLE_ID:
            raise InstallRefused('foreign_bundle', '目标位置是其他应用，未覆盖：'+str(destination))
        if _is_running(destination):
            raise InstallRefused('running', '应用正在运行，请先退出再安装：'+str(destination))
    _clean_stale(destination, exists)
    _copy_verified(app, temp)
    if exists:
        _swap(temp, destination, backup)
    else:
        try:
            temp.rename(destination)
        except OSError as error:
            shutil.rmtree(temp, ignore_errors=True)
            raise InstallRefused('copy_failed', '新包就位失败：'+str(error)) from error
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
    try:
        verify(app)
    except VerifyError as error:
        raise SystemExit('构建产物验签失败：'+str(error))
    if args.install:
        destination = Path.home() / 'Applications' / app.name
        try:
            app = install(app, destination)
        except InstallRefused as refused:
            raise SystemExit('安装已停止（'+refused.reason+'）'+('，旧应用保持原样' if refused.intact else '')+'：'+str(refused))
    print(summary(app, info))


if __name__ == '__main__':
    main()
