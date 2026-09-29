"""Create an encrypted root and a DNS-constrained issuing CA on Linux.

Run only for initial bootstrap in a private directory outside the repository.
Never overwrite a CA: replacement requires a separate trust/rotation plan.
"""
import argparse
import os
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOST = 'company-website.team5.arpa'


def openssl(*args):
    return subprocess.run(['openssl', *map(str, args)], check=True, capture_output=True).stdout


def create(directory, password_file):
    if os.name != 'posix':
        raise ValueError('Use Linux/WSL with a native private filesystem, not a Windows mount.')
    directory = Path(directory).resolve()
    password_file = Path(password_file).absolute()
    if directory.is_relative_to(ROOT) or directory.is_relative_to('/mnt'):
        raise ValueError('Keep CA keys outside the repository and Windows mounts.')
    info = password_file.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid():
        raise ValueError('The passphrase file must be an owned regular file with mode 0600 or stricter.')
    if len(password_file.read_bytes().strip()) < 24:
        raise ValueError('Use a random passphrase of at least 24 characters.')
    previous_umask = os.umask(0o077)
    try:
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        root_key = directory / 'root.key.pem'
        root_cert = directory / 'root.crt'
        key = directory / 'issuer.key.pem'
        cert = directory / 'issuer.crt'
        openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256',
                '-aes-256-cbc', '-pass', f'file:{password_file}', '-out', root_key)
        openssl('req', '-new', '-x509', '-sha256', '-key', root_key,
                '-passin', f'file:{password_file}', '-days', '1825',
                '-subj', '/CN=Team 5 Company Website Root CA', '-out', root_cert,
                '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:1',
                '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
                '-addext', 'subjectKeyIdentifier=hash')
        openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', key)
        request = directory / 'issuer.csr'
        openssl('req', '-new', '-key', key, '-subj', '/CN=Team 5 Company Website Issuing CA', '-out', request)
        extensions = directory / 'issuer.ext'
        extensions.write_text('basicConstraints=critical,CA:TRUE,pathlen:0\n'
                              'keyUsage=critical,keyCertSign,cRLSign\n'
                              'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n'
                              f'nameConstraints=critical,permitted;DNS:{HOST}\n')
        openssl('x509', '-req', '-in', request, '-CA', root_cert, '-CAkey', root_key,
                '-passin', f'file:{password_file}', '-set_serial', '0x' + os.urandom(16).hex(),
                '-days', '730', '-sha256', '-extfile', extensions, '-out', cert)
        openssl('verify', '-CAfile', root_cert, cert)
        (directory / 'issuer-chain.crt').write_bytes(cert.read_bytes() + root_cert.read_bytes())
        print(openssl('x509', '-in', root_cert, '-noout', '-fingerprint', '-sha256', '-enddate').decode().strip())
        print('Back up and verify CA recovery using the operator guide. Only issuer.key.pem and issuer-chain.crt go to Kubernetes.')
    finally:
        os.umask(previous_umask)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--password-file', type=Path, required=True)
    args = parser.parse_args()
    create(args.directory, args.password_file)
