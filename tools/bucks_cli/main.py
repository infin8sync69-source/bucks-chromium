"""Command line for fetching, patching and building the Bucks browser."""
from __future__ import annotations

import argparse

from . import branding, chromium, config, doctor, patches


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bucks", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check that this machine can build Chromium")

    init = sub.add_parser("init", help="fetch the pinned Chromium, link bucks-core, apply patches")
    init.add_argument("--android", action="store_true", help="also fetch the Android toolchain")
    init.add_argument("--full-history", action="store_true", help="clone full git history (much bigger)")

    sub.add_parser("sync", help="move the checkout to the pinned version and re-apply patches")

    pt = sub.add_parser("patches", help="manage patches to upstream files")
    pt_sub = pt.add_subparsers(dest="action", required=True)
    pt_sub.add_parser("status", help="show each patch's state")
    pt_sub.add_parser("apply", help="apply every patch that applies cleanly")
    pt_sub.add_parser("check", help="fail if any patch conflicts")
    pt_sub.add_parser("update", help="rewrite patches from the edited files in src/")
    add = pt_sub.add_parser("add", help="start tracking an edited upstream file as a patch")
    add.add_argument("path", help="path relative to src/, e.g. chrome/browser/BUILD.gn")
    pt_sub.add_parser("revert", help="restore every patched file to upstream")

    br = sub.add_parser("branding", help="Bucks logo files over Chromium's (bucks-core/branding/overlay)")
    br_sub = br.add_subparsers(dest="action", required=True)
    br_sub.add_parser("status", help="show each branded file's state")
    br_sub.add_parser("apply", help="copy every branded file into src/")
    br_sub.add_parser("check", help="fail if any branded file no longer fits upstream")
    br_sub.add_parser("revert", help="restore Chromium's own files")
    vb = br_sub.add_parser("verify-build", help="fail if a Chromium logo is still inside the built browser")
    vb.add_argument("out_dir", help="build output directory, e.g. out/linux_ci (relative to src/)")

    b = sub.add_parser("build", help="gn gen + autoninja for one profile")
    b.add_argument("profile", help="args profile in bucks-core/build/args, e.g. linux_debug")
    b.add_argument("--target", help="ninja target (default: chrome, or chrome_public_apk for android)")
    b.add_argument("--sccache", action="store_true", help="compile through sccache")
    b.add_argument("--time-limit", type=float, metavar="MINUTES",
                   help="stop cleanly after this long (exit code 3); run again to continue")

    v = sub.add_parser("version", help="show or change the pinned Chromium version")
    v_sub = v.add_subparsers(dest="action", required=True)
    v_sub.add_parser("show")
    latest = v_sub.add_parser("latest", help="print the current Chromium stable version")
    latest.add_argument("--platform", default="Linux")
    pin = v_sub.add_parser("pin", help="pin a version (run `bucks sync` afterwards)")
    pin.add_argument("version", nargs="?")
    pin.add_argument("--latest", action="store_true", help="pin the current stable version")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.cmd == "doctor":
        return doctor.report(doctor.run_checks(config.ROOT))

    if args.cmd == "version":
        if args.action == "latest":
            print(chromium.latest_stable(args.platform))
        elif args.action == "pin":
            version = chromium.latest_stable() if args.latest else args.version
            if not version:
                raise SystemExit("give a version or --latest")
            config.pin(version)
            print(f"pinned Chromium {version}; run `./bucks sync` to move the checkout")
        else:
            print(config.load().chromium_version)
        return 0

    cfg = config.load()
    if args.cmd == "init":
        chromium.init(cfg, args.android, args.full_history)
    elif args.cmd == "sync":
        chromium.sync(cfg)
    elif args.cmd == "build":
        if not chromium.build(cfg, args.profile, args.target, args.sccache, args.time_limit):
            return 3
    elif args.cmd == "patches":
        return _patches(cfg, args)
    elif args.cmd == "branding":
        return _branding(cfg, args)
    return 0


def _branding(cfg: config.Config, args: argparse.Namespace) -> int:
    overlay = branding.overlay_dir(cfg.core)
    if args.action == "apply":
        return 0 if chromium.apply_branding(cfg) else 1
    if args.action == "revert":
        for rel in branding.revert(cfg.src, overlay):
            print(f"reverted {rel}")
        return 0
    if args.action == "verify-build":
        packs = sorted((cfg.src / args.out_dir).glob("*.pak"))
        if not packs:
            print(f"no .pak files in {cfg.src / args.out_dir}")
            return 1
        left = branding.leftover_logos(cfg.src, packs)
        for rel in left:
            print(f"CHROMIUM LOGO STILL IN BUILD  {rel}")
        print(f"checked {len(branding.chromium_logos(cfg.src))} Chromium logo files against {len(packs)} packs: "
              + ("clean" if not left else f"{len(left)} left"))
        return 1 if left else 0
    results = branding.status(cfg.src, overlay)
    for rel, st in results:
        print(f"{st.value:<16} {rel}")
    bad = [rel for rel, st in results if st in (branding.State.MISSING, branding.State.SIZE)]
    return 1 if args.action == "check" and bad else 0


def _patches(cfg: config.Config, args: argparse.Namespace) -> int:
    if args.action == "apply":
        return 0 if chromium.apply_patches(cfg) else 1
    if args.action in ("status", "check"):
        results = patches.status(cfg.src, cfg.patches_dir)
        for patch, st in results:
            print(f"{st.value:<16} {patch.name}")
        conflicts = [p for p, st in results if st is patches.State.CONFLICT]
        return 1 if args.action == "check" and conflicts else 0
    if args.action in ("update", "add"):
        extra = [args.path] if args.action == "add" else []
        for line in patches.update(cfg.src, cfg.patches_dir, extra) or ["patches are up to date"]:
            print(line)
        return 0
    if args.action == "revert":
        for path in patches.revert_all(cfg.src, cfg.patches_dir):
            print(f"reverted {path}")
        return 0
    return 2
