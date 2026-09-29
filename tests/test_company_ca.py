import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('company_ca', Path(__file__).resolve().parents[1] / 'scripts/create-company-ca.py')
CA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CA)


@unittest.skipUnless(os.name == 'posix', 'CA bootstrap requires Linux permissions')
class CompanyCATests(unittest.TestCase):
    def test_encrypted_root_constrained_chain_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            password = base / 'password'
            password.write_text(os.urandom(32).hex())
            password.chmod(0o600)
            directory = base / 'ca'
            CA.create(directory, password)
            self.assertIn('ENCRYPTED PRIVATE KEY', (directory / 'root.key.pem').read_text())
            self.assertEqual((directory / 'issuer.key.pem').stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                CA.create(directory, password)
            for hostname, valid in [(CA.HOST, True), ('unrelated.example.com', False)]:
                CA.openssl('req', '-new', '-key', directory / 'issuer.key.pem', '-subj', f'/CN={hostname}', '-out', base / 'leaf.csr')
                (base / 'leaf.ext').write_text(f'basicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:{hostname}\nextendedKeyUsage=serverAuth\n')
                CA.openssl('x509', '-req', '-in', base / 'leaf.csr', '-CA', directory / 'issuer.crt',
                           '-CAkey', directory / 'issuer.key.pem', '-set_serial', '42', '-days', '90',
                           '-extfile', base / 'leaf.ext', '-out', base / 'leaf.crt')
                result = subprocess.run(['openssl', 'verify', '-purpose', 'sslserver', '-verify_hostname', hostname,
                                         '-CAfile', str(directory / 'root.crt'), '-untrusted', str(directory / 'issuer.crt'),
                                         str(base / 'leaf.crt')], capture_output=True)
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_public_passphrase_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            password = Path(tmp) / 'password'
            password.write_text('a' * 32)
            password.chmod(0o644)
            with self.assertRaises(ValueError):
                CA.create(Path(tmp) / 'ca', password)
