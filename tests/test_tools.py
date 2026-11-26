"""Tests for the bucks command-line tools. Run: python3 -m unittest discover -s tests"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from bucks_cli import chromium, config, doctor, patches  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
# Real Chromium files at the pinned version, at their paths in src/ (BSD licence). Every file that a
# bucks-core patch touches needs its upstream copy here; AllPatchesTest enforces that.
UPSTREAM = FIXTURES / "upstream"
CORE = config.load().core
BRANDING_PATH = "chrome/app/theme/chromium/BRANDING"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class FakeChromium:
    """A git repo holding the real upstream files from tests/fixtures/upstream at their Chromium paths,
    and a copy of bucks-core's patches (only those touching `only`, when given)."""

    def __init__(self, only=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        shutil.copytree(UPSTREAM, self.src, dirs_exist_ok=True)
        git(self.src, "init", "-q")
        git(self.src, "add", ".")
        git(self.src, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "upstream")
        self.patches = Path(self.tmp.name + "-patches")
        self.patches.mkdir()
        for patch in patches.list_patches(CORE / "patches"):
            if only is None or patches.target_of(patch) in only:
                shutil.copy(patch, self.patches)

    def close(self):
        self.tmp.cleanup()
        shutil.rmtree(self.patches, ignore_errors=True)


class ConfigTest(unittest.TestCase):
    def test_pinned_version_is_valid(self):
        self.assertRegex(config.load().chromium_version, config.VERSION_RE)

    def test_pin_rejects_bad_version(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "chromium.json").write_text(json.dumps({"version": "1.2.3.4"}))
            with self.assertRaises(ValueError):
                config.pin("158.0", Path(d))
            config.pin("159.0.1.2", Path(d))
            self.assertEqual(config.load(Path(d)).chromium_version, "159.0.1.2")


class GclientTest(unittest.TestCase):
    def test_file_is_python_and_pins_tag(self):
        scope = {}
        exec(chromium.gclient_file("158.0.8127.88", android=True), scope)
        self.assertEqual(scope["solutions"][0]["url"],
                         "https://chromium.googlesource.com/chromium/src.git@refs/tags/158.0.8127.88")
        self.assertFalse(scope["solutions"][0]["custom_vars"]["checkout_pgo_profiles"])
        self.assertEqual(scope["target_os"], ["android"])

    def test_core_url_adds_solution(self):
        scope = {}
        exec(chromium.gclient_file("158.0.8127.88", core_url="https://example.invalid/bucks-core.git"), scope)
        self.assertEqual(scope["solutions"][1]["name"], "src/bucks")
        self.assertNotIn("target_os", scope)


class PatchesTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeChromium(only=[BRANDING_PATH])

    def tearDown(self):
        self.fake.close()

    def test_branding_patch_applies_and_matches_branding_file(self):
        src, pdir = self.fake.src, self.fake.patches
        [(patch, state)] = patches.status(src, pdir)
        self.assertEqual(patches.target_of(patch), BRANDING_PATH)
        self.assertEqual(patch.name, patches.patch_name(BRANDING_PATH))
        self.assertIs(state, patches.State.CLEAN)

        patches.apply_all(src, pdir)
        self.assertEqual((src / BRANDING_PATH).read_text(), (CORE / "app/theme/BRANDING").read_text())

        # Applying again is a no-op.
        [(_, state)] = patches.apply_all(src, pdir)
        self.assertIs(state, patches.State.APPLIED)

    def test_update_reproduces_patch_and_revert_restores(self):
        src, pdir = self.fake.src, self.fake.patches
        original = (pdir / patches.patch_name(BRANDING_PATH)).read_text()
        patches.apply_all(src, pdir)
        self.assertEqual(patches.update(src, pdir), [])
        self.assertEqual((pdir / patches.patch_name(BRANDING_PATH)).read_text(), original)

        patches.revert_all(src, pdir)
        self.assertEqual((src / BRANDING_PATH).read_text(), (UPSTREAM / BRANDING_PATH).read_text())
        # A patch whose file matches upstream again is removed by update.
        self.assertIn("removed", patches.update(src, pdir)[0])

    def test_conflict_after_upstream_change(self):
        src, pdir = self.fake.src, self.fake.patches
        target = src / BRANDING_PATH
        target.write_text(target.read_text().replace("Chromium Installer", "Chromium Setup"))
        git(src, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "upstream change")
        [(_, state)] = patches.status(src, pdir)
        self.assertIs(state, patches.State.CONFLICT)

    def test_add_tracks_new_file(self):
        src, pdir = self.fake.src, self.fake.patches
        target = src / BRANDING_PATH
        target.write_text(target.read_text() + "EXTRA=1\n")
        for p in pdir.glob("*.patch"):
            p.unlink()
        log = patches.update(src, pdir, [BRANDING_PATH])
        self.assertEqual(log, ["wrote " + patches.patch_name(BRANDING_PATH)])


class AllPatchesTest(unittest.TestCase):
    """Every bucks-core patch applies cleanly to the pinned upstream files."""

    def test_every_patch_has_an_upstream_copy_and_applies(self):
        targets = [patches.target_of(p) for p in patches.list_patches(CORE / "patches")]
        self.assertIn(BRANDING_PATH, targets)
        for target in targets:
            self.assertTrue((UPSTREAM / target).is_file(),
                            f"add the upstream file to tests/fixtures/upstream/{target}")
        fake = FakeChromium()
        try:
            states = patches.status(fake.src, fake.patches)
            self.assertEqual(len(states), len(targets))
            for patch, state in states:
                self.assertIs(state, patches.State.CLEAN, patch.name)
            for patch, state in patches.apply_all(fake.src, fake.patches):
                self.assertIs(state, patches.State.APPLIED, patch.name)
        finally:
            fake.close()

    def test_root_build_file_pulls_in_bucks(self):
        if not (CORE / "patches" / patches.patch_name("BUILD.gn")).exists():
            self.skipTest("bucks-core has no root BUILD.gn patch")
        fake = FakeChromium(only=["BUILD.gn"])
        try:
            patches.apply_all(fake.src, fake.patches)
            gn_all = (fake.src / "BUILD.gn").read_text().split('group("gn_all")', 1)[1]
            self.assertIn('"//bucks",', gn_all.split("\n}\n", 1)[0])
        finally:
            fake.close()


class BuildTest(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(chromium.profiles(config.load()),
                         ["android_release", "linux_ci", "linux_debug", "linux_release", "mac_release",
                          "win_release"])

    def test_time_limit_stops_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "interrupted"
            # A stand-in for a build that cleans up on SIGINT, as ninja and siso do.
            script = f"trap 'touch {marker}; exit 130' INT; while :; do sleep 0.1; done"
            self.assertFalse(chromium.run_with_time_limit(["sh", "-c", script], Path(d), 0.5, grace=10))
            self.assertTrue(marker.exists())
            self.assertTrue(chromium.run_with_time_limit(["true"], Path(d), 5))
            with self.assertRaises(subprocess.CalledProcessError):
                chromium.run_with_time_limit(["false"], Path(d), 5)

    def test_time_limit_waits_for_the_real_build_tool(self):
        # autoninja exits on SIGINT at once while siso, its child, is still saving state. The stop must
        # wait for the child, or the saved output directory holds an incomplete state file.
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "state-saved"
            child = ("import pathlib, signal, time\n"
                     "def stop(*_):\n"
                     "    time.sleep(1)\n"
                     f"    pathlib.Path({str(marker)!r}).touch()\n"
                     "    raise SystemExit(0)\n"
                     "signal.signal(signal.SIGINT, stop)\n"
                     "while True: time.sleep(0.1)\n")
            wrapper = ("import subprocess, sys, time\n"
                       f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                       "time.sleep(30)\n")
            self.assertFalse(chromium.run_with_time_limit([sys.executable, "-c", wrapper], Path(d), 1,
                                                          grace=10))
            self.assertTrue(marker.exists(), "returned before the child saved its state")

    def test_gn_args(self):
        self.assertEqual(chromium.gn_args("linux_debug", sccache=True),
                         'import("//bucks/build/args/linux_debug.gn")\ncc_wrapper = "sccache"')


class DoctorTest(unittest.TestCase):
    def test_reports_core_checks(self):
        names = {c.name for c in doctor.run_checks(ROOT)}
        self.assertTrue({"CPU cores", "RAM", "Free disk", "gclient"} <= names)


if __name__ == "__main__":
    unittest.main()
