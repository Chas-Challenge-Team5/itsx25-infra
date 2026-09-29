#!/usr/bin/python3
"""Make the EFI mount optional at boot; never mount, unmount or repair a disk."""

import argparse
import difflib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def configure_text(text):
    """Change exactly one active vfat EFI entry and preserve other lines."""
    lines = text.splitlines(keepends=True)
    entries = []
    for index, line in enumerate(lines):
        fields = line.split('#', 1)[0].split()
        if len(fields) >= 2 and fields[1] == '/boot/efi':
            entries.append((index, fields))
    if len(entries) != 1:
        raise ValueError('Expected exactly one active /boot/efi entry; fstab left unchanged.')
    index, fields = entries[0]
    if len(fields) != 6 or fields[2] != 'vfat' or not all(x.isdigit() for x in fields[4:]):
        raise ValueError('Expected a six-field vfat EFI entry; fstab left unchanged.')
    # Remove conflicting/duplicate settings, retaining all unrelated options.
    options = [x for x in fields[3].split(',')
               if x not in ('fail', 'nofail') and not x.startswith('x-systemd.device-timeout=')]
    if any(x in options for x in ('noauto', 'x-systemd.automount')):
        raise ValueError('Unexpected EFI automount/noauto configuration; fstab left unchanged.')
    options.extend(('nofail', 'x-systemd.device-timeout=5s'))
    updated = fields[:3] + [','.join(options), '0', '0']
    if updated != fields:
        # Keep whitespace, inline comments and the original newline unchanged.
        line = lines[index]
        spans = list(re.finditer(r'\S+', line.split('#', 1)[0]))
        for position in (5, 4, 3):
            span = spans[position]
            line = line[:span.start()] + updated[position] + line[span.end():]
        lines[index] = line
    return ''.join(lines)


def configure_file(path, check=False):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular fstab file, not a symlink.')
    original = path.read_bytes()
    proposed = configure_text(original.decode('utf-8')).encode('utf-8')
    if check:
        print(''.join(difflib.unified_diff(
            original.decode().splitlines(keepends=True),
            proposed.decode().splitlines(keepends=True),
            fromfile=str(path), tofile=str(path) + ' (proposed)')), end='')
        return
    if proposed != original:
        info = path.stat()
        fd, backup_name = tempfile.mkstemp(prefix=path.name + '.before-efi-', dir=path.parent)
        os.close(fd)
        backup = Path(backup_name)
        shutil.copy2(path, backup)
        fd, staged_name = tempfile.mkstemp(prefix=path.name + '.efi-', dir=path.parent)
        staged = Path(staged_name)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(proposed)
                output.flush()
                os.fsync(output.fileno())
            shutil.copystat(path, staged)
            if hasattr(os, 'chown'):
                os.chown(staged, info.st_uid, info.st_gid)
                os.chown(backup, info.st_uid, info.st_gid)
            if path.is_symlink() or path.read_bytes() != original:
                raise ValueError('fstab changed during preparation; refusing to overwrite it.')
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)
        print(f'Updated EFI boot policy. Backup: {backup}')
    else:
        print('EFI boot policy is already configured.')
    # Also retry on unchanged files if an earlier reload failed. This does not
    # mount/unmount EFI or restart any service. Errors must remain visible.
    subprocess.run(['systemctl', 'daemon-reload'], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fstab', type=Path, default=Path('/etc/fstab'))
    parser.add_argument('--check', action='store_true', help='Show proposed changes without writing or reloading.')
    args = parser.parse_args()
    try:
        configure_file(args.fstab, args.check)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'EFI configuration failed: {error}\n')


if __name__ == '__main__':
    main()
