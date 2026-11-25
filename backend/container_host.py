"""Run SpareDrive with an explicitly mounted data drive."""

import argparse
from contextlib import closing
from getpass import getpass
import os
from pathlib import Path
import sqlite3
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from waitress import serve

from .account_and_file_api import create_app

DATA_DIR = Path('/data')
CONTAINER_PORT = 8765


def mounted_data_dir():
    with Path('/proc/self/mountinfo').open(encoding='utf-8') as mounts:
        if not any(line.split()[4] == str(DATA_DIR) for line in mounts):
            raise ValueError('Mount an existing data folder at /data before starting SpareDrive.')
    return DATA_DIR


def create_admin(app, host_port):
    code = app.config['SETUP_CODE']
    if not code:
        raise ValueError('The admin account already exists.')
    if not sys.stdin.isatty():
        raise ValueError('Run the setup command in an interactive terminal.')
    name = input('Display name: ')
    username = input('Username: ')
    password = getpass('Password: ')
    if password != getpass('Confirm password: '):
        raise ValueError('The passwords did not match.')

    with app.test_client() as client:
        response = client.post(
            '/api/setup',
            base_url=f'http://127.0.0.1:{host_port}',
            headers={'X-Family-Drive': '1'},
            json={'name': name, 'username': username, 'password': password, 'code': code},
        )
    if response.status_code != 200:
        raise ValueError(response.get_json()['error'])
    print('Admin account created. Sign in to SpareDrive in your browser.')


def check_health(host_port):
    request = Request(
        f'http://127.0.0.1:{CONTAINER_PORT}/api/state',
        headers={'Host': f'127.0.0.1:{host_port}'},
    )
    try:
        with closing(urlopen(request, timeout=3)):
            return 0
    except (OSError, URLError):
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'setup', 'health'), default='serve', nargs='?')
    action = parser.parse_args().action
    try:
        host_port = int(os.environ.get('SPAREDRIVE_HOST_PORT', '18765'))
        if not 1 <= host_port <= 65535:
            raise ValueError('SPAREDRIVE_HOST_PORT must be between 1 and 65535.')
        if action == 'health':
            return check_health(host_port)
        root = mounted_data_dir()
        app = create_app(
            root,
            port=host_port,
            public_url=os.environ.get('SPAREDRIVE_HTTPS_ORIGIN'),
            expected_storage_id=os.environ.get('SPAREDRIVE_STORAGE_ID'),
            setup_in_browser=action == 'setup',
        )
        if action == 'setup':
            create_admin(app, host_port)
        else:
            serve(app, host='0.0.0.0', port=CONTAINER_PORT)
    except (OSError, ValueError, sqlite3.Error, EOFError) as error:
        print(f'SpareDrive: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
