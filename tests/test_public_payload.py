"""Keep private machine data and generated binaries out of the shared recipe."""
import ipaddress
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist'}
PATTERNS = [
    re.compile(r'/home/[A-Za-z0-9_.-]+(?:/|(?=\s|["\']))'),
    re.compile(r'\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b'),
    re.compile(r'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----'),
    re.compile(r'\b(?:ghp|gho)_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{25,}\b'),
]
IPV4 = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
PRIVATE_NETWORKS = (
    ipaddress.IPv4Network((10 << 24, 8)),
    ipaddress.IPv4Network(((172 << 24) | (16 << 16), 12)),
    ipaddress.IPv4Network(((192 << 24) | (168 << 16), 16)),
)
PUBLIC_HOSTS = {'github.com', 'raw.githubusercontent.com', 'archive.ubuntu.com',
                'docs.ansible.com', 'packages.ubuntu.com', 'www.gnu.org',
                'thesofproject.github.io', 'lubuntu.me', 'cdimage.ubuntu.com',
                'releases.ubuntu.com', 'kernel.googlesource.com',
                'docs.kernel.org', 'www.kernel.org', 'www.normalesup.org',
                'spdx.org', 'fsf.org', 'download.lenovo.com', 'btrfs.readthedocs.io'}
BAD_SUFFIXES = {'.ko', '.wav', '.sqlite', '.db', '.efi', '.key'}


def private_text(text):
    if any(pattern.search(text) for pattern in PATTERNS):
        return True
    for candidate in IPV4.findall(text):
        try:
            address = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            continue
        if any(address in network for network in PRIVATE_NETWORKS):
            return True
    for url in re.findall(r'''https?://[^\s<>"')]+''', text):
        parsed = urlsplit(url)
        if parsed.username is not None or parsed.password is not None:
            return True
        host = parsed.hostname
        if host and host not in PUBLIC_HOSTS and not host.endswith('.invalid'):
            return True
    return False


def violations(root, paths=None):
    issues = []
    for p in (paths if paths is not None else root.rglob('*')):
        rel = p.relative_to(root)
        if (paths is None and any(part in SKIP for part in rel.parts)) or not p.is_file():
            continue
        if p.suffix in BAD_SUFFIXES:
            issues.append(str(rel)+': private or generated binary artifact')
            continue
        if p.stat().st_size > 2*1024*1024:
            issues.append(str(rel)+': unexpected large file')
            continue
        try:
            text = p.read_text()
        except UnicodeError:
            issues.append(str(rel)+': unexpected binary file')
            continue
        if private_text(text):
            issues.append(str(rel)+': private content pattern')
    return issues


class PublicPayloadTests(unittest.TestCase):
    def test_repository_has_no_private_machine_payload(self):
        paths = None
        if (ROOT/'.git').exists():
            tracked = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
            if any(tracked):
                paths = [ROOT/p for p in tracked if p]
        self.assertEqual(violations(ROOT, paths), [])

    def test_generic_patterns_detect_only_synthetic_sensitive_values(self):
        values = [str(Path('/home')/'synthetic-user'/'config'),
                  ':'.join(f'{n:02X}' for n in range(6)),
                  str(PRIVATE_NETWORKS[0].network_address+12345),
                  str(PRIVATE_NETWORKS[1].network_address+456),
                  str(PRIVATE_NETWORKS[2].network_address+789),
                  'gho_'+'A'*32,
                  'https://'+'synthetic:dummy@'+'github.com/project',
                  'https://'+'service.'+'private-domain.test'+'/settings']
        for value in values:
            with self.subTest(value_type=values.index(value)):
                self.assertTrue(private_text(value))
        self.assertFalse(private_text('https://example.invalid/dashboard'))
        self.assertFalse(private_text('https://github.com/example/project'))

    def test_scanner_rejects_generated_binary_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'module.ko').write_bytes(b'not-for-publication')
            self.assertEqual(len(violations(p)), 1)

    def test_local_configuration_is_ignored_by_git(self):
        rules = (ROOT/'.gitignore').read_text().splitlines()
        self.assertIn('/inventory.local.ini', rules)
        self.assertIn('/vars.local.yml', rules)
        self.assertIn('*.ko', rules)


if __name__ == '__main__': unittest.main()
