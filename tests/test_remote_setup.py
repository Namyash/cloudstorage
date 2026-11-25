import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend import remote_setup


HOST = 'sparedrive.example.ts.net'
LOCAL_URL = 'http://127.0.0.1:18766'
PUBLIC_URL = 'https://' + HOST


class RemoteSetupTest(unittest.TestCase):
    def test_reuses_tailscale_without_invoking_winget(self):
        with (
            patch.object(remote_setup, 'tailscale_path', return_value='tailscale.exe'),
            patch.object(remote_setup, 'command') as command,
        ):
            self.assertEqual(remote_setup.ensure_tailscale(), 'tailscale.exe')
        command.assert_not_called()

    def test_installs_missing_tailscale_with_winget_and_checks_the_executable(self):
        with (
            patch.object(sys, 'platform', 'win32'),
            patch.object(remote_setup, 'tailscale_path', side_effect=[None, 'tailscale.exe']),
            patch.object(remote_setup.shutil, 'which', return_value='winget.exe'),
            patch.object(remote_setup, 'command') as command,
            patch('builtins.print'),
        ):
            self.assertEqual(remote_setup.ensure_tailscale(), 'tailscale.exe')
        command.assert_called_once_with(
            'winget.exe', 'install', '--id', 'Tailscale.Tailscale', '--exact',
            '--source', 'winget', '--no-upgrade',
        )

    def test_tailscale_sign_in_can_continue_in_the_same_wizard(self):
        signed_in = {'BackendState': 'Running', 'Self': {'DNSName': HOST + '.'}}
        with (
            patch.object(remote_setup, 'command', side_effect=[
                json.dumps({'BackendState': 'NeedsLogin'}), json.dumps(signed_in),
            ]),
            patch('builtins.input', return_value='') as confirm,
            patch('builtins.print'),
        ):
            self.assertEqual(remote_setup.funnel_hostname('tailscale.exe'), HOST)
        confirm.assert_called_once()

    def test_funnel_reuses_matching_route_and_preserves_another_service(self):
        address = HOST + ':443'
        status = {
            'TCP': {'443': {'HTTPS': True}},
            'Web': {address: {'Handlers': {'/': {'Proxy': LOCAL_URL}}}},
            'AllowFunnel': {address: True},
        }
        with patch.object(remote_setup, 'command', return_value=json.dumps(status)):
            self.assertFalse(remote_setup.funnel_needs_setup('tailscale', HOST, LOCAL_URL))
            with self.assertRaisesRegex(ValueError, 'already has a route'):
                remote_setup.funnel_needs_setup('tailscale', HOST, 'http://127.0.0.1:8765')

    def test_wizard_checks_local_app_and_public_origin_before_enabling_funnel(self):
        with TemporaryDirectory() as directory:
            config = Path(directory) / 'test-host.json'
            settings = {'data': 'X:/FamilyData', 'port': 18766, 'storageId': 'test'}
            config.write_text(json.dumps(settings), encoding='utf-8')
            calls = []
            with (
                patch.object(sys, 'argv', ['sparedrive-remote', '--config', str(config)]),
                patch.object(remote_setup, 'app_ready', side_effect=lambda *args: calls.append(args)),
                patch.object(remote_setup, 'tailscale_path', return_value='tailscale'),
                patch.object(remote_setup, 'funnel_hostname', return_value=HOST),
                patch.object(remote_setup, 'funnel_needs_setup', return_value=True),
                patch.object(remote_setup, 'command', side_effect=lambda *args: calls.append(args)),
                patch.object(remote_setup, 'wait_for_app', side_effect=lambda *args: calls.append(args)),
                patch.object(remote_setup, 'publish_launch_page', return_value='https://family.vercel.app') as publish,
                patch('builtins.input', side_effect=['y', '', 'y']),
                patch('builtins.print'),
            ):
                self.assertEqual(remote_setup.main(), 0)

            self.assertEqual(json.loads(config.read_text(encoding='utf-8')), dict(settings, httpsUrl=PUBLIC_URL))
            self.assertEqual(calls, [
                (LOCAL_URL,),
                (LOCAL_URL, HOST),
                ('tailscale', 'funnel', '--bg', '--https=443', LOCAL_URL),
                (PUBLIC_URL,),
            ])
            publish.assert_called_once_with(PUBLIC_URL)

    def test_launch_domain_accepts_short_names_and_full_domains(self):
        with patch('builtins.input', side_effect=['bad;host', 'Smith-Family', 'https://drive.example.com/', '']):
            with patch('builtins.print'):
                self.assertEqual(remote_setup.read_launch_domain(), 'smith-family.vercel.app')
            self.assertEqual(remote_setup.read_launch_domain(), 'drive.example.com')
            self.assertIsNone(remote_setup.read_launch_domain())

    def test_vercel_prefers_requested_domain_and_falls_back_while_dns_is_pending(self):
        requested = 'drive.example.com'
        fallback = 'smith-family.vercel.app'
        calls = []

        def run_vercel(executable, action, *args, cwd=None, **kwargs):
            calls.append((action, *args))
            if action == 'link':
                metadata = cwd / '.vercel'
                metadata.mkdir()
                (metadata / 'project.json').write_text(
                    json.dumps({'projectId': 'prj_example', 'orgId': 'team_example'}), encoding='utf-8',
                )
            if action == 'deploy':
                return 'https://smith-family-123.vercel.app'
            if action == 'api':
                return json.dumps({'alias': [fallback]})

        for ready in (True, False):
            with self.subTest(custom_domain_ready=ready):
                calls.clear()
                with (
                    patch.object(remote_setup, 'vercel_cli', return_value=['vercel']),
                    patch.object(remote_setup, 'command', side_effect=run_vercel),
                    patch.object(remote_setup, 'launch_page_is_live', side_effect=lambda host, _: ready or host == fallback),
                    patch('builtins.input', side_effect=['', requested]),
                    patch('builtins.print'),
                ):
                    expected = requested if ready else fallback
                    self.assertEqual(remote_setup.publish_launch_page(PUBLIC_URL), f'https://{expected}')
                self.assertIn(('api', '/v10/projects/prj_example/domains?teamId=team_example',
                               '-X', 'POST', '-f', f'name={requested}'), calls)

    def test_windows_device_name_is_used_only_as_the_vercel_project_name(self):
        requested = 'con.vercel.app'

        def run_vercel(executable, action, *args, cwd=None, **kwargs):
            if action == 'link':
                self.assertEqual(cwd.name, 'sparedrive-family')
                metadata = cwd / '.vercel'
                metadata.mkdir()
                (metadata / 'project.json').write_text('{}', encoding='utf-8')
            elif action == 'deploy':
                return 'https://con-123.vercel.app'
            elif action == 'api':
                return json.dumps({'alias': [requested]})

        with (
            patch.object(remote_setup, 'vercel_cli', return_value=['vercel']),
            patch.object(remote_setup, 'command', side_effect=run_vercel),
            patch.object(remote_setup, 'launch_page_is_live', return_value=True),
            patch('builtins.input', side_effect=['', requested]),
            patch('builtins.print'),
        ):
            self.assertEqual(remote_setup.publish_launch_page(PUBLIC_URL), f'https://{requested}')

    def test_vercel_launch_page_contains_only_static_link(self):
        with TemporaryDirectory() as directory:
            staging = Path(directory)
            remote_setup.write_launch_page(staging, PUBLIC_URL)
            self.assertEqual(sorted(path.relative_to(staging).as_posix() for path in staging.rglob('*')),
                             ['public', 'public/index.html', 'vercel.json'])
            self.assertIn(f'href="{PUBLIC_URL}"', (staging / 'public' / 'index.html').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((staging / 'vercel.json').read_text(encoding='utf-8')),
                             {'framework': None, 'outputDirectory': 'public'})
