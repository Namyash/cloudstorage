"""Serve storage setup while the household's data drive is unavailable."""

import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
from threading import Condition, RLock, Thread
import tempfile
from time import monotonic

from flask import Flask, abort, jsonify, request, send_from_directory
from waitress import create_server
from werkzeug.exceptions import HTTPException

if __package__:
    from .storage_migration import move_household
    from .account_and_file_api import CHUNK, MIN_FREE, OVERHEAD, STORAGE_ASSETS, WEB, create_app
    from .drive_discovery import (
        drive_inventory, folder_choice, folder_contents, household_matches, physical_disks, relocated_storage_folder,
        storage_folder,
    )
else:
    from storage_migration import move_household
    from account_and_file_api import CHUNK, MIN_FREE, OVERHEAD, STORAGE_ASSETS, WEB, create_app
    from drive_discovery import (
        drive_inventory, folder_choice, folder_contents, household_matches, physical_disks, relocated_storage_folder,
        storage_folder,
    )


HOST_COOKIE = 'family_drive_host'
AUTH_AGE = 15 * 60
MUTATIONS = {'POST', 'PUT', 'PATCH', 'DELETE'}
MOVING = {'waiting', 'copying', 'verifying'}


def create_host(config, default_port=8765, set_temp=None):
    config = Path(config)
    settings = json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
    port = int(settings.get('port', default_port))
    origin = f'http://127.0.0.1:{port}'
    setup_code = secrets.token_hex(12)
    host_token = secrets.token_urlsafe(32)
    lock = RLock()
    writes = Condition(lock)
    writers = 0
    move = None
    mounted = None
    mount_error = ''
    next_relocation_check = 0
    authorized_until = 0
    attempts = 0
    attempt_window = 0
    portal = Flask(__name__, static_folder=None)
    portal.config.update(MAX_CONTENT_LENGTH=16 * 1024)

    def set_drive_temp(path):
        if set_temp:
            buffer_folder = path / '.http-tmp'
            buffer_folder.mkdir(exist_ok=True)
            set_temp(str(buffer_folder))

    def open_drive(path, drive_settings, *, require_empty_storage=False):
        storage_id = drive_settings.get('storageId')
        if storage_id and not household_matches(path, storage_id):
            raise ValueError('The original SpareDrive database is unavailable.')
        return create_app(path, port, drive_settings.get('httpsUrl'), storage_id, setup_code,
                          storage_move=queue_move, storage_status=move_status,
                          require_empty_storage=require_empty_storage)

    def active_app():
        nonlocal settings, mounted, mount_error, next_relocation_check
        with lock:
            if not settings:
                return None
            saved = Path(settings['data'])
            path = saved
            storage_id = settings.get('storageId')
            allow_system = settings.get('allowSystemDrive') is True
            if not household_matches(saved, storage_id):
                mounted = None
                mount_error = 'The saved household folder or database could not be opened. Reconnect your drive or use Storage explorer to choose a new household.'
                stamp = monotonic()
                if stamp < next_relocation_check:
                    return None
                next_relocation_check = stamp + 3
                path = relocated_storage_folder(saved, storage_id, allow_system)
                if path is None:
                    return None
            if mounted is None:
                try:
                    folder = storage_folder(path, allow_system)
                    updated = dict(settings, data=str(folder))
                    app = open_drive(folder, updated)
                    set_drive_temp(folder)
                    if folder != saved:
                        save_settings(updated)
                    settings, mounted, mount_error = updated, app, ''
                except (ValueError, OSError, sqlite3.Error):
                    mount_error = 'The storage folder is unavailable. Check the drive and folder permissions.'
            return mounted

    def moving():
        return move is not None and move['phase'] in MOVING

    def move_status():
        with lock:
            return dict(move) if move else None

    def save_settings(updated):
        config.parent.mkdir(parents=True, exist_ok=True)
        temp = config.with_suffix('.tmp')
        temp.write_text(json.dumps(updated, indent=2), encoding='utf-8')
        temp.replace(config)

    def run_move(source, source_id, target, updated):
        nonlocal settings, mounted, mount_error

        def report(phase, copied, total, files, file_count):
            with lock:
                move.update(phase=phase, copied=copied, total=total, files=files, fileCount=file_count)

        try:
            with writes:
                writes.wait_for(lambda: writers == 0)
            move_household(source, target, source_id, updated['storageId'], MIN_FREE, report)
            with lock:
                app = open_drive(target, updated)
                set_drive_temp(target)
                save_settings(updated)
                settings, mounted, mount_error = updated, app, ''
                move.update(phase='done')
        except ValueError as error:
            with lock:
                move.update(phase='failed', error=str(error))
        except (OSError, UnicodeError, sqlite3.Error):
            portal.logger.exception('Storage move failed')
            with lock:
                if set_temp:
                    set_temp(str(source / '.http-tmp'))
                move.update(phase='failed', error='The move stopped. Check that both drives are connected and writable, then try a new destination folder.')

    def queue_move(values):
        nonlocal move
        with lock:
            if moving() or active_app() is None:
                raise ValueError('The current storage folder is busy or unavailable.')
            if not isinstance(values.get('newName'), str) or not values['newName'].strip():
                raise ValueError('Enter the name of a new folder to receive the copy.')
            target = folder_choice(values)
            source = Path(settings['data'])
            if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
                raise ValueError('Choose a new folder outside the current SpareDrive folder.')
            updated = dict(settings, data=str(target), storageId=secrets.token_hex(16), allowSystemDrive=values.get('allowSystem') is True)
            move = {'phase': 'waiting', 'target': str(target), 'copied': 0, 'total': 0, 'files': 0, 'fileCount': 0}
            Thread(target=run_move, args=(source, settings['storageId'], target, updated), daemon=True, name='family-drive-storage-move').start()
            return dict(move)

    def authorized():
        token = request.cookies.get(HOST_COOKIE, '')
        return bool(token and monotonic() < authorized_until and hmac.compare_digest(token, host_token))

    @portal.before_request
    def local_only():
        if request.host != f'127.0.0.1:{port}' or request.remote_addr != '127.0.0.1':
            abort(403, 'Open the storage setup on your SpareDrive computer.')
        if request.method == 'POST':
            source = request.headers.get('Origin')
            if request.headers.get('X-Family-Drive') != '1' or (source and source != origin):
                abort(403, 'Reload the storage setup page before trying again.')

    @portal.after_request
    def headers(response):
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
                                 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @portal.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @portal.errorhandler(OSError)
    @portal.errorhandler(sqlite3.Error)
    def drive_error(_error):
        return jsonify(error='The folder is unavailable or access is restricted.'), 400

    @portal.get('/')
    @portal.get('/storage')
    def page():
        return send_from_directory(WEB, 'storage.html')

    @portal.get('/assets/<name>')
    def asset(name):
        if name not in STORAGE_ASSETS:
            abort(404)
        return send_from_directory(WEB, name)

    @portal.get('/api/storage/state')
    def state():
        with lock:
            info = {'mode': 'moving' if moving() else 'offline' if settings else 'setup', 'selected': settings.get('data'),
                    'detail': mount_error, 'unlocked': authorized(), 'move': move_status()}
        return jsonify(**info, volumes=drive_inventory(), disks=physical_disks())

    @portal.post('/api/storage/unlock')
    def unlock():
        nonlocal authorized_until, attempts, attempt_window
        values = request.get_json(silent=True)
        value = values.get('code') if isinstance(values, dict) else None
        if not isinstance(value, str) or len(value) > 64:
            abort(400, 'Enter the setup code printed in the terminal.')
        with lock:
            stamp = monotonic()
            if stamp >= attempt_window:
                attempts, attempt_window = 0, stamp + 300
            if attempts >= 8:
                abort(429, 'Too many setup-code attempts. Try again in a few minutes.')
            attempts += 1
            if not hmac.compare_digest(value.strip().encode(), setup_code.encode()):
                abort(403, 'That setup code is incorrect.')
            attempts = 0
            authorized_until = stamp + AUTH_AGE
        response = jsonify(ok=True)
        response.set_cookie(HOST_COOKIE, host_token, max_age=AUTH_AGE, httponly=True, samesite='Strict', path='/api/storage')
        return response

    @portal.get('/api/storage/folders')
    def folders():
        if not authorized():
            abort(401, 'Enter your setup code to browse drive folders.')
        try:
            return jsonify(folder_contents(request.args.get('drive', ''), request.args.get('path', ''),
                                           request.args.get('offset', 0, type=int), request.args.get('system') == '1'))
        except ValueError as error:
            abort(400, str(error))

    @portal.post('/api/storage/select')
    def select():
        nonlocal settings, mounted, mount_error, authorized_until
        values = request.get_json(silent=True)
        if not isinstance(values, dict):
            abort(400, 'Select a drive and storage folder.')
        with lock:
            if not authorized():
                abort(401, 'Enter your setup code before selecting a storage folder.')
            if moving() or active_app() is not None:
                abort(409, 'The storage folder is already connected.')
            start_new = values.get('newHousehold') is True
            try:
                path = folder_choice(values)
            except ValueError as error:
                abort(400, str(error))
            if settings and not start_new and not household_matches(path, settings.get('storageId')):
                abort(409, 'Choose the original SpareDrive folder with its database and matching storage identity.')
            updated = dict({} if start_new else settings, data=str(path), port=port,
                           allowSystemDrive=values.get('allowSystem') is True)
            try:
                current = open_drive(path, updated, require_empty_storage=start_new or not settings)
            except ValueError as error:
                abort(409, str(error))
            updated['storageId'] = (path / '.family-drive-id').read_text(encoding='ascii')
            if start_new and settings:
                backup = config.with_name(f'{config.stem}.previous-{secrets.token_hex(6)}.json')
                with backup.open('x', encoding='utf-8') as stream:
                    json.dump(settings, stream, indent=2)
            set_drive_temp(path)
            save_settings(updated)
            settings, mounted, mount_error = updated, current, ''
            authorized_until = 0
        response = jsonify(ok=True)
        response.delete_cookie(HOST_COOKIE, path='/api/storage', httponly=True, samesite='Strict')
        return response

    @portal.route('/api/<path:unused>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
    def unavailable(unused):
        abort(503, 'Storage is offline. Open the storage explorer to check the connected drive.')

    def dispatch(environ, start_response):
        nonlocal writers
        with writes:
            app = None if moving() else active_app()
            writing = app is not None and environ['REQUEST_METHOD'] in MUTATIONS
            if writing:
                writers += 1
        try:
            return (app if app is not None else portal)(environ, start_response)
        finally:
            if writing:
                with writes:
                    writers -= 1
                    writes.notify_all()

    return dispatch, port, setup_code


def bind_local_listener(port):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Windows SO_REUSEADDR otherwise permits overlapping local servers.
        option = socket.SO_EXCLUSIVEADDRUSE if os.name == 'nt' else socket.SO_REUSEADDR
        listener.setsockopt(socket.SOL_SOCKET, option, 1)
        listener.bind(('127.0.0.1', port))
    except OSError:
        listener.close()
        raise
    return listener


def main():
    parser = argparse.ArgumentParser(description='Run SpareDrive and the local storage explorer.')
    local = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.config')) / 'FamilyDrive' / 'host.json'
    parser.add_argument('config', type=Path, nargs='?', default=local, help='Host settings file')
    parser.add_argument('--port', type=int, default=8765, help='Local port for a new host setup')
    args = parser.parse_args()
    service, port, code = create_host(args.config, args.port, set_temp=lambda path: setattr(tempfile, 'tempdir', path))
    try:
        listener = bind_local_listener(port)
    except OSError:
        parser.exit(1, f'SpareDrive could not use 127.0.0.1:{port}. '
                       'Close the server already using this port and try again.\n')
    with listener:
        server = create_server(service, sockets=[listener], threads=6,
                               max_request_body_size=CHUNK + OVERHEAD, inbuf_overflow=CHUNK + OVERHEAD + 1)
        print(f'SpareDrive is available at http://127.0.0.1:{server.effective_port}/', flush=True)
        print(f'Local storage and admin setup code: {code}', flush=True)
        server.run()


if __name__ == '__main__':
    main()
