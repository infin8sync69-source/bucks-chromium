"""Tests for the Bucks branding overlay. Run: python3 -m unittest discover -s tests"""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bucks_cli import branding, config  # noqa: E402

OVERLAY = branding.overlay_dir(config.load().core)
UPSTREAM = json.loads((ROOT / "tests" / "fixtures" / "upstream_branding.json").read_text())


def png(width: int, height: int, tag: str = "") -> bytes:
    """A valid, tiny, all-black PNG of the given size (standard library only).

    `tag` goes into a text chunk so that stand-in files of the same size still differ, as real ones do.
    """
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\x00" + b"\x00" * width for _ in range(height))
    text = chunk(b"tEXt", b"Comment\x00" + tag.encode()) if tag else b""
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + text + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class FakeTree:
    """A git repo holding a stand-in upstream file, of the right size, for every overlay file."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        for rel, f in branding.overlay_files(OVERLAY):
            target = self.src / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            size = branding.image_size(f)
            if f.suffix == ".png":
                target.write_bytes(png(*size, tag=rel))
            elif f.suffix == ".xpm":
                target.write_text(f'/* XPM */\nstatic char * x[] = {{\n"{size[0]} {size[1]} 1 1",\n}};\n')
            else:
                target.write_bytes(b"upstream " + rel.encode())
        git(self.src, "init", "-q")
        git(self.src, "add", ".")
        git(self.src, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "upstream")

    def close(self):
        self.tmp.cleanup()


class OverlayMatchesChromiumTest(unittest.TestCase):
    def test_overlay_exists(self):
        self.assertGreaterEqual(len(branding.overlay_files(OVERLAY)), 20)

    def test_every_file_replaces_an_upstream_file_of_the_same_size(self):
        sizes = UPSTREAM["sizes"]
        for rel, f in branding.overlay_files(OVERLAY):
            with self.subTest(rel):
                self.assertIn(rel, sizes, "no such file in Chromium " + UPSTREAM["chromium"])
                if sizes[rel] is not None:
                    self.assertEqual(list(branding.image_size(f)), sizes[rel])

    def test_xpm_keeps_the_variable_name_chromium_compiles(self):
        xpm = OVERLAY / "chrome/app/theme/chromium/linux/product_logo_32.xpm"
        self.assertIn("static char * linux_icon_chromium_32_xpm[]", xpm.read_text())


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTree()

    def tearDown(self):
        self.fake.close()

    def test_apply_is_idempotent_and_revert_restores(self):
        src = self.fake.src
        before = {rel: (src / rel).read_bytes() for rel, _ in branding.overlay_files(OVERLAY)}
        self.assertTrue(all(st is branding.State.READY for _, st in branding.status(src, OVERLAY)))

        results = branding.apply(src, OVERLAY)
        self.assertTrue(all(st is branding.State.APPLIED for _, st in results))
        for rel, f in branding.overlay_files(OVERLAY):
            self.assertEqual((src / rel).read_bytes(), f.read_bytes())
        self.assertTrue(all(st is branding.State.APPLIED for _, st in branding.apply(src, OVERLAY)))

        branding.revert(src, OVERLAY)
        for rel, data in before.items():
            self.assertEqual((src / rel).read_bytes(), data)

    def test_size_change_upstream_is_refused(self):
        rel = "chrome/app/theme/chromium/product_logo_48.png"
        (self.fake.src / rel).write_bytes(png(50, 50))
        upstream = (self.fake.src / rel).read_bytes()
        states = dict(branding.apply(self.fake.src, OVERLAY))
        self.assertIs(states[rel], branding.State.SIZE)
        self.assertEqual((self.fake.src / rel).read_bytes(), upstream)

    def test_file_dropped_upstream_is_reported(self):
        rel = "chrome/app/theme/default_100_percent/chromium/product_logo_name_22.png"
        (self.fake.src / rel).unlink()
        self.assertIs(dict(branding.status(self.fake.src, OVERLAY))[rel], branding.State.MISSING)


class VerifyBuildTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeTree()
        self.out = Path(self.fake.tmp.name + "-out")
        self.out.mkdir()

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.out, ignore_errors=True)

    def pack(self, *parts: bytes) -> Path:
        p = self.out / "resources.pak"
        p.write_bytes(b"PAK" + b"".join(parts))
        return p

    def test_finds_only_logo_files(self):
        logos = branding.chromium_logos(self.fake.src)
        self.assertIn("chrome/app/theme/chromium/product_logo_48.png", logos)
        self.assertIn("components/resources/default_100_percent/chromium/favicon_product.png", logos)
        self.assertNotIn("chrome/app/theme/chromium/linux/product_logo_32.xpm", logos)

    def test_branded_build_is_clean(self):
        branding.apply(self.fake.src, OVERLAY)
        bucks = [f.read_bytes() for _, f in branding.overlay_files(OVERLAY)]
        self.assertEqual(branding.leftover_logos(self.fake.src, [self.pack(*bucks)]), [])

    def test_unbranded_logo_is_caught(self):
        rel = "components/resources/default_200_percent/chromium/favicon_product.png"
        original = (self.fake.src / rel).read_bytes()
        branding.apply(self.fake.src, OVERLAY)
        self.assertEqual(branding.leftover_logos(self.fake.src, [self.pack(b"x", original)]), [rel])


class ImageSizeTest(unittest.TestCase):
    def test_png_and_xpm(self):
        with tempfile.TemporaryDirectory() as d:
            p, x, s = Path(d, "a.png"), Path(d, "a.xpm"), Path(d, "a.svg")
            p.write_bytes(png(97, 22))
            x.write_text('/* XPM */\nstatic char * v[] = {\n"32 32 4 1",\n};\n')
            s.write_text("<svg/>")
            self.assertEqual(branding.image_size(p), (97, 22))
            self.assertEqual(branding.image_size(x), (32, 32))
            self.assertIsNone(branding.image_size(s))


if __name__ == "__main__":
    unittest.main()
