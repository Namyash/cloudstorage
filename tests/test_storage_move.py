import base64
import json
from pathlib import Path
import re
import secrets
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from werkzeug.test import Client
from werkzeug.wrappers import Response

from backend import drive_discovery
from backend import host_server as host


ORIGIN = 'http://127.0.0.1:8765'
PASSWORD = 'example-test-admin-password'


class StorageMoveTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.original = self.root / 'original'
        self.destination = self.root / 'new'
        self.config = self.root / 'host.json'
        folders = patch.object(host, 'folder_choice', side_effect=lambda values: self.root / (values.get('newName') or values['path']))
        roots = patch.object(host, 'storage_folder', side_effect=lambda path, _system=False: path)
        inventory = patch.object(host, 'drive_inventory', return_value=[])
        hardware = patch.object(host, 'physical_disks', return_value=[])
        for mock in (folders, roots, inventory, hardware):
            mock.start()
            self.addCleanup(mock.stop)
        service, _, setup_code = host.create_host(self.config)
        self.client = Client(service, Response)
        self.send('POST', 'storage/unlock', code=setup_code)
        self.send('POST', 'storage/select', newName=self.original.name)
        self.send('POST', 'setup', code=setup_code, name='Test admin', username='admin', password=PASSWORD)
        self.initial_config = json.loads(self.config.read_text(encoding='utf-8'))

    def send(self, method, endpoint, expected=200, payload=None, **values):
        if payload is not None:
            body = {'data': payload, 'content_type': 'application/octet-stream'}
        else:
            body = {'json': values} if values else {}
        result = self.client.open(f'/api/{endpoint}', method=method, base_url=ORIGIN, buffered=True, **body,
                                  headers={'X-Family-Drive': '1'}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        self.assertEqual(result.status_code, expected, result.get_json(silent=True))
        return result

    def move(self, expected=202, password=PASSWORD):
        self.send('POST', 'storage/move', expected, newName=self.destination.name, password=password)

    def wait_move(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.send('GET', 'storage/state').json
            if result['move'] and result['move']['phase'] in ('done', 'failed'):
                return result
            time.sleep(0.03)
        self.fail('Storage move did not finish')

    def test_local_listener_rejects_a_second_server_on_the_same_port(self):
        with host.bind_local_listener(0) as listener:
            listener.listen()
            port = listener.getsockname()[1]
            with self.assertRaises(OSError):
                with host.bind_local_listener(port):
                    self.fail('A second server acquired the occupied port.')

    def test_storage_explorer_markup_has_every_script_control(self):
        html = self.client.get('/storage', base_url=ORIGIN, buffered=True)
        script = self.client.get('/assets/storage.js', base_url=ORIGIN, buffered=True)
        self.assertEqual(html.status_code, 200)
        self.assertEqual(script.status_code, 200)
        ids = set(re.findall(r'\bid="([^"]+)"', html.get_data(as_text=True)))
        controls = set(re.findall(r"\bel\('([^']+)'\)", script.get_data(as_text=True)))
        self.assertTrue(controls)
        self.assertEqual(controls - ids, set())

    def test_fresh_host_requires_a_separate_household_and_admin(self):
        new_config = self.root / 'new-host.json'
        service, _, setup_code = host.create_host(new_config, default_port=18766)
        client = Client(service, Response)
        old_session = self.client.get_cookie('family_drive_session', domain='127.0.0.1')
        client.set_cookie('family_drive_session', old_session.value, domain='127.0.0.1')

        def request(method, endpoint, **values):
            return client.open(f'/api/{endpoint}', method=method, json=values if values else None,
                               base_url='http://127.0.0.1:18766',
                               headers={'X-Family-Drive': '1'}, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})

        self.assertEqual(request('POST', 'storage/unlock', code=setup_code).status_code, 200)
        for selection in ({'path': self.original.name}, {'newName': self.original.name}):
            with self.subTest(selection=selection):
                rejected = request('POST', 'storage/select', **selection)
                self.assertEqual(rejected.status_code, 409)
                self.assertIn('new or empty folder', rejected.json['error'])
                self.assertFalse(new_config.exists())

        empty = self.root / 'client-storage'
        empty.mkdir()
        self.assertEqual(request('POST', 'storage/select', path=empty.name).status_code, 200)
        self.assertEqual(request('GET', 'state').json, {'user': None, 'setup': True, 'setupOnHost': False})
        setup = request('POST', 'setup', code=setup_code, name='Client admin', username='client-admin', password=PASSWORD)
        self.assertEqual(setup.status_code, 200)
        self.assertEqual(request('GET', 'state').json['user']['username'], 'client-admin')
        self.assertEqual(self.send('GET', 'state').json['user']['username'], 'admin')
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8')), self.initial_config)

    def test_relocated_drive_preserves_household_and_updates_saved_path(self):
        self.original.rename(self.destination)
        storage_id = self.initial_config['storageId']
        with patch.object(host, 'relocated_storage_folder', return_value=self.destination) as locate:
            self.assertEqual(self.send('GET', 'state').json['user']['username'], 'admin')
        locate.assert_called_once_with(self.original, storage_id, False)
        saved = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(saved, dict(self.initial_config, data=str(self.destination)))

    def test_discovery_checks_the_same_folder_on_eligible_drive_letters(self):
        duplicate = self.root / 'duplicate'
        duplicate.mkdir()
        identity = self.initial_config['storageId']
        (duplicate / '.family-drive-id').write_text(identity, encoding='ascii')
        volumes = [
            {'drive': 'F:', 'eligible': True, 'system': False, 'ready': True},
            {'drive': 'G:', 'eligible': True, 'system': False, 'ready': True},
            {'drive': 'K:', 'eligible': True, 'system': False, 'ready': True},
            {'drive': 'C:', 'eligible': False, 'system': True, 'ready': True},
        ]
        candidates = {'G:': duplicate, 'K:': self.original}
        saved = r'F:\Family\SpareDriveData'
        with (
            patch.object(drive_discovery, 'drive_inventory', return_value=volumes),
            patch.object(drive_discovery, 'joined_folder', side_effect=lambda drive, *_: candidates[drive]) as browse,
        ):
            self.assertEqual(drive_discovery.relocated_storage_folder(saved, identity), self.original)
            self.assertEqual([call.args for call in browse.call_args_list], [
                ('G:', 'Family/SpareDriveData', False), ('K:', 'Family/SpareDriveData', False),
            ])
            (duplicate / 'family-drive.sqlite3').touch()
            self.assertIsNone(drive_discovery.relocated_storage_folder(saved, identity))

    def test_offline_new_household_requires_unlock_and_keeps_old_storage(self):
        carried_away = self.root / 'disconnected'
        self.original.rename(carried_away)
        old_database = carried_away / 'family-drive.sqlite3'
        old_contents = old_database.read_bytes()
        with patch.object(host, 'relocated_storage_folder', return_value=None):
            service, _, setup_code = host.create_host(self.config)
            self.client = Client(service, Response)
            self.send('POST', 'storage/select', 401, newName=self.destination.name, newHousehold=True)
            self.send('POST', 'storage/unlock', code=setup_code)
            self.send('POST', 'storage/select', 409, newName=self.destination.name)
            self.send('POST', 'storage/select', 409, path=carried_away.name, newHousehold=True)
            self.send('POST', 'storage/select', newName=self.destination.name, newHousehold=True)

        backup, = self.root.glob('host.previous-*.json')
        self.assertEqual(json.loads(backup.read_text(encoding='utf-8')), self.initial_config)
        saved = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(saved['data'], str(self.destination))
        self.assertNotEqual(saved['storageId'], self.initial_config['storageId'])
        self.assertEqual(old_database.read_bytes(), old_contents)
        self.assertTrue(self.send('GET', 'state').json['setup'])
        self.send('POST', 'setup', name='New admin', username='new-admin', password=PASSWORD, code=setup_code)
        self.assertEqual(self.send('GET', 'state').json['user']['username'], 'new-admin')

    def test_switch_preserves_ciphertext_accounts_and_quota(self):
        user = self.send('GET', 'state').json['user']
        self.send('PATCH', f'people/{user["id"]}', quota=1_000_000)
        self.send('POST', 'vault', revision=0, salt=self.blob(16), verifier=self.blob(43),
                  wrappedKey=self.blob(60), recoveryWrap=self.blob(60))
        payload = secrets.token_bytes(137)
        file_id = secrets.token_hex(16)
        self.send('POST', 'uploads', 201, id=file_id, space='private', revision=1, size=len(payload) - 28, label=self.blob(43))
        self.send('PUT', f'uploads/{file_id}/0', payload=payload)

        self.move(expected=400, password='wrong-password')
        self.assertFalse(self.destination.exists())
        self.move()
        state = self.wait_move()
        self.assertEqual(state['move']['phase'], 'done', state['move'])
        self.assertEqual(state['selected'], str(self.destination))
        self.assertEqual(self.send('GET', 'state').json['user'], dict(user, quota=1_000_000))
        self.assertEqual(self.send('GET', f'files/{file_id}/blob').data, payload)
        self.assertEqual((self.original / 'objects' / file_id).read_bytes(), payload)
        self.assertEqual((self.destination / 'objects' / file_id).read_bytes(), payload)
        self.assertEqual((self.original / '.family-drive-id').read_text(), self.initial_config['storageId'])
        self.assertNotEqual((self.destination / '.family-drive-id').read_text(), self.initial_config['storageId'])

    def test_pending_upload_leaves_old_storage_active(self):
        self.send('PATCH', 'family', quota=1_000_000)
        file_id = secrets.token_hex(16)
        self.send('POST', 'uploads', 201, id=file_id, space='family', size=40, label='test file')
        self.move()
        result = self.wait_move()
        self.assertEqual(result['move']['phase'], 'failed')
        self.assertIn('cancel', result['move']['error'])
        self.assertEqual(result['selected'], str(self.original))
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8')), self.initial_config)
        self.assertFalse(self.destination.exists())
        self.send('DELETE', f'uploads/{file_id}')

    @staticmethod
    def blob(size):
        return base64.b64encode(secrets.token_bytes(size)).decode()


if __name__ == '__main__':
    unittest.main()
