"""Bucks branding: replace Chromium's logo files with Bucks ones.

bucks-core/branding/overlay/ mirrors the Chromium source tree. Every file there replaces the upstream
file of the same path (icons, the product-name image, the Linux .xpm). No patch is involved, so a new
Chromium version never conflicts; the check only fails if upstream drops a file or changes an image's
pixel size, which would mean Chromium's layout expects something different.

Uses only the standard library: the build machines have no imaging library.
"""
from __future__ import annotations

import filecmp
import re
import shutil
import struct
import subprocess
from enum import Enum
from pathlib import Path


class State(str, Enum):
    APPLIED = "applied"
    READY = "ready"
    MISSING = "NO UPSTREAM FILE"
    SIZE = "SIZE DIFFERS"


def overlay_dir(core: Path) -> Path:
    return core / "branding" / "overlay"


def overlay_files(overlay: Path) -> list[tuple[str, Path]]:
    """(path relative to the Chromium tree, overlay file), sorted by path."""
    if not overlay.is_dir():
        return []
    return sorted((p.relative_to(overlay).as_posix(), p) for p in overlay.rglob("*") if p.is_file())


def image_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a PNG or XPM file, or None for other formats."""
    data = path.read_bytes()[:4096]
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data.lstrip().startswith(b"/* XPM */"):
        m = re.search(rb'"\s*(\d+)\s+(\d+)\s+\d+\s+\d+', data)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def state(src: Path, rel: str, file: Path) -> State:
    target = src / rel
    if not target.is_file():
        return State.MISSING
    if filecmp.cmp(target, file, shallow=False):
        return State.APPLIED
    if image_size(target) != image_size(file):
        return State.SIZE
    return State.READY


def status(src: Path, overlay: Path) -> list[tuple[str, State]]:
    return [(rel, state(src, rel, f)) for rel, f in overlay_files(overlay)]


def apply(src: Path, overlay: Path) -> list[tuple[str, State]]:
    """Copies every overlay file whose upstream file exists with the same size.

    Returns the state of each file afterwards; files that were MISSING or SIZE are left untouched.
    """
    results = []
    for rel, f in overlay_files(overlay):
        st = state(src, rel, f)
        if st is State.READY:
            shutil.copyfile(f, src / rel)
            st = State.APPLIED
        results.append((rel, st))
    return results


def revert(src: Path, overlay: Path) -> list[str]:
    """Restores every branded file to upstream with git."""
    paths = [rel for rel, _ in overlay_files(overlay) if (src / rel).exists()]
    if paths:
        subprocess.run(["git", "checkout", "--", *paths], cwd=src, check=True, capture_output=True)
    return paths
