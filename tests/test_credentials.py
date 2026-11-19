import base64
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from server import SCHEMA, create_app, now, password_hash


ORIGIN = 'http://127.0.0.1:8765'


class CredentialTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def send(self, client, endpoint, status=200, **data):
        response = client.post('/api/' + endpoint, base_url=ORIGIN, json=data,
                               headers={'X-Family-Drive': '1'}, buffered=True)
        self.assertEqual(response.status_code, status, response.get_json(silent=True))
        return response.get_json()

    def test_short_admin_credentials_and_long_sign_in_password(self):
        app = create_app(self.root, storage_move=lambda _: {'phase': 'waiting'})
        client = app.test_client()
        setup = {'code': app.config['SETUP_CODE'], 'name': 'Test administrator'}
        self.send(client, 'setup', 400, **setup, username=' ', password='a')
        self.send(client, 'setup', 400, **setup, username='?', password='')
        self.send(client, 'setup', **setup, username='?', password='a')
        long_password = ('✦ Test pass! ' * 20) + ' '
        self.send(client, 'password', current='a', password=long_password)
        self.send(client, 'logout')
        self.send(client, 'login', 401, username='?', password=long_password.strip())
        self.send(client, 'login', username='?', password=long_password)
        self.send(client, 'storage/move', 202, password=long_password)

        def encoded(size):
            return base64.b64encode(bytes(size)).decode()

        self.send(client, 'vault', revision=0, salt=encoded(16), verifier=encoded(43),
                  wrappedKey=encoded(60), recoveryWrap=encoded(60))
        self.send(client, 'vault/reset', password=long_password, revision=1)
        self.send(client, 'password', current=long_password, password='é')
        self.send(client, 'logout')
        self.send(client, 'login', username='?', password='é')

    def test_member_username_preserves_spelling_and_ignores_case_on_sign_in(self):
        app = create_app(self.root)
        admin = app.test_client()
        self.send(admin, 'setup', code=app.config['SETUP_CODE'], name='Test administrator', username='Admin', password='x')
        name = '❇ É Family / ' + ('Test ' * 15).strip()
        options = {'name': 'Test member', 'role': 'family', 'quota': 0}
        created = self.send(admin, 'people', 201, **options, username=name)
        self.assertEqual(created['username'], name)
        alternate = name.casefold().replace('é', 'e\N{COMBINING ACUTE ACCENT}')
        self.send(admin, 'people', 409, **options, username=alternate)
        member = app.test_client()
        self.send(member, 'login', username=alternate, password=created['temporaryPassword'])
        self.send(member, 'password', current=created['temporaryPassword'], password='?')
        reset = self.send(admin, 'people/' + created['id'] + '/reset')
        self.assertEqual(reset['username'], name)
        self.send(member, 'login', username=name, password=reset['temporaryPassword'])
        self.send(member, 'password', current=reset['temporaryPassword'], password='🌿')
        self.send(member, 'logout')
        self.send(member, 'login', username=alternate, password='🌿')

    def test_existing_database_sign_in_survives_username_lookup_upgrade(self):
        with closing(sqlite3.connect(self.root / 'family-drive.sqlite3')) as db:
            db.executescript(SCHEMA)
            db.execute('INSERT INTO users(id, username, name, role, password, quota, created) VALUES(?,?,?,?,?,?,?)',
                       ('a' * 32, 'old-login', 'Existing account', 'admin', password_hash('existing-test-passphrase'), 0, now()))
            db.commit()
        updated = create_app(self.root)
        client = updated.test_client()
        self.send(client, 'login', username='OLD-LOGIN', password='existing-test-passphrase')
        state = client.get('/api/state', base_url=ORIGIN).get_json()
        self.assertEqual(state['user']['username'], 'old-login')
