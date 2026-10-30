# Landing a patch

How a fix gets from openpod (or your own tree) into ipod-patches, and from
here into flashpod. The short version is in README.md under "Adding a patch";
this is the full sequence with the commands.

You need the base's stock firmware on your machine (for `apple-1g2g-1.5`,
Apple's `iPod_1.1.5.ipsw`). It is never committed. The tools only hash it and
copy bytes out of it at apply time.

## 1. Write the patch folder

From an openpod fix file (format 2, one Markdown file per fix):

```sh
python3 tools/from_openpod.py \
    --fixes <openpod>/firmware/1/1.6 \
    --stock iPod_1.1.5.ipsw \
    --base apple-1g2g-1.5 \
    --source openpod@<commit> \
    --only <fix-id>
```

This writes `patches/<base>/<fix-id>/` with `patch.json`, `README.md` and
`append.hex`. The README is the fix file's prose without its "For the
patcher" block, since that block holds Apple's bytes. The tool refuses an
edit whose stated stock bytes don't match the firmware, and any stock run
that would fail the scan in step 3 is cut out of the published bytes and
turned into a `copies` entry that restores it from the user's firmware.

Without openpod, write `patch.json` by hand against `schema/patch.schema.json`
and SPEC.md. Set `status` to `testing` until it has run on hardware.

The README must say what was wrong, which code the patch changes, what it
does, and how it was tested: emulator or hardware, with dates.

## 2. Rebuild the index

```sh
python3 tools/make_index.py
```

`validate.py` fails with "index.json is not current" until you do, and CI
runs `make_index.py --check`.

## 3. Validate against the real firmware

```sh
python3 tools/validate.py --stock iPod_1.1.5.ipsw
```

This scans every published byte run against the stock firmware and fails
any shared run of 16 bytes or more that isn't fill. It must report 0 runs.
It also reproduces every build byte for byte and prints what it got.

## 4. Run the remaining checks

```sh
python3 tools/test_vectors.py
pip install jsonschema        # once, in a venv if you like
python3 tools/check_schemas.py
python3 tools/check_schemas.py --root vectors
```

These, plus `validate.py` without `--stock` and `make_index.py --check`, are
what CI runs. CI has no stock firmware, so step 3 is the maintainer's job.

## 5. Put it in a build (optional)

A build is a named result, such as `builds/flashpod-1.6.json`. To add a
patch to one, or to make a new build:

- add the patch id to `patches`;
- set `result.bytes`, `result.sha256` and `result.osos_sha256` to what
  `validate.py --stock` reports for the build;
- add a `tested` entry: `{"where": "hardware" | "emulator", "date":
  "YYYY-MM-DD", "what": "..."}`. Only record a test that ran on this exact
  result (these hashes).

Changing a released build changes what people get when they ask for it by
name; prefer a new build id.

## 6. Open a pull request

CI checks structure, schemas, the index and the vectors. A maintainer reruns
step 3 with the stock file before merging.

## After it merges: flashpod

flashpod reads this repository as its primary patch source and ships a copy
for when it can't reach it. In a flashpod checkout:

```sh
python3 scripts/sync_patches_snapshot.py --from <ipod-patches checkout>
python3 scripts/make_fixes_json.py --openpod <openpod checkout>   # fixes list shown by inspect
```

Then run flashpod's `scripts/test_patchlib.py`.
