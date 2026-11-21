from base64 import b64encode
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

    def test_file_management_preserves_ownership_and_vault_metadata(self):
        with TemporaryDirectory() as directory:
            app = create_app(directory)
            admin, member = app.test_client(), app.test_client()
            self.request(admin, 'POST', 'setup', json={'code': app.config['SETUP_CODE'],
                         'name': 'Admin', 'username': 'admin', 'password': 'admin password'})
            self.request(admin, 'PATCH', 'family', json={'quota': 1000})
            account = self.request(admin, 'POST', 'people', 201, json={'name': 'Member', 'username': 'member',
                                   'role': 'family', 'quota': 1000}).json
            self.request(member, 'POST', 'login', json={'username': 'member', 'password': account['temporaryPassword']})
            self.request(member, 'POST', 'password', json={'current': account['temporaryPassword'], 'password': 'member password'})

            household, personal, second, private = [secrets.token_hex(16) for _ in range(4)]
            for client, file_id in [(admin, household), (member, personal), (member, second)]:
                self.request(client, 'POST', 'uploads', 201,
                             json={'id': file_id, 'space': 'family', 'label': 'initial.txt', 'size': 3})
                self.request(client, 'PUT', f'uploads/{file_id}/0', data=b'abc', content_type='application/octet-stream')
            self.request(member, 'PATCH', f'files/{household}', 403, json={'label': 'new.txt'})
            self.request(member, 'PATCH', f'files/{personal}', 400, json={'label': '../invalid.txt'})
            self.request(member, 'PATCH', f'files/{personal}', json={'label': 'renamed.txt'})
            renamed = self.request(admin, 'GET', f'files/{personal}/blob')
            self.assertEqual(renamed.data, b'abc')
            self.assertIn('renamed.txt', renamed.headers['Content-Disposition'])
            self.request(admin, 'PATCH', f'files/{personal}', json={'label': 'admin-renamed.txt'})

            # A rejected delete must leave even the permitted files in the batch.
            self.request(member, 'POST', 'files/bulk-delete', 403, json={'ids': [personal, household]})
            self.request(member, 'GET', f'files/{personal}/blob')
            self.request(member, 'POST', 'files/bulk-delete', 400, json={'ids': [personal, []]})
            result = self.request(member, 'POST', 'files/bulk-delete', json={'ids': [personal, second, personal]})
            self.assertEqual(result.json['deleted'], 2)
            self.assertEqual([file['id'] for file in self.request(member, 'GET', 'files?space=family').json['files']],
                             [household])

            packet = lambda length: b64encode(secrets.token_bytes(length)).decode('ascii')
            self.request(member, 'POST', 'vault', json={'salt': packet(16), 'verifier': packet(32),
                         'wrappedKey': packet(60), 'recoveryWrap': packet(60), 'revision': 0})
            self.request(member, 'POST', 'uploads', 201, json={'id': private, 'space': 'private',
                         'label': packet(29), 'size': 0, 'revision': 1})
            blob = secrets.token_bytes(28)
            self.request(member, 'PUT', f'uploads/{private}/0', data=blob, content_type='application/octet-stream')
            label = packet(45)
            self.request(admin, 'PATCH', f'files/{private}', 404, json={'label': label, 'revision': 1})
            self.request(admin, 'POST', 'files/bulk-delete', 404, json={'ids': [private]})
            self.request(member, 'PATCH', f'files/{private}', 409, json={'label': label, 'revision': 0})
            self.request(member, 'PATCH', f'files/{private}', 400, json={'label': 'plaintext.txt', 'revision': 1})
            self.request(member, 'PATCH', f'files/{private}', json={'label': label, 'revision': 1})
            self.assertEqual(self.request(member, 'GET', 'files').json['files'][0]['label'], label)
            self.assertEqual(self.request(member, 'GET', f'files/{private}/blob').data, blob)
            self.request(member, 'POST', 'vault/reset', json={'password': 'member password', 'revision': 1})
            self.request(member, 'PATCH', f'files/{private}', 409, json={'label': label, 'revision': 2})
            self.request(member, 'POST', 'files/bulk-delete', 409, json={'ids': [private]})

    def test_nested_folder_lifecycle_and_shared_permissions(self):
        with TemporaryDirectory() as directory:
            app = create_app(directory)
            admin, member = app.test_client(), app.test_client()
            self.request(admin, 'POST', 'setup', json={'code': app.config['SETUP_CODE'],
                         'name': 'Admin', 'username': 'admin', 'password': 'admin password'})
            self.request(admin, 'PATCH', 'family', json={'quota': 1000})
            account = self.request(admin, 'POST', 'people', 201, json={'name': 'Member', 'username': 'member',
                                   'role': 'family', 'quota': 1000}).json
            self.request(member, 'POST', 'login', json={'username': 'member', 'password': account['temporaryPassword']})
            self.request(member, 'POST', 'password', json={'current': account['temporaryPassword'], 'password': 'member password'})

            parent, child, file, pending, encrypted_folder = [secrets.token_hex(16) for _ in range(5)]
            for folder_id, folder_id_parent in [(parent, None), (child, parent)]:
                self.request(member, 'POST', 'folders', 201, json={'id': folder_id, 'space': 'family',
                             'folderId': folder_id_parent, 'label': 'Photos'})
            self.request(member, 'PATCH', f'folders/{child}', json={'label': 'Holiday'})
            for client, fid in [(admin, file), (member, pending)]:
                self.request(client, 'POST', 'uploads', 201, json={'id': fid, 'space': 'family',
                             'folderId': child, 'size': 3, 'label': 'photo.jpg'})
            self.request(admin, 'PUT', f'uploads/{file}/0', data=b'abc', content_type='application/octet-stream')
            self.request(member, 'POST', 'folders', 404, json={'id': encrypted_folder, 'space': 'private',
                         'folderId': child, 'label': 'Invalid'})

            ancestor = {'items': [{'kind': 'folder', 'id': parent}]}
            self.request(member, 'POST', 'items/move', 409, json={**ancestor, 'folderId': child})
            self.request(member, 'POST', 'items/star', json={**ancestor, 'starred': True})
            view = 'files?space=family'
            self.assertTrue(next(x for x in self.request(member, 'GET', view).json['folders'] if x['id'] == parent)['starred'])
            self.assertFalse(next(x for x in self.request(admin, 'GET', view).json['folders'] if x['id'] == parent)['starred'])
            self.request(admin, 'POST', 'items/trash', 409, json=ancestor)
            self.request(member, 'DELETE', f'uploads/{pending}')
            self.request(member, 'POST', 'items/trash', 403, json=ancestor)
            self.request(admin, 'POST', 'items/trash', json=ancestor)
            state = self.request(admin, 'GET', view).json
            self.assertEqual(state['files'], [])
            self.assertEqual(state['folders'], [])
            self.assertEqual([x['id'] for x in state['trashFolders']], [parent])
            self.assertEqual(self.request(admin, 'GET', 'state').json['familyUsed'], 3)
            self.request(admin, 'GET', f'files/{file}/blob', 404)
            self.request(admin, 'POST', 'items/restore', json=ancestor)
            self.assertEqual(self.request(admin, 'GET', f'files/{file}/blob').data, b'abc')
            self.assertEqual(self.request(admin, 'GET', view).json['files'][0]['folderId'], child)
            self.request(admin, 'POST', 'items/trash', json=ancestor)
            self.request(admin, 'POST', 'items/purge', json=ancestor)
            self.assertFalse((Path(directory) / 'objects' / file).exists())
            self.assertEqual(self.request(admin, 'GET', 'state').json['familyUsed'], 0)

            def packet(length):
                return b64encode(secrets.token_bytes(length)).decode('ascii')

            self.request(member, 'POST', 'vault', json={'salt': packet(16), 'verifier': packet(32),
                         'wrappedKey': packet(60), 'recoveryWrap': packet(60), 'revision': 0})
            label = packet(40)
            self.request(member, 'POST', 'folders', 201, json={'id': encrypted_folder, 'space': 'private',
                         'label': label, 'revision': 1})
            self.request(admin, 'PATCH', f'folders/{encrypted_folder}', 404, json={'label': 'Admin'})
            result = self.request(member, 'POST', 'vault/reset', json={'password': 'member password', 'revision': 1})
            self.assertTrue(result.json['archiveCreated'])
            archive = self.request(member, 'GET', 'state').json['archives'][0]
            self.assertEqual(archive['folderCount'], 1)
            self.assertEqual(self.request(member, 'GET', f'files?space=archive:{archive["id"]}').json['folders'][0]['label'], label)
            self.request(admin, 'GET', f'files?space=archive:{archive["id"]}', 404)
