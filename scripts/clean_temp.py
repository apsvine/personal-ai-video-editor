"""Preview temp-file cleanup; explicit --apply is required to delete files."""

import argparse
import os
from pathlib import Path
import sys

from doctor import runtime_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete listed regular files")
    args = parser.parse_args()
    try:
        target = runtime_path("temp")
        if not target.exists():
            print("PASS | No runtime/temp directory; nothing to clean")
            return 0
        if not target.is_dir():
            raise OSError("runtime/temp must be a directory")

        def raise_walk_error(error):
            raise error

        count = 0
        for directory, _, files in os.walk(target, followlinks=False,
                                            onerror=raise_walk_error):
            for name in sorted(files):
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    continue
                print(f"{'DELETE' if args.apply else 'WOULD DELETE'} | {path.relative_to(target)}")
                if args.apply:
                    path.unlink()
                count += 1
        print(f"PASS | {count} file(s); {'cleanup complete' if args.apply else 'dry run only'}")
        return 0
    except OSError as error:
        print(f"FAIL | {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
