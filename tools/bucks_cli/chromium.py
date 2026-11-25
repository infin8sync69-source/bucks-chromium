"""Fetching, syncing and building Chromium with the Bucks layer."""
from __future__ import annotations

import json
import pprint
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import patches
from .config import CHROMIUM_URL, Config

RELEASES_URL = "https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform={platform}&num=1"
# Build target per OS. Everything else builds the desktop browser.
TARGETS = {"android": "chrome_public_apk"}


def gclient_file(version: str, android: bool = False, core_url: str | None = None) -> str:
    solutions = [{
        "name": "src",
        "url": f"{CHROMIUM_URL}@refs/tags/{version}",
        "managed": False,
        "custom_deps": {},
        # Profile-guided optimisation data is Google-internal for official Chrome; Bucks builds
        # without it (chrome_pgo_phase = 0 in the release args).
        "custom_vars": {"checkout_pgo_profiles": False},
    }]
    if core_url:
        solutions.append({"name": "src/bucks", "url": core_url, "managed": False})
    text = "# Written by `bucks init`. Edit chromium.json instead.\n"
    text += "solutions = " + pprint.pformat(solutions, sort_dicts=False) + "\n"
    if android:
        text += 'target_os = ["android"]\n'
    return text


def latest_stable(platform: str = "Linux") -> str:
    with urllib.request.urlopen(RELEASES_URL.format(platform=platform), timeout=30) as r:
        return json.load(r)[0]["version"]


def _run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def _require(tool: str) -> None:
    if not shutil.which(tool):
        sys.exit(f"{tool} not found. Install depot_tools and put it on PATH (run `./bucks doctor`).")


def link_core(cfg: Config) -> None:
    """Makes bucks-core visible at src/bucks, unless gclient manages it."""
    if cfg.core_url or cfg.core_in_src.exists():
        return
    if not cfg.core.is_dir():
        sys.exit(f"bucks-core not found at {cfg.core} (set BUCKS_CORE or clone it next to bucks-chromium).")
    cfg.core_in_src.symlink_to(cfg.core, target_is_directory=True)
    print(f"linked {cfg.core_in_src} -> {cfg.core}")


def init(cfg: Config, android: bool, full_history: bool) -> None:
    _require("gclient")
    (cfg.root / ".gclient").write_text(gclient_file(cfg.chromium_version, android, cfg.core_url))
    cmd = ["gclient", "sync", "--nohooks", "--with_tags", f"--revision=src@refs/tags/{cfg.chromium_version}"]
    if not full_history:
        cmd.append("--no-history")
    _run(cmd, cfg.root)
    link_core(cfg)
    _run(["gclient", "runhooks"], cfg.root)
    apply_patches(cfg)


def sync(cfg: Config) -> None:
    """Moves an existing checkout to the pinned version and re-applies the patches."""
    _require("gclient")
    patches.revert_all(cfg.src, cfg.patches_dir)
    _run(["gclient", "sync", "-D", "--with_tags", f"--revision=src@refs/tags/{cfg.chromium_version}"], cfg.root)
    link_core(cfg)
    apply_patches(cfg)


def apply_patches(cfg: Config) -> bool:
    ok = True
    for patch, st in patches.apply_all(cfg.src, cfg.patches_dir):
        print(f"{st.value:<16} {patch.name}")
        ok &= st is not patches.State.CONFLICT
    if not ok:
        print("Some patches conflict with this Chromium version. Fix them in src/, then run "
              "`./bucks patches update`.")
    return ok


def profiles(cfg: Config) -> list[str]:
    return sorted(p.stem for p in cfg.args_dir.glob("*.gn") if p.stem != "common")


def gn_args(profile: str, sccache: bool) -> str:
    lines = [f'import("//bucks/build/args/{profile}.gn")']
    if sccache:
        lines.append('cc_wrapper = "sccache"')
    return "\n".join(lines)


def build(cfg: Config, profile: str, target: str | None, sccache: bool) -> None:
    if profile not in profiles(cfg):
        sys.exit(f"unknown profile {profile!r}; choose one of: {', '.join(profiles(cfg))}")
    _require("gn")
    _require("autoninja")
    out = f"out/{profile}"
    _run(["gn", "gen", out, f"--args={gn_args(profile, sccache)}"], cfg.src)
    target = target or TARGETS.get(profile.split("_")[0], "chrome")
    _run(["autoninja", "-C", out, target, "bucks"], cfg.src)
