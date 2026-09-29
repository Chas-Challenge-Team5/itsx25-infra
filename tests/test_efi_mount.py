"""Exercise EFI fstab changes using temporary files; never touch host mounts."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('efi_mount', ROOT / 'scripts/configure-efi-mount.py')
efi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(efi)

PREFIX = '# Keep root and swap unchanged\nUUID=root / ext4 defaults 0 1\n/swapfile none swap sw 0 0\n'
ENTRY = 'PARTUUID=4234dc70-5cb2-4fc6-910b-78f850f56155 /boot/efi vfat defaults,umask=077 0 2\n'
EXPECTED = ENTRY.replace('defaults,umask=077 0 2', 'defaults,umask=077,nofail,x-systemd.device-timeout=5s 0 0')


class EfiMountTests(unittest.TestCase):
    def test_changes_only_efi_entry_and_is_idempotent(self):
        result = efi.configure_text(PREFIX + ENTRY)
        self.assertEqual(result, PREFIX + EXPECTED)
        self.assertEqual(efi.configure_text(result), result)

    def test_existing_nofail_does_not_skip_passno_or_timeout(self):
        for options in ('defaults,umask=077,nofail',
                        'defaults,umask=077,nofail,nofail,x-systemd.device-timeout=90s',
                        'defaults,umask=077,fail'):
            with self.subTest(options=options):
                self.assertEqual(efi.configure_text(ENTRY.replace('defaults,umask=077', options)), EXPECTED)

    def test_preserves_comments_spacing_and_other_options(self):
        entry = ' UUID=efi\t/boot/efi  vfat  rw,umask=0077 1 2   # EFI partition\n'
        expected = entry.replace('rw,umask=0077 1 2', 'rw,umask=0077,nofail,x-systemd.device-timeout=5s 0 0')
        commented = '# ' + ENTRY
        self.assertEqual(efi.configure_text(PREFIX + commented + entry), PREFIX + commented + expected)

    def test_unexpected_configurations_are_rejected(self):
        for text in (PREFIX, ENTRY + ENTRY, ENTRY.replace('vfat', 'ext4'),
                     ENTRY.replace(' 0 2', ''), ENTRY.replace(' 0 2', ' 0 bad'),
                     ENTRY.replace('defaults', 'noauto'), ENTRY.replace('defaults', 'x-systemd.automount')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                efi.configure_text(text)

    def test_update_backup_mode_and_second_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(efi.subprocess, 'run') as run:
            path = Path(directory) / 'fstab'
            path.write_text(PREFIX + ENTRY)
            path.chmod(0o640)
            mode = path.stat().st_mode
            with contextlib.redirect_stdout(io.StringIO()):
                efi.configure_file(path)
                efi.configure_file(path)
            self.assertEqual(path.read_text(), PREFIX + EXPECTED)
            self.assertEqual(path.stat().st_mode, mode)
            backups = list(path.parent.glob('fstab.before-efi-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), PREFIX + ENTRY)
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), sorted([path.name, backups[0].name]))
            self.assertEqual(run.call_count, 2)
            run.assert_called_with(['systemctl', 'daemon-reload'], check=True)

    def test_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(efi.subprocess, 'run') as run:
            path = Path(directory) / 'fstab'
            path.write_text(ENTRY)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                efi.configure_file(path, check=True)
            self.assertIn('nofail', output.getvalue())
            self.assertEqual(path.read_text(), ENTRY)
            self.assertEqual(list(path.parent.iterdir()), [path])
            run.assert_not_called()

    def test_invalid_input_does_not_write_or_reload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(efi.subprocess, 'run') as run:
            path = Path(directory) / 'fstab'
            path.write_text(ENTRY + ENTRY)
            with self.assertRaises(ValueError):
                efi.configure_file(path)
            self.assertEqual(path.read_text(), ENTRY + ENTRY)
            self.assertEqual(list(path.parent.iterdir()), [path])
            run.assert_not_called()

    def test_replace_failure_keeps_original_and_backup(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(efi.subprocess, 'run') as run:
            path = Path(directory) / 'fstab'
            path.write_text(ENTRY)
            with patch.object(efi.os, 'replace', side_effect=OSError('write failed')), self.assertRaises(OSError):
                efi.configure_file(path)
            self.assertEqual(path.read_text(), ENTRY)
            self.assertEqual(len(list(path.parent.glob('fstab.before-efi-*'))), 1)
            self.assertEqual(len(list(path.parent.iterdir())), 2)
            run.assert_not_called()

    def test_reload_error_is_reported_and_retried(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / 'fstab'
            path.write_text(ENTRY)
            with patch.object(efi.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'systemctl')):
                with self.assertRaises(subprocess.CalledProcessError):
                    efi.configure_file(path)
            self.assertEqual(path.read_text(), EXPECTED)
            with patch.object(efi.subprocess, 'run') as run:
                efi.configure_file(path)
                run.assert_called_once_with(['systemctl', 'daemon-reload'], check=True)


class SystemdGeneratorTests(unittest.TestCase):
    def test_missing_efi_device_is_optional_and_has_no_fsck_dependency(self):
        generator = Path('/usr/lib/systemd/system-generators/systemd-fstab-generator')
        if os.name != 'posix' or not generator.exists():
            if os.environ.get('CI'):
                self.fail('The systemd fstab generator is required in CI')
            self.skipTest('Requires the Linux systemd fstab generator')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fstab = root / 'fstab'
            # A deliberately nonexistent device exercises the dependency graph,
            # without mounting a filesystem or starting any generated unit.
            fstab.write_text(efi.configure_text(ENTRY))
            directories = [root / name for name in ('normal', 'early', 'late')]
            for output in directories:
                output.mkdir()
            subprocess.run([str(generator), *map(str, directories)], check=True,
                           capture_output=True, text=True,
                           env=os.environ | {'SYSTEMD_FSTAB': str(fstab), 'SYSTEMD_IN_INITRD': '0',
                                             'SYSTEMD_PROC_CMDLINE': ''})
            normal = directories[0]
            mount = (normal / 'boot-efi.mount').read_text()
            self.assertNotIn('systemd-fsck', mount)
            self.assertNotIn('Before=local-fs.target', mount)
            self.assertTrue((normal / 'local-fs.target.wants/boot-efi.mount').is_symlink())
            self.assertFalse((normal / 'local-fs.target.requires/boot-efi.mount').is_symlink())
            dropins = list(normal.glob('*.device.d/*.conf'))
            self.assertTrue(any('JobRunningTimeoutSec=5s' in p.read_text() for p in dropins))


if __name__ == '__main__':
    unittest.main()
