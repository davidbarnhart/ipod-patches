# ipod-patches format 3

A format for publishing patches to iPod firmware without publishing the
firmware. Anyone may implement it; `tools/fw.py` is the reference
implementation, and an implementation conforms when it gives the outcome
`vectors/cases.json` names for every case.

All numbers written as strings are hexadecimal with a `0x` prefix. Every
sha256 is lowercase hex. Files are UTF-8 JSON.

## What a firmware is

An iPod firmware file (the `Firmware-*` file inside an Apple `.ipsw`) has a
`]ih[` header at 0x100, whose u32 at 0x104 points at a staging directory.
The live directory is 0x200 past it. It holds up to ten 40-byte entries
(little-endian):

`dev[4] type[4, byte-reversed] id devOffset len addr entryOffset checksum vers loadAddr`

An image is `len` bytes at `devOffset`, or at `devOffset + 0x200` when the
header's u16 at 0x10a is 3. Its checksum is the byte sum of those bytes, mod
2^32. Patches name images by `type`: `osos`, `aupd`, `rsrc`.

## Bases: `bases/<id>.json`

A base is one stock firmware file, named by its sha256. Patches are written
against a base and apply to nothing else.

```json
{"format": 3, "id": "apple-1g2g-1.5", "title": "...", "maker": "apple", "version": "1.5",
 "models": ["1G", "2G"], "file": "where the file comes from", "bytes": 5068800, "sha256": "...",
 "images": {"osos": {"bytes": 3234472, "sha256": "...", "addr": "0x28000000",
                     "max_bytes": "0x380000", "max_bytes_why": "..."}}}
```

`max_bytes` is how large the image may grow. Appended code must end at or
below it. It is a fact about the firmware (where its loader writes), so it
belongs to the base, not to a tool.

## Patches: `patches/<base id>/<patch id>/`

A patch is a folder holding `patch.json`, `README.md` (for people: what was
wrong, which code, what the patch does, how it was tested) and any appended
files it names.

```json
{"format": 3, "id": "library-leak", "author": "openpod", "title": "...",
 "base": "apple-1g2g-1.5", "requires": [], "conflicts": [], "status": "released",
 "edits":  [{"image": "osos", "offset": "0x34dd4", "vaddr": "0x28034dd4", "patched": "082094e5...",
             "check": {"offset": "0x34dc0", "bytes": 96, "sha256": "..."}, "why": "..."}],
 "append": [{"image": "osos", "offset": "0x315aa8", "bytes": 820, "sha256": "...", "file": "append.hex"}],
 "copies": [{"image": "osos", "offset": "0x315ab0",
             "from": {"image": "osos", "offset": "0x147190", "bytes": 96, "sha256": "..."}}],
 "source": {"from": "where the bytes were built"}, "license": "MIT"}
```

- **id**: the folder name. It is unique within its base; `author` says whose it is.
- **requires / conflicts**: ids of patches for the same base that this one needs, or can't go with.
- **status**: `released`, `testing`, `withdrawn` or `test` (vectors only).
- **edits**: bytes of the stock image that change, in place. `offset` is
  inside the image; `vaddr` is informational. `patched` is the new bytes.
- **check**: the stock bytes the edit was made against, given as a hash.
  The window is the edit widened to 16-byte boundaries, then by 16 bytes at
  a time on each side until it is at least 32 bytes long, clipped to the
  image. A hash of a short edit's own bytes could be reversed by brute force;
  a 32-byte window can't.
- **append**: code placed past the image's end. It must sit on a 4-byte
  boundary at or past the stock image's length, and end at or below
  `max_bytes`. The file is hex, any whitespace. `bytes` and `sha256` are of
  the decoded file.
- **copies**: stock bytes the patch needs in its own bytes, such as a
  relocated instruction sequence or a string the firmware already holds. The
  published bytes there are zeros; the patcher copies `from` out of the
  user's stock firmware after checking its sha256. A copy must land inside
  this patch's own edits or append.

## Applying

Given a firmware file, its base and a list of patches:

1. The file's sha256 must be the base's (`base_mismatch`), and every patch's
   `base` must be that base's id (`base_mismatch`).
2. Every `requires` must be in the list (`requires`), and no `conflicts`
   may be (`conflicts`).
3. For every edit:
   - the image must exist (`no_image`);
   - the edit must lie inside it (`outside_image`);
   - its check window must cover it and hash to `sha256` in stock (`stock_mismatch`).
4. For every append:
   - it must be 4-byte aligned at or past the stock image's end (`misaligned`);
   - it must end at or below `max_bytes` (`no_room`).
5. For every copy:
   - its source must hash to `sha256` in stock (`copy_source`);
   - it must land inside the patch's own bytes (`copy_outside`).
6. No two patches may own the same byte of an image, counting edits and
   appends (`overlap`).
7. Build each image: stock, extended with zeros to the furthest append's end,
   then every append and every edit written in. Copies are written last, from stock.
8. **Layout.** Write the images back in their stock devOffset order:
   - Everything before the first image is kept as it was.
   - An image starts where it was, unless the one before it now runs past
     that point. Then it starts at the next 0x200 boundary after it.
   - Each entry's devOffset, len and checksum are rewritten.
   - Nothing follows the last image.
   - The result must fit the 32 MiB firmware partition (`too_big`).

Each refusal code in parentheses is what `vectors/cases.json` expects.

## Builds: `builds/<id>.json`

A named result: a base, patch ids in order, and the expected output. Anyone
with the stock file can reproduce it and compare.

```json
{"format": 3, "id": "flashpod-1.6", "base": "apple-1g2g-1.5", "patches": ["article-memory", "..."],
 "result": {"bytes": 5479893, "sha256": "...", "osos_sha256": "..."}, "tested": [...]}
```

## No stock bytes

Nothing published may contain the stock firmware's bytes: not `patched`,
not appended files, not hex quoted in `README.md`. `tools/validate.py
--stock FILE` checks it, using these rules:

- **Seeds:** stock seeds are the 16-byte windows of every image, at 4-aligned offsets.
- **Scan:** published bytes are scanned at every offset. A seed hit grows
  forward byte by byte against the first stock copy holding it, and the scan
  resumes after the run.
- **Verdict:** a run of 16 bytes or more fails unless it is fill: at most 3
  distinct 4-aligned words, or at most 6 distinct bytes. Fill is zeros, 0xff,
  no-op sleds and small-integer tables.

Bytes a patch truly needs from stock go in `copies`.

## Catalog: `catalog/firmware.json`

Firmware files by sha256 (`bytes`, `sha256` of the firmware file itself),
with the `base` or `build` each one is, and `urls`: where to download it, in
order. The `primary` is the maker's own download where one still exists
(Apple's for Apple firmware); `fallback`s follow (an archive.org copy). Each
URL records the downloaded file's own `sha256` and its `container` (`ipsw`,
`bin`, `bin.gz`). A client checks the download against it, unpacks it, and
checks the firmware file against the entry's `sha256`.

## Index: `index.json`

Every file under `bases/ builds/ catalog/ patches/ schema/`, with its path,
size and sha256. A client fetches `index.json`, then only the files it
doesn't already hold by sha256, and checks each one against the index.
