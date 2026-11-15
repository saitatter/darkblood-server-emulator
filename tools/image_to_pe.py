"""Wrap a loaded PE image for static analysis; output is NOT a runnable EXE.

Memory addresses map 1:1 to image offsets plus ImageBase. Loader directories
referencing erased packer metadata are deliberately removed. Requires pefile.
"""
import argparse
from pathlib import Path
import pefile


def convert(source, destination, entry):
    data = bytearray(Path(source).read_bytes())
    pe = pefile.PE(data=data)
    pe.FILE_HEADER.NumberOfSections = 1
    pe.OPTIONAL_HEADER.AddressOfEntryPoint = entry - pe.OPTIONAL_HEADER.ImageBase
    pe.OPTIONAL_HEADER.SizeOfImage = len(data)
    for directory in pe.OPTIONAL_HEADER.DATA_DIRECTORY:
        directory.VirtualAddress = directory.Size = 0
    section = pe.sections[0]
    section.Name = b'.image\0\0'
    section.VirtualAddress = section.PointerToRawData = 0x1000
    section.Misc_VirtualSize = section.SizeOfRawData = len(data) - 0x1000
    section.Characteristics = 0xE0000060
    pe.sections = [section]
    Path(destination).write_bytes(pe.write())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('--entry', type=lambda n: int(n, 0), required=True,
                        help='Analyzed virtual address used to seed disassembly')
    args = parser.parse_args()
    convert(args.source, args.destination, args.entry)
