"""Bucks patches to upstream Chromium files.

One patch per upstream file, stored in bucks-core/patches/ and named after the file's path with
"/" replaced by "-" (chrome/app/theme/chromium/BRANDING -> chrome-app-theme-chromium-BRANDING.patch).
The true path is always read from the patch's own `diff --git` header, so the name is only a label.

Every operation is idempotent: applying twice is a no-op, and `check` tells apart a patch that is
already applied, one that applies cleanly and one that conflicts after an upstream change.
"""
from __future__ import annotations

import re
import subprocess
from enum import Enum
from pathlib import Path

HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)


class State(str, Enum):
    APPLIED = "applied"
    CLEAN = "applies cleanly"
    CONFLICT = "CONFLICT"


def patch_name(path: str) -> str:
    return path.replace("/", "-") + ".patch"


def target_of(patch: Path) -> str:
    match = HEADER.search(patch.read_text())
    if not match:
        raise ValueError(f"{patch.name}: no 'diff --git' header")
    return match.group(2)


def list_patches(patches_dir: Path) -> list[Path]:
    return sorted(patches_dir.glob("*.patch"))


def _git(src: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=src, check=check, capture_output=True, text=True)


def state(src: Path, patch: Path) -> State:
    if _git(src, "apply", "--check", str(patch), check=False).returncode == 0:
        return State.CLEAN
    if _git(src, "apply", "--check", "--reverse", str(patch), check=False).returncode == 0:
        return State.APPLIED
    return State.CONFLICT


def status(src: Path, patches_dir: Path) -> list[tuple[Path, State]]:
    return [(p, state(src, p)) for p in list_patches(patches_dir)]


def apply_all(src: Path, patches_dir: Path) -> list[tuple[Path, State]]:
    """Applies every clean patch. Returns the state of each patch after the run."""
    results = []
    for patch, st in status(src, patches_dir):
        if st is State.CLEAN:
            _git(src, "apply", str(patch))
            st = State.APPLIED
        results.append((patch, st))
    return results


def update(src: Path, patches_dir: Path, extra_paths: list[str] = ()) -> list[str]:
    """Regenerates patches from the working tree in src. Returns a log of what changed."""
    log = []
    targets = {target_of(p): p for p in list_patches(patches_dir)}
    for path in extra_paths:
        targets.setdefault(path, patches_dir / patch_name(path))
    for path, patch in sorted(targets.items()):
        diff = _git(src, "diff", "--full-index", "--", path).stdout
        if not diff:
            if patch.exists():
                patch.unlink()
                log.append(f"removed {patch.name} ({path} matches upstream)")
            continue
        if not patch.exists() or patch.read_text() != diff:
            patch.write_text(diff)
            log.append(f"wrote {patch.name}")
    return log


def revert_all(src: Path, patches_dir: Path) -> list[str]:
    """Restores every patched file to upstream."""
    paths = [target_of(p) for p in list_patches(patches_dir)]
    if paths:
        _git(src, "checkout", "--", *paths)
    return paths
