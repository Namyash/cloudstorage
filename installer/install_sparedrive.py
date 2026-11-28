"""Install SpareDrive from its release wheel into ONE self-contained folder.

This is the source of Install-SpareDrive.cmd, the single file a release publishes. The release build
writes its version, repository and the wheel's SHA-256 into the four RELEASE_ / WHEEL_ values below, so
the installer downloads exactly the wheel it was built with and refuses a different or damaged file.

Everything lives in the one install folder, so it can sit on an external drive and be moved or backed up
as a whole. Only the three shortcuts show; the technical parts are in one hidden folder that this installer
creates and hides. It hides nothing else: not the install folder itself and not anything already in it.

    Install-SpareDrive.cmd          a copy of this installer, used to upgrade later
    Start-SpareDrive.cmd            starts SpareDrive
    Configure-Internet-Access.cmd   the Tailscale link and optional Vercel launch page
    .sparedrive\\                    hidden:
        program\\                      the program (a private Python environment)
        host.json                      settings
        data\\                         the household's database and files

Put Install-SpareDrive.cmd in an empty folder and double-click it to install into that folder. Run from
anywhere else, it proposes a folder on an external drive and asks. It downloads the wheel, checks its
checksum, creates the private environment, installs, checks the result, and offers to set up internet
access and to start SpareDrive. Running a newer installer upgrades the program and keeps data and settings.

    Install-SpareDrive.cmd [--folder DIR] [--start | --no-start] [--internet | --no-internet]
                           [--stop-running] [--allow-system-drive] [--wheel FILE] [--base-url URL]

To upgrade, a SpareDrive running from the install folder has to be stopped first, because Windows does not
let a running program be replaced. The installer says so and asks; --stop-running stops it without asking.

Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
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
# The commands the wheel installs (see [project.scripts] in pyproject.toml), and the modules they run.
SERVER_COMMAND, SERVER_MODULE = 'sparedrive', 'family_drive'
INTERNET_COMMAND, INTERNET_MODULE = 'sparedrive-remote', 'family_drive.remote_setup'
# Everything but the three shortcuts goes in one folder that is hidden on Windows. Hiding a folder is reliable:
# files inside it can be rewritten freely. Hiding single files is not, because replacing one makes it visible again.
SYSTEM_FOLDER = '.sparedrive'
PROGRAM_FOLDER = 'program'  # The private Python environment.
SETTINGS_FILE = 'host.json'
DATA_FOLDER = 'data'
FOLDER_NAME = 'SpareDrive'
DEFAULT_PORT = 8765
INSTALLER_COPY = 'Install-SpareDrive.cmd'
WINDOWS = os.name == 'nt'


def fail(message: str) -> None:
    raise SystemExit(f'Install stopped. {message}')


def ask(question: str, default: bool) -> bool:
    answer = input(f'\n{question} [{"Y/n" if default else "y/N"}] ').strip().lower()
    return default if not answer else answer in ('y', 'yes')


def environment_folder(folder: Path) -> Path:
    return folder / SYSTEM_FOLDER / PROGRAM_FOLDER


def settings_path(folder: Path) -> Path:
    return folder / SYSTEM_FOLDER / SETTINGS_FILE


def data_path(folder: Path) -> Path:
    return folder / SYSTEM_FOLDER / DATA_FOLDER


def hide(path: Path) -> None:
    """Mark a folder hidden in Windows Explorer. Best effort: the install works the same if this does not."""
    if not WINDOWS:
        return  # A name starting with a dot is already hidden elsewhere.
    import ctypes
    attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attributes != 0xFFFFFFFF:  # INVALID_FILE_ATTRIBUTES
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attributes | 0x2)  # FILE_ATTRIBUTE_HIDDEN


def release_url() -> str:
    return f'https://github.com/{RELEASE_REPOSITORY}/releases/download/v{RELEASE_VERSION}'


# ---------------------------------------------------------------- where to install

def system_drive() -> str:
    return os.environ.get('SystemDrive', 'C:').rstrip('\\/').casefold()


def on_system_drive(path: Path) -> bool:
    return WINDOWS and path.drive.casefold() == system_drive()


def external_drives() -> list[Path]:
    """Connected drives other than the Windows drive, removable (USB) drives first. Windows only."""
    if not WINDOWS:
        return []
    import ctypes
    found = []
    for letter in string.ascii_uppercase:
        root = Path(f'{letter}:\\')
        kind = ctypes.windll.kernel32.GetDriveTypeW(str(root))  # 2 removable, 3 fixed
        if kind in (2, 3) and f'{letter}:'.casefold() != system_drive():
            try:
                if root.exists():
                    found.append((kind != 2, root))
            except OSError:
                continue  # A card reader with no card.
    return [root for _, root in sorted(found)]


def looks_installed(folder: Path) -> bool:
    return (folder / SYSTEM_FOLDER).is_dir()


def holds_only_installer(folder: Path) -> bool:
    """A folder set aside for SpareDrive: nothing in it but this installer and the files that came with it."""
    ours = {INSTALLER_COPY.casefold(), 'install_sparedrive.py', 'sha256sums.txt'}
    try:
        return all(item.name.casefold() in ours or item.suffix.casefold() == '.whl' for item in folder.iterdir())
    except OSError:
        return False


def default_folder(here: Path) -> Path:
    """Install where the installer sits if that folder is already SpareDrive's or set aside for it. Otherwise
    propose a folder on an external drive, which is what SpareDrive is for, and finally one in the home folder."""
    if here != here.parent and (looks_installed(here) or holds_only_installer(here)):
        return here
    drives = external_drives()
    return (drives[0] if drives else Path.home()) / FOLDER_NAME


def choose_folder(given: Path | None, here: Path, asking: bool) -> tuple[Path, bool]:
    """The install folder, and whether the person chose it themselves."""
    if given is not None:
        return given.expanduser().resolve(), True
    proposal = default_folder(here)
    if not asking:
        return proposal, False
    print('\nSpareDrive keeps everything in ONE folder: the program, its settings and your household\'s files.')
    print('Put the folder on an external drive to carry it with you, or leave it where it is to back it up as one piece.')
    answer = input(f'Install folder [{proposal}]: ').strip().strip('"')
    return (Path(answer).expanduser().resolve() if answer else proposal), bool(answer)


def confirm_folder(folder: Path, chosen: bool, asking: bool, allow_system: bool) -> bool:
    """Check the folder is a sensible home. Returns whether the household may live on the Windows drive."""
    if folder == folder.parent:
        fail('Choose a folder, not the root of a drive, for example D:\\SpareDrive.')
    if not chosen and folder.exists() and not looks_installed(folder) and not holds_only_installer(folder) \
            and any(folder.iterdir()):
        if not (asking and ask(f'{folder} already holds other files. Install SpareDrive there anyway?', default=False)):
            fail(f'{folder} already holds other files. Pass --folder with an empty folder, or run the installer from one.')
    if on_system_drive(folder) and not allow_system:
        if not (asking and ask(f'{folder} is on your Windows drive. SpareDrive is meant for a separate drive, so its files '
                               'are not on the same disk as Windows. Use it anyway?', default=False)):
            fail(f'{folder} is on your Windows drive. Choose a folder on another drive, or pass --allow-system-drive.')
        return True
    return allow_system and on_system_drive(folder)


# ---------------------------------------------------------------- getting and checking the wheel

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


# ---------------------------------------------------------------- installing

def run(*command: object, capture: bool = False) -> str:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)  # Keep the new environment independent of the one running this script.
    environment.pop('PYTHONHOME', None)
    result = subprocess.run([str(part) for part in command], env=environment, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ''


def environment_paths(folder: Path) -> tuple[Path, Path]:
    """The environment's Python and its folder of commands."""
    scripts = environment_folder(folder) / ('Scripts' if WINDOWS else 'bin')
    return scripts / ('python.exe' if WINDOWS else 'python'), scripts


def command_path(scripts: Path, name: str) -> Path:
    return scripts / (name + '.exe' if WINDOWS else name)


def processes_running_from(environment: Path) -> list[int]:
    """Process IDs of programs started from this environment, other than this installer. Windows only."""
    if not WINDOWS or not environment.exists():
        return []
    path = str(environment).replace("'", "''")  # For a PowerShell single-quoted string.
    # $PID is this PowerShell itself, whose command line contains the path being searched for.
    script = (f"$p = '{path}'; Get-CimInstance Win32_Process | Where-Object {{ $_.ProcessId -ne $PID -and $_.ProcessId -ne {os.getpid()} -and "
              "(($_.ExecutablePath -and $_.ExecutablePath.StartsWith($p, 'OrdinalIgnoreCase')) -or "
              "($_.CommandLine -and $_.CommandLine.IndexOf($p, [StringComparison]::OrdinalIgnoreCase) -ge 0)) } | "
              "ForEach-Object { $_.ProcessId }")
    result = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, text=True)
    return [int(line) for line in result.stdout.split() if line.isdigit()]


def free_environment(folder: Path, stop: bool) -> None:
    """A running SpareDrive holds its program files, and Windows does not let those be replaced. Stop it, if allowed."""
    environment = environment_folder(folder)
    running = processes_running_from(environment)
    if not running:
        return
    print(f'SpareDrive is running from {environment} (process {", ".join(map(str, running))}). '
          'It must be stopped before it can be upgraded.')
    if not (stop or (sys.stdin.isatty() and ask('Stop it now? Anyone using it is disconnected.', default=False))):
        fail('Close the SpareDrive window (press Ctrl+C in it) and run the installer again, or run it with --stop-running.')
    for pid in running:
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
    for _ in range(20):  # Give Windows up to ten seconds to release the files.
        if not processes_running_from(environment):
            print('SpareDrive was stopped.')
            return
        time.sleep(0.5)
    fail('Could not stop SpareDrive. Close it by hand and run the installer again.')


def install(wheel: Path, folder: Path, stop_running: bool) -> Path:
    match = WHEEL_NAME.fullmatch(wheel.name)
    if match is None:
        fail(f'{wheel.name} is not a wheel file name such as family_drive-1.2.3-py3-none-any.whl.')
    distribution, version = match['name'].replace('_', '-'), match['version']
    folder.mkdir(parents=True, exist_ok=True)
    python, scripts = environment_paths(folder)
    free_environment(folder, stop_running)
    system = folder / SYSTEM_FOLDER
    created = not system.exists()
    system.mkdir(exist_ok=True)
    if created:
        hide(system)  # Only a folder this installer made; one that was already there keeps whatever you set.

    print(f'Creating the private environment in {environment_folder(folder)} ...', flush=True)
    venv.EnvBuilder(with_pip=True).create(environment_folder(folder))
    print(f'Installing {wheel.name} and its dependencies ...', flush=True)
    run(python, '-m', 'pip', 'install', '--upgrade', '--force-reinstall', wheel)
    run(python, '-m', 'pip', 'check')

    installed = run(python, '-c', f'from importlib.metadata import version; print(version("{distribution}"))', capture=True)
    if installed != version:
        fail(f'Installed version {installed} does not match {version}.')
    for command in (SERVER_COMMAND, INTERNET_COMMAND):
        if not command_path(scripts, command).is_file():
            fail(f'The wheel did not install the command {command}.')
    run(python, '-m', SERVER_MODULE, '--help')
    return python


def write_settings(folder: Path, allow_system: bool) -> Path:
    """Name the household's folder, inside the install folder. Existing settings are never overwritten."""
    settings = settings_path(folder)
    if settings.exists():
        print(f'Kept your existing settings: {settings}')
    else:
        settings.write_text(json.dumps({'data': str(data_path(folder)), 'port': DEFAULT_PORT,
                                        'allowSystemDrive': allow_system}, indent=2) + '\n', encoding='utf-8')
    return settings


def keep_installer_copy(folder: Path) -> None:
    """Put a copy of this installer in the folder so it can be upgraded from there."""
    this = Path(__file__).resolve()
    if this.suffix.casefold() == '.cmd' and this != (folder / INSTALLER_COPY).resolve():
        shutil.copyfile(this, folder / INSTALLER_COPY)


def write_launchers(folder: Path) -> list[Path]:
    """Windows shortcuts that run the program from this folder. They use only paths relative to themselves, so the
    folder keeps working when its drive letter or location changes. Other systems run the commands directly."""
    if not WINDOWS:
        return []
    system = f'%~dp0{SYSTEM_FOLDER}\\'
    python = f'"{system}{PROGRAM_FOLDER}\\Scripts\\python.exe"'
    settings = f'"{system}{SETTINGS_FILE}"'
    launchers = {
        'Start-SpareDrive.cmd': f'@echo off\r\n{python} -m {SERVER_MODULE} {settings} %*\r\npause\r\n',
        'Configure-Internet-Access.cmd': f'@echo off\r\n{python} -m {INTERNET_MODULE} --config {settings} %*\r\npause\r\n',
    }
    for name, text in launchers.items():
        (folder / name).write_bytes(text.encode('ascii'))
    return [folder / name for name in launchers]


# ---------------------------------------------------------------- after installing

def set_up_internet(folder: Path, python: Path, launcher: Path | None) -> int:
    """Run the internet wizard, which is the Tailscale link and an optional Vercel launch page.

    The wizard waits until SpareDrive is running with its first admin account, so SpareDrive is opened in a
    second window while the wizard continues in this one.
    """
    if launcher is not None and WINDOWS:
        subprocess.Popen(['cmd', '/k', str(launcher)], creationflags=subprocess.CREATE_NEW_CONSOLE)
        print('\nSpareDrive is starting in a new window. If this is a new household, open http://127.0.0.1:8765/ in your '
              'browser, enter the setup code shown in that window and create the admin account.')
    else:
        print(f'\nStart SpareDrive in another terminal now: {python} -m {SERVER_MODULE} {settings_path(folder)}')
    print('The internet setup continues here: it asks about Tailscale Funnel and, at the end, an optional Vercel launch page.\n')
    try:
        return subprocess.call([str(python), '-m', INTERNET_MODULE, '--config', str(settings_path(folder))])
    except KeyboardInterrupt:
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--folder', type=Path, help='Install here. Default: the folder holding only this installer, or a new '
                                                    'SpareDrive folder on an external drive.')
    parser.add_argument('--wheel', type=Path, help='Install this local wheel instead of downloading one.')
    parser.add_argument('--base-url', help='Download the wheel from this address instead of the GitHub release.')
    parser.add_argument('--stop-running', action='store_true',
                        help='Stop a SpareDrive running from the install folder, instead of asking.')
    parser.add_argument('--allow-system-drive', action='store_true',
                        help='Allow the install folder, and so the household, on the Windows drive.')
    start = parser.add_mutually_exclusive_group()
    start.add_argument('--start', action='store_true', help='Start SpareDrive when the install finishes.')
    start.add_argument('--no-start', action='store_true', help='Do not ask to start SpareDrive or to set up internet access.')
    internet = parser.add_mutually_exclusive_group()
    internet.add_argument('--internet', action='store_true', help='Set up internet access when the install finishes.')
    internet.add_argument('--no-internet', action='store_true', help='Do not ask about internet access.')
    args = parser.parse_args()
    asking = sys.stdin.isatty() and not args.no_start  # Prompts only for a person at a terminal.

    try:
        if sys.version_info < MINIMUM_PYTHON:
            fail(f'Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required; this is {sys.version.split()[0]}.')
        if args.wheel is None and not (RELEASE_REPOSITORY and RELEASE_VERSION and WHEEL_FILE):
            fail('This copy of the installer is not tied to a release. Download Install-SpareDrive.cmd from the '
                 'Releases page, or name a wheel with --wheel FILE.')
        if args.wheel is not None and not args.wheel.is_file():
            fail(f'The wheel {args.wheel} does not exist.')
        folder, chosen = choose_folder(args.folder, Path(__file__).resolve().parent, asking)
        allow_system = confirm_folder(folder, chosen, asking, args.allow_system_drive)
        with tempfile.TemporaryDirectory(prefix='sparedrive-install-') as scratch:
            wheel = args.wheel.resolve() if args.wheel else download_wheel(args.base_url or release_url(), Path(scratch))
            check_checksum(wheel)
            python = install(wheel, folder, args.stop_running)
        settings = write_settings(folder, allow_system)
        keep_installer_copy(folder)
        launchers = write_launchers(folder)
    except subprocess.CalledProcessError as error:
        fail(f'A step failed ({error.cmd[-1] if error.cmd else "command"}, exit code {error.returncode}). Read the messages above.')
    except PermissionError as error:
        fail(f'{error}. A program is still using files in the install folder. Close any SpareDrive window or other '
             'program running from there, and try again.')
    except OSError as error:
        fail(str(error))

    print(f'\nSpareDrive is installed in {folder}')
    print('Everything is in this one folder. Move it, or back it up, as a whole.')
    if launchers:
        print(f'  Start SpareDrive:         {launchers[0]}')
        print(f'  Set up internet access:   {launchers[1]}')
        print(f'  Upgrade later:            {folder / INSTALLER_COPY}')
    else:
        print(f'  Start SpareDrive:         {python} -m {SERVER_MODULE} {settings}')
        print(f'  Set up internet access:   {python} -m {INTERNET_MODULE} --config {settings}')
    print(f'  Your household\'s files:   {data_path(folder)}  (created the first time SpareDrive starts)')
    print(f'The technical parts are in the hidden folder {SYSTEM_FOLDER}. To see it in Explorer: View > Show > Hidden items.')
    print('Then open http://127.0.0.1:8765/ and enter the setup code shown in the terminal.')

    if args.internet or (asking and not args.no_internet
                         and ask('Set up internet access now (Tailscale link and optional Vercel launch page)?', default=False)):
        return set_up_internet(folder, python, launchers[0] if launchers else None)
    if args.start or (asking and ask('Start SpareDrive now?', default=True)):
        try:
            return subprocess.call([str(python), '-m', SERVER_MODULE, str(settings)])
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
