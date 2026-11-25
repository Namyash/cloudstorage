import sys
import unittest
from unittest.mock import patch

from backend import container_host
from backend.account_and_file_api import CHUNK, OVERHEAD


class ContainerHostTest(unittest.TestCase):
    def test_caps_waitress_request_buffer_at_one_upload_chunk(self):
        with (
            patch.object(sys, 'argv', ['sparedrive', 'serve']),
            patch.object(container_host, 'mounted_data_dir'),
            patch.object(container_host, 'create_app') as create_app,
            patch.object(container_host, 'serve') as serve,
        ):
            self.assertEqual(container_host.main(), 0)

        limit = CHUNK + OVERHEAD
        serve.assert_called_once_with(create_app.return_value, host='0.0.0.0',
                                      port=container_host.CONTAINER_PORT,
                                      max_request_body_size=limit, inbuf_overflow=limit + 1)
