"""Build the portable Windows bundle without deleting its existing user data."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def build():
    if sys.platform != 'win32':
        raise RuntimeError('Windows EXE yalnız Windows üzerinde derlenebilir.')
    destination = ROOT / 'dist' / 'Yolbulan'
    with tempfile.TemporaryDirectory(prefix='yolbulan-derleme-', dir=ROOT) as temporary:
        temp = Path(temporary)
        args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                '--onedir', '--windowed', '--name', 'Yolbulan', '--icon', str(ROOT / 'Yolbulan.ico'),
                '--add-data', f'{ROOT / "kurallar.json"}:.',
                '--add-data', f'{ROOT / "Yolbulan.png"}:.',
                '--collect-all', 'faster_whisper', '--collect-all', 'ctranslate2',
                '--collect-all', 'av', '--distpath', str(temp / 'dist'),
                '--workpath', str(temp / 'work'), '--specpath', str(temp / 'spec'),
                str(ROOT / 'gui.py')]
        subprocess.run(args, cwd=ROOT, check=True)
        staged = temp / 'dist' / 'Yolbulan'
        if not (staged / 'Yolbulan.exe').is_file():
            raise RuntimeError('Derleme tamamlandı fakat Yolbulan.exe bulunamadı.')

        # Existing portable data wins over source data. Build in a staging folder
        # before touching the live dist directory so failures cannot erase it.
        backup = temp / 'previous'
        if destination.exists():
            destination.replace(backup)
        try:
            state = (backup / 'calisma_verisi' if backup.exists() else
                     ROOT / 'calisma_verisi')
            if state.is_dir():
                shutil.copytree(state, staged / 'calisma_verisi')
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
    print(f'Derlendi: {destination / "Yolbulan.exe"}')
    print(f'Ayarlar ve transkriptler: {destination / "calisma_verisi"}')


if __name__ == '__main__':
    build()
