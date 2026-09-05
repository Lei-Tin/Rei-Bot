import copy
import stat
import tempfile
import unittest
from pathlib import Path

from deploy.smoke import safe_media_error, redact_media_text
from deploy.entrypoint import write_secrets
from deploy.prepare import configurations


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

    def test_deployment_preserves_mounts_resources_and_rollback_credentials(self):
        before = app(); original = copy.deepcopy(before)
        values = {'DISCORD_TOKEN': 'fake-token', 'YT_COOKIES': '# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tSID\tfake-cookie\n'}
        deploy, rollback = configurations(before, [{'name': 'registry', 'value': 'fake-registry'}],
            'registry.hub.docker.com/hleitr/reibot@sha256:' + 'a' * 64, 'gh-1-1', values)
        self.assertEqual(before, original)
        after = deploy['properties']['template']
        old = rollback['properties']['template']
        self.assertEqual(after['volumes'], before['properties']['template']['volumes'])
        self.assertEqual(old['volumes'], after['volumes'])
        self.assertEqual(old['containers'][0]['image'], 'old-image')
        self.assertEqual(old['containers'][0]['env'], before['properties']['template']['containers'][0]['env'])
        self.assertNotIn('fake-token', repr(rollback))
        self.assertNotIn('fake-cookie', repr(rollback))
        container = after['containers'][0]
        self.assertEqual(container['resources'], {'cpu': .5, 'memory': '1Gi'})
        self.assertEqual(container['volumeMounts'], before['properties']['template']['containers'][0]['volumeMounts'])
        self.assertIn({'name': 'EXISTING', 'secretRef': 'unrelated-secret'}, container['env'])
        self.assertNotIn('value', repr(container['env']))
        secrets = {v['name']: v['value'] for v in deploy['properties']['configuration']['secrets']}
        self.assertEqual(secrets['registry'], 'fake-registry')
        self.assertEqual(secrets['rb-gh-1-1-youtube'], values['YT_COOKIES'])

    def test_configuration_rejects_removed_storage_and_multiple_workers(self):
        for change in ('storage', 'replicas'):
            before = app()
            if change == 'storage': before['properties']['template']['volumes'][0]['storageName'] = 'reibot'
            else: before['properties']['template']['scale']['maxReplicas'] = 2
            with self.subTest(change=change), self.assertRaises(ValueError):
                configurations(before, [], 'registry.hub.docker.com/hleitr/reibot@sha256:' + 'a' * 64,
                    'gh-1-1', {'DISCORD_TOKEN': 'fake', 'YT_COOKIES': '# Netscape HTTP Cookie File'})

    def test_verbose_log_redaction_preserves_error_context(self):
        result = redact_media_text('debug\nError: cookie=private-cookie\nTraceback\nhttps://example.test/signed?token=secret',
                                   ['private-cookie'])
        self.assertIn('debug\nError:', result)
        self.assertIn('\nTraceback\n', result)
        self.assertNotIn('private-cookie', result)
        self.assertNotIn('token=secret', result)

    def test_media_error_redacts_cookies_token_and_signed_urls(self):
        message = 'ERROR: failed for fake-cookie and fake-token at https://example.test/audio?signature=private\nretry'
        result = safe_media_error(message, ['fake-cookie', 'fake-token'])
        self.assertNotIn('fake-cookie', result)
        self.assertNotIn('fake-token', result)
        self.assertNotIn('signature', result)
        self.assertNotIn('\n', result)
        self.assertIn('ERROR: failed', result)



if __name__ == '__main__':
    unittest.main()
