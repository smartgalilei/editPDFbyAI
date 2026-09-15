"""Build a portable bundle on the target OS. No document/user configuration included."""
import pathlib
import subprocess
import sys
import shutil
import importlib.metadata

root = pathlib.Path(__file__).resolve().parents[1]
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--onedir', '--console', '--name', 'editPDFbyAI',
    '--add-data', f'{root / "web"}:web',
    '--collect-all', 'pymupdf', '--collect-all', 'pathops',
    '--collect-all', 'fontTools', str(root / 'server.py'),
], cwd=root, check=True)

bundle = root / 'dist' / 'editPDFbyAI'
for name in ['LICENSE', 'README.md', 'THIRD_PARTY_NOTICES.md']:
    shutil.copy2(root / name, bundle / name)
notices = bundle / 'THIRD_PARTY_LICENSES'
for package in ['PyMuPDF', 'pypdf', 'fonttools', 'skia-pathops', 'certifi', 'pyinstaller']:
    dist = importlib.metadata.distribution(package)
    copied = False
    for file in dist.files or []:
        if any(word in str(file).lower() for word in ['license', 'copying', 'notice']):
            source = pathlib.Path(dist.locate_file(file))
            if source.is_file():
                target = notices / package / str(file).replace('..', '_')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied = True
    if not copied:
        raise RuntimeError('Missing dependency license: ' + package)
for name in ['LICENSE.txt', 'LICENSE']:
    source = pathlib.Path(sys.base_prefix) / name
    if source.exists():
        shutil.copy2(source, notices / 'Python-LICENSE.txt')
        break
else:
    raise RuntimeError('Python runtime license not found')
