#!/usr/bin/env python3
"""本机构建：绑定解释器，携带同源工具，ad-hoc 签名；安装不覆盖已有应用。"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--python', default=sys.executable)
parser.add_argument('--install', action='store_true')
args = parser.parse_args()
python = Path(args.python).resolve()
subprocess.run([str(python), '-c', 'import sys; assert sys.version_info >= (3,10), "需要 Python >= 3.10"'], check=True)
subprocess.run(['bun', 'run', 'build', '-skip-dmg'], cwd=root, env={**os.environ, 'MYGO_LDFLAGS': '-X main.pythonPath='+str(python)}, check=True)
app = next((root / 'build').glob('darwin-*/*.app'))
canonical = root.parents[1] / 'skills/delivery-pipeline-setup/scripts'
resources = app / 'Contents/Resources'
shutil.copy2(canonical / 'model_config.py', resources / 'model_config.py')
shutil.copytree(canonical / '_vendor', resources / '_vendor', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
# 对最终资源执行隔离 probe，防止源码可用但应用漏带依赖。
subprocess.run([str(python), str(root.parents[1] / 'scripts/check_config_toml.py'),
                '--python', str(python), '--tool', str(resources / 'model_config.py')], check=True)
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)], check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(app)], check=True)
if args.install:
    destination = Path.home() / 'Applications' / app.name
    if destination.exists():
        raise SystemExit('已有应用，未覆盖：'+str(destination))
    destination.parent.mkdir(exist_ok=True)
    shutil.copytree(app, destination)
    app = destination
print(app)
