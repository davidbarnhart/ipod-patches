"""Reference implementation of the ipod-patches format (SPEC.md), Python 3.6+,
stdlib only. Other implementations should follow SPEC.md and pass vectors/.

Reads an iPod firmware file (the raw Firmware-* file, a .bin.gz of it, or an
.ipsw), applies format-3 patches and returns the patched firmware file. Nothing
about a particular iPod is built in: what a firmware's images are, where they
load and how far they may grow comes from its base file (bases/*.json).
"""
import gzip
import hashlib
import json
import os
import struct
import zipfile

FORMAT = 3
ENTRY_FMT = "<4s4sIIIIIIII"      # dev, type (byte-reversed), id, devOffset, len, addr, entryOffset, chksum, vers, loadAddr
ENTRY_SIZE = 40
DEVOFF_FIELD, LEN_FIELD, CK_FIELD = 12, 16, 28
SECTOR = 0x200
FW_PARTITION_BYTES = 65536 * 512
CHECK_MIN = 32                    # stock bytes hashed per edit, at least (SPEC.md "Checks")


class PatchError(Exception):
    """A patch, build or base that can't be used: `code` is the SPEC.md
    refusal code (the same in every implementation), the message is for people."""

    def __init__(self, message, code="invalid"):
        Exception.__init__(self, message)
        self.code = code


def sha(b):
    return hashlib.sha256(bytes(b)).hexdigest()


def hexnum(s):
    return int(s, 16)


def load_firmware(path):
    """The firmware file's bytes, from a raw file, a .bin.gz or an .ipsw."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] == b"PK":
        with zipfile.ZipFile(path) as zf:
            name = next((n for n in zf.namelist() if os.path.basename(n).startswith("Firmware")), None)
            if name is None:
                raise PatchError("%s: no Firmware-* file in the .ipsw" % path, "not_firmware")
            return bytearray(zf.read(name))
    if data[:2] == b"\x1f\x8b":
        return bytearray(gzip.decompress(data))
    return bytearray(data)


def directory_offset(fw):
    """The live directory: one sector after the header's pointer (format 2 and 3)."""
    if fw[0x100:0x104] != b"]ih[":
        raise PatchError("not an iPod firmware file (no ]ih[ header at 0x100)", "not_firmware")
    ptr, = struct.unpack_from("<I", fw, 0x104)
    return ptr + 0x200


def directory_shift(fw):
    """Format 3 (4th generation on) stores each image 0x200 past its devOffset."""
    fmt, = struct.unpack_from("<H", fw, 0x10a)
    return 0x200 if fmt == 3 else 0


def read_dir(fw):
    """{type: (entry offset, record)} of the live directory, first of each type."""
    out, off = {}, directory_offset(fw)
    for _ in range(10):
        if off + ENTRY_SIZE > len(fw):
            break
        rec = struct.unpack_from(ENTRY_FMT, fw, off)
        if rec[0] == b"\0\0\0\0":
            break
        out.setdefault(rec[1][::-1].decode("latin-1"), (off, rec))
        off += ENTRY_SIZE
    return out


def images(fw):
    """{type: bytes} of every image in the directory."""
    shift = directory_shift(fw)
    return {t: bytes(fw[r[3] + shift:r[3] + shift + r[4]]) for t, (_o, r) in read_dir(fw).items()}


def check_window(offset, n, size):
    """The stock bytes a patch hashes for an edit of n bytes at `offset`: the
    edit widened to 16-byte boundaries, then by 16 at a time on each side
    until it is at least CHECK_MIN bytes, inside the image (SPEC.md)."""
    lo, hi = offset // 16 * 16, -(-(offset + n) // 16) * 16
    while hi - lo < CHECK_MIN and (lo > 0 or hi < size):
        lo, hi = max(0, lo - 16), min(size, hi + 16)
    return lo, min(size, hi)


def read_base(path):
    with open(path) as fh:
        return json.load(fh)


def read_patch(folder):
    """A format-3 patch folder -> dict with bytes decoded."""
    path = os.path.join(folder, "patch.json")
    with open(path) as fh:
        doc = json.load(fh)
    if doc.get("format") != FORMAT:
        raise PatchError("%s: format %r; this tool reads format %d" % (path, doc.get("format"), FORMAT), "format")
    edits = []
    for e in doc["edits"]:
        c = e["check"]
        edits.append(dict(image=e["image"], offset=hexnum(e["offset"]), patched=bytes.fromhex(e["patched"]),
                          check=(hexnum(c["offset"]), c["bytes"], c["sha256"]), why=e.get("why", ""),
                          vaddr=hexnum(e["vaddr"]) if "vaddr" in e else None))
    appends = []
    for a in doc.get("append") or []:
        with open(os.path.join(folder, a["file"])) as fh:
            blob = bytes.fromhex("".join(fh.read().split()))
        if len(blob) != a["bytes"] or sha(blob) != a["sha256"]:
            raise PatchError("%s: %s is not the %d bytes its sha256 names" % (path, a["file"], a["bytes"]), "append_file")
        appends.append(dict(image=a["image"], offset=hexnum(a["offset"]), blob=blob))
    copies = []
    for c in doc.get("copies") or []:
        f = c["from"]
        copies.append(dict(image=c["image"], offset=hexnum(c["offset"]),
                           src=(f["image"], hexnum(f["offset"]), f["bytes"], f["sha256"])))
    return dict(doc, folder=folder, edits=edits, append=appends, copies=copies)


def apply(fw, base, patches):
    """The patched firmware file (SPEC.md "Applying"). Raises PatchError for a
    firmware that isn't the base, stock bytes that differ, two patches owning
    one byte, a missing requirement or a declared conflict, or code past an
    image's room."""
    fw = bytearray(fw)
    if sha(fw) != base["sha256"]:
        raise PatchError("this firmware file (sha256 %s...) is not base %s" % (sha(fw)[:16], base["id"]), "base_mismatch")
    stock = images(fw)
    info = base["images"]
    owned = []
    stems = {p["stem"] for p in patches}
    for p in patches:
        if p["base"] != base["id"]:
            raise PatchError("%s is for base %s, not %s" % (p["stem"], p["base"], base["id"]), "base_mismatch")
        for r in p.get("requires", []):
            if r not in stems:
                raise PatchError("%s requires %s" % (p["stem"], r), "requires")
        for c in p.get("conflicts", []):
            if c in stems:
                raise PatchError("%s conflicts with %s" % (p["stem"], c), "conflicts")
        for e in p["edits"]:
            img = stock.get(e["image"])
            if img is None:
                raise PatchError("%s: no %s image in this firmware" % (p["stem"], e["image"]), "no_image")
            o, n = e["offset"], len(e["patched"])
            co, cn, csha = e["check"]
            if o + n > len(img):
                raise PatchError("%s: the %s edit at +0x%x is outside the stock image" % (p["stem"], e["image"], o), "outside_image")
            if not (co <= o and o + n <= co + cn) or sha(img[co:co + cn]) != csha:
                raise PatchError("%s: stock %s around +0x%x isn't what the patch was made for" % (p["stem"], e["image"], o), "stock_mismatch")
            owned.append((e["image"], o, o + n, p["stem"]))
        for a in p["append"]:
            size, room = len(stock[a["image"]]), hexnum(info[a["image"]]["max_bytes"])
            if a["offset"] < size or a["offset"] % 4:
                raise PatchError("%s: appended code at +0x%x must be 4-byte aligned at or past the image's end (+0x%x)" % (p["stem"], a["offset"], size), "misaligned")
            if a["offset"] + len(a["blob"]) > room:
                raise PatchError("%s: appended code ends at +0x%x; %s has room to +0x%x" % (p["stem"], a["offset"] + len(a["blob"]), a["image"], room), "no_room")
            owned.append((a["image"], a["offset"], a["offset"] + len(a["blob"]), p["stem"]))
        mine = [o for o in owned if o[3] == p["stem"]]
        for c in p["copies"]:
            img_name, so, n, csha = c["src"]
            src = stock.get(img_name)
            if src is None or so + n > len(src) or sha(src[so:so + n]) != csha:
                raise PatchError("%s: the stock bytes it copies from %s +0x%x aren't there" % (p["stem"], img_name, so), "copy_source")
            if not any(t == c["image"] and lo <= c["offset"] and c["offset"] + n <= hi for t, lo, hi, _ in mine):
                raise PatchError("%s: a copy to %s +0x%x lands outside the patch's own bytes" % (p["stem"], c["image"], c["offset"]), "copy_outside")
    owned.sort()
    for a, b in zip(owned, owned[1:]):
        if a[0] == b[0] and b[1] < a[2]:
            raise PatchError("%s and %s both own %s +0x%x" % (a[3], b[3], a[0], b[1]), "overlap")
    new = {t: bytearray(b) for t, b in stock.items()}
    for p in patches:
        for a in p["append"]:
            img = new[a["image"]]
            end = a["offset"] + len(a["blob"])
            if len(img) < end:
                img += bytes(end - len(img))
            img[a["offset"]:end] = a["blob"]
    for p in patches:
        for e in p["edits"]:
            new[e["image"]][e["offset"]:e["offset"] + len(e["patched"])] = e["patched"]
    for p in patches:
        for c in p["copies"]:
            img_name, so, n, _ = c["src"]
            new[c["image"]][c["offset"]:c["offset"] + n] = stock[img_name][so:so + n]
    return relayout(fw, new)


def relayout(fw, new):
    """Put the images back (SPEC.md "Layout"): each image keeps its place in
    devOffset order; an image that grew pushes the ones after it to the next
    sector boundary past its end. Every changed or moved image gets its length,
    devOffset and checksum (byte sum) redone."""
    d = read_dir(fw)
    shift = directory_shift(fw)
    order = sorted(d.items(), key=lambda kv: kv[1][1][3])
    first = order[0][1][1][3] + shift
    out = bytearray(fw[:first])
    for t, (off, rec) in order:
        if len(out) > rec[3] + shift:
            out += b"\0" * ((-len(out)) % SECTOR)
        else:
            out += b"\0" * (rec[3] + shift - len(out))
        at = len(out)
        out += new[t]
        struct.pack_into("<I", out, off + DEVOFF_FIELD, at - shift)
        struct.pack_into("<I", out, off + LEN_FIELD, len(new[t]))
        struct.pack_into("<I", out, off + CK_FIELD, sum(new[t]) & 0xFFFFFFFF)
    if len(out) > FW_PARTITION_BYTES:
        raise PatchError("patched firmware is %d bytes, past the 32 MiB firmware partition" % len(out), "too_big")
    return bytes(out)


def read_build(path, root):
    """A build file -> (build, base, [patches in order])."""
    with open(path) as fh:
        doc = json.load(fh)
    base = read_base(os.path.join(root, "bases", doc["base"] + ".json"))
    patches = []
    for stem in doc["patches"]:
        p = read_patch(os.path.join(root, "patches", doc["base"], stem))
        p["stem"] = stem
        patches.append(p)
    return doc, base, patches
