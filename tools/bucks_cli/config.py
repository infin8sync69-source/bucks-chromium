"""Paths and settings for one bucks-chromium checkout.

Layout:
    bucks-chromium/            this repository
    bucks-chromium/src/        the Chromium checkout (created by `bucks init`)
    bucks-chromium/src/bucks   the bucks-core repository (symlink or gclient solution)
    ../bucks-core             default location of bucks-core next to this repository
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROMIUM_URL = "https://chromium.googlesource.com/chromium/src.git"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class Config:
    root: Path
    chromium_version: str
    core_url: str | None = None

    @property
    def src(self) -> Path:
        return self.root / "src"

    @property
    def out(self) -> Path:
        return self.src / "out"

    @property
    def core(self) -> Path:
        env = os.environ.get("BUCKS_CORE")
        return Path(env).resolve() if env else (self.root.parent / "bucks-core")

    @property
    def core_in_src(self) -> Path:
        return self.src / "bucks"

    @property
    def patches_dir(self) -> Path:
        return self.core / "patches"

    @property
    def args_dir(self) -> Path:
        return self.core / "build" / "args"


def load(root: Path = ROOT) -> Config:
    data = json.loads((root / "chromium.json").read_text())
    version = data["version"]
    if not VERSION_RE.match(version):
        raise ValueError(f"chromium.json: bad version {version!r}")
    return Config(root=root, chromium_version=version, core_url=data.get("core_url"))


def pin(version: str, root: Path = ROOT) -> None:
    if not VERSION_RE.match(version):
        raise ValueError(f"not a Chromium version: {version!r} (expected e.g. 158.0.8127.88)")
    path = root / "chromium.json"
    data = json.loads(path.read_text())
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
