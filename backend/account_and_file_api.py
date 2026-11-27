"""Local SpareDrive server. The browser encrypts files in personal spaces."""

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
from threading import BoundedSemaphore
import time
import unicodedata
from urllib.parse import urlsplit

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

if __package__:
    from .drive_discovery import drive_inventory, folder_contents, physical_disks, storage_folder
else:
    from drive_discovery import drive_inventory, folder_contents, physical_disks, storage_folder


PACKAGE_DIR = Path(__file__).resolve().parent
WEB = (PACKAGE_DIR if __package__ == 'family_drive' else PACKAGE_DIR.parent) / 'frontend'
STORAGE_ASSETS = {'storage.js', 'storage.css', 'styles.css', 'sparedrive-logo.png'}
CHUNK = 4 * 1024 * 1024
OVERHEAD = 28  # 12-byte IV and 16-byte authentication tag
MIN_FREE = 512 * 1024 * 1024
SESSION_AGE = 12 * 60 * 60
# Uploads cannot resume, so one that receives no chunk for this long was interrupted.
# The wait must exceed the time a slow connection needs to send a single chunk.
UPLOAD_IDLE = 30 * 60
UPLOAD_IDLE_NOTE = f'Interrupted uploads are cleared after {UPLOAD_IDLE // 60} minutes.'
ACCOUNT_ITEM_LIMIT = 25_000
ID = re.compile(r'[a-f0-9]{32}')
COOKIE = 'family_drive_session'
DUMMY_SALT = secrets.token_bytes(16)
ITEM_TABLES = {'file': ('files', 'folder_id'), 'folder': ('folders', 'parent_id')}
FOLDER_TREE = '''WITH RECURSIVE tree(id) AS (
    SELECT id FROM folders WHERE id = ?
    UNION SELECT f.id FROM folders f JOIN tree ON f.parent_id = tree.id
) '''

SCHEMA = '''
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','family','guest')),
  password TEXT NOT NULL, quota INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  expires INTEGER, exchange INTEGER NOT NULL DEFAULT 0,
  change_password INTEGER NOT NULL DEFAULT 0, salt TEXT, verifier TEXT, created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, count INTEGER NOT NULL, until INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), space TEXT NOT NULL,
  label TEXT NOT NULL, size INTEGER NOT NULL, stored INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL CHECK(state IN ('uploading','ready','removed')), created INTEGER NOT NULL,
  modified INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS files_space ON files(space, state);
CREATE INDEX IF NOT EXISTS files_owner ON files(owner, state);
CREATE TABLE IF NOT EXISTS vault_archives (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), created INTEGER NOT NULL,
  salt TEXT NOT NULL, verifier TEXT NOT NULL, vault_wrap TEXT, recovery_wrap TEXT
);
CREATE TABLE IF NOT EXISTS folders (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), space TEXT NOT NULL,
  parent_id TEXT REFERENCES folders(id), archive_id TEXT REFERENCES vault_archives(id),
  label TEXT NOT NULL, created INTEGER NOT NULL, trashed INTEGER
);
CREATE INDEX IF NOT EXISTS folders_parent ON folders(parent_id);
CREATE INDEX IF NOT EXISTS folders_space ON folders(space, archive_id);
CREATE INDEX IF NOT EXISTS folders_owner ON folders(owner);
CREATE TABLE IF NOT EXISTS stars (
  user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, item_id TEXT NOT NULL,
  PRIMARY KEY (user_id, kind, item_id)
);
'''


def now():
    return int(time.time())


def server_options():
    """Waitress settings for every entry point.

    Waitress reads a whole request body before Flask runs, so only the server can refuse an
    oversized body before it fills memory or temporary storage.
    """
    return {'threads': 6, 'max_request_body_size': CHUNK + OVERHEAD, 'inbuf_overflow': CHUNK + OVERHEAD + 1}


def session_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return f'{salt.hex()}:{digest.hex()}'


def check_password(password, stored):
    salt = bytes.fromhex(stored.split(':')[0]) if stored else DUMMY_SALT
    candidate = password_hash(password, salt)
    return stored is not None and hmac.compare_digest(candidate, stored)


def storable(text):
    """Whether text can be saved as UTF-8. JSON escapes can carry unpaired surrogates, which SQLite rejects."""
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def credential_text(value, label, *, trim=False):
    if not isinstance(value, str):
        abort(400, f'Enter your {label}.')
    if trim:
        value = value.strip()
    if not value:
        abort(400, f'Enter your {label}.')
    if not storable(value):
        abort(400, f'Enter a valid {label}.')
    return value


def username_key(username):
    return unicodedata.normalize('NFC', username.casefold())


def named_account(data):
    name = data.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        abort(400, 'Enter a display name of up to 60 characters.')
    if not storable(name):
        abort(400, 'Enter a valid display name.')
    return name.strip(), credential_text(data.get('username'), 'username', trim=True)


def number(value, label):
    if type(value) is not int or not 0 <= value <= 10**15:
        abort(400, f'Invalid {label}.')
    return value


def encoded(value, minimum, maximum):
    if not isinstance(value, str) or len(value) > maximum * 2:
        abort(400, 'Invalid encrypted metadata.')
    try:
        size = len(base64.b64decode(value, validate=True))
    except ValueError:
        abort(400, 'Invalid encrypted metadata.')
    if not minimum <= size <= maximum:
        abort(400, 'Invalid encrypted metadata.')
    return value


def file_label(space, label):
    if space == 'private':
        return encoded(label, 29, 1052)
    if (not isinstance(label, str) or not 1 <= len(label) <= 255 or label in ('.', '..')
            or re.search(r'[\x00-\x1f\x7f/\\]', label) or not storable(label)):
        abort(400, 'Invalid filename.')
    return label


def guest_expiry(value, previous=None):
    if value in (None, ''):
        return None
    if isinstance(value, str) and value.endswith(('Z', 'z')):
        value = value[:-1] + '+00:00'  # Browsers send UTC as "Z", which Python 3.10 cannot parse.
    try:
        parsed = datetime.fromisoformat(value)
        stamp = int(parsed.timestamp()) if parsed.tzinfo else 0
    except (TypeError, ValueError, OverflowError, OSError):
        stamp = 0
    if stamp <= now() and stamp != previous:
        abort(400, 'Choose an expiry in the future.')
    return stamp


def create_app(root, port=8765, public_url=None, expected_storage_id=None, setup_code_override=None,
               storage_move=None, storage_status=None, setup_in_browser=True, require_empty_storage=False):
    root = Path(root).expanduser().resolve()
    if root == root.parent:
        raise ValueError('Choose a dedicated folder on the drive, such as E:\\SpareDriveData.')
    marker = root / '.family-drive-id'
    if expected_storage_id:
        try:
            root_id = marker.read_text(encoding='ascii')
        except (OSError, UnicodeError):
            root_id = None
        if root_id != expected_storage_id:
            raise ValueError('The configured storage folder belongs to a different drive or is unavailable.')
    else:
        root.mkdir(parents=True, exist_ok=True)
        fresh_folder_error = 'Choose a new or empty folder. This folder already contains files or a SpareDrive household.'
        if require_empty_storage and next(root.iterdir(), None) is not None:
            raise ValueError(fresh_folder_error)
        if require_empty_storage or not marker.exists():
            try:
                with marker.open('x', encoding='ascii') as stream:
                    stream.write(secrets.token_hex(16))
            except FileExistsError as error:
                if require_empty_storage:
                    raise ValueError(fresh_folder_error) from error
        root_id = marker.read_text(encoding='ascii')
    objects = root / 'objects'
    objects.mkdir(exist_ok=True)
    database = root / 'family-drive.sqlite3'
    app = Flask(__name__, static_folder=None)
    login_slots = BoundedSemaphore(3)
    loopback = f'http://127.0.0.1:{port}'
    origins = {urlsplit(loopback).netloc: loopback}
    if public_url:
        url = urlsplit(public_url)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('The public URL must be an HTTPS origin, such as https://host.example.net.')
        origins[url.netloc.lower()] = f'https://{url.netloc.lower()}'
    app.config.update(TRUSTED_HOSTS=[urlsplit(o).hostname for o in origins.values()], MAX_CONTENT_LENGTH=CHUNK + OVERHEAD)

    def connect():
        db = sqlite3.connect(database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        return db

    with connect() as db:
        db.execute('PRAGMA journal_mode = WAL')
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        user_columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
        if 'username_key' not in user_columns:
            db.execute('ALTER TABLE users ADD COLUMN username_key TEXT')
        if 'family_access' not in user_columns:
            db.execute('ALTER TABLE users ADD COLUMN family_access INTEGER NOT NULL DEFAULT 1')
        users_to_index = db.execute('SELECT id, username FROM users WHERE username_key IS NULL').fetchall()
        db.executemany('UPDATE users SET username_key = ? WHERE id = ?',
                       ((username_key(row['username']), row['id']) for row in users_to_index))
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_username_key ON users(username_key)')
        if 'vault_wrap' not in user_columns:
            db.execute('ALTER TABLE users ADD COLUMN vault_wrap TEXT')
        if 'recovery_wrap' not in user_columns:
            db.execute('ALTER TABLE users ADD COLUMN recovery_wrap TEXT')
        if 'vault_revision' not in user_columns:
            db.execute('ALTER TABLE users ADD COLUMN vault_revision INTEGER NOT NULL DEFAULT 0')
        file_columns = {row['name'] for row in db.execute('PRAGMA table_info(files)')}
        if 'archive_id' not in file_columns:
            db.execute('ALTER TABLE files ADD COLUMN archive_id TEXT REFERENCES vault_archives(id)')
        if 'folder_id' not in file_columns:
            db.execute('ALTER TABLE files ADD COLUMN folder_id TEXT REFERENCES folders(id)')
        if 'trashed' not in file_columns:
            db.execute('ALTER TABLE files ADD COLUMN trashed INTEGER')
        db.execute('CREATE INDEX IF NOT EXISTS files_folder ON files(folder_id)')
        db.execute("INSERT OR IGNORE INTO config VALUES ('family_quota', '0')")
        needs_setup = not db.execute('SELECT 1 FROM users LIMIT 1').fetchone()
    db.close()
    setup_code = (setup_code_override or secrets.token_hex(12)) if needs_setup and setup_in_browser else None
    app.config['SETUP_CODE'] = setup_code

    def connection():
        if 'db' not in g:
            g.db = connect()
        return g.db

    def one(sql, values=()):
        return connection().execute(sql, values).fetchone()

    def session_user(session):
        return one('''SELECT users.* FROM users JOIN sessions ON user_id = users.id
            WHERE token = ? AND sessions.expires > ? AND active = 1
            AND (users.expires IS NULL OR users.expires > ?)''', (session, now(), now()))

    @contextmanager
    def write():
        db = connection()
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise

    @app.teardown_appcontext
    def close(_error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    def clean_removed():
        with write() as db:
            for row in db.execute("SELECT id FROM files WHERE state = 'removed'").fetchall():
                try:
                    (objects / row['id']).unlink(missing_ok=True)
                except OSError:
                    continue  # Windows can retain a file while an earlier download is open.
                db.execute("DELETE FROM files WHERE id = ? AND state = 'removed'", (row['id'],))
                db.execute("DELETE FROM stars WHERE kind = 'file' AND item_id = ?", (row['id'],))

    def expire_uploads():
        connection().execute("UPDATE files SET state = 'removed' WHERE state = 'uploading' AND modified < ?", (now() - UPLOAD_IDLE,))
        clean_removed()

    def cancel_uploads(db, owner, space=None):
        """Stop an account's unfinished uploads, optionally in one space, and return how many stopped."""
        sql, values = "UPDATE files SET state = 'removed' WHERE owner = ? AND state = 'uploading'", (owner,)
        if space is not None:
            sql, values = sql + ' AND space = ?', (owner, space)
        return db.execute(sql, values).rowcount

    with app.app_context():
        expire_uploads()
        connection().execute('DELETE FROM sessions WHERE expires <= ?', (now(),))
        connection().execute('DELETE FROM attempts WHERE until <= ?', (now(),))

    @app.before_request
    def protect_requests():
        g.origin = origins.get(request.host.lower())
        if not g.origin:
            abort(400, 'Unrecognized host.')
        if request.path.startswith('/api/'):
            try:
                present = marker.read_text(encoding='ascii') == root_id
            except (OSError, UnicodeError):
                present = False
            if not present:
                abort(503, 'The storage drive is unavailable. Reconnect it and restart SpareDrive.')
            if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                origin = request.headers.get('Origin')
                if request.headers.get('X-Family-Drive') != '1' or (origin and origin != g.origin):
                    abort(403, 'Request blocked. Reload SpareDrive and try again.')
            g.user = None
            token = request.cookies.get(COOKIE, '')
            if len(token) == 43:
                g.session = session_hash(token)
                g.user = session_user(g.session)

    @app.after_request
    def headers(response):
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src blob:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(OSError)
    @app.errorhandler(sqlite3.OperationalError)
    def storage_error(error):
        app.logger.error('Storage operation failed: %s', error)
        return jsonify(error='Storage could not be accessed. Check the drive and try again.'), 503

    def json_body():
        if (request.content_length or 0) > 16_384:
            abort(413)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, 'Expected a JSON object.')
        return data

    def require_user(admin=False, allow_change=False):
        user = g.user
        if user is None:
            abort(401, 'Sign in to continue.')
        if user['change_password'] and not allow_change:
            abort(403, 'Set your own password to continue.')
        if admin and user['role'] != 'admin':
            abort(403, 'Admin access is required.')
        return user

    def signed_in(db, user_id):
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions VALUES (?, ?, ?)', (session_hash(token), user_id, now() + SESSION_AGE))
        response = jsonify(ok=True)
        response.set_cookie(COOKIE, token, max_age=SESSION_AGE, httponly=True, samesite='Strict', secure=g.origin.startswith('https://'))
        return response

    def throttle(key, limit):
        stamp = now()
        with write() as db:
            row = db.execute('SELECT * FROM attempts WHERE key = ?', (key,)).fetchone()
            if row and row['until'] > stamp:
                if row['count'] >= limit:
                    abort(429, 'Too many attempts. Try again in a few minutes.')
                db.execute('UPDATE attempts SET count = count + 1 WHERE key = ?', (key,))
            else:
                db.execute('DELETE FROM attempts WHERE until <= ?', (stamp,))
                db.execute('REPLACE INTO attempts VALUES (?, 1, ?)', (key, stamp + 300))

    @app.get('/')
    def index():
        return send_from_directory(WEB, 'index.html')

    @app.get('/storage')
    def storage_page():
        return send_from_directory(WEB, 'storage.html')

    @app.get('/assets/<name>')
    def asset(name):
        if name not in STORAGE_ASSETS | {'app.js', 'vault.js'}:
            abort(404)
        return send_from_directory(WEB, name)

    @app.get('/api/storage/state')
    def storage_state():
        require_user(admin=True)
        return jsonify(mode='active', selected=str(root), volumes=drive_inventory(), disks=physical_disks(), unlocked=True,
                       canMove=storage_move is not None and g.origin == loopback,
                       move=storage_status() if storage_status and g.origin == loopback else None)

    @app.get('/api/storage/folders')
    def storage_folders():
        require_user(admin=True)
        try:
            return jsonify(folder_contents(request.args.get('drive', ''), request.args.get('path', ''),
                                           request.args.get('offset', 0, type=int), request.args.get('system') == '1'))
        except (OSError, ValueError) as error:
            abort(400, str(error) if isinstance(error, ValueError) else 'This folder is unavailable or access is restricted.')

    @app.post('/api/storage/move')
    def move_storage():
        user = require_user(admin=True)
        if storage_move is None or g.origin != loopback:
            abort(403, 'Open Storage explorer on the computer hosting SpareDrive to move its data.')
        values = json_body()
        password = credential_text(values.get('password'), 'SpareDrive sign-in password')
        throttle('storage-move:' + user['id'], 8)
        if not check_password(password, user['password']):
            abort(400, 'The sign-in password is incorrect.')
        expire_uploads()
        try:
            return jsonify(storage_move(values)), 202
        except (ValueError, PermissionError) as error:
            abort(400, str(error))

    @app.post('/api/setup')
    def setup():
        if not setup_in_browser or g.origin != loopback:
            abort(403, 'Create the first admin account on the computer hosting SpareDrive.')
        if not setup_code or one('SELECT 1 FROM users LIMIT 1'):
            abort(409, 'The admin account already exists.')
        data = json_body()
        name, username = named_account(data)
        chosen_password = credential_text(data.get('password'), 'password')
        throttle('setup-code', 8)
        code = data.get('code')
        code = code.strip() if isinstance(code, str) else ''
        if not code.isascii() or not hmac.compare_digest(code, setup_code):
            abort(403, 'Enter the setup code displayed on the host computer.')
        password = password_hash(chosen_password)
        uid = secrets.token_hex(16)
        with write() as db:
            if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                abort(409, 'The admin account already exists.')
            db.execute('INSERT INTO users(id, username, username_key, name, role, password, quota, created) VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
                       (uid, username, username_key(username), name, 'admin', password, 0, now()))
            db.execute("DELETE FROM attempts WHERE key IN ('setup', 'setup-code')")
            return signed_in(db, uid)

    sign_in_failed = 'The username or password is incorrect, or the account is inactive.'

    def sign_in_attempts(key):
        return 'login:' + session_hash(key)

    def verify_sign_in(key, password):
        attempt_key = sign_in_attempts(key)
        throttle(attempt_key, 8)
        user = one('SELECT id, password, change_password FROM users WHERE username_key = ? AND active = 1 '
                   'AND (expires IS NULL OR expires > ?)', (key, now()))
        valid = check_password(password, user['password'] if user else None)
        if user is None or not valid:
            abort(401, sign_in_failed)
        return user, attempt_key

    @app.post('/api/login')
    def login():
        data = json_body()
        key = username_key(credential_text(data.get('username'), 'username', trim=True))
        password = credential_text(data.get('password'), 'password')
        if not login_slots.acquire(blocking=False):
            abort(429, 'Sign-in is busy. Try again in a moment.')
        try:
            user, attempt_key = verify_sign_in(key, password)
            with write() as db:
                current = one('''SELECT 1 FROM users WHERE id = ? AND password = ? AND username_key = ? AND active = 1
                    AND (expires IS NULL OR expires > ?)''', (user['id'], user['password'], key, now()))
                if not current:
                    abort(401, sign_in_failed)
                db.execute('DELETE FROM attempts WHERE key = ?', (attempt_key,))
                return signed_in(db, user['id'])
        finally:
            login_slots.release()

    @app.post('/api/logout')
    def logout():
        if getattr(g, 'session', None):
            connection().execute('DELETE FROM sessions WHERE token = ?', (g.session,))
        response = jsonify(ok=True)
        response.delete_cookie(COOKIE, httponly=True, samesite='Strict', secure=g.origin.startswith('https://'))
        return response

    @app.post('/api/password')
    def change_password():
        user = require_user(allow_change=True)
        data = json_body()
        current = credential_text(data.get('current'), 'current password')
        throttle('password:' + user['id'], 8)
        if not check_password(current, user['password']):
            abort(400, 'The current password is incorrect.')
        username = credential_text(data.get('username', user['username']), 'username', trim=True)
        password = data.get('password', '')
        if password != '' or user['change_password'] or 'username' not in data:
            password = credential_text(password, 'new password')
            if current == password:
                abort(400, 'Choose a different password.')
        if not password and username == user['username']:
            abort(400, 'Enter a new username or password.')
        updated = password_hash(password) if password else user['password']
        with write() as db:
            live_user = session_user(g.session)
            if live_user is None or live_user['password'] != user['password']:
                abort(401, 'Your sign-in changed. Sign in again before updating your account.')
            key = username_key(username)
            if one('SELECT 1 FROM users WHERE username_key = ? AND id != ?', (key, user['id'])):
                abort(409, 'That username is already in use.')
            db.execute('UPDATE users SET username = ?, username_key = ?, password = ?, change_password = 0 WHERE id = ?',
                       (username, key, updated, user['id']))
            db.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
            db.execute('DELETE FROM attempts WHERE key = ?', ('password:' + user['id'],))
            return signed_in(db, user['id'])

    @app.post('/api/password/change')
    def change_password_from_sign_in():
        data = json_body()
        key = username_key(credential_text(data.get('username'), 'username', trim=True))
        current = credential_text(data.get('current'), 'current password')
        password = credential_text(data.get('password'), 'new password')
        if not login_slots.acquire(blocking=False):
            abort(429, 'Sign-in is busy. Try again in a moment.')
        try:
            user, attempt_key = verify_sign_in(key, current)
            if user['change_password']:
                abort(400, 'Sign in with your temporary password to finish setting up your account.')
            if password == current:
                abort(400, 'Choose a different password.')
            updated = password_hash(password)
            with write() as db:
                result = db.execute('''UPDATE users SET password = ? WHERE id = ? AND username_key = ?
                    AND password = ? AND active = 1 AND change_password = 0
                    AND (expires IS NULL OR expires > ?)''', (updated, user['id'], key, user['password'], now()))
                if result.rowcount != 1:
                    abort(401, sign_in_failed)
                db.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
                db.execute('DELETE FROM attempts WHERE key IN (?, ?)', (attempt_key, 'password:' + user['id']))
            return jsonify(ok=True)
        finally:
            login_slots.release()

    def family_quota():
        return int(one("SELECT value FROM config WHERE key = 'family_quota'")['value'])

    def usage(space=None, owner=None, reserved=False):
        field = 'stored' if reserved else 'size'
        states = "('ready','uploading')" if reserved else "('ready')"
        sql = f'SELECT COALESCE(SUM({field}), 0) AS amount FROM files WHERE state IN {states}'
        args = ()
        if space is not None:
            sql, args = sql + ' AND space = ?', (space,)
        if owner is not None:
            sql, args = sql + " AND owner = ? AND space != 'family'", (owner,)
        return one(sql, args)['amount']

    def account(row):
        return dict({key: row[key] for key in ('id', 'username', 'name', 'role', 'quota', 'active', 'expires', 'exchange')},
                    familyAccess=family_access(row))

    def family_access(user):
        return user['role'] == 'admin' or (user['role'] == 'family' and bool(user['family_access']))

    def family_permission(data, default):
        value = data.get('familyAccess', default)
        if type(value) is not bool:
            abort(400, 'Choose whether to allow Family Space access.')
        return int(value)

    def vault_info(row):
        return {'salt': row['salt'], 'verifier': row['verifier'],
                'wrappedKey': row['vault_wrap'], 'recoveryWrap': row['recovery_wrap']}

    @app.get('/api/state')
    def state():
        user = g.user
        if user is None:
            needs_setup = not one('SELECT 1 FROM users LIMIT 1')
            can_set_up = setup_in_browser and g.origin == loopback
            return jsonify(user=None, setup=needs_setup and can_set_up,
                           setupOnHost=needs_setup and not can_set_up)
        result = {'user': account(user), 'changePassword': bool(user['change_password'])}
        if user['change_password']:
            return jsonify(result)
        active_files = one("SELECT COUNT(*) AS amount FROM files WHERE owner = ? AND space = 'private' AND state = 'ready' AND archive_id IS NULL", (user['id'],))['amount']
        active_folders = one("SELECT COUNT(*) AS amount FROM folders WHERE owner = ? AND space = 'private' AND archive_id IS NULL", (user['id'],))['amount']
        archives = connection().execute('''SELECT v.*,
            (SELECT COUNT(*) FROM files f WHERE f.archive_id = v.id AND f.owner = v.owner AND f.state = 'ready') AS file_count,
            (SELECT COUNT(*) FROM folders f WHERE f.archive_id = v.id AND f.owner = v.owner) AS folder_count
            FROM vault_archives v WHERE v.owner = ? ORDER BY v.created DESC, v.id''', (user['id'],))
        result.update(vault=dict(vault_info(user), revision=user['vault_revision'], fileCount=active_files, folderCount=active_folders),
                      archives=[dict(vault_info(row), id=row['id'], created=row['created'],
                                     fileCount=row['file_count'], folderCount=row['folder_count']) for row in archives],
                      used=usage(owner=user['id']), chunkSize=CHUNK)
        if family_access(user):
            result.update(familyUsed=usage(space='family'), familyQuota=family_quota())
        if user['role'] == 'admin':
            users = connection().execute("SELECT * FROM users ORDER BY role = 'admin' DESC, created, name").fetchall()
            result['people'] = [dict(account(row), used=usage(owner=row['id']), reserved=usage(owner=row['id'], reserved=True)) for row in users]
            disk = shutil.disk_usage(root)
            allocated = sum(row['quota'] for row in users) + family_quota()
            capacity = allocation_capacity(disk.free)
            result['drive'] = {'total': disk.total, 'free': disk.free,
                               'allocated': allocated, 'allocatableCapacity': capacity,
                               'availableToAllocate': max(0, capacity - allocated),
                               'used': usage(), 'root': str(root), 'reserve': MIN_FREE}
        return jsonify(result)

    @app.route('/api/vault', methods=['POST', 'PATCH'])
    def save_vault():
        user = require_user()
        data = json_body()
        salt, verifier = encoded(data.get('salt'), 16, 16), encoded(data.get('verifier'), 32, 128)
        wrapped = encoded(data.get('wrappedKey'), 60, 60)
        recovery = encoded(data.get('recoveryWrap'), 60, 60)
        revision = number(data.get('revision'), 'vault revision')
        with write() as db:
            current = one('SELECT verifier, vault_revision FROM users WHERE id = ?', (user['id'],))
            if current['vault_revision'] != revision:
                abort(409, 'The vault changed in another tab. Reload before continuing.')
            if request.method == 'POST' and current['verifier'] is not None:
                abort(409, 'This vault is already set up. Reload to unlock it.')
            if request.method == 'PATCH' and current['verifier'] != verifier:
                abort(409, 'The vault configuration has changed. Reload before continuing.')
            db.execute('''UPDATE users SET salt = ?, verifier = ?, vault_wrap = ?, recovery_wrap = ?,
                          vault_revision = vault_revision + 1 WHERE id = ?''',
                       (salt, verifier, wrapped, recovery, user['id']))
        return jsonify(ok=True)

    @app.post('/api/vault/reset')
    def reset_vault():
        user = require_user()
        data = json_body()
        revision = number(data.get('revision'), 'vault revision')
        password = credential_text(data.get('password'), 'SpareDrive sign-in password')
        throttle('vault-reset:' + user['id'], 8)
        if not check_password(password, user['password']):
            abort(400, 'The sign-in password is incorrect.')
        expire_uploads()
        with write() as db:
            current = one('SELECT * FROM users WHERE id = ?', (user['id'],))
            if current['vault_revision'] != revision or not current['salt'] or current['password'] != user['password']:
                abort(409, 'Your account or vault changed. Reload before continuing.')
            pending = one("SELECT 1 FROM files WHERE owner = ? AND space = 'private' AND state = 'uploading'", (user['id'],))
            if pending:
                abort(409, f'Finish or cancel the active private upload before resetting the vault. {UPLOAD_IDLE_NOTE}')
            ready = one("SELECT COUNT(*) AS amount FROM files WHERE owner = ? AND space = 'private' AND state = 'ready' AND archive_id IS NULL", (user['id'],))['amount']
            has_folders = one("SELECT 1 FROM folders WHERE owner = ? AND space = 'private' AND archive_id IS NULL", (user['id'],))
            if ready or has_folders:
                archive = secrets.token_hex(16)
                db.execute('INSERT INTO vault_archives VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (archive, user['id'], now(), current['salt'], current['verifier'], current['vault_wrap'], current['recovery_wrap']))
                db.execute("UPDATE files SET archive_id = ? WHERE owner = ? AND space = 'private' AND state = 'ready' AND archive_id IS NULL",
                           (archive, user['id']))
                db.execute("UPDATE folders SET archive_id = ? WHERE owner = ? AND space = 'private' AND archive_id IS NULL",
                           (archive, user['id']))
            db.execute('''UPDATE users SET salt = NULL, verifier = NULL, vault_wrap = NULL, recovery_wrap = NULL,
                          vault_revision = vault_revision + 1 WHERE id = ?''', (user['id'],))
            db.execute('DELETE FROM attempts WHERE key = ?', ('vault-reset:' + user['id'],))
        return jsonify(ok=True, archived=ready, archiveCreated=bool(ready or has_folders))

    @app.post('/api/archives/<archive_id>/delete')
    def delete_archive(archive_id):
        user = require_user()
        if not ID.fullmatch(archive_id):
            abort(404, 'Archived vault not found.')
        password = credential_text(json_body().get('password'), 'SpareDrive sign-in password')
        throttle('archive-delete:' + user['id'], 8)
        if not check_password(password, user['password']):
            abort(400, 'The sign-in password is incorrect.')
        with write() as db:
            if not one('SELECT 1 FROM vault_archives WHERE id = ? AND owner = ?', (archive_id, user['id'])):
                abort(404, 'Archived vault not found.')
            archived_folders = 'SELECT id FROM folders WHERE archive_id = ?'
            # Detach every row that points at the archive so the foreign keys allow deleting it.
            db.execute(f'UPDATE files SET folder_id = NULL WHERE folder_id IN ({archived_folders})', (archive_id,))
            db.execute("UPDATE files SET state = 'removed', archive_id = NULL WHERE archive_id = ?", (archive_id,))
            db.execute(f"DELETE FROM stars WHERE kind = 'folder' AND item_id IN ({archived_folders})", (archive_id,))
            db.execute('DELETE FROM folders WHERE archive_id = ?', (archive_id,))
            db.execute('DELETE FROM vault_archives WHERE id = ?', (archive_id,))
            db.execute('DELETE FROM attempts WHERE key = ?', ('archive-delete:' + user['id'],))
        clean_removed()
        return jsonify(ok=True)

    def allocation_capacity(free):
        claimed = one("SELECT COALESCE(SUM(received), 0) AS amount FROM files WHERE state != 'removed'")['amount']
        return max(0, free + claimed - MIN_FREE)

    def check_allocation(new, previous=0):
        allocated = one('SELECT COALESCE(SUM(quota), 0) AS amount FROM users')['amount'] + family_quota()
        if new > previous and allocated - previous + new > allocation_capacity(shutil.disk_usage(root).free):
            abort(409, 'This allocation exceeds the available drive capacity with the other quotas.')

    def check_item_capacity(owner):
        count = one('''SELECT (SELECT COUNT(*) FROM files WHERE owner = ?)
                             + (SELECT COUNT(*) FROM folders WHERE owner = ?) AS amount''', (owner, owner))['amount']
        if count >= ACCOUNT_ITEM_LIMIT:
            abort(409, 'This account has reached its file and folder limit. Permanently delete items to make room.')

    def check_drive_reserve(additional=0):
        pending = one("SELECT COALESCE(SUM(stored-received), 0) AS amount FROM files WHERE state = 'uploading'")['amount']
        if pending + additional > shutil.disk_usage(root).free - MIN_FREE:
            abort(409, 'The drive does not have enough free space.')

    @app.post('/api/people')
    def add_person():
        require_user(admin=True)
        data = json_body()
        name, username = named_account(data)
        key = username_key(username)
        role, quota = data.get('role'), number(data.get('quota'), 'quota')
        if role not in ('family', 'guest'):
            abort(400, 'Choose family member or guest.')
        expiry = guest_expiry(data.get('expires')) if role == 'guest' else None
        exchange = int(role == 'guest' and data.get('exchange') is True)
        shared = family_permission(data, True) if role == 'family' else 0
        temporary = secrets.token_urlsafe(18)
        password = password_hash(temporary)
        uid = secrets.token_hex(16)
        with write() as db:
            check_allocation(quota)
            if one('SELECT 1 FROM users WHERE username_key = ?', (key,)):
                abort(409, 'That username is already in use.')
            db.execute('''INSERT INTO users(id, username, username_key, name, role, password, quota, expires, exchange, family_access, change_password, created)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)''', (uid, username, key, name, role, password, quota, expiry, exchange, shared, now()))
        return jsonify(id=uid, username=username, temporaryPassword=temporary), 201

    @app.patch('/api/people/<uid>')
    def edit_person(uid):
        actor = require_user(admin=True)
        data = json_body()
        quota = number(data.get('quota'), 'quota')
        expire_uploads()
        with write() as db:
            user = one('SELECT * FROM users WHERE id = ?', (uid,))
            if not user:
                abort(404, 'Account not found.')
            active = int(data.get('active', bool(user['active'])) is True)
            if uid == actor['id'] and not active:
                abort(400, 'The admin account must stay active.')
            expires, exchange = user['expires'], bool(user['exchange'])
            shared = family_permission(data, bool(user['family_access'])) if user['role'] == 'family' else user['family_access']
            if user['role'] == 'guest':
                if 'expires' in data:
                    expires = guest_expiry(data['expires'], previous=expires)
                exchange = data.get('exchange', exchange) is True
            if quota < usage(owner=uid, reserved=True):
                abort(409, 'The new quota is below the storage already used or reserved by this account.')
            check_allocation(quota, user['quota'])
            db.execute('UPDATE users SET quota = ?, active = ?, expires = ?, exchange = ?, family_access = ? WHERE id = ?',
                       (quota, active, expires, int(exchange), shared, uid))
            if not active:
                db.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))
            elif not user['active']:
                # Sign-in attempts made while paused must not lock out the reactivated account.
                db.execute('DELETE FROM attempts WHERE key = ?', (sign_in_attempts(user['username_key']),))
            # Uploads the account can no longer finish would otherwise hold its quota until they expire.
            if not active:
                cancelled = cancel_uploads(db, uid)
            elif user['role'] == 'family' and not shared:
                cancelled = cancel_uploads(db, uid, 'family')
            elif user['role'] == 'guest' and not exchange:
                cancelled = cancel_uploads(db, uid, 'exchange:' + uid)
            else:
                cancelled = 0
        if cancelled:
            clean_removed()
        return jsonify(ok=True)

    @app.post('/api/people/<uid>/reset')
    def reset_person(uid):
        actor = require_user(admin=True)
        if uid == actor['id']:
            abort(400, 'Change your own password from your account settings.')
        temporary = secrets.token_urlsafe(18)
        password = password_hash(temporary)
        with write() as db:
            user = one('SELECT username, username_key FROM users WHERE id = ?', (uid,))
            if not user:
                abort(404, 'Account not found.')
            db.execute('UPDATE users SET password = ?, change_password = 1 WHERE id = ?', (password, uid))
            db.execute('DELETE FROM sessions WHERE user_id = ?', (uid,))
            # The new temporary password starts without earlier sign-in or password-change failures.
            db.execute('DELETE FROM attempts WHERE key IN (?, ?)', (sign_in_attempts(user['username_key']), 'password:' + uid))
            cancelled = cancel_uploads(db, uid)  # Revoked sessions cannot finish them.
        if cancelled:
            clean_removed()
        return jsonify(username=user['username'], temporaryPassword=temporary)

    @app.patch('/api/family')
    def edit_family():
        require_user(admin=True)
        quota = number(json_body().get('quota'), 'quota')
        expire_uploads()
        with write() as db:
            if quota < usage(space='family', reserved=True):
                abort(409, 'The new quota is below the Family Space usage.')
            check_allocation(quota, family_quota())
            db.execute("UPDATE config SET value = ? WHERE key = 'family_quota'", (str(quota),))
        return jsonify(ok=True)

    def can_access(user, space):
        if space == 'private':
            return False
        if space == 'family':
            current = one('SELECT role, family_access FROM users WHERE id = ? AND active = 1', (user['id'],))
            return current is not None and family_access(current)
        if isinstance(space, str) and space.startswith('exchange:'):
            uid = space.removeprefix('exchange:')
            if user['role'] == 'admin':
                return bool(one("SELECT 1 FROM users WHERE id = ? AND role = 'guest'", (uid,)))
            return user['role'] == 'guest' and user['id'] == uid and bool(one(
                'SELECT 1 FROM users WHERE id = ? AND active = 1 AND exchange = 1 AND (expires IS NULL OR expires > ?)',
                (uid, now())))
        return False

    def folder_lineage(folder_id):
        return connection().execute('''WITH RECURSIVE ancestry AS (
            SELECT id, parent_id, trashed FROM folders WHERE id = ?
            UNION SELECT f.id, f.parent_id, f.trashed FROM folders f JOIN ancestry a ON f.id = a.parent_id
        ) SELECT * FROM ancestry''', (folder_id,)).fetchall()

    def item_accessible(user, row):
        if row['space'] == 'private':
            return row['owner'] == user['id']
        return can_access(user, row['space'])

    def item_row(kind, item_id, *, uploading=False, in_trash=False):
        user = require_user()
        if not isinstance(item_id, str) or not ID.fullmatch(item_id):
            abort(404, 'Item not found.')
        if kind == 'folder':
            row = one('SELECT * FROM folders WHERE id = ?', (item_id,))
        else:
            row = one('SELECT * FROM files WHERE id = ? AND state = ?', (item_id, 'uploading' if uploading else 'ready'))
        if not row or not item_accessible(user, row):
            abort(404, 'Item not found.')
        if row['archive_id'] is None:
            parent = row['parent_id'] if kind == 'folder' else row['folder_id']
            if bool(row['trashed']) != in_trash or (parent and any(node['trashed'] for node in folder_lineage(parent))):
                abort(404, 'Item not found.')
        elif in_trash:
            abort(404, 'Item not found.')
        return row

    def file_row(fid, ready=True):
        return item_row('file', fid, uploading=not ready)

    def can_manage_file(user, row):
        return row['archive_id'] is None and (row['owner'] == user['id'] or user['role'] == 'admin')

    def managed_item(kind, item_id, *, in_trash=False):
        row = item_row(kind, item_id, in_trash=in_trash)
        if row['archive_id'] is not None:
            abort(409, 'Archived files are read-only.')
        if not can_manage_file(g.user, row):
            abort(403, 'Only the uploader or admin can manage this shared file.')
        return row

    def managed_file(fid):
        return managed_item('file', fid)

    def verify_vault_revision(user, revision):
        current = one('SELECT salt, vault_revision FROM users WHERE id = ?', (user['id'],))
        if not current['salt'] or type(revision) is not int or revision != current['vault_revision']:
            abort(409, 'The vault changed. Reload and unlock it before continuing.')

    def destination(space, folder_id):
        user = require_user()
        if space != 'private' and not can_access(user, space):
            abort(404, 'Space not found.')
        if folder_id is None:
            return None
        row = item_row('folder', folder_id)
        if row['space'] != space or row['archive_id'] is not None:
            abort(404, 'Destination folder not found in this space.')
        return row['id']

    @app.get('/api/files')
    def list_files():
        user = require_user()
        space = request.args.get('space', 'private')
        archive = None
        if space.startswith('archive:'):
            archive = space.removeprefix('archive:')
            if not ID.fullmatch(archive) or not one('SELECT 1 FROM vault_archives WHERE id = ? AND owner = ?', (archive, user['id'])):
                abort(404, 'Archived vault not found.')
            space = 'private'
        if space == 'private':
            scope, params = 'f.space = ? AND f.owner = ? AND f.archive_id IS ?', (space, user['id'], archive)
        elif can_access(user, space):
            scope, params = 'f.space = ?', (space,)
        else:
            abort(404, 'Space not found.')
        db = connection()
        db.execute('BEGIN')
        folders = db.execute(f'SELECT f.*, u.name FROM folders f JOIN users u ON u.id=f.owner WHERE {scope}', params).fetchall()
        files = db.execute(f"""SELECT f.*, u.name FROM files f JOIN users u ON u.id=f.owner
                               WHERE f.state = 'ready' AND {scope} ORDER BY f.created DESC""", params).fetchall()
        stars = {(r['kind'], r['item_id']) for r in db.execute(
            'SELECT kind, item_id FROM stars WHERE user_id = ?', (user['id'],))}
        db.commit()
        children = {}
        for row in folders:
            children.setdefault(row['parent_id'], []).append(row['id'])
        hidden_folders = set()
        pending = [] if archive else [row['id'] for row in folders if row['trashed']]
        while pending:
            folder_id = pending.pop()
            if folder_id not in hidden_folders:
                hidden_folders.add(folder_id)
                pending.extend(children.get(folder_id, ()))
        result = dict(files=[], folders=[], trashFiles=[], trashFolders=[])
        for kind, rows, parent_column, active_key, trash_key in (
                ('folder', folders, 'parent_id', 'folders', 'trashFolders'),
                ('file', files, 'folder_id', 'files', 'trashFiles')):
            for row in rows:
                parent = row[parent_column]
                if parent in hidden_folders:
                    continue
                trashed = row['trashed'] if not archive else None
                manage = can_manage_file(user, row)
                if trashed and not manage:
                    continue
                entry = dict(id=row['id'], label=row['label'], kind=kind, folderId=parent,
                             size=row['size'] if kind == 'file' else 0, created=row['created'],
                             by=row['name'], canDelete=manage, starred=(kind, row['id']) in stars,
                             trashed=trashed)
                result[trash_key if trashed else active_key].append(entry)
        return jsonify(result)

    @app.post('/api/folders')
    def create_folder():
        user = require_user()
        data = json_body()
        folder_id, space = data.get('id'), data.get('space')
        if not isinstance(folder_id, str) or not ID.fullmatch(folder_id):
            abort(400, 'Invalid folder identifier.')
        with write() as db:
            parent = destination(space, data.get('folderId'))
            if space == 'private':
                verify_vault_revision(user, data.get('revision'))
            check_item_capacity(user['id'])
            check_drive_reserve()
            if one('SELECT 1 FROM folders WHERE id = ?', (folder_id,)):
                abort(409, 'This folder already exists.')
            db.execute('INSERT INTO folders (id, owner, space, parent_id, label, created) VALUES (?, ?, ?, ?, ?, ?)',
                       (folder_id, user['id'], space, parent, file_label(space, data.get('label')), now()))
        return jsonify(id=folder_id), 201

    @app.post('/api/uploads')
    def create_upload():
        user = require_user()
        data = json_body()
        fid, space, label = data.get('id'), data.get('space'), data.get('label')
        size = number(data.get('size'), 'file size')
        if not isinstance(fid, str) or not ID.fullmatch(fid):
            abort(400, 'Invalid file identifier.')
        if space != 'private' and not can_access(user, space):
            abort(404, 'Space not found.')
        file_label(space, label)
        chunks = max(1, (size + CHUNK - 1) // CHUNK)
        stored = size + (chunks * OVERHEAD if space == 'private' else 0)
        expire_uploads()
        with write() as db:
            # Read the latest quota under the same lock that reserves the space.
            parent = destination(space, data.get('folderId'))
            current = one('SELECT quota FROM users WHERE id = ?', (user['id'],))
            if space == 'private':
                verify_vault_revision(user, data.get('revision'))
            quota = family_quota() if space == 'family' else current['quota']
            used = usage(space='family', reserved=True) if space == 'family' else usage(owner=user['id'], reserved=True)
            if quota == 0 or used + stored > quota:
                abort(409, 'This file would exceed the storage quota.')
            check_item_capacity(user['id'])
            check_drive_reserve(stored)
            if one('SELECT 1 FROM files WHERE id = ?', (fid,)) or (objects / fid).exists():
                abort(409, 'This upload already exists. Try the file again.')
            with (objects / fid).open('xb'):
                pass
            try:
                db.execute("INSERT INTO files (id, owner, space, folder_id, label, size, stored, received, state, created, modified) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                           (fid, user['id'], space, parent, label, size, stored, 'ready' if stored == 0 else 'uploading', now(), now()))
            except BaseException:
                (objects / fid).unlink(missing_ok=True)
                raise
        return jsonify(id=fid), 201

    @app.put('/api/uploads/<fid>/<int:offset>')
    def upload_chunk(fid, offset):
        if request.mimetype != 'application/octet-stream':
            abort(415, 'Expected a binary upload chunk.')
        data = request.get_data()
        with write() as db:
            row = file_row(fid, ready=False)
            if row['owner'] != g.user['id']:
                abort(404, 'Upload not found.')
            unit = CHUNK + (OVERHEAD if row['space'] == 'private' else 0)
            expected = min(unit, row['stored'] - row['received'])
            if offset != row['received'] or len(data) != expected or expected <= 0:
                abort(409, 'Upload chunks arrived out of order. Start the upload again.')
            if shutil.disk_usage(root).free < MIN_FREE + len(data):
                abort(409, 'The drive does not have enough free space.')
            with (objects / fid).open('r+b') as stream:
                if stream.seek(0, os.SEEK_END) < offset:
                    abort(503, 'The partial upload is incomplete. Start the upload again.')
                stream.seek(offset)
                stream.write(data)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
            received = offset + len(data)
            db.execute('UPDATE files SET received=?, state=?, modified=? WHERE id=?',
                       (received, 'ready' if received == row['stored'] else 'uploading', now(), fid))
        return jsonify(received=received)

    @app.delete('/api/uploads/<fid>')
    def cancel_upload(fid):
        with write() as db:
            row = file_row(fid, ready=False)
            if row['owner'] != g.user['id']:
                abort(404, 'Upload not found.')
            db.execute("UPDATE files SET state = 'removed' WHERE id = ?", (fid,))
        clean_removed()
        return jsonify(ok=True)

    @app.get('/api/files/<fid>/blob')
    def download_file(fid):
        row = file_row(fid)
        try:
            return send_file(objects / fid, as_attachment=True, mimetype='application/octet-stream',
                             download_name='private-file.enc' if row['space'] == 'private' else row['label'],
                             conditional=True, etag=False)
        except FileNotFoundError:
            abort(404, 'The file is missing from the drive.')

    @app.patch('/api/files/<fid>')
    @app.patch('/api/folders/<fid>')
    def rename_item(fid):
        data = json_body()
        kind = 'folder' if request.path.startswith('/api/folders/') else 'file'
        table, _ = ITEM_TABLES[kind]
        with write() as db:
            row = managed_item(kind, fid)
            label = file_label(row['space'], data.get('label'))
            if row['space'] == 'private':
                verify_vault_revision(g.user, data.get('revision'))
            db.execute(f'UPDATE {table} SET label = ? WHERE id = ?', (label, fid))
        return jsonify(ok=True)

    def remove_files(ids):
        with write() as db:
            for fid in ids:
                managed_file(fid)
                db.execute("UPDATE files SET state = 'removed' WHERE id = ?", (fid,))
        clean_removed()

    @app.delete('/api/files/<fid>')
    def remove_file(fid):
        remove_files([fid])
        return jsonify(ok=True)

    @app.post('/api/files/bulk-delete')
    def bulk_delete():
        require_user()
        ids = json_body().get('ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(fid, str) or not ID.fullmatch(fid) for fid in ids):
            abort(400, 'Select valid files to delete.')
        unique_ids = list(dict.fromkeys(ids))
        remove_files(unique_ids)
        return jsonify(ok=True, deleted=len(unique_ids))

    def check_folder_removal(folder_id):
        if one(FOLDER_TREE + """SELECT 1 FROM files WHERE folder_id IN (SELECT id FROM tree)
                                 AND state = 'uploading' LIMIT 1""", (folder_id,)):
            abort(409, f'Finish the uploads in this folder before removing it. {UPLOAD_IDLE_NOTE}')
        if g.user['role'] != 'admin' and one(FOLDER_TREE + '''
                SELECT 1 FROM folders WHERE id IN (SELECT id FROM tree) AND owner <> ?
                UNION ALL SELECT 1 FROM files WHERE folder_id IN (SELECT id FROM tree)
                    AND state = 'ready' AND owner <> ? LIMIT 1''', (folder_id, g.user['id'], g.user['id'])):
            abort(403, 'Only an admin can remove a folder containing other people’s items.')

    def purge_item(db, kind, item_id):
        if kind == 'file':
            db.execute("UPDATE files SET state = 'removed' WHERE id = ?", (item_id,))
            return
        db.execute(FOLDER_TREE + """UPDATE files SET state = 'removed', folder_id = NULL
                                     WHERE folder_id IN (SELECT id FROM tree)""", (item_id,))
        db.execute(FOLDER_TREE + """DELETE FROM stars WHERE kind = 'folder' AND item_id IN (SELECT id FROM tree)""", (item_id,))
        db.execute(FOLDER_TREE + 'DELETE FROM folders WHERE id IN (SELECT id FROM tree)', (item_id,))

    @app.post('/api/items/<action>')
    def organize_items(action):
        user = require_user()
        if action not in {'move', 'trash', 'restore', 'purge', 'star'}:
            abort(404)
        data = json_body()
        items = data.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            abort(400, 'Select between 1 and 200 items.')
        keys = {}
        for item in items:
            if not isinstance(item, dict):
                abort(400, 'Invalid item.')
            kind, item_id = item.get('kind'), item.get('id')
            if not isinstance(kind, str) or kind not in ITEM_TABLES or not isinstance(item_id, str) or not ID.fullmatch(item_id):
                abort(400, 'Invalid item.')
            keys[(kind, item_id)] = None
        if action in {'trash', 'purge'}:
            expire_uploads()  # Interrupted uploads must not block removing their folder.
        with write() as db:
            if action == 'star':
                starred = data.get('starred')
                if type(starred) is not bool:
                    abort(400, 'Choose whether to star these items.')
                for kind, item_id in keys:
                    item_row(kind, item_id)
                    if starred:
                        db.execute('INSERT OR IGNORE INTO stars VALUES (?, ?, ?)', (user['id'], kind, item_id))
                    else:
                        db.execute('DELETE FROM stars WHERE user_id = ? AND kind = ? AND item_id = ?',
                                   (user['id'], kind, item_id))
                return jsonify(ok=True)

            rows = [(kind, managed_item(kind, item_id, in_trash=action in {'restore', 'purge'}))
                    for kind, item_id in keys]
            if action in {'move', 'trash'}:
                selected_folders = {row['id'] for kind, row in rows if kind == 'folder'}
                if selected_folders:
                    rows = [(kind, row) for kind, row in rows if not any(
                        node['id'] in selected_folders
                        for node in folder_lineage(row[ITEM_TABLES[kind][1]]))]
            if action == 'move':
                space = rows[0][1]['space']
                if any(row['space'] != space for _, row in rows):
                    abort(400, 'Choose items from the same space.')
                target = destination(space, data.get('folderId'))
                ancestry = {node['id'] for node in folder_lineage(target)} if target else set()
                if any(kind == 'folder' and row['id'] in ancestry for kind, row in rows):
                    abort(409, 'A folder cannot be moved into itself or a subfolder.')
            elif action in {'trash', 'purge'}:
                for kind, row in rows:
                    if kind == 'folder':
                        check_folder_removal(row['id'])
            stamp = now()
            for kind, row in rows:
                table, parent_column = ITEM_TABLES[kind]
                if action == 'move':
                    db.execute(f'UPDATE {table} SET {parent_column} = ? WHERE id = ?', (target, row['id']))
                elif action == 'purge':
                    purge_item(db, kind, row['id'])
                else:
                    db.execute(f'UPDATE {table} SET trashed = ? WHERE id = ?',
                               (stamp if action == 'trash' else None, row['id']))
        if action == 'purge':
            clean_removed()
        return jsonify(ok=True)

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run SpareDrive on your home computer.')
    parser.add_argument('--data', required=True, help='Dedicated storage folder on the selected drive')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--https-url', help='Optional private HTTPS reverse-proxy origin')
    parser.add_argument('--allow-system-drive', action='store_true', help='Explicitly allow storage on the Windows system drive')
    parser.add_argument('--storage-id', help=argparse.SUPPRESS)
    args = parser.parse_args()
    from waitress import create_server

    try:
        folder = storage_folder(args.data, args.allow_system_drive)
        site = create_app(folder, args.port, args.https_url, args.storage_id)
    except (ValueError, OSError) as error:
        parser.exit(1, f'SpareDrive could not start. {error}\n')
    buffer_folder = folder / '.http-tmp'
    buffer_folder.mkdir(exist_ok=True)
    tempfile.tempdir = str(buffer_folder)
    server = create_server(site, host='127.0.0.1', port=args.port, **server_options())
    print(f'SpareDrive is available at http://127.0.0.1:{args.port}', flush=True)
    if site.config['SETUP_CODE']:
        print('One-time admin setup code: ' + site.config['SETUP_CODE'], flush=True)
    server.run()
