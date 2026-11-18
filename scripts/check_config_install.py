#!/usr/bin/env python3
"""用临时目录里的假 .app 穿过构建脚本公开的 install，覆盖 Spec DD-581 的 T1–T7、R1、R2、R6；
同样穿过 build_info / build_label / ldflags / stamp_bundle / summary，覆盖 R3 的构建号（DD-583）。

每条 R 另有消融：把 build.py 改成错误实现，同一套检查必须失败；
任何错误实现仍通过，本脚本即失败。
"""
import contextlib
import datetime
import errno
import hashlib
import importlib.util
import io
import os
import pathlib
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

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
    mod.real_verify = mod.verify
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
    except mod.InstallRefused as caught:
        error = caught
        assert error.reason == reason, f'期望 {reason}，实际 {error.reason}'
        assert error.intact, '拒绝时旧应用应完好（仅回滚失败例外）'
    else:
        raise AssertionError(f'期望拒绝 {reason}，但安装成功')
    assert entries(dest.parent) == parent_before, '拒绝后目录里出现了临时件或备份：'+str(entries(dest.parent))
    if before is not None:
        assert snapshot(dest) == before, '拒绝后旧包不是逐字节不变'
    return error


@contextlib.contextmanager
def failing_rename(when):
    """故障注入：满足 when(源, 目标) 的 Path.rename 抛 OSError，其余照常；模拟磁盘、权限或竞争导致的改名失败。"""
    real = pathlib.Path.rename
    def fake(self, target):
        if when(self, target):
            raise OSError(errno.EIO, 'injected rename failure')
        return real(self, target)
    pathlib.Path.rename = fake
    try:
        yield
    finally:
        pathlib.Path.rename = real


@contextlib.contextmanager
def path_env(directory):
    saved = os.environ['PATH']
    os.environ['PATH'] = str(directory)
    try:
        yield
    finally:
        os.environ['PATH'] = saved


def install_quietly(mod, app, dest):
    """返回 (install 结果, stderr 警告文本)。"""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = mod.install(app, dest)
    return result, err.getvalue()


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

        review_checks(mod, source, tmp, new, fresh)
        build_checks(mod, source, tmp)


def old_name(pid=None):
    return '.'+NAME+'.old-'+str(pid or os.getpid())


def new_name(pid=None):
    return '.'+NAME+'.new-'+str(pid or os.getpid())


def check_a_rename_failures(mod, new, fresh):
    """R2：交换阶段的 OSError 一律成为 InstallRefused('copy_failed')，旧包原样，无临时件与备份。"""
    # 旧包移开失败
    parent, dest = fresh('a1')
    make_app(dest, mod.BUNDLE_ID, 'old')
    with failing_rename(lambda src, dst: src.name == NAME):
        refused(mod, new, dest, 'copy_failed')
    # 新包就位失败，回滚成功
    parent, dest = fresh('a2')
    make_app(dest, mod.BUNDLE_ID, 'old')
    with failing_rename(lambda src, dst: src.name.startswith('.'+NAME+'.new-')):
        refused(mod, new, dest, 'copy_failed')
    # 首次安装就位失败：目录保持为空
    parent, dest = fresh('a3')
    with failing_rename(lambda src, dst: src.name.startswith('.'+NAME+'.new-')):
        refused(mod, new, dest, 'copy_failed')
    assert entries(parent) == [], 'a3 不应留下临时件：'+str(entries(parent))
    # 回滚也失败：消息必须给出备份完整路径，备份原样保留，临时件已清
    parent, dest = fresh('a4')
    make_app(dest, mod.BUNDLE_ID, 'old')
    old_snapshot = snapshot(dest)
    backup = parent / old_name()
    with failing_rename(lambda src, dst: src.name.startswith(('.'+NAME+'.new-', '.'+NAME+'.old-'))):
        try:
            mod.install(new, dest)
        except mod.InstallRefused as error:
            assert error.reason == 'copy_failed', error.reason
            assert str(backup) in str(error), 'a4 回滚失败的消息应含备份完整路径：'+str(error)
            assert error.intact is False, 'a4 回滚失败不得声称旧应用原样'
        else:
            raise AssertionError('a4 回滚失败应拒绝')
    assert entries(parent) == [old_name()], 'a4 应只剩备份：'+str(entries(parent))
    assert snapshot(backup) == old_snapshot, 'a4 备份应是逐字节的旧包'


def check_b_backup_and_stale(mod, new, fresh):
    """备份删不掉要警告并留下路径；安装前清理本应用的遗留件，且只清本应用的。"""
    parent, dest = fresh('b1')
    make_app(dest, mod.BUNDLE_ID, 'old')
    backup = parent / old_name()
    remove = shutil.rmtree

    def fail_backup_removal(path, *args, **kwargs):
        if Path(path) == backup:
            # 错误本身不提供路径，验证应用能明确报告残留位置。
            raise PermissionError(errno.EACCES, 'injected backup removal failure')
        return remove(path, *args, **kwargs)

    with patch.object(shutil, 'rmtree', side_effect=fail_backup_removal):
        result, warning = install_quietly(mod, new, dest)
    assert result == dest and snapshot(dest) == snapshot(new), 'b1 备份删不掉时安装仍应成功'
    assert backup.exists(), 'b1 删不掉的备份应留在原处'
    assert str(backup) in warning, 'b1 警告必须带残留路径：'+repr(warning)
    # 下一次安装先清掉遗留的备份
    install_quietly(mod, new, dest)
    assert entries(parent) == [NAME], 'b1 下一次安装应清掉遗留备份：'+str(entries(parent))

    # 只清本应用名前缀的遗留件
    parent, dest = fresh('b2')
    make_app(dest, mod.BUNDLE_ID, 'old')
    stale = ['.'+NAME+'.new-111', '.'+NAME+'.old-222']
    keep = ['.Other.app.new-111', '.Other.app.old-222', NAME+'.new-111', '.'+NAME+'.newer', '.'+NAME, 'notes.txt']
    for name in stale:
        make_app(parent / name, mod.BUNDLE_ID, 'stale')
    for name in keep:
        if name.endswith('.txt') or name == '.'+NAME:
            (parent / name).write_text('keep')
        else:
            make_app(parent / name, mod.BUNDLE_ID, 'keep')
    install_quietly(mod, new, dest)
    assert entries(parent) == sorted([NAME, *keep]), 'b2 只应清本应用的遗留件：'+str(entries(parent))

    # 目标不存在时，遗留的 .old-* 可能是回滚失败后唯一的旧包：保留并警告
    parent, dest = fresh('b3')
    make_app(parent / old_name(333), mod.BUNDLE_ID, 'only-copy')
    kept = snapshot(parent / old_name(333))
    make_app(parent / new_name(333), mod.BUNDLE_ID, 'junk')
    _, warning = install_quietly(mod, new, dest)
    assert entries(parent) == sorted([NAME, old_name(333)]), 'b3：'+str(entries(parent))
    assert snapshot(parent / old_name(333)) == kept, 'b3 遗留备份应原样保留'
    assert str(parent / old_name(333)) in warning, 'b3 应警告遗留备份路径：'+repr(warning)


def check_c_ps_failure(mod, new, fresh, tmp):
    """ps 失败时无法确认是否在运行，按拒绝处理。"""
    bin_dir = tmp / 'fake-bin'
    bin_dir.mkdir()
    ps = bin_dir / 'ps'
    ps.write_text('#!/bin/sh\necho boom >&2\nexit 1\n')
    ps.chmod(0o755)
    for index, (label, directory) in enumerate((('ps 非零退出', bin_dir), ('找不到 ps', tmp / 'empty-bin'))):
        parent, dest = fresh('c'+str(index))
        make_app(dest, mod.BUNDLE_ID, 'old')
        with path_env(directory):
            error = refused(mod, new, dest, 'running')
        assert '无法确认' in str(error), f'{label}：消息应说明无法确认：{error}'


def check_d_symlink(mod, new, fresh, tmp):
    """目标是符号链接：拒绝，不替换链接，也不动链接指向的应用。"""
    parent, dest = fresh('d1')
    target = make_app(tmp / 'd1-real.app', mod.BUNDLE_ID, 'real')
    dest.symlink_to(target)
    target_before = snapshot(target)
    refused(mod, new, dest, 'foreign_bundle')
    assert dest.is_symlink() and os.readlink(dest) == str(target), 'd1 链接应保持不变'
    assert snapshot(target) == target_before, 'd1 链接指向的应用不应被改'
    parent, dest = fresh('d2')
    dest.symlink_to(tmp / 'd2-missing.app')  # 悬空链接
    refused(mod, new, dest, 'foreign_bundle')
    assert dest.is_symlink(), 'd2 悬空链接应保持不变'


def check_g_verify_stderr(mod, tmp):
    """真实 verify 失败时，codesign 的 stderr 进入异常文本（main 与复制验签都据此报告）。"""
    bin_dir = tmp / 'fake-codesign'
    bin_dir.mkdir()
    codesign = bin_dir / 'codesign'
    codesign.write_text('#!/bin/sh\necho "a sealed resource is missing or invalid" >&2\nexit 1\n')
    codesign.chmod(0o755)
    with path_env(str(bin_dir)+os.pathsep+os.environ['PATH']):
        try:
            mod.real_verify(tmp / 'whatever.app')
        except Exception as error:
            assert 'a sealed resource is missing or invalid' in str(error), 'g verify 失败应带 codesign stderr：'+str(error)
        else:
            raise AssertionError('g 假 codesign 失败时 verify 应抛异常')


def check_g_copy_verify_error(mod, new, fresh):
    """复制后的验签抛 VerifyError（真实 verify 的失败形态）：同样成为 copy_failed，消息带原因，旧包原样。"""
    parent, dest = fresh('g2')
    make_app(dest, mod.BUNDLE_ID, 'old')
    fake = mod.verify
    def failing(app):
        raise mod.VerifyError('codesign 验签失败：invalid signature marker')
    mod.verify = failing
    try:
        error = refused(mod, new, dest, 'copy_failed')
    finally:
        mod.verify = fake
    assert 'invalid signature marker' in str(error), 'g2 消息应带验签原因：'+str(error)


def review_checks(mod, source, tmp, new, fresh):
    check_a_rename_failures(mod, new, fresh)
    check_b_backup_and_stale(mod, new, fresh)
    check_c_ps_failure(mod, new, fresh, tmp)
    check_d_symlink(mod, new, fresh, tmp)
    check_g_verify_stderr(mod, tmp)
    check_g_copy_verify_error(mod, new, fresh)
    main_src = source[source.index('def main()'):]
    assert 'except VerifyError' in main_src, 'g main 应处理验签失败'
    handler = main_src.split('except VerifyError')[1].split('\n')[1]
    assert 'SystemExit(' in handler and 'str(error)' in handler, 'g main 验签失败应带 codesign 原因退出：'+handler
    assert 'refused.intact' in main_src, 'a main 回滚失败时不得声称旧应用原样'


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-C', str(repo), *args],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


def build_checks(mod, source, tmp):
    """R3：构建号三段、写入 Info.plist 与二进制 ldflags、读不到 git 不中断。期望值来自 Spec 示例与独立的 git 命令。"""
    at = datetime.datetime(2026, 11, 16, 6, 40, 0, tzinfo=datetime.timezone.utc)

    # build_label：Spec 示例格式
    assert mod.build_label({'commit': '658b108', 'dirty': False, 'built_at': '2026-11-16T06:40:00Z'}) == '658b108 · 2026-11-16 06:40Z', 'R3 label 格式'
    assert mod.build_label({'commit': '658b108', 'dirty': True, 'built_at': '2026-11-16T06:40:00Z'}) == '658b108+未提交 · 2026-11-16 06:40Z', 'R3 dirty 标记'
    assert mod.build_label({'commit': 'unknown', 'dirty': False, 'built_at': '2026-11-16T06:40:00Z'}) == 'unknown · 2026-11-16 06:40Z', 'R3 unknown'

    # build_info：真实 git 仓
    repo = tmp / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'a.txt').write_text('one')
    git(repo, 'add', 'a.txt')
    git(repo, 'commit', '-q', '-m', 'init')
    full = git(repo, 'rev-parse', 'HEAD')
    info = mod.build_info(repo, now=at)
    assert full.startswith(info['commit']) and 7 <= len(info['commit']) < len(full), f'R3 commit 应为 HEAD 短哈希：{info}'
    assert info['dirty'] is False and info['built_at'] == '2026-11-16T06:40:00Z', f'R3 干净仓与 UTC 时间：{info}'
    (repo / 'a.txt').write_text('two')
    assert mod.build_info(repo, now=at)['dirty'] is True, 'R3 已跟踪文件有未提交改动应标 dirty'
    # 只有未跟踪文件也算未提交；被 .gitignore 排除的不算
    only_new = tmp / 'repo-untracked'
    only_new.mkdir()
    git(only_new, 'init', '-q')
    (only_new / '.gitignore').write_text('ignored.log\n')
    git(only_new, 'add', '.gitignore')
    git(only_new, 'commit', '-q', '-m', 'init')
    assert mod.build_info(only_new, now=at)['dirty'] is False, 'R3 干净仓不应 dirty'
    (only_new / 'ignored.log').write_text('x')
    assert mod.build_info(only_new, now=at)['dirty'] is False, 'R3 gitignore 排除的文件不算 dirty'
    (only_new / 'new.txt').write_text('x')
    assert mod.build_info(only_new, now=at)['dirty'] is True, 'R3 只有未跟踪文件也应标 dirty'
    # 钩子环境变量不得把构建号指向别的仓
    other = tmp / 'not-a-repo'
    other.mkdir()
    saved = os.environ.get('GIT_DIR')
    os.environ['GIT_DIR'] = str(repo / '.git')
    try:
        assert mod.build_info(other, now=at)['commit'] == 'unknown', 'R3 不继承 GIT_DIR'
    finally:
        if saved is None:
            del os.environ['GIT_DIR']
        else:
            os.environ['GIT_DIR'] = saved

    # 读不到 git：commit=unknown，不抛异常，构建继续
    assert mod.build_info(other, now=at) == {'commit': 'unknown', 'dirty': False, 'built_at': '2026-11-16T06:40:00Z'}, 'R3 非仓库'
    saved_path = os.environ['PATH']
    os.environ['PATH'] = str(tmp / 'empty-bin')
    try:
        assert mod.build_info(repo, now=at)['commit'] == 'unknown', 'R3 无 git 可执行文件'
    finally:
        os.environ['PATH'] = saved_path

    # 二进制：ldflags 与既有 pythonPath 并列注入三段
    flags = mod.ldflags('/usr/bin/python3', {'commit': '658b108', 'dirty': True, 'built_at': '2026-11-16T06:40:00Z'}).split()
    for expected in ('-X', 'main.pythonPath=/usr/bin/python3', 'main.buildCommit=658b108', 'main.buildDirty=true', 'main.builtAt=2026-11-16T06:40:00Z'):
        assert expected in flags, f'R3 ldflags 缺 {expected}：{flags}'

    # Info.plist：CFBundleVersion=build_label，其余键不动
    app = make_app(tmp / 'stamp/x.app', mod.BUNDLE_ID, 'old')
    with (app / 'Contents/Info.plist').open('rb') as f:
        plist = plistlib.load(f)
    plist['CFBundleShortVersionString'] = '0.1.0'
    with (app / 'Contents/Info.plist').open('wb') as f:
        plistlib.dump(plist, f)
    info = {'commit': '658b108', 'dirty': False, 'built_at': '2026-11-16T06:40:00Z'}
    mod.stamp_bundle(app, info)
    with (app / 'Contents/Info.plist').open('rb') as f:
        plist = plistlib.load(f)
    assert plist['CFBundleVersion'] == '658b108 · 2026-11-16 06:40Z', f'R3 CFBundleVersion：{plist}'
    assert plist['CFBundleShortVersionString'] == '0.1.0' and plist['CFBundleIdentifier'] == mod.BUNDLE_ID, 'R3 不改其他键'

    # 安装输出：构建号与路径都在
    text = mod.summary(Path('/Users/x/Applications/Delivery Pipeline Settings.app'), info)
    assert '658b108 · 2026-11-16 06:40Z' in text and '/Users/x/Applications/Delivery Pipeline Settings.app' in text, f'R3 输出：{text}'

    # 写入必须在 codesign 之前，否则改过的 Info.plist 会让签名失效
    main_src = source[source.index('def main()'):]
    assert 0 <= main_src.index('stamp_bundle(') < main_src.index("'codesign'"), 'R3 stamp_bundle 必须先于 codesign'
    assert "'MYGO_LDFLAGS': ldflags(" in main_src, 'R3 构建需把构建号注入二进制'
    assert 'print(summary(app, info))' in main_src, 'R3 命令行必须打印构建号与（安装后的）路径'


# 错误实现：(消融名, 被替换的片段, 替换成)
MUTANTS = [
    ('T2/R1 交换后不删除备份',
     "        shutil.rmtree(backup)\n    except OSError as error:", "        pass\n    except OSError as error:"),
    ('T3 去掉运行检查', "if _is_running(destination):", "if False:"),
    ('T4 去掉 bundle id 检查', "if _bundle_id(destination) != BUNDLE_ID:", "if False:"),
    ('R2 先删旧包再复制',
     "    _copy_verified(app, temp)\n    if exists:\n        _swap(",
     "    if exists:\n        shutil.rmtree(destination)\n    _copy_verified(app, temp)\n    if exists:\n        destination.mkdir()\n        _swap("),
    ('T5/T6 失败不清理临时件',
     "        shutil.rmtree(temp, ignore_errors=True)\n        raise InstallRefused('copy_failed', '新包复制或验签失败：'",
     "        raise InstallRefused('copy_failed', '新包复制或验签失败：'"),
    ('T5 验签失败当作成功', "        verify(temp)\n", "        pass\n"),
    ('T7 运行检查永远拒绝', "if _is_running(destination):", "if True:"),
    ('R2/a 旧包移开失败不转 InstallRefused',
     "        destination.rename(backup)\n    except OSError as error:", "        destination.rename(backup)\n    except KeyError as error:"),
    ('R2/a 旧包移开失败不清临时件',
     "        shutil.rmtree(temp, ignore_errors=True)\n        raise InstallRefused('copy_failed', '无法移开旧应用", "        raise InstallRefused('copy_failed', '无法移开旧应用"),
    ('R2/a 新包就位失败不转 InstallRefused',
     "    try:\n        temp.rename(destination)\n    except OSError as error:", "    try:\n        temp.rename(destination)\n    except KeyError as error:"),
    ('R2/a 新包就位失败不回滚', "            backup.rename(destination)\n", "            pass\n"),
    ('R2/a 新包就位失败不清临时件',
     "        shutil.rmtree(temp, ignore_errors=True)\n        try:\n            backup.rename", "        try:\n            backup.rename"),
    ('R2/a 回滚失败 OSError 外泄', "except OSError as rollback_error:", "except KeyError as rollback_error:"),
    ('R2/a 回滚失败消息不含备份路径', "+str(backup)+'，请手动改回 '", "+'，请手动改回 '"),
    ('R2/a 回滚失败仍声称旧应用原样', ", intact=False)", ")"),
    ('R2/a 首次安装就位失败不转 InstallRefused',
     "        try:\n            temp.rename(destination)\n        except OSError as error:", "        try:\n            temp.rename(destination)\n        except KeyError as error:"),
    ('R2/a 首次安装就位失败不清临时件',
     "            shutil.rmtree(temp, ignore_errors=True)\n            raise InstallRefused('copy_failed', '新包就位失败", "            raise InstallRefused('copy_failed', '新包就位失败"),
    ('b 备份删不掉仍静默', "        _warn('安装已完成，但旧应用备份没有删干净，请手动删除：'+str(backup)+'（'+str(error)+'）')", "        pass"),
    ('b 警告不含残留路径', "请手动删除：'+str(backup)+'（'", "请手动删除。（'"),
    ('b 备份删不掉让安装失败', "    except OSError as error:\n        _warn('安装已完成", "    except KeyError as error:\n        _warn('安装已完成"),
    ('b 安装前不清遗留件', "    _clean_stale(destination, exists)\n", ""),
    ('b 清理不看应用名前缀', "        elif path.name.startswith((new_prefix, old_prefix)):", "        elif True:"),
    ('b 清理前缀丢掉开头的点', "new_prefix, old_prefix = '.'+destination.name+'.new-', '.'+destination.name+'.old-'", "new_prefix, old_prefix = destination.name+'.new-', destination.name+'.old-'"),
    ('b 只清 .new- 不清 .old-', "startswith((new_prefix, old_prefix)):", "startswith(new_prefix):"),
    ('b 目标不存在也删遗留备份', "if path.name.startswith(old_prefix) and not destination_exists:", "if False:"),
    ('c ps 非零退出当作未运行', "    if ps.returncode != 0:\n        raise", "    if False:\n        raise"),
    ('c ps 无法执行时抛 OSError', "    except OSError as error:\n        raise InstallRefused('running'", "    except KeyError as error:\n        raise InstallRefused('running'"),
    ('c ps 非零的消息不说明无法确认', "'无法确认应用是否在运行（ps 退出码 '", "'ps 失败（退出码 '"),
    ('c ps 无法执行的消息不说明无法确认', "'无法确认应用是否在运行（ps 无法执行：'", "'ps 无法执行：'"),
    ('d 不拒绝符号链接目标', "    if destination.is_symlink():", "    if False:"),
    ('g verify 丢掉 codesign stderr', "+(error.stderr or '').strip()", ""),
    ('g 复制验签不捕获 VerifyError', "subprocess.CalledProcessError, VerifyError) as error:", "subprocess.CalledProcessError) as error:"),
    ('g main 不处理 VerifyError', "    except VerifyError as error:", "    except KeyError as error:"),
    ('g main 验签失败不带原因', "raise SystemExit('构建产物验签失败：'+str(error))", "raise SystemExit('构建产物验签失败')"),
    ('R6 BUNDLE_ID 与 MyGo 不一致',
     "BUNDLE_ID = 'com.dimon.delivery-pipeline.settings'", "BUNDLE_ID = 'com.dimon.delivery-pipeline.settings.test'"),
    ('R6 增加改 bundle id 的参数',
     "    parser.add_argument('--install', action='store_true')\n",
     "    parser.add_argument('--install', action='store_true')\n    parser.add_argument('--bundle-id')\n"),
    ('R3 label 丢掉未提交标记', "info['commit'] + ('+未提交' if info['dirty'] else '') + ' · '", "info['commit'] + ' · '"),
    ('R3 label 时间保留 T', ".replace('T', ' ')", ""),
    ('R3 dirty 永远为假',
     "dirty = bool(git('status', '--porcelain')) if commit != 'unknown' else False", "dirty = False"),
    ('R3 dirty 忽略未跟踪文件', "git('status', '--porcelain')", "git('status', '--porcelain', '--untracked-files=no')"),
    ('R3 dirty 把 gitignore 排除的文件也算上', "git('status', '--porcelain')", "git('status', '--porcelain', '--ignored')"),
    ('R3 commit 用完整哈希', "'rev-parse', '--short', 'HEAD'", "'rev-parse', 'HEAD'"),
    ('R3 非仓库时抛异常', "except (OSError, subprocess.CalledProcessError):", "except OSError:"),
    ('R3 无 git 时抛异常', "except (OSError, subprocess.CalledProcessError):", "except subprocess.CalledProcessError:"),
    ('R3 继承 GIT_ 环境变量', "if not k.startswith('GIT_')}", "if True}"),
    ('R3 时间不是 UTC', "now.astimezone(datetime.timezone.utc)", "now.astimezone(datetime.timezone(datetime.timedelta(hours=8)))"),
    ('R3 ldflags 缺 dirty', "'-X main.buildDirty='+('true' if info['dirty'] else 'false')", "'-X main.buildDirty=false'"),
    ('R3 ldflags commit 写死', "'-X main.buildCommit='+info['commit']", "'-X main.buildCommit=unknown'"),
    ('R3 ldflags 缺 builtAt', ", '-X main.builtAt='+info['built_at']", ""),
    ('R3 构建没把 ldflags 交给 MyGo', "'MYGO_LDFLAGS': ldflags(python, info)", "'MYGO_LDFLAGS': '-X main.pythonPath='+str(python)"),
    ('R3 Info.plist 写错键', "plist['CFBundleVersion'] = build_label(info)", "plist['CFBundleShortVersionString'] = build_label(info)"),
    ('R3 Info.plist 只写哈希', "plist['CFBundleVersion'] = build_label(info)", "plist['CFBundleVersion'] = info['commit']"),
    ('R3 签名后才写 Info.plist',
     "    stamp_bundle(app, info)\n    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)], check=True)\n",
     "    subprocess.run(['codesign','--force','--deep','--sign','-',str(app)], check=True)\n    stamp_bundle(app, info)\n"),
    ('R3 输出缺构建号', "return '构建号：'+build_label(info)+'\\n路径：'+str(app)", "return '路径：'+str(app)"),
    ('R3 输出缺路径', "return '构建号：'+build_label(info)+'\\n路径：'+str(app)", "return '构建号：'+build_label(info)"),
    ('R3 命令行不打印构建号', "print(summary(app, info))", "print(app)"),
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
