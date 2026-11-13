#!/usr/bin/env python3
"""Build a new IA32 GRUB EFI file; never write a USB stick or the installed ESP."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

# The ISO contents must be extracted onto a FAT32 USB volume beforehand.
EMBEDDED_CONFIG = """search --no-floppy --file --set=root /casper/vmlinuz
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
"""
MODULES = ("normal", "configfile", "search", "search_fs_file", "fat", "iso9660",
           "part_gpt", "part_msdos", "linux", "gzio", "all_video", "efi_gop",
           "ext2", "btrfs")


def build(output, module_dir=Path('/usr/lib/grub/i386-efi'), runner=subprocess.run):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Refusing to replace an existing output')
    if not output.parent.is_dir():
        raise ValueError('Output parent must already exist')
    if str(output.resolve()).startswith(('/boot/', '/dev/', '/sys/', '/proc/')):
        raise ValueError('Choose an ordinary file, outside boot and device paths')
    tool = shutil.which('grub-mkimage')
    if not tool:
        raise RuntimeError('Install grub-common and grub-efi-ia32-bin first')
    missing = [name for name in MODULES if not (module_dir / (name+'.mod')).is_file()]
    if missing:
        raise RuntimeError('Missing IA32 GRUB modules: '+', '.join(missing))
    # Exclusive creation prevents following an existing symlink. GRUB needs a regular file.
    with tempfile.TemporaryDirectory(prefix='miix-bootia32-') as td:
        config = Path(td) / 'embedded.cfg'
        config.write_text(EMBEDDED_CONFIG)
        image = Path(td) / 'bootia32.efi'
        runner([tool, '-O', 'i386-efi', '-d', str(module_dir), '-p', '/boot/grub',
                '-c', str(config), '-o', str(image), *MODULES], check=True,
               capture_output=True, timeout=60)
        payload = image.read_bytes()
        if not payload.startswith(b'MZ'):
            raise RuntimeError('grub-mkimage did not produce an EFI executable')
        with output.open('xb') as stream:
            stream.write(payload)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='New local output file, normally bootia32.efi')
    parser.add_argument('--module-dir', type=Path, default=Path('/usr/lib/grub/i386-efi'))
    args = parser.parse_args()
    try:
        result = build(args.output, args.module_dir)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error)+'\n')
    print(result)


if __name__ == '__main__':
    main()
