"""Read-only system diagnostics, except local runtime directories/write probes."""

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
            report("WARN", command, "not installed; optional in Phase 00")
            continue
        flag = "-version" if command in ("ffmpeg", "ffprobe") else "--version"
        try:
            result = subprocess.run([executable, flag], capture_output=True,
                                    text=True, timeout=10, check=False)
            lines = (result.stdout or result.stderr).strip().splitlines()
            detail = lines[0][:200] if lines else "no version output"
            report("PASS" if result.returncode == 0 and lines else "WARN",
                   command, detail)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            report("WARN", command, type(error).__name__)

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

    print(f"\n{'FAIL' if failures else 'PASS'} | Phase 00 diagnostics complete")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
