# bucks-browser

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
git clone <bucks-browser url> bucks-browser
git clone <bucks-core url> bucks-core
cd bucks-browser

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
| `./bucks build <profile> [--sccache] [--target T]` | `gn gen` and `autoninja` for a profile in `bucks-core/build/args` |
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
