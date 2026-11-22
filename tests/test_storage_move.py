import base64
import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from werkzeug.test import Client
from werkzeug.wrappers import Response

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
        folders = patch.object(host, 'folder_choice', side_effect=lambda values: self.root / values['newName'])
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

    def send(self, method, path, expected=200, payload=None, **values):
        if payload is not None:
            body = {'data': payload, 'content_type': 'application/octet-stream'}
        else:
            body = {'json': values} if values else {}
        result = self.client.open(f'/api/{path}', method=method, base_url=ORIGIN, buffered=True, **body,
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
