import copy
import io
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from deploy.smoke import safe_media_error
from deploy.entrypoint import write_secrets
from deploy import azure_deploy as deployment


def app():
    return {'properties': {'runningStatus': 'Running',
            'configuration': {'activeRevisionsMode': 'Single', 'ingress': None},
            'template': {'revisionSuffix': 'old',
                'scale': {'minReplicas': 1, 'maxReplicas': 1},
                'volumes': [{'name': 'reibotfs', 'storageType': 'AzureFile',
                             'storageName': 'reibot-payg'}],
                'containers': [{'name': 'reibot', 'image': 'old-image',
                    'resources': {'cpu': .5, 'memory': '1Gi', 'ephemeralStorage': '2Gi'},
                    'volumeMounts': [{'volumeName': 'reibotfs', 'mountPath': '/app/Rei/Guilds'}],
                    'env': [{'name': 'EXISTING', 'secretRef': 'unrelated-secret'}]}]}}}


class DeploymentTests(unittest.TestCase):
    def test_credentials_preserve_multiline_and_are_private(self):
        cookies = '# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t1999999999\tTEST\tfake\n'
        env = {'DISCORD_TOKEN': ' fake-token \n', 'YT_COOKIES': cookies}
        with tempfile.TemporaryDirectory() as folder:
            write_secrets(folder, env)
            self.assertEqual((Path(folder) / 'cookies.txt').read_text(), cookies)
            self.assertEqual((Path(folder) / 'discord_token').read_text(), 'fake-token\n')
            for file in Path(folder).iterdir():
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertFalse(env)

    def test_missing_secret_does_not_write_partial_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                write_secrets(folder, {'DISCORD_TOKEN': 'fake'})
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_image_change_preserves_storage_resources_and_other_secrets(self):
        before = app(); original = copy.deepcopy(before)
        after = deployment.template_for(before, 'new-image', 'gh-1-1',
                                        {'DISCORD_TOKEN': 'fake', 'YT_COOKIES': 'fake'})
        self.assertEqual(before, original)
        self.assertEqual(after['volumes'], before['properties']['template']['volumes'])
        container = after['containers'][0]
        self.assertEqual(container['resources'], {'cpu': .5, 'memory': '1Gi'})
        self.assertEqual(container['volumeMounts'], before['properties']['template']['containers'][0]['volumeMounts'])
        self.assertIn({'name': 'EXISTING', 'secretRef': 'unrelated-secret'}, container['env'])
        self.assertNotIn('value', repr(container['env']))

    def test_media_failure_restores_previous_image_and_storage(self):
        before = app(); calls = []
        current = copy.deepcopy(before)
        def fake_rest(method, suffix='', body=None):
            calls.append((method, suffix, copy.deepcopy(body)))
            if suffix == '/listSecrets': return {'value': [{'name': 'registry', 'value': 'fake-registry'}]}
            if suffix == '/stop': current['properties']['runningStatus'] = 'Stopped'
            if suffix == '/start': current['properties']['runningStatus'] = 'Running'
            if method == 'patch': current['properties'].update(copy.deepcopy(body['properties']))
            if method == 'get': return copy.deepcopy(current)
        env = {'DEPLOY_IMAGE': 'registry.hub.docker.com/hleitr/reibot@sha256:' + 'a' * 64,
               'DEPLOY_SUFFIX': 'gh-1-1', 'DISCORD_TOKEN': 'fake-sensitive-token',
               'YT_COOKIES': '# Netscape HTTP Cookie File\nfake-sensitive-cookie'}
        output = io.StringIO()
        with patch.dict(os.environ, env), patch.object(deployment, 'rest', side_effect=fake_rest), \
             patch.object(deployment, 'wait_for'), patch.object(deployment.time, 'sleep'), \
             patch.object(deployment, 'smoke', side_effect=RuntimeError('media unavailable')), redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, 'media unavailable'):
                deployment.main()
        patches = [body for method, suffix, body in calls if method == 'patch']
        self.assertEqual(len(patches), 2)
        rollback = patches[-1]['properties']['template']
        self.assertEqual(rollback['containers'][0]['image'], 'old-image')
        self.assertEqual(rollback['volumes'], before['properties']['template']['volumes'])
        self.assertEqual(calls[-1][:2], ('post', '/start'))
        self.assertNotIn('fake-sensitive', output.getvalue())

    def test_rejected_patch_restarts_original_without_stopping_twice(self):
        current = app(); calls = []
        def fake_rest(method, suffix='', body=None):
            calls.append((method, suffix))
            if suffix == '/listSecrets': return {'value': []}
            if suffix == '/stop': current['properties']['runningStatus'] = 'Stopped'
            if suffix == '/start': current['properties']['runningStatus'] = 'Running'
            if method == 'patch': raise RuntimeError('patch rejected')
            if method == 'get': return copy.deepcopy(current)
        env = {'DEPLOY_IMAGE': 'registry.hub.docker.com/hleitr/reibot@sha256:' + 'a' * 64,
               'DEPLOY_SUFFIX': 'gh-2-1', 'DISCORD_TOKEN': 'fake',
               'YT_COOKIES': '# Netscape HTTP Cookie File\nfake'}
        with patch.dict(os.environ, env), patch.object(deployment, 'rest', side_effect=fake_rest), \
             patch.object(deployment, 'wait_for'), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'patch rejected'):
                deployment.main()
        self.assertEqual(calls.count(('post', '/stop')), 1)
        self.assertEqual(calls[-1], ('post', '/start'))
        self.assertEqual(current['properties']['runningStatus'], 'Running')

    def test_media_error_redacts_cookies_token_and_signed_urls(self):
        message = 'ERROR: failed for fake-cookie and fake-token at https://example.test/audio?signature=private\nretry'
        result = safe_media_error(message, ['fake-cookie', 'fake-token'])
        self.assertNotIn('fake-cookie', result)
        self.assertNotIn('fake-token', result)
        self.assertNotIn('signature', result)
        self.assertNotIn('\n', result)
        self.assertIn('ERROR: failed', result)

    def test_smoke_failure_reports_stage_without_exposing_raw_output(self):
        output = b'private-token REIBOT_STORAGE_OK\nREIBOT_SMOKE_FAILED:DownloadError\nprivate-cookie'
        self.assertEqual(deployment.smoke_failure(output),
                         'REIBOT_STORAGE_OK, REIBOT_SMOKE_FAILED:DownloadError')
        self.assertEqual(deployment.smoke_failure(b'private-token'), 'no check result received')

    def test_azure_operation_lock_is_retried_without_logging_payload(self):
        results = [subprocess.CompletedProcess([], 1, '', '{"code":"ContainerAppOperationInProgress"}'),
                   subprocess.CompletedProcess([], 0, '{"ok":true}', '')]
        output = io.StringIO()
        with patch.object(deployment.subprocess, 'run', side_effect=results) as run, \
             patch.object(deployment.time, 'sleep'), redirect_stdout(output):
            self.assertEqual(deployment.rest('patch', body={'secret': 'fake-private-value'}), {'ok': True})
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('fake-private-value', output.getvalue())


if __name__ == '__main__':
    unittest.main()
