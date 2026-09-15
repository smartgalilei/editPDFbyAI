"""Build a portable bundle on the target OS. No document/user configuration included."""
import pathlib
import subprocess
import sys
import shutil
import importlib.metadata
import platform
import ssl
import urllib.request
import certifi

root = pathlib.Path(__file__).resolve().parents[1]
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--onedir', '--console', '--name', 'editPDFbyAI',
    '--add-data', f'{root / "web"}:web',
    '--collect-all', 'pymupdf', '--collect-all', 'pathops',
    '--collect-all', 'fontTools', str(root / 'server.py'),
], cwd=root, check=True)

bundle = root / 'dist' / 'editPDFbyAI'
for name in ['LICENSE', 'README.md', 'README.zh-CN.md', 'README.ja.md', 'THIRD_PARTY_NOTICES.md']:
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
    # Framework installations on macOS do not always include a top-level LICENSE.
    url = f'https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE'
    with urllib.request.urlopen(url, timeout=60,
                                context=ssl.create_default_context(cafile=certifi.where())) as response:
        license_text = response.read()
    if b'PYTHON SOFTWARE FOUNDATION LICENSE' not in license_text:
        raise RuntimeError('Invalid Python runtime license response')
    (notices / 'Python-LICENSE.txt').write_bytes(license_text)
