"""Build all runtime artifacts on the local D: drive."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = Path(r'D:\VTI-control')
for entry, name, windowed in [('run_service.py', 'VTI-Logger', False),
                              ('run_windows_service.py', 'VTI-Service', False),
                              ('run_gui.py', 'VTI-Control', True)]:
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
           '--name', name, '--distpath', str(RUNTIME/'app'), '--workpath', str(RUNTIME/'build'/name),
           '--specpath', str(RUNTIME/'build'), '--paths', str(ROOT/'src')]
    if windowed:
        cmd += ['--windowed']
    for module in ['PyQt5', 'PyQt6', 'PySide2', 'matplotlib', 'scipy', 'pandas',
                   'IPython', 'jupyter', 'tkinter', 'numba', 'PySide6.QtWebEngineCore',
                   'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtPdf']:
        cmd += ['--exclude-module', module]
    if entry == 'run_windows_service.py':
        cmd += ['--hidden-import', 'win32timezone']
    cmd.append(str(ROOT/entry))
    print('Building', name, flush=True)
    subprocess.run(cmd, cwd=RUNTIME, check=True)
