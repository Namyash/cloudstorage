"""First-run setup for the Windows launcher."""

import os
from pathlib import Path
import subprocess
import sys


APP = Path(__file__).resolve().parent
RUNTIME = APP / '.runtime'
CONFIG = RUNTIME / 'host.json'
REQUIREMENTS = APP / 'requirements.txt'


def main():
    if sys.version_info < (3, 10):
        raise ValueError('Install Python 3.10 or newer, then run this launcher again.')
    packages = RUNTIME / f'python-{sys.version_info.major}.{sys.version_info.minor}'
    completed = packages / '.requirements'
    wanted = REQUIREMENTS.read_text(encoding='utf-8')
    if not completed.exists() or completed.read_text(encoding='utf-8') != wanted:
        packages.mkdir(parents=True, exist_ok=True)
        print('Installing SpareDrive dependencies…', flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade',
                        '--target', str(packages), '-r', str(REQUIREMENTS)], check=True)
        completed.write_text(wanted, encoding='utf-8')

    env = dict(os.environ, PYTHONPATH=str(packages), PYTHONDONTWRITEBYTECODE='1')
    cmd = [sys.executable, '-m', 'backend.host_server', str(CONFIG)]
    return subprocess.call(cmd, cwd=APP, env=env)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'SpareDrive could not start. {error}', file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(0)
