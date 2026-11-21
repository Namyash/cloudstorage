from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest

from server import create_app


ORIGIN = 'http://127.0.0.1:8765'
HEADERS = {'X-Family-Drive': '1'}


class FamilyAccessTest(unittest.TestCase):
    def request(self, client, method, endpoint, status=200, **options):
        response = client.open('/api/' + endpoint, method=method, base_url=ORIGIN,
                               headers=HEADERS, buffered=True, **options)
        self.assertEqual(response.status_code, status, response.get_json(silent=True))
        return response

    def test_admin_can_grant_revoke_and_pause_a_family_account(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root)
            admin, member = app.test_client(), app.test_client()
            self.request(admin, 'POST', 'setup', json={'code': app.config['SETUP_CODE'],
                         'name': 'Test administrator', 'username': 'admin', 'password': 'test password'})
            self.request(admin, 'PATCH', 'family', json={'quota': 100})
            account = self.request(admin, 'POST', 'people', 201, json={'name': 'Test member', 'username': 'member',
                                   'role': 'family', 'quota': 0, 'familyAccess': False}).json
            self.request(member, 'POST', 'login', json={'username': 'member', 'password': account['temporaryPassword']})
            self.request(member, 'POST', 'password', json={'current': account['temporaryPassword'], 'password': 'member password'})
            path = 'people/' + account['id']
            self.request(member, 'PATCH', path, 403, json={'quota': 0, 'familyAccess': True})
            self.request(member, 'GET', 'files?space=family', 404)
            self.assertNotIn('familyQuota', self.request(member, 'GET', 'state').json)

            self.request(admin, 'PATCH', path, json={'quota': 0, 'familyAccess': True})
            self.assertTrue(self.request(member, 'GET', 'state').json['user']['familyAccess'])
            ready, pending = secrets.token_hex(16), secrets.token_hex(16)
            for file_id in (ready, pending):
                self.request(member, 'POST', 'uploads', 201, json={'id': file_id, 'space': 'family', 'label': 'note.txt', 'size': 3})
            self.request(member, 'PUT', f'uploads/{ready}/0', data=b'abc', content_type='application/octet-stream')

            self.request(admin, 'PATCH', path, json={'quota': 0, 'familyAccess': False})
            self.request(member, 'GET', 'files?space=family', 404)
            self.request(member, 'GET', f'files/{ready}/blob', 404)
            self.request(member, 'DELETE', f'files/{ready}', 404)
            self.request(member, 'PUT', f'uploads/{pending}/0', 404, data=b'abc', content_type='application/octet-stream')
            self.request(member, 'POST', 'uploads', 404, json={'id': secrets.token_hex(16), 'space': 'family', 'label': 'note.txt', 'size': 3})
            self.assertEqual(self.request(admin, 'GET', f'files/{ready}/blob').data, b'abc')
            self.assertFalse((root / 'objects' / pending).exists())
            self.request(member, 'GET', 'files')

            self.request(admin, 'PATCH', path, json={'quota': 0, 'familyAccess': True})
            self.assertEqual(self.request(member, 'GET', f'files/{ready}/blob').data, b'abc')
            self.request(admin, 'PATCH', path, json={'quota': 0, 'active': False})
            self.request(member, 'GET', 'files', 401)
            self.request(admin, 'PATCH', path, json={'quota': 0, 'active': True})
            self.request(member, 'POST', 'login', json={'username': 'member', 'password': 'member password'})
            self.request(member, 'GET', 'files?space=family')
