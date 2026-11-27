"""Install SpareDrive from its release wheel into its own virtual environment.

This is the source of Install-SpareDrive.cmd, the single file a release publishes. The release build
writes its version, repository and the wheel's SHA-256 into the four RELEASE_ / WHEEL_ values below, so
the installer downloads exactly the wheel it was built with and refuses a different or damaged file.

Double-click Install-SpareDrive.cmd. It downloads the wheel, checks its checksum, creates a private
environment, installs the wheel with its dependencies, checks the result, and writes
Start-SpareDrive.cmd and Configure-Internet-Access.cmd. Household data and settings are never touched,
so running a newer installer upgrades the program.

    Install-SpareDrive.cmd [--folder DIR] [--start | --no-start] [--wheel FILE] [--base-url URL]

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import venv
from pathlib import Path

# Filled in by the release build (ci/release_tools.py build-installer). Empty in the source tree.
RELEASE_REPOSITORY = ''
RELEASE_VERSION = ''
WHEEL_FILE = ''
WHEEL_SHA256 = ''

MINIMUM_PYTHON = (3, 10)
MAX_DOWNLOAD = 200 * 1024 * 1024  # A wheel is a few hundred KB; refuse anything absurd.
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


def release_url() -> str:
    return f'https://github.com/{RELEASE_REPOSITORY}/releases/download/v{RELEASE_VERSION}'


def download_wheel(base_url: str, folder: Path) -> Path:
    url = f'{base_url.rstrip("/")}/{WHEEL_FILE}'
    target = folder / WHEEL_FILE
    print(f'Downloading {url} ...', flush=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, target.open('wb') as stream:
            received = 0
            while chunk := response.read(64 * 1024):
                received += len(chunk)
                if received > MAX_DOWNLOAD:
                    fail('The download is far larger than a SpareDrive wheel, so it was stopped.')
                stream.write(chunk)
    except urllib.error.HTTPError as error:
        fail(f'GitHub answered {error.code} for {url}. Check that the release exists and your connection works.')
    except (urllib.error.URLError, OSError) as error:
        fail(f'Could not download {url}: {getattr(error, "reason", error)}')
    return target


def check_checksum(wheel: Path) -> None:
    """Refuse a wheel that differs from the one this installer was built with."""
    if not WHEEL_SHA256 or wheel.name != WHEEL_FILE:
        print('Note: this is not the wheel this installer was built with, so its checksum was not verified.')
        return
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
        fail(f'{wheel.name} does not match the checksum this installer was built with. The download is '
             'incomplete or has been changed; run the installer again, or download it again from the release page.')
    print(f'Checksum verified: {wheel.name}')


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
    parser.add_argument('--folder', type=Path, default=default_folder(), help='Where to install. Default: %(default)s')
    parser.add_argument('--wheel', type=Path, help='Install this local wheel instead of downloading one.')
    parser.add_argument('--base-url', help='Download the wheel from this address instead of the GitHub release.')
    start = parser.add_mutually_exclusive_group()
    start.add_argument('--start', action='store_true', help='Start SpareDrive when the install finishes.')
    start.add_argument('--no-start', action='store_true', help='Do not ask to start SpareDrive.')
    args = parser.parse_args()
    folder = args.folder.expanduser().resolve()

    try:
        if sys.version_info < MINIMUM_PYTHON:
            fail(f'Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required; this is {sys.version.split()[0]}.')
        if args.wheel is None and not (RELEASE_REPOSITORY and RELEASE_VERSION and WHEEL_FILE):
            fail('This copy of the installer is not tied to a release. Download Install-SpareDrive.cmd from the '
                 'Releases page, or name a wheel with --wheel FILE.')
        if args.wheel is not None and not args.wheel.is_file():
            fail(f'The wheel {args.wheel} does not exist.')
        with tempfile.TemporaryDirectory(prefix='sparedrive-install-') as scratch:
            wheel = args.wheel.resolve() if args.wheel else download_wheel(args.base_url or release_url(), Path(scratch))
            check_checksum(wheel)
            server = install(wheel, folder)
        launchers = write_launchers(folder)
    except subprocess.CalledProcessError as error:
        fail(f'A step failed ({error.cmd[-1] if error.cmd else "command"}, exit code {error.returncode}). Read the messages above.')
    except OSError as error:
        fail(str(error))

    print(f'\nSpareDrive is installed in {folder}')
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
