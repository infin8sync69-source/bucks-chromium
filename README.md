# bucks-chromium

Fetches Chromium at a pinned stable version, adds the Bucks layer ([bucks-core](../bucks-core)) and
builds the Bucks browser. Plan: `Bucks-Browser-Release-2026-10-27/docs/CHROMIUM-FORK-PLAN.md`.

Pinned Chromium: see `chromium.json` (`./bucks version show`).

## Machine

Chromium does not build on an ordinary laptop. Run `./bucks doctor` first. You need about:

| | Minimum | Comfortable |
|---|---|---|
| CPU cores | 8 | 32+ |
| RAM | 16 GiB | 64–128 GiB |
| Free disk (SSD) | 150 GiB | 300 GiB+ |

Linux builds Linux and Android, a Mac builds macOS, and Windows builds Windows. Develop on a build
server over SSH; a laptop only needs to edit code.

## First build

```bash
# 1. depot_tools (Chromium's fetch and build tools)
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git ~/depot_tools
export PATH="$HOME/depot_tools:$PATH"

# 2. this repo and bucks-core side by side
git clone https://github.com/infin8sync69-source/bucks-chromium.git
git clone https://github.com/infin8sync69-source/bucks-core.git
cd bucks-chromium

# 3. check the machine, fetch Chromium (about 100 GB, takes a while), apply Bucks patches
./bucks doctor
./bucks init                 # add --android for the Android toolchain
sudo src/build/install-build-deps.sh   # Linux only, once

# 4. build and run
./bucks build linux_debug
src/out/linux_debug/chrome
```

`bucks-core` is found next to this repo, or wherever `BUCKS_CORE` points. When it has a git URL, put
it in `chromium.json` as `core_url` and gclient fetches it into `src/bucks` instead.

## Commands

| Command | Does |
|---|---|
| `./bucks doctor` | Checks cores, RAM, disk and tools |
| `./bucks init [--android]` | Writes `.gclient`, fetches the pinned Chromium tag, links `src/bucks`, runs hooks, applies patches |
| `./bucks sync` | Reverts patches, moves the checkout to the pinned version, re-applies patches |
| `./bucks patches status\|apply\|check\|update\|add <path>\|revert` | Patches to upstream files (rules in bucks-core `PATCHES.md`) |
| `./bucks branding status\|apply\|check\|revert` | Bucks logo files from `bucks-core/branding/overlay` over Chromium's; `init` and `sync` apply them and stop if one no longer fits upstream |
| `./bucks build <profile> [--sccache] [--target T] [--time-limit MIN]` | `gn gen` and `autoninja` for a profile in `bucks-core/build/args`; with a time limit it stops cleanly and exits 3, and a later run continues |
| `./bucks version show\|latest\|pin <v>\|pin --latest` | Shows or changes the pinned Chromium version |

## Updating Chromium (every release)

```bash
./bucks version pin --latest
./bucks sync                 # stops and lists any patch that conflicts
# fix conflicts in src/, then
./bucks patches update
./bucks build linux_release
```

Target: ship within 5 days of a Chrome stable release, 2 days for a security fix.

## Tests

```bash
python3 -m unittest discover -s tests
```

They test the tools themselves, including applying the real branding patch to the real upstream
`BRANDING` file (`tests/fixtures/BRANDING.upstream`, from Chromium 158.0.8127.88, BSD licence).
They do not need a Chromium checkout.

## Building on GitHub's free machines

`bucks-chromium` is public, so GitHub runs its workflows for free. Their machines are small (4 cores,
16 GB RAM) and a job may run at most 6 hours, so the **build (GitHub machines)** workflow builds in
stages: each stage builds until shortly before the limit, stops cleanly (`./bucks build --time-limit`)
and hands its output to the next stage. Expect most of a day for a full build. It uses the `linux_ci`
profile (optimised, no link-time optimisation, no symbols), which is for testing; official releases
use `linux_release` on a bigger machine (`build (own server)` workflow).

Start it from the Actions tab, or:

```bash
gh workflow run build-github.yml -R infin8sync69-source/bucks-chromium
```

The finished browser is the `bucks-linux_ci` artifact of the run (`tar --zstd -xf` it, then run
`./chrome`).

## CI setup (once)

Both repos are private, and each one's CI checks out the other, which GitHub's built-in CI token cannot
do. Each repo therefore gets a read-only deploy key, stored as a secret in the other repo:

| Secret | Stored in | Deploy key added to |
|---|---|---|
| `BUCKS_CORE_DEPLOY_KEY` | bucks-chromium | bucks-core (read-only) |
| `BUCKS_CHROMIUM_DEPLOY_KEY` | bucks-core | bucks-chromium (read-only) |
