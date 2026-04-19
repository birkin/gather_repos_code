import tempfile
import unittest
from pathlib import Path

from lib.sensitive_cleanup import (
    is_secret_key,
    is_sensitive_host,
    is_username_key,
    looks_like_host,
    looks_like_url,
    replacement_for_email,
    replacement_for_host,
    replacement_for_secret,
    replacement_for_url,
    sanitize_emails,
    sanitize_hosts,
    sanitize_repo_contents,
    sanitize_sensitive_assignments,
    sanitize_text,
    sanitize_urls,
)


class SensitiveCleanupTests(unittest.TestCase):
    def test_is_sensitive_host_cases(self) -> None:
        """
        Checks sensitive-host detection covers matching and non-matching hostnames.
        """
        cases: list[tuple[str, bool]] = [
            ('video.hosted.panopto.com', True),
            ('api.hosted.panopto.com', True),
            ('some.domain.edu', False),
            ('localhost', False),
        ]

        hostname: str
        expected: bool
        for hostname, expected in cases:
            with self.subTest(hostname):
                self.assertEqual(is_sensitive_host(hostname), expected)

    def test_is_secret_key_cases(self) -> None:
        """
        Checks secret-key detection covers matching and non-matching field names.
        """
        cases: list[tuple[str, bool]] = [
            ('password', True),
            ('api_token', True),
            ('description', False),
            ('contact_email', False),
        ]

        key: str
        expected: bool
        for key, expected in cases:
            with self.subTest(key):
                self.assertEqual(is_secret_key(key), expected)

    def test_is_username_key_cases(self) -> None:
        """
        Checks username-key detection covers matching and non-matching field names.
        """
        cases: list[tuple[str, bool]] = [
            ('username', True),
            ('user_id', True),
            ('api_user_token', False),
            ('description', False),
        ]

        key: str
        expected: bool
        for key, expected in cases:
            with self.subTest(key):
                self.assertEqual(is_username_key(key), expected)

    def test_looks_like_url_cases(self) -> None:
        """
        Checks URL detection covers matching and non-matching values.
        """
        cases: list[tuple[str, bool]] = [
            ('https://some.domain.edu/path', True),
            ('http://localhost:8000/', True),
            ('some.domain.edu', False),
            ('not a url', False),
        ]

        value: str
        expected: bool
        for value, expected in cases:
            with self.subTest(value):
                self.assertEqual(looks_like_url(value), expected)

    def test_looks_like_host_cases(self) -> None:
        """
        Checks host detection covers matching and non-matching values.
        """
        cases: list[tuple[str, bool]] = [
            ('some.domain.edu', True),
            ('video.hosted.panopto.com', True),
            ('https://some.domain.edu/path', False),
            ('localhost', False),
        ]

        value: str
        expected: bool
        for value, expected in cases:
            with self.subTest(value):
                self.assertEqual(looks_like_host(value), expected)

    def test_replacement_for_email_cases(self) -> None:
        """
        Checks email replacement returns deterministic placeholders.
        """
        cases: list[tuple[str, str]] = [
            ('foo@university.edu', 'redacted-email-e4f1c182d7@example.test'),
            ('alerts@example.org', 'redacted-email-be23bab226@example.test'),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(replacement_for_email(source), expected)

    def test_replacement_for_secret_cases(self) -> None:
        """
        Checks secret replacement returns deterministic placeholders.
        """
        cases: list[tuple[str, str]] = [
            ('some_password', 'redacted-secret-1464acd676'),
            ('secret-token-123', 'redacted-secret-11a2ff949c'),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(replacement_for_secret(source), expected)

    def test_replacement_for_host_cases(self) -> None:
        """
        Checks host replacement redacts sensitive hosts and preserves others.
        """
        cases: list[tuple[str, str]] = [
            ('video.hosted.panopto.com', 'redacted-host-632ff12eb6.example.test'),
            ('api.hosted.panopto.com', 'redacted-host-a7bc64094e.example.test'),
            ('some.domain.edu', 'some.domain.edu'),
            ('localhost', 'localhost'),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(replacement_for_host(source), expected)

    def test_replacement_for_url_cases(self) -> None:
        """
        Checks URL replacement redacts sensitive-host URLs and preserves others.
        """
        cases: list[tuple[str, str]] = [
            (
                'https://video.hosted.panopto.com/path/to/something/?token=secret',
                'https://redacted-host-632ff12eb6.example.test/redacted-path-a5a7b42abb',
            ),
            (
                'https://api.hosted.panopto.com/path/to/something?token=secret',
                'https://redacted-host-a7bc64094e.example.test/redacted-path-39bcceb61e',
            ),
            (
                'https://some.domain.edu/path/to/something/?token=secret',
                'https://some.domain.edu/path/to/something/?token=secret',
            ),
            ('http://localhost:8000/', 'http://localhost:8000/'),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(replacement_for_url(source), expected)

    def test_sanitize_sensitive_assignments_cases(self) -> None:
        """
        Checks assignment-stage sanitization changes only matching sensitive assignments.
        """
        cases: list[tuple[str, str]] = [
            (
                "CONTACT_EMAIL = 'foo@university.edu'\n",
                "CONTACT_EMAIL = 'redacted-email-e4f1c182d7@example.test'\n",
            ),
            (
                "PASSWORD = 'some_password'\n",
                "PASSWORD = 'redacted-secret-1464acd676'\n",
            ),
            (
                "DESCRIPTION = 'some_password'\n",
                "DESCRIPTION = 'some_password'\n",
            ),
            (
                "NOTE = 'secret-token-123'\n",
                "NOTE = 'secret-token-123'\n",
            ),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(sanitize_sensitive_assignments(source), expected)

    def test_sanitize_urls_cases(self) -> None:
        """
        Checks URL-stage sanitization changes only sensitive-host URLs.
        """
        cases: list[tuple[str, str]] = [
            (
                "LOGIN_URL = 'https://video.hosted.panopto.com/path/to/something/?token=secret'\n",
                "LOGIN_URL = 'https://redacted-host-632ff12eb6.example.test/redacted-path-a5a7b42abb'\n",
            ),
            (
                "SERVER_URL = 'https://api.hosted.panopto.com/path/to/something?token=secret'\n",
                "SERVER_URL = 'https://redacted-host-a7bc64094e.example.test/redacted-path-39bcceb61e'\n",
            ),
            (
                "LOGIN_URL = 'https://some.domain.edu/path/to/something/?token=secret'\n",
                "LOGIN_URL = 'https://some.domain.edu/path/to/something/?token=secret'\n",
            ),
            (
                "SERVER_ROOT = 'http://localhost:8000/'\n",
                "SERVER_ROOT = 'http://localhost:8000/'\n",
            ),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(sanitize_urls(source), expected)

    def test_sanitize_emails_cases(self) -> None:
        """
        Checks email-stage sanitization changes email addresses and preserves non-emails.
        """
        cases: list[tuple[str, str]] = [
            (
                "CONTACT_EMAIL = 'foo@university.edu'\n",
                "CONTACT_EMAIL = 'redacted-email-e4f1c182d7@example.test'\n",
            ),
            (
                "OWNER = 'alerts@example.org'\n",
                "OWNER = 'redacted-email-be23bab226@example.test'\n",
            ),
            (
                "CONTACT_EMAIL = 'not-an-email'\n",
                "CONTACT_EMAIL = 'not-an-email'\n",
            ),
            (
                "SERVER_ROOT = 'http://localhost:8000/'\n",
                "SERVER_ROOT = 'http://localhost:8000/'\n",
            ),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(sanitize_emails(source), expected)

    def test_sanitize_hosts_cases(self) -> None:
        """
        Checks host-stage sanitization changes only sensitive bare hostnames.
        """
        cases: list[tuple[str, str]] = [
            (
                "HOST = 'video.hosted.panopto.com'\n",
                "HOST = 'redacted-host-632ff12eb6.example.test'\n",
            ),
            (
                "SERVER_HOST = 'api.hosted.panopto.com'\n",
                "SERVER_HOST = 'redacted-host-a7bc64094e.example.test'\n",
            ),
            (
                "HOST = 'some.domain.edu'\n",
                "HOST = 'some.domain.edu'\n",
            ),
            (
                "SERVER_ROOT = 'http://localhost:8000/'\n",
                "SERVER_ROOT = 'http://localhost:8000/'\n",
            ),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                self.assertEqual(sanitize_hosts(source), expected)

    def test_sanitize_text_end_to_end_cases(self) -> None:
        """
        Checks full-pipeline sanitization on mixed source text.
        """
        cases: list[tuple[str, str]] = [
            (
                "CONTACT_EMAIL = 'foo@university.edu'\n",
                "CONTACT_EMAIL = 'redacted-email-cfeae6fd2d@example.test'\n",
            ),
            (
                "PASSWORD = 'some_password'\nHOST = 'some.domain.edu'\nSERVER_ROOT = 'http://localhost:8000/'\n",
                "PASSWORD = 'redacted-secret-1464acd676'\nHOST = 'some.domain.edu'\nSERVER_ROOT = 'http://localhost:8000/'\n",
            ),
        ]

        source: str
        expected: str
        for source, expected in cases:
            with self.subTest(source):
                sanitized_text, _replacement_count = sanitize_text(source)
                self.assertEqual(sanitized_text, expected)

    def test_sanitize_repo_contents_rewrites_text_and_skips_binary_files(self) -> None:
        """
        Checks repo sanitization updates text files in place and ignores binary files.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir) / 'repo_a'
            repo_dir.mkdir()
            text_file = repo_dir / 'settings.py'
            binary_file = repo_dir / 'logo.png'

            text_file.write_text("SERVER_EMAIL = 'foo@university.edu'\n", encoding='utf-8')
            binary_file.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')

            stats = sanitize_repo_contents(repo_dir)

            updated_text = text_file.read_text(encoding='utf-8')
            self.assertNotIn('foo@university.edu', updated_text)
            self.assertEqual(binary_file.read_bytes(), b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR')
            self.assertEqual(stats.files_changed, 1)


if __name__ == '__main__':
    unittest.main()
