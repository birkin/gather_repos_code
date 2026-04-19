"""
Helpers to obfuscate sensitive text in gathered repositories.
"""

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import urlunsplit


TEXT_SUFFIX_BLOCKLIST: set[str] = {
    '.7z',
    '.a',
    '.class',
    '.db',
    '.dll',
    '.dylib',
    '.eot',
    '.gif',
    '.gz',
    '.ico',
    '.jar',
    '.jpeg',
    '.jpg',
    '.mp3',
    '.mp4',
    '.o',
    '.pdf',
    '.png',
    '.pyc',
    '.so',
    '.sqlite',
    '.tar',
    '.ttf',
    '.wav',
    '.woff',
    '.woff2',
    '.zip',
}
LOCAL_HOST_VALUES: set[str] = {'0.0.0.0', '127.0.0.1', '::1', 'localhost'}
SENSITIVE_HOST_SUFFIXES: tuple[str, ...] = (
    'brown.edu',
    'hosted.panopto.com',
)
SENSITIVE_KEY_PATTERN: re.Pattern[str] = re.compile(
    r'(?P<prefix>(?:["\'])?(?P<key>[A-Za-z0-9_-]*'
    r'(?:password|passwd|secret|token|api[_-]?key|auth(?:orization)?[_-]?code|'
    r'username|user(?:name)?|email|host|server|url|uri|dsn)'
    r'[A-Za-z0-9_-]*)(?:["\'])?\s*[:=]\s*)(?P<quote>["\'])(?P<value>.*?)(?P=quote)',
    flags=re.IGNORECASE,
)
EMAIL_PATTERN: re.Pattern[str] = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
URL_PATTERN: re.Pattern[str] = re.compile(r'https?://[^\s\'"<>)]+')
HOST_PATTERN: re.Pattern[str] = re.compile(r'\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b')


@dataclass
class SanitizationStats:
    """
    Captures repo sanitization counts.

    Called by: main.main()
    """

    files_scanned: int = 0
    files_changed: int = 0
    replacement_count: int = 0


class SensitiveTextSanitizer:
    """
    Holds per-pass placeholder caches and replacement counts.

    Called by: lib.sensitive_cleanup.sanitize_text()
    """

    def __init__(self) -> None:
        """
        Initializes placeholder caches for deterministic substitutions.

        Called by: lib.sensitive_cleanup.sanitize_text()
        """
        self._email_map: dict[str, str] = {}
        self._host_map: dict[str, str] = {}
        self._url_map: dict[str, str] = {}
        self._secret_map: dict[str, str] = {}
        self._username_map: dict[str, str] = {}
        self.replacement_count: int = 0

    def replacement_for_email(self, value: str) -> str:
        """
        Returns a deterministic placeholder email address.

        Called by: lib.sensitive_cleanup.replacement_for_email()
        """
        replacement_value: str = self._email_map.get(value, '')
        if not replacement_value:
            digest: str = short_hash(value)
            replacement_value = f'redacted-email-{digest}@example.test'
            self._email_map[value] = replacement_value
        return replacement_value

    def replacement_for_host(self, value: str) -> str:
        """
        Returns a deterministic placeholder hostname for sensitive hosts.

        Called by: lib.sensitive_cleanup.replacement_for_host()
        """
        if not is_sensitive_host(value):
            return value

        replacement_value: str = self._host_map.get(value, '')
        if not replacement_value:
            digest: str = short_hash(value)
            replacement_value = f'redacted-host-{digest}.example.test'
            self._host_map[value] = replacement_value
        return replacement_value

    def replacement_for_secret(self, value: str) -> str:
        """
        Returns a deterministic placeholder for secret-like values.

        Called by: lib.sensitive_cleanup.replacement_for_secret()
        """
        replacement_value: str = self._secret_map.get(value, '')
        if not replacement_value:
            digest: str = short_hash(value)
            replacement_value = f'redacted-secret-{digest}'
            self._secret_map[value] = replacement_value
        return replacement_value

    def replacement_for_url(self, value: str) -> str:
        """
        Returns a deterministic placeholder URL for sensitive hosts.

        Called by: lib.sensitive_cleanup.replacement_for_url()
        """
        if not looks_like_url(value):
            return value

        parsed_url = urlsplit(value)
        if not is_sensitive_host(parsed_url.hostname or ''):
            return value

        replacement_value: str = self._url_map.get(value, '')
        if not replacement_value:
            digest: str = short_hash(value)
            replacement_host: str = self.replacement_for_host(parsed_url.hostname or '')
            replacement_value = urlunsplit(
                (parsed_url.scheme, replacement_host, f'/redacted-path-{digest}', '', ''),
            )
            self._url_map[value] = replacement_value
        return replacement_value

    def replacement_for_username(self, value: str) -> str:
        """
        Returns a deterministic placeholder username.

        Called by: lib.sensitive_cleanup.replacement_for_username()
        """
        replacement_value: str = self._username_map.get(value, '')
        if not replacement_value:
            digest: str = short_hash(value)
            replacement_value = f'redacted-user-{digest}'
            self._username_map[value] = replacement_value
        return replacement_value

    def increment_replacement_count_if_changed(self, original_value: str, replacement_value: str) -> None:
        """
        Increments the replacement counter when a value changes.

        Called by: lib.sensitive_cleanup.sanitize_sensitive_assignments()
        """
        if original_value != replacement_value:
            self.replacement_count += 1


def sanitize_sensitive_assignments(text: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Sanitizes sensitive assignment values in one text blob.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_sanitize_sensitive_assignments_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    updated_text: str = text
    match: re.Match[str]
    for match in reversed(list(SENSITIVE_KEY_PATTERN.finditer(text))):
        prefix: str = match.group('prefix')
        quote: str = match.group('quote')
        key: str = match.group('key').lower()
        value: str = match.group('value')

        replacement_value: str = value
        if EMAIL_PATTERN.fullmatch(value):
            replacement_value = replacement_for_email(value, active_sanitizer)
        elif looks_like_url(value):
            replacement_value = replacement_for_url(value, active_sanitizer)
        elif looks_like_host(value):
            replacement_value = replacement_for_host(value, active_sanitizer)
        elif is_secret_key(key):
            replacement_value = replacement_for_secret(value, active_sanitizer)
        elif is_username_key(key):
            replacement_value = replacement_for_username(value, active_sanitizer)

        active_sanitizer.increment_replacement_count_if_changed(value, replacement_value)
        replaced_text: str = f'{prefix}{quote}{replacement_value}{quote}'
        updated_text = f'{updated_text[:match.start()]}{replaced_text}{updated_text[match.end():]}'
    return updated_text


def sanitize_urls(text: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Sanitizes URLs in one text blob.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_sanitize_urls_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    updated_text: str = text
    match: re.Match[str]
    for match in reversed(list(URL_PATTERN.finditer(text))):
        original_value: str = match.group(0)
        replacement_value: str = replacement_for_url(original_value, active_sanitizer)
        active_sanitizer.increment_replacement_count_if_changed(original_value, replacement_value)
        updated_text = f'{updated_text[:match.start()]}{replacement_value}{updated_text[match.end():]}'
    return updated_text


def sanitize_emails(text: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Sanitizes email addresses in one text blob.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_sanitize_emails_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    updated_text: str = text
    match: re.Match[str]
    for match in reversed(list(EMAIL_PATTERN.finditer(text))):
        original_value: str = match.group(0)
        replacement_value: str = replacement_for_email(original_value, active_sanitizer)
        active_sanitizer.increment_replacement_count_if_changed(original_value, replacement_value)
        updated_text = f'{updated_text[:match.start()]}{replacement_value}{updated_text[match.end():]}'
    return updated_text


def sanitize_hosts(text: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Sanitizes bare hostnames in one text blob.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_sanitize_hosts_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    updated_text: str = text
    match: re.Match[str]
    for match in reversed(list(HOST_PATTERN.finditer(text))):
        original_value: str = match.group(0)
        replacement_value: str = replacement_for_host(original_value, active_sanitizer)
        active_sanitizer.increment_replacement_count_if_changed(original_value, replacement_value)
        updated_text = f'{updated_text[:match.start()]}{replacement_value}{updated_text[match.end():]}'
    return updated_text


def replacement_for_email(value: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Returns the deterministic email placeholder for one value.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_replacement_for_email_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    replacement_value: str = active_sanitizer.replacement_for_email(value)
    return replacement_value


def replacement_for_secret(value: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Returns the deterministic secret placeholder for one value.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_replacement_for_secret_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    replacement_value: str = active_sanitizer.replacement_for_secret(value)
    return replacement_value


def replacement_for_host(value: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Returns the deterministic host placeholder for one value.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_replacement_for_host_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    replacement_value: str = active_sanitizer.replacement_for_host(value)
    return replacement_value


def replacement_for_url(value: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Returns the deterministic URL placeholder for one value.

    Called by: tests.test_sensitive_cleanup.SensitiveCleanupTests.test_replacement_for_url_cases()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    replacement_value: str = active_sanitizer.replacement_for_url(value)
    return replacement_value


def sanitize_text(text: str) -> tuple[str, int]:
    """
    Sanitizes one text blob and returns the updated content with a replacement count.

    Called by: lib.sensitive_cleanup.sanitize_file()
    """
    sanitizer: SensitiveTextSanitizer = SensitiveTextSanitizer()
    sanitized_text: str = text
    sanitized_text = sanitize_sensitive_assignments(sanitized_text, sanitizer)
    sanitized_text = sanitize_urls(sanitized_text, sanitizer)
    sanitized_text = sanitize_emails(sanitized_text, sanitizer)
    sanitized_text = sanitize_hosts(sanitized_text, sanitizer)
    result: tuple[str, int] = (sanitized_text, sanitizer.replacement_count)
    return result


def replacement_for_username(value: str, sanitizer: SensitiveTextSanitizer | None = None) -> str:
    """
    Returns the deterministic username placeholder for one value.

    Called by: lib.sensitive_cleanup.sanitize_sensitive_assignments()
    """
    active_sanitizer: SensitiveTextSanitizer = sanitizer or SensitiveTextSanitizer()
    replacement_value: str = active_sanitizer.replacement_for_username(value)
    return replacement_value


def sanitize_file(file_path: Path) -> int:
    """
    Sanitizes one text file in place when its contents change.

    Called by: sanitize_repo_contents()
    """
    file_bytes: bytes = file_path.read_bytes()
    if _is_probably_binary_content(file_path, file_bytes):
        return 0

    decoded_text, encoding = _decode_text_content(file_bytes)
    if decoded_text is None or encoding is None:
        return 0

    sanitized_text, replacement_count = sanitize_text(decoded_text)
    if sanitized_text != decoded_text:
        file_path.write_text(sanitized_text, encoding=encoding)
    return replacement_count


def sanitize_repo_contents(repo_dir: Path) -> SanitizationStats:
    """
    Sanitizes text files across one cloned repository tree.

    Called by: main.main()
    """
    stats: SanitizationStats = SanitizationStats()
    file_path: Path
    for file_path in sorted(repo_dir.rglob('*')):
        if not file_path.is_file() or file_path.is_symlink():
            continue

        stats.files_scanned += 1
        replacement_count: int = sanitize_file(file_path)
        if replacement_count > 0:
            stats.files_changed += 1
            stats.replacement_count += replacement_count

    return stats


def _decode_text_content(file_bytes: bytes) -> tuple[str | None, str | None]:
    """
    Decodes bytes into text using common source-file encodings.

    Called by: sanitize_file()
    """
    encoding: str
    for encoding in ('utf-8', 'latin-1'):
        try:
            decoded_text: str = file_bytes.decode(encoding)
            return decoded_text, encoding
        except UnicodeDecodeError:
            continue
    return None, None


def _is_probably_binary_content(file_path: Path, file_bytes: bytes) -> bool:
    """
    Heuristically skips binary files from in-place text rewriting.

    Called by: sanitize_file()
    """
    suffix: str = file_path.suffix.lower()
    if suffix in TEXT_SUFFIX_BLOCKLIST:
        return True
    is_binary: bool = b'\x00' in file_bytes[:1024]
    return is_binary


def is_secret_key(key: str) -> bool:
    """
    Returns whether a field name implies a secret-like value.

    Called by: sanitize_sensitive_assignments()
    """
    result: bool = any(
        marker in key
        for marker in ('password', 'passwd', 'secret', 'token', 'api_key', 'apikey', 'authorization_code', 'auth')
    )
    return result


def is_sensitive_host(hostname: str) -> bool:
    """
    Returns whether a hostname looks private to the organization.

    Called by: replacement_for_host() and replacement_for_url()
    """
    normalized_host: str = hostname.strip().strip('.').lower()
    if not normalized_host or normalized_host in LOCAL_HOST_VALUES:
        return False
    return normalized_host.endswith(SENSITIVE_HOST_SUFFIXES)


def is_username_key(key: str) -> bool:
    """
    Returns whether a field name implies a username-like value.

    Called by: sanitize_sensitive_assignments()
    """
    result: bool = 'user' in key and not is_secret_key(key)
    return result


def looks_like_host(value: str) -> bool:
    """
    Returns whether a value resembles a bare hostname.

    Called by: sanitize_sensitive_assignments()
    """
    host_match = HOST_PATTERN.fullmatch(value)
    return bool(host_match)


def looks_like_url(value: str) -> bool:
    """
    Returns whether a value resembles an HTTP or HTTPS URL.

    Called by: sanitize_sensitive_assignments() and replacement_for_url()
    """
    url_match = URL_PATTERN.fullmatch(value)
    return bool(url_match)


def short_hash(value: str) -> str:
    """
    Returns a short deterministic digest for placeholder generation.

    Called by: replacement_for_email()
    """
    digest: str = hashlib.sha256(value.encode('utf-8')).hexdigest()[:10]
    return digest
