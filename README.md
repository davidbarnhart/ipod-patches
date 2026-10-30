# ipod-patches

Patches for classic iPod firmware, published without the firmware.

Apple's last firmware for the 1st and 2nd generation iPod, 1.5, came out in
2005. These patches pick up where it stopped. They let an iPod from 2001
play FLAC, use a modern flash card larger than 128 GB, and hold a library of
30,000 songs; on one real iPod, stock 1.5 showed no songs at all past 5,297.
They also make its menus faster.

Each patch is a documented change to Apple's own code, and you can pick the
ones you want. All 22 together are **flashpod 1.6**: on 2026-10-16 they
booted, played, skipped and seeked on a 1st-generation iPod with a 250 GB card
and 31,958 songs.

## Example patches

| Patch | What it does for you |
|---|---|
| [flac](patches/apple-1g2g-1.5/flac/) | plays FLAC files; fast-forward and rewind land at once, and a track starts without a dropout |
| [large-disks](patches/apple-1g2g-1.5/large-disks/) | LBA48: storage larger than 128 GB, for flash-modded iPods |
| [library-leak](patches/apple-1g2g-1.5/library-leak/) | fixes the memory leak that makes a large library vanish: the iPod starts, then shows no songs |
| [track-record](patches/apple-1g2g-1.5/track-record/) | each song takes 160 bytes of memory instead of 448: 9.2 MB less with 31,958 songs |
| [menu-sort](patches/apple-1g2g-1.5/menu-sort/) | Artists, an artist and Songs open in about 2 s instead of 4–6 |
| [missing-characters](patches/apple-1g2g-1.5/missing-characters/) | a character the font lacks shows as `?` instead of vanishing from the name |
| [shuffle-audiobooks](patches/apple-1g2g-1.5/shuffle-audiobooks/) | Shuffle Songs leaves audiobooks out without looking up every track |
| [disk-mode-large-disks](patches/apple-1g2g-1.5/disk-mode-large-disks/) | FireWire disk mode reads and writes past 128 GB (needs the iPod's flash chip reprogrammed) |

There are 22 in all, in [`patches/apple-1g2g-1.5/`](patches/apple-1g2g-1.5/).
Each patch's README says what was wrong, which code it changes, what the
patch does, and how it was tested, in the emulator and on real iPods.
[flashpod](https://github.com/davidbarnhart/flashpod) writes flashpod 1.6 to
a card for you; choosing your own set of patches is coming to it.

## For developers

The patches are for anyone who builds or applies them, not one tool. The
format is described in [SPEC.md](SPEC.md); [vectors/](vectors/) holds the
cases an implementation must pass. If you're patching iPod firmware too,
publish here, or use the format in your own repository.

**No Apple bytes are published here.** A patch records the stock bytes it
replaces only as a sha256 over a window of at least 32 bytes. Stock bytes a
patch needs, such as a relocated instruction sequence or a string the
firmware already holds, are copied from the user's own firmware when the
patch is applied. `tools/validate.py --stock` checks every published byte
run against the stock firmware, and fails any shared run of 16 bytes or
more that isn't fill. SPEC.md has the exact rules.

## What's here

| | |
|---|---|
| `bases/` | stock firmware files patches apply to, by sha256 (not the files) |
| `patches/<base>/<id>/` | one patch: `patch.json`, `README.md`, appended code |
| `builds/` | named results, such as flashpod 1.6: a base, patches in order, the expected sha256 |
| `catalog/` | firmware files, by sha256, with where to get them |
| `schema/` | JSON Schemas for all of the above |
| `index.json` | every published file's path and sha256, for clients that sync |
| `tools/` | the reference implementation (Python 3.6+, stdlib only) and the checks |

## Using it

```sh
python3 tools/validate.py                          # structure + index (what CI runs)
python3 tools/test_vectors.py                      # the reference implementation against vectors/
python3 tools/validate.py --stock iPod_1.1.5.ipsw  # no stock bytes, and every build reproduces
```

flashpod reads this repository as its primary patch source, and ships a
copy for when it can't be reached.

## Adding a patch

1. Put the patch in `patches/<base>/<id>/` with `patch.json` and a
   `README.md`: what was wrong, which code, what it does, how it was tested
   (emulator or hardware, with dates). openpod fixes are imported with
   `tools/from_openpod.py`.
2. Run `python3 tools/make_index.py`, then `python3 tools/validate.py --stock <the base's firmware>`.
   It must pass.
3. Open a pull request. CI checks structure, schemas, the index and the
   vectors. A maintainer reruns step 2 with the real stock file before merging.

## License

MIT (see LICENSE). This covers the patches and tools; Apple's firmware is
not here and is not covered.
