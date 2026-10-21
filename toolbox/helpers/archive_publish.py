#!/usr/bin/env python3
"""Publish an adjacent archive atomically, without a hidden cross-disk copy."""
import os
from pathlib import Path
import sys


def publish(source, destination):
    if (source.is_symlink() or not source.is_file() or source == destination
            or destination.is_symlink() or source.parent.resolve() != destination.parent.resolve()):
        raise ValueError('Expected a distinct adjacent regular archive output')
    # Unlike mv, never turn EXDEV into a long copy over the destination.
    os.replace(source, destination)


if __name__ == '__main__':
    try:
        publish(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError) as error:
        print(f'Atomic archive publication failed; temporary archive retained: {error}', file=sys.stderr)
        raise SystemExit(1)
