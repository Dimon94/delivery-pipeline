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
shutil.copy2(root.parent / 'skills/delivery-pipeline-setup/scripts/model_config.py', app / 'Contents/Resources/model_config.py')
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
