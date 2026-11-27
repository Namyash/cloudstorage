"""Helpers for ci/Jenkinsfile: version numbers, package checks and the GitHub release.

Standard library only, and Python 3.11 or newer (tomllib). Run from the repository root:

    python ci/release_tools.py check-repo                    repository and packaging metadata are consistent
    python ci/release_tools.py released-tag                  the release tag the current commit already has
    python ci/release_tools.py next-version                  the version the next release gets
    python ci/release_tools.py wheel-name VERSION            the wheel file name for a version
    python ci/release_tools.py set-version VERSION           write the version into the working copy
    python ci/release_tools.py verify-wheel WHEEL VERSION    the wheel holds everything the source tree packages
    python ci/release_tools.py smoke VERSION                 run in an environment with the wheel installed
    python ci/release_tools.py build-installer VERSION WHEEL OUT_DIR --repo OWNER/NAME
                                                             write the one-file Install-SpareDrive.cmd
    python ci/release_tools.py installer-files               the name of that file
    python ci/release_tools.py notes VERSION WHEEL OUT_DIR   write SHA256SUMS.txt and release-notes.md
    python ci/release_tools.py publish ... ASSET [ASSET ...] create the GitHub release (token in GITHUB_TOKEN)

Names, folders and entry points are read from pyproject.toml, so nothing here is tied to one package.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

GITHUB_API = os.environ.get('GITHUB_API_URL', 'https://api.github.com')
VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')
TAG = re.compile(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)')
PROJECT_VERSION = re.compile(rb'(?m)^version = "([^"\r\n]+)"[ \t]*\r?$')
PINNED = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9._+!-]+)')
REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
COMMIT = re.compile(r'[0-9a-f]{40}')
CHECKSUM_FILE = 'SHA256SUMS.txt'
INSTALLER_DIR = 'installer'
INSTALLER_SOURCE = 'install_sparedrive.py'  # The readable installer in the repository.
INSTALLER_ASSET = 'Install-SpareDrive.cmd'  # The one installer file a release publishes, built from the source.
INSTALLER_VALUES = ('RELEASE_REPOSITORY', 'RELEASE_VERSION', 'WHEEL_FILE', 'WHEEL_SHA256')  # Set per release.
# cmd.exe runs this part of the .cmd; Python skips the first line of the file (python -x) and never reaches it.
INSTALLER_BATCH = r'''@echo off
setlocal
set "PYTHON=py -3"
%PYTHON% --version >nul 2>nul || set "PYTHON=python"
%PYTHON% --version >nul 2>nul || (
    echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and run this again.
    pause
    exit /b 1
)
%PYTHON% -x "%~f0" %*
set "RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RESULT%
'''
Version = tuple[int, int, int]


def fail(message: str) -> None:
    raise SystemExit(f'ERROR: {message}')


def parse_version(text: str, pattern: re.Pattern[str] = VERSION) -> Version | None:
    match = pattern.fullmatch(text.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def format_version(version: Version) -> str:
    return '.'.join(map(str, version))


def load_project(root: Path) -> dict:
    return tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))


def wheel_name(project: dict, version: str) -> str:
    distribution = re.sub(r'[-_.]+', '_', project['project']['name'])  # the form wheel file names use
    return f'{distribution}-{version}-py3-none-any.whl'


def next_version(declared: str, tags: list[str]) -> str:
    """One patch above the newest release tag, unless pyproject.toml declares a higher version.

    Editing the version in pyproject.toml is how a person starts a new minor or major line.
    With no release tag yet, the declared version is the first release.
    """
    declared_version = parse_version(declared)
    if declared_version is None:
        raise ValueError(f'pyproject.toml has no major.minor.patch version: {declared!r}.')
    released = sorted(version for tag in tags if (version := parse_version(tag, TAG)))
    if not released or declared_version > released[-1]:
        return format_version(declared_version)
    major, minor, patch = released[-1]
    return format_version((major, minor, patch + 1))


def git(*arguments: str) -> str:
    return subprocess.run(['git', *arguments], check=True, text=True, capture_output=True).stdout.strip()


def requirements(root: Path) -> list[tuple[str, str]]:
    """The pinned (name, version) pairs of requirements.txt."""
    pairs = []
    for line in (root / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        line = line.split('#')[0].strip()
        if line:
            match = PINNED.fullmatch(line)
            if match is None:
                raise ValueError(f'requirements.txt must pin each package with ==, found {line!r}.')
            pairs.append((match[1].lower(), match[2]))
    return pairs


def module_file(project: dict, root: Path, module: str) -> Path:
    """The source file of an installed module name, using the package-dir mapping of pyproject.toml."""
    setuptools = project['tool']['setuptools']
    for package in sorted(setuptools['packages'], key=len, reverse=True):
        if module == package or module.startswith(package + '.'):
            rest = module[len(package):].lstrip('.')
            folder = root / setuptools['package-dir'][package]
            return folder / (rest.replace('.', '/') + '.py' if rest else '__init__.py')
    raise ValueError(f'{module} is not in a package listed in pyproject.toml.')


def packaged_files(project: dict, root: Path) -> set[str]:
    """Every file the wheel must hold: each package's Python files plus its package-data matches."""
    setuptools = project['tool']['setuptools']
    members = set()
    for package in setuptools['packages']:
        folder, prefix = root / setuptools['package-dir'][package], package.replace('.', '/')
        members.update(f'{prefix}/{path.name}' for path in folder.glob('*.py'))
        for pattern in setuptools.get('package-data', {}).get(package, []):
            members.update(f'{prefix}/{path.name}' for path in folder.glob(pattern) if path.is_file())
    return members


def check_repo(root: Path) -> list[str]:
    errors = []
    project = load_project(root)
    declared = project['project']['version']
    if parse_version(declared) is None:
        errors.append(f'pyproject.toml version {declared!r} is not major.minor.patch.')
    elif wheel_name(project, declared) not in (root / 'README.md').read_text(encoding='utf-8'):
        errors.append(f'README.md does not mention {wheel_name(project, declared)}; the release job rewrites that file name.')
    try:
        requirements(root)
    except ValueError as error:
        errors.append(str(error))
    installer = root / INSTALLER_DIR / INSTALLER_SOURCE
    if not installer.is_file():
        errors.append(f'{INSTALLER_DIR}/{INSTALLER_SOURCE} is missing; every release is built from it.')
    else:
        source = installer.read_text(encoding='utf-8')
        errors.extend(f"{INSTALLER_DIR}/{INSTALLER_SOURCE} must contain the line {name} = '' exactly once."
                      for name in INSTALLER_VALUES if len(re.findall(rf"(?m)^{name} = ''$", source)) != 1)
        if not source.isascii():
            errors.append(f'{INSTALLER_DIR}/{INSTALLER_SOURCE} must be plain ASCII so cmd.exe can read the .cmd built from it.')
        if "\nif __name__ == '__main__':" not in source:
            errors.append(f'{INSTALLER_DIR}/{INSTALLER_SOURCE} must end with an `if __name__ == \'__main__\':` block.')
    setuptools = project['tool']['setuptools']
    for package in setuptools['packages']:
        folder = root / setuptools['package-dir'][package]
        if not folder.is_dir():
            errors.append(f'Package {package} points at {folder.name}, which does not exist.')
            continue
        for pattern in setuptools.get('package-data', {}).get(package, []):
            if not any(path.is_file() for path in folder.glob(pattern)):
                errors.append(f'Package data {pattern!r} for {package} matches no file.')
    for script, target in project['project'].get('scripts', {}).items():
        module, _, function = target.partition(':')
        try:
            tree = ast.parse(module_file(project, root, module).read_text(encoding='utf-8'))
        except (OSError, ValueError, SyntaxError) as error:
            errors.append(f'Entry point {script} = {target}: {error}')
            continue
        if not any(isinstance(node, ast.FunctionDef) and node.name == function for node in tree.body):
            errors.append(f'Entry point {script} = {target}: {module} defines no function {function}.')
    return errors


def set_version(root: Path, version: str) -> None:
    """Write the release version into the working copy, as the local release script does."""
    if not VERSION.fullmatch(version):
        raise ValueError(f'{version!r} is not major.minor.patch.')
    project = load_project(root)
    previous = project['project']['version']
    metadata = (root / 'pyproject.toml').read_bytes()
    current = PROJECT_VERSION.search(metadata)
    readme = (root / 'README.md').read_bytes()
    old, new = wheel_name(project, previous).encode(), wheel_name(project, version).encode()
    if current is None or old not in readme:
        raise ValueError('Could not find the current version in pyproject.toml and its wheel file name in README.md.')
    (root / 'pyproject.toml').write_bytes(metadata[:current.start(1)] + version.encode() + metadata[current.end(1):])
    (root / 'README.md').write_bytes(readme.replace(old, new))


def verify_wheel(root: Path, wheel: Path, version: str) -> list[str]:
    project = load_project(root)
    errors = []
    if wheel.name != wheel_name(project, version):
        errors.append(f'The wheel is named {wheel.name}, expected {wheel_name(project, version)}.')
    with zipfile.ZipFile(wheel) as archive:
        if (broken := archive.testzip()) is not None:
            return [f'{broken} in the wheel is corrupted.']
        names = set(archive.namelist())
        if missing := sorted(packaged_files(project, root) - names):
            errors.append('The wheel is missing: ' + ', '.join(missing))
        info = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(info) != 1:
            return errors + ['The wheel has no single METADATA file.']
        metadata = archive.read(info[0]).decode('utf-8')
        entry_points = archive.read(info[0].replace('METADATA', 'entry_points.txt')).decode('utf-8') \
            if info[0].replace('METADATA', 'entry_points.txt') in names else ''
    headers = [line.partition(': ')[::2] for line in metadata.splitlines() if ': ' in line]
    if ('Version', version) not in headers:
        errors.append(f'The wheel metadata is not version {version}.')
    wanted_python = project['project'].get('requires-python')
    if wanted_python and ('Requires-Python', wanted_python) not in headers:
        errors.append(f'The wheel does not require Python {wanted_python}.')
    declared = {(match[1].lower(), match[2]) for key, value in headers
                if key == 'Requires-Dist' and (match := PINNED.match(value))}
    if declared != set(requirements(root)):
        errors.append('The wheel dependencies differ from requirements.txt.')
    parser = configparser.ConfigParser(delimiters=('=',))
    parser.optionxform = str  # script names are case sensitive
    parser.read_string(entry_points)
    installed = dict(parser['console_scripts']) if parser.has_section('console_scripts') else {}
    for script, target in project['project'].get('scripts', {}).items():
        if installed.get(script) != target:
            errors.append(f'The wheel does not install the command {script} = {target}.')
    return errors


def smoke(root: Path, version: str) -> None:
    """Exercise the INSTALLED package: its version, its commands, and every page and script it serves."""
    from importlib.metadata import version as installed_version

    from family_drive.account_and_file_api import STORAGE_ASSETS, create_app

    project = load_project(root)
    if installed_version(project['project']['name']) != version:
        fail(f'The installed version is not {version}.')
    for module in sorted({target.partition(':')[0] for target in project['project'].get('scripts', {}).values()}):
        subprocess.run([sys.executable, '-m', module, '--help'], check=True, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory() as folder:
        client = create_app(folder).test_client()
        pages = ['/', '/storage'] + [f'/assets/{name}' for name in sorted(STORAGE_ASSETS | {'app.js', 'vault.js'})]
        for page in pages:
            response = client.get(page, base_url='http://127.0.0.1:8765')
            response.close()
            if response.status_code != 200:
                fail(f'The installed package answered {response.status_code} for {page}.')
        state = client.get('/api/state', base_url='http://127.0.0.1:8765').get_json()
        if state.get('setup') is not True:
            fail('A fresh installation should offer first-run setup.')
    print(f'[OK] installed {project["project"]["name"]} {version}: commands run, {len(pages)} pages and assets are served')


def build_installer(root: Path, version: str, wheel: Path, out_dir: Path, repository: str) -> Path:
    """Write the one-file installer: the installer source with this release's values, behind a cmd.exe header.

    The file is both a batch file and a Python program. cmd.exe runs the first line, which jumps to the batch
    commands at the end; those start Python as `python -x`, which skips that first line, so Python reads the rest.
    The wheel's SHA-256 is written inside, so the installer needs no separate checksum file.
    """
    if not (REPOSITORY.fullmatch(repository) and VERSION.fullmatch(version)):
        raise ValueError('Give the repository as owner/name and the version as major.minor.patch.')
    source = (root / INSTALLER_DIR / INSTALLER_SOURCE).read_text(encoding='utf-8').replace('\r\n', '\n')
    if not source.isascii():
        raise ValueError(f'{INSTALLER_SOURCE} must be plain ASCII so cmd.exe can read the .cmd built from it.')
    values = dict(zip(INSTALLER_VALUES, (repository, version, wheel.name, hashlib.sha256(wheel.read_bytes()).hexdigest())))
    for name, value in values.items():
        source, count = re.subn(rf"(?m)^{name} = ''$", lambda _, name=name, value=value: f'{name} = {value!r}', source)
        if count != 1:
            raise ValueError(f"{INSTALLER_SOURCE} must contain the line {name} = '' exactly once.")
    body, marker, tail = source.partition("\nif __name__ == '__main__':")
    if not marker:
        raise ValueError(f"{INSTALLER_SOURCE} must end with an `if __name__ == '__main__':` block.")
    text = ('@goto :begin_batch & rem Python skips this line (python -x); cmd.exe jumps to the batch commands below.\n'
            + body + "\n\n_BATCH = r'''\n:begin_batch\n" + INSTALLER_BATCH + "'''\n" + marker + tail)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / INSTALLER_ASSET
    target.write_bytes(text.replace('\n', '\r\n').encode('ascii'))  # cmd.exe needs Windows line endings.
    return target


def write_notes(root: Path, version: str, wheel: Path, out_dir: Path, commit: str, product: str, build_url: str,
                extras: list[Path]) -> None:
    project = load_project(root)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    checksums = [f'{digest}  {wheel.name}'] + [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in extras]
    (out_dir / CHECKSUM_FILE).write_text('\n'.join(checksums) + '\n', encoding='ascii')
    requires = project['project'].get('requires-python', '')
    python = f'Python {requires[2:]} or newer' if requires.startswith('>=') else f'Python {requires}'.strip()
    built = f'Built by Jenkins from commit `{commit}` after every check passed.' + (f' [Build log]({build_url})' if build_url else '')
    (out_dir / 'release-notes.md').write_text(f'''# {product} v{version} for Windows

Requires {python}.

## Easy install
1. Download `{INSTALLER_ASSET}` from Assets. It is the only file you need.
2. Double-click it. It downloads this release's wheel from GitHub, checks it against the checksum built into the installer, creates a private environment, installs {product} and offers to start it.
3. Open [{product}](http://127.0.0.1:8765/), enter the setup code shown in the terminal, select a dedicated folder on your data drive, and create your admin account.

Run the installer of a newer release to upgrade. Your data and settings are never touched.

## Manual install
Download `{wheel.name}`, open PowerShell in the download folder and run `python -m pip install .\\{wheel.name}`, then `python -m family_drive`.

`{CHECKSUM_FILE}` lists the SHA-256 of every file here. The wheel's is `{digest}`.

{built}
''', encoding='utf-8')


class GitHub:
    """The few GitHub REST calls a release needs. The token never appears in an error message."""

    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, url: str, payload: dict | None = None, data: bytes | None = None,
                content_type: str = 'application/json', allow_missing: bool = False, timeout: int = 60):
        body = json.dumps(payload).encode() if payload is not None else data
        request = urllib.request.Request(url if '://' in url else GITHUB_API + url, data=body, method=method, headers={
            'Accept': 'application/vnd.github+json', 'Authorization': f'Bearer {self.token}',
            'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': content_type, 'User-Agent': 'release-tools'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_missing:
                return None
            detail = error.read(2000).decode('utf-8', 'replace')
            raise RuntimeError(f'GitHub answered HTTP {error.code} to {method} {url}: {detail}') from None
        except urllib.error.URLError as error:
            raise RuntimeError(f'Could not reach GitHub for {method} {url}: {error.reason}') from None
        return json.loads(text) if text else None


def publish(repository: str, tag: str, commit: str, title: str, notes: Path, assets: list[Path]) -> str:
    """Create the GitHub release as a draft, attach every file, then publish it.

    A draft has no tag and is invisible, so a failed upload never leaves a public release without its
    files: the draft is deleted. Publishing creates the tag on `commit`, the exact commit that was tested.
    """
    if not (token := os.environ.get('GITHUB_TOKEN')):
        fail('GITHUB_TOKEN is not set.')
    github, base = GitHub(token), f'/repos/{repository}'
    if github.request('GET', f'{base}/git/ref/tags/{tag}', allow_missing=True) is not None:
        fail(f'{tag} already exists on GitHub. A release is never replaced; the next build takes the next number.')
    draft = github.request('POST', f'{base}/releases', {
        'tag_name': tag, 'target_commitish': commit, 'name': title, 'body': notes.read_text(encoding='utf-8'),
        'draft': True, 'prerelease': False, 'generate_release_notes': True})
    try:
        for asset in assets:
            github.request('POST', f'{draft["upload_url"].partition("{")[0]}?name={urllib.parse.quote(asset.name)}',
                           data=asset.read_bytes(), content_type='application/octet-stream', timeout=300)
        released = github.request('PATCH', f'{base}/releases/{draft["id"]}', {'draft': False, 'make_latest': 'true'})
    except BaseException:
        github.request('DELETE', f'{base}/releases/{draft["id"]}', allow_missing=True)
        raise
    attached = {asset['name']: asset for asset in released.get('assets', [])}
    for asset in assets:
        listed = attached.get(asset.name)
        if listed is None or listed.get('state') != 'uploaded' or listed.get('size') != asset.stat().st_size:
            fail(f'{released["html_url"]} was published, but {asset.name} is not attached correctly. Check the release page.')
    reference = github.request('GET', f'{base}/git/ref/tags/{tag}')
    if reference['object']['sha'] != commit:
        fail(f'{tag} points at {reference["object"]["sha"]}, not the tested commit {commit}.')
    return released['html_url']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('check-repo', 'released-tag', 'next-version', 'installer-files'):
        commands.add_parser(name)
    for name, arguments in (('wheel-name', ['version']), ('set-version', ['version']), ('smoke', ['version']),
                            ('verify-wheel', ['wheel', 'version']), ('notes', ['version', 'wheel', 'out_dir']),
                            ('build-installer', ['version', 'wheel', 'out_dir'])):
        command = commands.add_parser(name)
        for argument in arguments:
            command.add_argument(argument, type=Path if argument in ('wheel', 'out_dir') else str)
    commands.choices['build-installer'].add_argument('--repo', required=True)
    notes = commands.choices['notes']
    notes.add_argument('--commit', default='unknown')
    notes.add_argument('--product', default='Release')
    notes.add_argument('--build-url', default='')
    notes.add_argument('--also', nargs='*', type=Path, default=[], help='More files to list in the checksum file.')
    upload = commands.add_parser('publish')
    for name in ('repo', 'tag', 'sha', 'title'):
        upload.add_argument(f'--{name}', required=True)
    upload.add_argument('--notes-file', type=Path, required=True)
    upload.add_argument('assets', nargs='+', type=Path)
    args = parser.parse_args()

    root = Path.cwd()
    try:
        if args.command == 'check-repo':
            if errors := check_repo(root):
                fail('\n'.join(errors))
            print('[OK] pyproject.toml, requirements.txt, README.md and the entry points agree')
        elif args.command == 'released-tag':
            tags = git('tag', '--points-at', 'HEAD').splitlines()
            print(next((tag for tag in tags if TAG.fullmatch(tag)), ''))
        elif args.command == 'next-version':
            print(next_version(load_project(root)['project']['version'], git('tag', '--list', 'v*').splitlines()))
        elif args.command == 'installer-files':
            print(INSTALLER_ASSET)
        elif args.command == 'build-installer':
            print(f'[OK] wrote {build_installer(root, args.version, args.wheel, args.out_dir, args.repo)}')
        elif args.command == 'wheel-name':
            print(wheel_name(load_project(root), args.version))
        elif args.command == 'set-version':
            set_version(root, args.version)
        elif args.command == 'verify-wheel':
            if errors := verify_wheel(root, args.wheel, args.version):
                fail('\n'.join(errors))
            print(f'[OK] {args.wheel.name} holds every packaged file, the right metadata and the commands')
        elif args.command == 'smoke':
            smoke(root, args.version)
        elif args.command == 'notes':
            write_notes(root, args.version, args.wheel, args.out_dir, args.commit, args.product, args.build_url, args.also)
        else:
            if not (REPOSITORY.fullmatch(args.repo) and TAG.fullmatch(args.tag) and COMMIT.fullmatch(args.sha)):
                fail('Give --repo as owner/name, --tag as vMAJOR.MINOR.PATCH and --sha as a full commit hash.')
            print(f'[OK] published {publish(args.repo, args.tag, args.sha, args.title, args.notes_file, args.assets)}')
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        fail(str(error))
    return 0


if __name__ == '__main__':
    sys.exit(main())
