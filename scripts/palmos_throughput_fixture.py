#!/usr/bin/env python3
"""Create the deterministic 64 KiB input for NioLibTest's File speed page."""
import argparse
import hashlib
from pathlib import Path


def fixture():
    return b''.join(bytes(value ^ block for value in range(256))
                    for block in range(256))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='output file, normally nio-throughput.bin')
    args = parser.parse_args()
    data = fixture()
    args.output.write_bytes(data)
    print(f'{len(data)} bytes; sum {sum(data):08X}; SHA256 {hashlib.sha256(data).hexdigest()}')
