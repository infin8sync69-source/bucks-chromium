"""Checks whether this machine can fetch and build Chromium."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GIB = 1024 ** 3


@dataclass
class Check:
    name: str
    value: str
    level: str  # "ok", "warn" or "fail"
    advice: str = ""


def _ram_bytes() -> int | None:
    try:
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def _grade(value: float, fail_below: float, warn_below: float) -> str:
    return "fail" if value < fail_below else "warn" if value < warn_below else "ok"


def run_checks(root: Path) -> list[Check]:
    checks = []

    cores = os.cpu_count() or 0
    checks.append(Check("CPU cores", str(cores), _grade(cores, 8, 32),
                        "Chromium wants 32+ cores; with fewer, a full build takes many hours."))

    ram = _ram_bytes()
    if ram is None:
        checks.append(Check("RAM", "unknown", "warn"))
    else:
        gib = ram / GIB
        checks.append(Check("RAM", f"{gib:.1f} GiB", _grade(gib, 16, 64),
                            "Under 16 GiB the linker runs out of memory; 64-128 GiB is comfortable."))

    free = shutil.disk_usage(root if root.exists() else Path.home()).free / GIB
    checks.append(Check("Free disk", f"{free:.0f} GiB", _grade(free, 150, 300),
                        "A checkout plus one output directory needs about 150-250 GiB."))

    os_name = f"{platform.system()} {platform.machine()}"
    checks.append(Check("System", os_name, "ok" if platform.system() in ("Linux", "Darwin", "Windows") else "fail",
                        "Linux builds Linux and Android; macOS builds macOS; Windows builds Windows."))

    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    checks.append(Check("Python", py, "ok" if sys.version_info >= (3, 9) else "fail"))

    for tool, advice in (("git", "Install git."),
                         ("gclient", "Install depot_tools and put it on PATH: "
                                     "https://commondatastorage.googleapis.com/chrome-infra-docs/flat/"
                                     "depot_tools/docs/html/depot_tools_tutorial.html")):
        found = shutil.which(tool)
        checks.append(Check(tool, found or "not found", "ok" if found else "fail", "" if found else advice))

    sccache = shutil.which("sccache")
    checks.append(Check("sccache", sccache or "not found", "ok" if sccache else "warn",
                        "" if sccache else "Optional, shares compiled objects between builds and CI."))
    return checks


def report(checks: list[Check]) -> int:
    marks = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    for c in checks:
        line = f"[{marks[c.level]}] {c.name:<10} {c.value}"
        if c.level != "ok" and c.advice:
            line += f"\n         {c.advice}"
        print(line)
    failed = [c for c in checks if c.level == "fail"]
    print()
    if failed:
        print("This machine cannot build Chromium. Use a build server (see README.md).")
        return 1
    print("This machine can build Chromium.")
    return 0
