"""Read-only system diagnostics, except local runtime directories/write probes."""

import argparse
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_NAMES = ("projects", "cache", "logs", "temp")


def runtime_path(name):
    """Reject redirected runtime paths before creating or touching any files."""
    if name not in RUNTIME_NAMES:
        raise ValueError("Unknown runtime directory")
    runtime = ROOT / "runtime"
    target = runtime / name
    if runtime.is_symlink() or target.is_symlink():
        raise OSError("Runtime paths must not be symlinks")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase01", action="store_true",
                        help="also require the Phase 01 development environment")
    parser.add_argument("--phase02", action="store_true",
                        help="require Phase 01 plus working FFmpeg and ffprobe")
    args = parser.parse_args()
    args.phase01 = args.phase01 or args.phase02
    failures = []

    def report(level, label, detail):
        print(f"{level:4} | {label}: {detail}")
        if level == "FAIL":
            failures.append(label)

    report("PASS" if sys.version_info >= (3, 10) else "FAIL", "Python",
           f"{sys.version.split()[0]} (minimum 3.10)")
    for command in ("node", "npm", "ffmpeg", "ffprobe"):
        executable = shutil.which(command)
        if not executable:
            required = ((args.phase01 and command in ("node", "npm"))
                        or (args.phase02 and command in ("ffmpeg", "ffprobe")))
            report("FAIL" if required else "WARN", command,
                   "required for the selected phase" if required else "not installed; optional in Phase 00")
            continue
        flag = "-version" if command in ("ffmpeg", "ffprobe") else "--version"
        try:
            result = subprocess.run([executable, flag], capture_output=True,
                                    text=True, timeout=10, check=False)
            lines = (result.stdout or result.stderr).strip().splitlines()
            detail = lines[0][:200] if lines else "no version output"
            report("PASS" if result.returncode == 0 and lines else "WARN",
                   command, detail)
            if args.phase02 and command in ("ffmpeg", "ffprobe"):
                report("PASS" if result.returncode == 0 and lines else "FAIL",
                       f"Phase 02 {command}", "must execute successfully")
            if args.phase01 and command in ("node", "npm"):
                valid = result.returncode == 0 and bool(lines)
                if valid and command == "node":
                    try:
                        version = tuple(int(part) for part in lines[0].lstrip("v").split("."))
                        valid = ((20, 19, 0) <= version < (21, 0, 0)
                                 or version >= (22, 12, 0))
                    except ValueError:
                        valid = False
                report("PASS" if valid else "FAIL", f"Phase 01 {command}",
                       "compatible" if valid else "version check failed; see README requirements")
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            required = ((args.phase01 and command in ("node", "npm"))
                        or (args.phase02 and command in ("ffmpeg", "ffprobe")))
            report("FAIL" if required else "WARN", command, type(error).__name__)

    if args.phase01:
        report("PASS" if sys.version_info[:2] == (3, 11) else "FAIL", "Phase 01 Python",
               "requires Python 3.11; run with the project virtual environment")
        report("PASS" if sys.prefix != sys.base_prefix else "WARN", "Virtual environment",
               "active" if sys.prefix != sys.base_prefix else "not active; isolation recommended")
        for package in ("fastapi", "uvicorn", "httpx"):
            try:
                report("PASS", package, importlib.metadata.version(package))
            except importlib.metadata.PackageNotFoundError:
                report("FAIL", package, "missing; install apps/api/requirements-dev.txt")
        report("PASS" if (ROOT / "apps/web/node_modules/vite/package.json").is_file() else "FAIL",
               "Frontend dependencies", "run npm ci in apps/web if missing")

    for name in RUNTIME_NAMES:
        try:
            target = runtime_path(name)
            target.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=target) as probe:
                probe.write(b"phase00-write-check\n")
                probe.flush()
            report("PASS", f"runtime/{name}", "directory writable; probe removed")
        except OSError as error:
            report("FAIL", f"runtime/{name}", str(error))

    try:
        free_gib = shutil.disk_usage(ROOT).free / (1024 ** 3)
        report("PASS" if free_gib >= 1 else "WARN", "Disk space",
               f"approximately {free_gib:.1f} GiB free; future media needs vary")
    except OSError as error:
        report("WARN", "Disk space", str(error))

    for name in ("PERSONAL_AI_VIDEO_EDITOR_LOG_LEVEL",
                 "PERSONAL_AI_VIDEO_EDITOR_TRANSCRIPTION_PROVIDER"):
        present = bool(os.environ.get(name))
        report("PASS" if present else "WARN", name,
               "set (value hidden)" if present else "unset; optional placeholder")

    phase = "02" if args.phase02 else "01" if args.phase01 else "00"
    print(f"\n{'FAIL' if failures else 'PASS'} | Phase {phase} diagnostics complete")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
