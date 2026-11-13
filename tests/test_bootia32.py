import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'scripts/build_bootia32.py'
spec = importlib.util.spec_from_file_location('build_bootia32', PATH)
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class BootImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.modules = self.root / 'modules'; self.modules.mkdir()
        for name in boot.MODULES:
            (self.modules / (name+'.mod')).touch()

    @patch.object(boot.shutil, 'which', return_value='/usr/bin/grub-mkimage')
    def test_image_contains_embedded_search_and_never_addresses_a_disk(self, _):
        seen = []
        def run(command, **kwargs):
            seen.extend(command)
            config = Path(command[command.index('-c')+1]).read_text()
            self.assertIn('search --no-floppy --file --set=root /casper/vmlinuz', config)
            self.assertIn('configfile $prefix/grub.cfg', config)
            self.assertEqual(command[command.index('-O')+1], 'i386-efi')
            self.assertFalse(any(str(v).startswith('/dev/') for v in command))
            Path(command[command.index('-o')+1]).write_bytes(b'MZ'+b'\0'*64)
            return subprocess.CompletedProcess(command, 0, stdout=b'')
        output = self.root / 'bootia32.efi'
        boot.build(output, self.modules, run)
        self.assertTrue(output.read_bytes().startswith(b'MZ'))
        self.assertNotEqual(Path(seen[seen.index('-o')+1]), output)

    def test_existing_output_is_never_overwritten(self):
        out = self.root / 'existing'; out.write_bytes(b'keep')
        with self.assertRaises(ValueError): boot.build(out, self.modules)
        self.assertEqual(out.read_bytes(), b'keep')

    def test_output_symlink_is_refused(self):
        out = self.root / 'link'; out.symlink_to(self.root/'absent')
        with self.assertRaises(ValueError): boot.build(out, self.modules)

    @patch.object(boot.shutil, 'which', return_value='/usr/bin/grub-mkimage')
    def test_missing_modules_fail_before_execution(self, _):
        (self.modules/'linux.mod').unlink()
        with self.assertRaises(RuntimeError): boot.build(self.root/'new', self.modules)

    @patch.object(boot.shutil, 'which', return_value='/usr/bin/grub-mkimage')
    def test_non_efi_output_is_not_written(self, _):
        def run(command, **kwargs):
            Path(command[command.index('-o')+1]).write_bytes(b'bad data')
            return subprocess.CompletedProcess(command, 0, stdout=b'')
        out = self.root/'new'
        with self.assertRaises(RuntimeError): boot.build(out, self.modules, run)
        self.assertFalse(out.exists())


if __name__ == '__main__': unittest.main()
