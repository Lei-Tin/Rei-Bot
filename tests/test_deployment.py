import stat
import tempfile
import unittest
from pathlib import Path

from deploy.smoke import safe_media_error, redact_media_text
from deploy.entrypoint import write_secrets



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
