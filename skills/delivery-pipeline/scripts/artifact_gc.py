#!/usr/bin/env python3
"""按保留期清理 delivery-pipeline 工件树。

单元 = 各工件根目录的直接子项（lanes/artifacts 再下钻一层）与根目录下 map* 散落文件。
单元内最新 mtime 早于保留期且不含 `.keep` 才过期。默认只预览；`--apply` 才删除。
配置（model-roles.json*）、bin/ 与其他未列出的路径从不触碰。

用法：artifact_gc.py [--root DIR] [--days 14] [--apply] [--json]
      artifact_gc.py install-schedule [--days 14] [--hour 4]   # macOS launchd，每天 --apply
      artifact_gc.py uninstall-schedule
      artifact_gc.py self-test
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time

DEFAULT_ROOT = Path.home() / ".config" / "delivery-pipeline"
LABEL = "com.delivery-pipeline.artifact-gc"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
GC_DIRS = ("lanes", "lanes/artifacts", "artifacts", "review-bundles", "review-evidence",
           "packets", "checkpoints", "reports", "logs", "private-backups")
NESTED = {"lanes": {"artifacts"}}
KEEP = ".keep"


def units(root: Path):
    for rel in GC_DIRS:
        base = root / rel
        if not base.is_dir() or base.is_symlink():
            continue
        skip = NESTED.get(rel, set())
        for entry in os.scandir(base):
            if entry.name not in skip:
                yield Path(entry.path)
    for entry in os.scandir(root):
        if entry.is_file(follow_symlinks=False) and entry.name.startswith("map"):
            yield Path(entry.path)
        elif entry.is_dir(follow_symlinks=False) and entry.name.startswith("orca-"):
            yield Path(entry.path)


def fresh_or_kept(path: Path, cutoff: float) -> bool:
    """发现任一新于 cutoff 的文件或 .keep 即返回 True（提前退出）。"""
    if path.lstat().st_mtime >= cutoff:
        return True
    if not path.is_dir() or path.is_symlink():
        return False
    stack = [path]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            return True  # 读不了就当活跃，不删
        for entry in entries:
            if entry.name == KEEP:
                return True
            st = entry.stat(follow_symlinks=False)
            if st.st_mtime >= cutoff:
                return True
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
    return False


def size_of(path: Path) -> int:
    if not path.is_dir() or path.is_symlink():
        return path.lstat().st_size
    total, stack = 0, [path]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            else:
                total += entry.stat(follow_symlinks=False).st_blocks * 512
    return total


def _make_writable(func, target, excinfo) -> None:
    """只读 bundle 只表示审查期不可改写；过期后恢复父目录写权限再删。uchg 等标志不碰。"""
    if func not in (os.unlink, os.remove, os.rmdir) or not isinstance(excinfo[1], PermissionError):
        raise excinfo[1]
    parent = os.path.dirname(target)
    os.chmod(parent, os.stat(parent).st_mode | stat.S_IRWXU)
    func(target)


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onerror=_make_writable)
    else:
        path.unlink()


def collect(root: Path, days: float, apply: bool) -> dict:
    cutoff = time.time() - days * 86400
    expired, failed, reclaimed = [], [], 0
    for unit in units(root):
        if fresh_or_kept(unit, cutoff):
            continue
        size = size_of(unit)
        if apply:
            try:
                remove(unit)
            except OSError as exc:  # 单元删不掉只记录，继续处理其余单元
                failed.append({"path": str(unit), "error": str(exc)})
                continue
        expired.append({"path": str(unit), "bytes": size})
        reclaimed += size
    return {"root": str(root), "days": days, "applied": apply, "units": len(expired),
            "bytes": reclaimed, "expired": expired, "failed": failed}


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def schedule_plist(days: float, hour: int, root: Path = DEFAULT_ROOT) -> dict:
    log = str(root / "logs" / "artifact-gc.log")
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(Path(__file__).resolve()),
                             "--root", str(root), "--days", f"{days:g}", "--apply"],
        "StartCalendarInterval": {"Hour": hour, "Minute": 0},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def install_schedule(days: float, hour: int) -> int:
    (DEFAULT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    PLIST.write_bytes(plistlib.dumps(schedule_plist(days, hour)))
    result = subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True, text=True)
    print(f"installed {PLIST} (daily {hour:02d}:00, >{days:g}d idle)" if result.returncode == 0
          else f"launchctl load failed: {result.stderr.strip()}")
    return result.returncode


def uninstall_schedule() -> int:
    if PLIST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink()
    print(f"removed {PLIST}")
    return 0


def self_test() -> int:
    old = time.time() - 30 * 86400
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        def make(rel: str, stale: bool = True) -> Path:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
            if stale:
                os.utime(p, (old, old))
            return p
        make("lanes/artifacts/map-old/a/b.bin")
        make("lanes/artifacts/map-new/b.bin", stale=False)
        make("lanes/lane-old/x")
        make("artifacts/kept/x"); make("artifacts/kept/.keep")
        make("artifacts/mixed/old"); make("artifacts/mixed/new", stale=False)
        make("model-roles.json"); make("model-roles.json.bak"); make("bin/tool")
        make("map814-old.json")
        make("orca-old/x")
        for d in sorted({p for p in root.rglob("*") if p.is_dir()}, key=lambda p: -len(p.parts)):
            if not any(c.stat().st_mtime > old + 1 for c in d.iterdir()):
                os.utime(d, (old, old))
        make("artifacts/deep/a/b/new", stale=False)  # 目录 mtime 旧、深层文件新
        for rel in ("artifacts/deep/a/b", "artifacts/deep/a", "artifacts/deep"):
            os.utime(root / rel, (old, old))
        expected = {"lanes/artifacts/map-old", "lanes/lane-old", "map814-old.json", "orca-old"}
        dry = collect(root, 14, apply=False)
        got = {str(Path(e["path"]).relative_to(root)) for e in dry["expired"]}
        failures = []
        if got != expected:
            failures.append(f"expired set {sorted(got)} != {sorted(expected)}")
        if not (root / "lanes/artifacts/map-old").exists():
            failures.append("dry-run deleted data")
        make("lanes/zz-readonly/bundle/diff.patch")  # 只读 review bundle 过期后照删
        os.chmod(root / "lanes/zz-readonly/bundle/diff.patch", 0o444)
        os.chmod(root / "lanes/zz-readonly/bundle", 0o555)
        os.utime(root / "lanes/zz-readonly/bundle", (old, old)); os.utime(root / "lanes/zz-readonly", (old, old))
        expected.add("lanes/zz-readonly")
        immutable = make("lanes/zz-immutable/f")  # uchg 删不掉：记 failed，不中断其余单元
        os.chflags(immutable, stat.UF_IMMUTABLE)
        os.utime(root / "lanes/zz-immutable", (old, old))
        try:
            applied = collect(root, 14, apply=True)
        except OSError as exc:
            applied = {"failed": [], "error": exc}
            failures.append(f"apply aborted on one unit: {exc}")
        finally:
            os.chflags(immutable, 0)
            if (root / "lanes/zz-readonly/bundle").exists():
                os.chmod(root / "lanes/zz-readonly/bundle", 0o755)
        if "error" not in applied and [Path(e["path"]).name for e in applied["failed"]] != ["zz-immutable"]:
            failures.append(f"apply must report only the immutable unit as failed: {applied['failed']}")
        for rel in expected:
            if (root / rel).exists():
                failures.append(f"apply kept {rel}")
        for rel in ("lanes/artifacts/map-new", "artifacts/kept", "artifacts/mixed", "artifacts/deep",
                    "model-roles.json", "model-roles.json.bak", "bin/tool", "lanes/artifacts"):
            if not (root / rel).exists():
                failures.append(f"apply removed protected/fresh {rel}")
    plist = plistlib.loads(plistlib.dumps(schedule_plist(14, 4)))
    args = plist["ProgramArguments"]
    if args[-1] != "--apply" or not Path(args[1]).is_absolute() or "--days" not in args:
        failures.append(f"schedule must run absolute script with --days and --apply: {args}")
    for f in failures:
        print(f"FAIL {f}")
    print("artifact_gc: " + ("fail" if failures else "pass"))
    return 1 if failures else 0


def main() -> int:
    if sys.argv[1:] == ["self-test"]:
        return self_test()
    if sys.argv[1:2] == ["uninstall-schedule"]:
        return uninstall_schedule()
    if sys.argv[1:2] == ["install-schedule"]:
        sched = argparse.ArgumentParser(prog="artifact_gc.py install-schedule")
        sched.add_argument("--days", type=float, default=14)
        sched.add_argument("--hour", type=int, default=4)
        opts = sched.parse_args(sys.argv[2:])
        return install_schedule(opts.days, opts.hour)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--days", type=float, default=14)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        print(f"root missing: {args.root}", file=sys.stderr)
        return 1
    result = collect(args.root, args.days, args.apply)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        verb = "removed" if args.apply else "would remove"
        print(f"{time.strftime('%F %T')} {verb} {result['units']} units, {human(result['bytes'])} "
              f"(>{args.days:g}d idle) under {args.root}")
        for item in result["failed"]:
            print(f"  failed {item['path']}: {item['error']}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
