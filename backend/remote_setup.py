"""Give an initialized SpareDrive host a public HTTPS URL and optional Vercel launch page."""

import argparse
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, gettempdir, mkdtemp
from time import monotonic, sleep
from urllib.request import ProxyHandler, Request, build_opener


HTTPS_PORT = 443
NODE_NAME = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){2,}\Z')
DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
VERCEL_HOST = re.compile(r'[a-z0-9][a-z0-9-]*\.vercel\.app\Z')
EMAIL = re.compile(r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\Z')
HTTP = build_opener(ProxyHandler({}))


def command(executable, *arguments, cwd=None, capture=False):
    result = subprocess.run(
        [str(executable), *arguments], cwd=cwd, check=True,
        text=True, stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else None


def read_json(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected an object in {path.name}.')
    return value


def app_ready(url, host=None):
    endpoint = url + '/api/state'
    request = Request(endpoint, headers={'Host': host} if host else {})
    with HTTP.open(request, timeout=5) as response:
        if response.geturl() != endpoint:
            raise ValueError(f'SpareDrive redirected the readiness check at {url}.')
        result = json.loads(response.read(16_384))
    if not isinstance(result, dict) or result.get('setup') is not False or result.get('setupOnHost') is not False or 'user' not in result:
        raise ValueError(f'Complete the local drive and first-admin setup before sharing {url}.')


def wait_for_app(url):
    deadline = monotonic() + 40
    while True:
        try:
            app_ready(url)
            return
        except (OSError, ValueError) as error:
            if monotonic() >= deadline:
                raise ValueError(f'Could not verify SpareDrive at {url}. Check Funnel status and leave SpareDrive running.') from error
            sleep(2)


def tailscale_path():
    found = shutil.which('tailscale.exe') or shutil.which('tailscale')
    if found:
        return found
    default = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Tailscale' / 'tailscale.exe'
    if default.is_file():
        return default
    return None


def ensure_tailscale():
    executable = tailscale_path()
    if executable:
        return executable

    download = 'https://tailscale.com/download/windows'
    winget = shutil.which('winget.exe') if sys.platform == 'win32' else None
    if not winget:
        raise ValueError(f'WinGet is unavailable. Install Tailscale from {download} and rerun internet setup.')

    print('Installing Tailscale using Windows Package Manager. Approve the installer if Windows prompts you.',
          flush=True)
    try:
        command(winget, 'install', '--id', 'Tailscale.Tailscale', '--exact', '--source', 'winget', '--no-upgrade')
    except subprocess.CalledProcessError as error:
        raise ValueError(f'WinGet could not install Tailscale. See its output above or install from {download}.') from error

    executable = tailscale_path()
    if not executable:
        raise ValueError('Tailscale was not detected after installation. Reopen internet setup and try again.')
    return executable


def funnel_hostname(tailscale):
    status = json.loads(command(tailscale, 'status', '--json', capture=True))
    if status.get('BackendState') != 'Running':
        print('Open Tailscale from the Windows system tray, sign in or connect, and approve this PC if prompted.',
              flush=True)
        input('When Tailscale is connected, press Enter: ')
        status = json.loads(command(tailscale, 'status', '--json', capture=True))

    name = (status.get('Self') or {}).get('DNSName', '').lower().removesuffix('.')
    if (status.get('BackendState') != 'Running' or len(name) > 253 or
            not name.endswith('.ts.net') or not NODE_NAME.fullmatch(name + '.')):
        raise ValueError('Tailscale must be connected with a valid .ts.net device name.')
    return name


def funnel_needs_setup(tailscale, hostname, local_url):
    status = json.loads(command(tailscale, 'serve', 'status', '--json', capture=True) or '{}') or {}
    address = f'{hostname}:{HTTPS_PORT}'
    web = status.get('Web') or {}
    handlers = web.get(address, {}).get('Handlers', {})
    public = (status.get('AllowFunnel') or {}).get(address) is True
    if public and set(handlers) == {'/'} and handlers['/'].get('Proxy') == local_url:
        return False
    configs = [status, *(status.get('Foreground') or {}).values()]
    for config in configs:
        if str(HTTPS_PORT) in (config.get('TCP') or {}) or any(
            key.endswith(f':{HTTPS_PORT}') for key in (config.get('Web') or {})
        ):
            raise ValueError('Tailscale already has a route on HTTPS port 443. Use a separate host or reconfigure that route before continuing.')
    return True


def save_public_origin(config, settings, origin):
    current = read_json(config)
    if current != settings:
        raise ValueError('Your host settings changed during setup. Run internet setup again.')
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=config.parent,
                                prefix='.sparedrive-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(dict(settings, httpsUrl=origin), stream, indent=2)
            stream.write('\n')
        temporary.replace(config)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_launch_page(directory, destination):
    public = directory / 'public'
    public.mkdir()
    link = escape(destination, quote=True)
    (public / 'index.html').write_text(f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Open SpareDrive</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
          background: #f0f4ef; color: #172720; font: 16px/1.55 system-ui, sans-serif; }}
  main {{ width: min(100%, 30rem); background: #fff; border-radius: 20px; padding: clamp(24px, 7vw, 48px);
          border: 1px solid #dae4dc; }}
  h1 {{ font-size: 2.4rem; letter-spacing: -.045em; line-height: 1.1; margin: 0 0 12px; }}
  p {{ margin: 0 0 24px; }}
  a {{ display: inline-block; background: #165b48; color: white; padding: 12px 18px;
       border-radius: 9px; text-decoration: none; font-weight: 650; }}
  a:focus-visible {{ outline: 3px solid #17392c; outline-offset: 4px; }}
</style>
</head>
<body><main data-sparedrive-launch>
<h1>SpareDrive</h1>
<p>Open your household drive and sign in with your SpareDrive account.</p>
<a href="{link}" rel="noreferrer">Open SpareDrive</a>
</main></body></html>
''', encoding='utf-8')
    (directory / 'vercel.json').write_text(
        json.dumps({'framework': None, 'outputDirectory': 'public'}, indent=2) + '\n',
        encoding='utf-8',
    )


def vercel_cli():
    installed = shutil.which('vercel')
    if installed:
        return [installed]
    npx = shutil.which('npx')
    if npx:
        return [npx, '--yes', 'vercel@latest']
    raise ValueError('Install Node.js with npx, or install the Vercel CLI, and run internet setup again.')


def read_launch_domain():
    while True:
        choice = input(
            'Launch page address (e.g. smith-family or drive.example.com; Enter for Vercel default): '
        ).strip().lower()
        if not choice:
            return None
        host = choice.removeprefix('https://').removesuffix('/')
        if DNS_LABEL.fullmatch(host):
            return f'{host}.vercel.app'
        labels = host.split('.')
        if (len(host) <= 253 and len(labels) > 1 and all(DNS_LABEL.fullmatch(label) for label in labels)
                and not labels[-1].isdigit() and host != 'vercel.app'
                and (not host.endswith('.vercel.app') or len(labels) == 3)):
            return host
        print('Enter a single Vercel name or a full domain without a port or path.', flush=True)


def launch_page_is_live(host, destination):
    url = f'https://{host}/'
    try:
        with HTTP.open(url, timeout=8) as response:
            data = response.read(16_384)
            expected_link = f'href="{escape(destination, quote=True)}"'.encode()
            return (response.geturl() == url and b'data-sparedrive-launch' in data
                    and expected_link in data)
    except OSError:
        return False


def publish_launch_page(destination):
    cli = vercel_cli()

    def vercel(*args, **options):
        return command(cli[0], *cli[1:], *args, **options)

    email = input('Vercel account email (Enter to use an existing CLI login): ').strip()
    if email:
        if not EMAIL.fullmatch(email):
            raise ValueError('Enter a valid email address for Vercel.')
        print("Complete Vercel's verification in the official login flow.", flush=True)
        vercel('login', email)
    vercel('whoami')
    requested = read_launch_domain()
    project_name = requested.removesuffix('.vercel.app') if requested and VERCEL_HOST.fullmatch(requested) else 'sparedrive-family'

    temp_root = Path(gettempdir()).resolve()
    staging = Path(mkdtemp(prefix='sparedrive-vercel-', dir=temp_root))
    try:
        directory = staging / project_name
        directory.mkdir()
        write_launch_page(directory, destination)
        print('Choose your Vercel account or team and a dedicated project for the SpareDrive launch page.', flush=True)
        if requested and VERCEL_HOST.fullmatch(requested):
            print(f'For {requested}, use {project_name} as the project name when creating a project.', flush=True)
        vercel('link', cwd=directory)
        deployed = vercel('deploy', '--prod', '--yes', cwd=directory, capture=True)
        host = deployed.removeprefix('https://').rstrip('/')
        if not VERCEL_HOST.fullmatch(host):
            raise ValueError('Vercel did not report a deployment URL.')
        project = read_json(directory / '.vercel' / 'project.json')
        team_id = project.get('orgId', '')
        query = f'?teamId={team_id}' if re.fullmatch(r'team_[A-Za-z0-9]+', team_id) else ''
        result = json.loads(vercel('api', f'/v13/deployments/{host}{query}', '--raw', cwd=directory, capture=True))
        aliases = result.get('alias') or []
        if requested:
            if requested not in aliases:
                project_id = project.get('projectId', '')
                if not re.fullmatch(r'prj_[A-Za-z0-9]+', project_id):
                    raise ValueError(f'Vercel deployed {deployed}, but the linked project ID is missing.')
                try:
                    vercel('api', f'/v10/projects/{project_id}/domains{query}', '-X', 'POST',
                           '-f', f'name={requested}', cwd=directory)
                except subprocess.CalledProcessError:
                    print(f'Vercel could not attach {requested}. Check the command output and the project Domains tab.',
                          flush=True)
            if launch_page_is_live(requested, destination):
                return f'https://{requested}'
            print(f'Requested address https://{requested} is not ready. '
                  'Check availability, DNS verification and HTTPS under Domains in Vercel.', flush=True)

        for alias in aliases:
            if (isinstance(alias, str) and alias != requested and VERCEL_HOST.fullmatch(alias)
                    and launch_page_is_live(alias, destination)):
                return f'https://{alias}'
        raise ValueError(f'Vercel deployed {deployed}, but no production address served the public launch page. '
                         'Check Domains and Deployment Protection in Vercel.')
    finally:
        # Windows can briefly keep the CLI working directory open after deployment.
        if staging.resolve().parent == temp_root:
            shutil.rmtree(staging, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_config = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.config')) / 'FamilyDrive' / 'host.json'
    parser.add_argument('--config', type=Path, default=default_config, help='Windows SpareDrive host settings')
    config = parser.parse_args().config.expanduser().resolve()
    try:
        if not config.is_file():
            print('Start SpareDrive and complete its storage and first-admin setup in your browser.', flush=True)
            input('When the SpareDrive dashboard opens, press Enter here: ')
        settings = read_json(config)
        port = settings.get('port', 8765)
        if not settings.get('data') or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Use the host settings from an initialized SpareDrive installation.')
        local_url = f'http://127.0.0.1:{port}'
        try:
            app_ready(local_url)
        except (OSError, ValueError):
            print(f'Open SpareDrive at {local_url} and complete its setup if prompted.', flush=True)
            input('When the SpareDrive dashboard opens, press Enter here: ')
            app_ready(local_url)

        tailscale = ensure_tailscale()
        hostname = funnel_hostname(tailscale)
        public_url = f'https://{hostname}'
        needs_funnel = funnel_needs_setup(tailscale, hostname, local_url)
        if needs_funnel and input(f'Enable public HTTPS for SpareDrive at {public_url}? [y/N] ').strip().lower() != 'y':
            return 0

        previous = settings.get('httpsUrl')
        if previous != public_url:
            if previous and input(f'Replace the current HTTPS address {previous}? [y/N] ').strip().lower() != 'y':
                return 0
            save_public_origin(config, settings, public_url)
            print('Saved the HTTPS address. Restart SpareDrive using the same settings file.', flush=True)
            input('When SpareDrive is running again, press Enter: ')
        app_ready(local_url, hostname)

        if needs_funnel:
            command(tailscale, 'funnel', '--bg', f'--https={HTTPS_PORT}', local_url)
        print(f'To disable this public link: tailscale funnel --https={HTTPS_PORT} off', flush=True)
        print('Checking the HTTPS address…', flush=True)
        wait_for_app(public_url)
        print(f'SpareDrive HTTPS link: {public_url}', flush=True)
        if input('Publish a Vercel launch page linking to SpareDrive? [y/N] ').strip().lower() == 'y':
            origin = publish_launch_page(public_url)
            print(f'Family launch page: {origin}', flush=True)
        print('Leave the home PC awake with SpareDrive, Tailscale and the selected drive running.')
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\nInternet setup stopped.', file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Internet setup stopped. {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
