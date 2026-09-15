"""Create a portable archive with permissions intact, plus a SHA-256 checksum."""
import hashlib
from pathlib import Path
import shutil
import sys

label = sys.argv[1]
root = Path(__file__).resolve().parents[1]
name = root / ('editPDFbyAI-' + label)
archive = Path(shutil.make_archive(str(name), 'zip' if sys.platform == 'win32' else 'gztar',
                                    root_dir=root/'dist', base_dir='editPDFbyAI'))
archive.with_name(archive.name+'.sha256').write_text(
    hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
print(archive.name)
