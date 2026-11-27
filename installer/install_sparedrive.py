"""Install SpareDrive from a release wheel into its own virtual environment.

Put this file next to the downloaded wheel and SHA256SUMS.txt, then run it (on Windows, double-click
Install-SpareDrive.cmd). It creates a private environment, checks the wheel against SHA256SUMS.txt,
installs the wheel with its dependencies, checks the result, and writes Start-SpareDrive.cmd and
Configure-Internet-Access.cmd. Household data and settings are never touched, so running it again
upgrades the program.

    python install_sparedrive.py [--wheel FILE] [--folder DIR] [--start | --no-start]

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import venv
from pathlib import Path

MINIMUM_PYTHON = (3, 10)
CHECKSUM_FILE = 'SHA256SUMS.txt'
WHEEL_NAME = re.compile(r'(?P<name>[A-Za-z0-9_.]+)-(?P<version>[0-9][A-Za-z0-9_.+!]*)-[^-]+-[^-]+-[^-]+\.whl')
# The commands the wheel installs (see [project.scripts] in pyproject.toml).
SERVER_COMMAND = 'sparedrive'
INTERNET_COMMAND = 'sparedrive-remote'
WINDOWS = os.name == 'nt'


def fail(message: str) -> None:
    raise SystemExit(f'Install stopped. {message}')


def default_folder() -> Path:
    if WINDOWS:
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'SpareDrive'
    return Path.home() / '.local' / 'share' / 'sparedrive'


def find_wheel(here: Path, given: Path | None) -> Path:
    if given is not None:
        if not given.is_file():
            fail(f'The wheel {given} does not exist.')
        return given.resolve()
    found = sorted(here.glob('*.whl'))
    if len(found) != 1:
        fail('Put exactly one SpareDrive .whl file next to this script, or name it with --wheel. '
             f'Found {len(found)} in {here}.')
    return found[0].resolve()


def check_checksum(wheel: Path) -> None:
    """Refuse a wheel that differs from the SHA256SUMS.txt beside it. Without that file, say so."""
    sums = wheel.parent / CHECKSUM_FILE
    if not sums.is_file():
        print(f'Note: {CHECKSUM_FILE} is not next to the wheel, so its checksum was not verified.')
        return
    for line in sums.read_text(encoding='utf-8').splitlines():
        digest, _, name = line.strip().partition(' ')
        if name.strip().lstrip('*') == wheel.name:  # sha256sum marks binary files with a leading "*"
            actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
            if actual != digest.lower():
                fail(f'{wheel.name} does not match {CHECKSUM_FILE}. The download is incomplete or has been changed; '
                     'download it again.')
            print(f'Checksum verified: {wheel.name}')
            return
    fail(f'{CHECKSUM_FILE} has no entry for {wheel.name}.')


def run(*command: object, capture: bool = False) -> str:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)  # Keep the new environment independent of the one running this script.
    environment.pop('PYTHONHOME', None)
    result = subprocess.run([str(part) for part in command], env=environment, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ''


def environment_paths(folder: Path) -> tuple[Path, Path]:
    """The environment's Python and its folder of commands."""
    scripts = folder / '.venv' / ('Scripts' if WINDOWS else 'bin')
    return scripts / ('python.exe' if WINDOWS else 'python'), scripts


def command_path(scripts: Path, name: str) -> Path:
    return scripts / (name + '.exe' if WINDOWS else name)


def write_launchers(folder: Path) -> list[Path]:
    """Windows shortcuts that start the program from this environment. Other systems run the commands directly."""
    if not WINDOWS:
        return []
    launchers = {
        'Start-SpareDrive.cmd': f'@echo off\r\n"%~dp0.venv\\Scripts\\{SERVER_COMMAND}.exe" %*\r\npause\r\n',
        'Configure-Internet-Access.cmd': f'@echo off\r\n"%~dp0.venv\\Scripts\\{INTERNET_COMMAND}.exe" %*\r\npause\r\n',
    }
    for name, text in launchers.items():
        (folder / name).write_bytes(text.encode('ascii'))
    return [folder / name for name in launchers]


def install(wheel: Path, folder: Path) -> Path:
    match = WHEEL_NAME.fullmatch(wheel.name)
    if match is None:
        fail(f'{wheel.name} is not a wheel file name such as family_drive-1.2.3-py3-none-any.whl.')
    distribution, version = match['name'].replace('_', '-'), match['version']
    folder.mkdir(parents=True, exist_ok=True)
    python, scripts = environment_paths(folder)

    print(f'Creating the private environment in {folder / ".venv"} ...', flush=True)
    venv.EnvBuilder(with_pip=True).create(folder / '.venv')
    print(f'Installing {wheel.name} and its dependencies ...', flush=True)
    run(python, '-m', 'pip', 'install', '--upgrade', '--force-reinstall', wheel)
    run(python, '-m', 'pip', 'check')

    installed = run(python, '-c', f'from importlib.metadata import version; print(version("{distribution}"))', capture=True)
    if installed != version:
        fail(f'Installed version {installed} does not match {version}.')
    for command in (SERVER_COMMAND, INTERNET_COMMAND):
        if not command_path(scripts, command).is_file():
            fail(f'The wheel did not install the command {command}.')
    run(command_path(scripts, SERVER_COMMAND), '--help')
    return command_path(scripts, SERVER_COMMAND)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--wheel', type=Path, help='The wheel to install. Default: the one next to this script.')
    parser.add_argument('--folder', type=Path, default=default_folder(), help='Where to install. Default: %(default)s')
    start = parser.add_mutually_exclusive_group()
    start.add_argument('--start', action='store_true', help='Start SpareDrive when the install finishes.')
    start.add_argument('--no-start', action='store_true', help='Do not ask to start SpareDrive.')
    args = parser.parse_args()

    try:
        if sys.version_info < MINIMUM_PYTHON:
            fail(f'Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required; this is {sys.version.split()[0]}.')
        wheel = find_wheel(Path(__file__).resolve().parent, args.wheel)
        check_checksum(wheel)
        server = install(wheel, args.folder.expanduser().resolve())
        launchers = write_launchers(args.folder.expanduser().resolve())
    except subprocess.CalledProcessError as error:
        fail(f'A step failed ({error.cmd[-1] if error.cmd else "command"}, exit code {error.returncode}). Read the messages above.')
    except OSError as error:
        fail(str(error))

    print(f'\nSpareDrive is installed in {args.folder.expanduser().resolve()}')
    if launchers:
        print('Start it:                  ' + str(launchers[0]))
        print('Set up internet access:    ' + str(launchers[1]))
    else:
        print(f'Start it:                  {server}')
        print(f'Set up internet access:    {command_path(server.parent, INTERNET_COMMAND)}')
    print('Then open http://127.0.0.1:8765/ and enter the setup code shown in the terminal.')

    wants_start = args.start or (not args.no_start and sys.stdin.isatty()
                                 and input('\nStart SpareDrive now? [Y/n] ').strip().lower() in ('', 'y', 'yes'))
    if wants_start:
        try:
            return subprocess.call([str(server)])
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
