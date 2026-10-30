#!/usr/bin/env python3
"""Write vectors/: a synthetic stock firmware (no Apple bytes), a base file for
it, patches that must apply and patches that must be refused, and
cases.json saying which outcome each set of patches has. Any implementation
of the format runs cases.json (tools/test_vectors.py is this repo's runner).

    python3 tools/make_vectors.py        # rewrite vectors/ (deterministic)
"""
import json
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw  # noqa: E402
import make_index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(ROOT, "vectors")
BASE_ID = "synthetic-1"
OSOS_LEN, AUPD_LEN = 0x1000, 0x400
OSOS_DEV = 0x4400
OSOS_MAX = 0x1800
TEXT = b"This licence text stands in for a vendor's own strings.\x00"


def prng(n, seed):
    out, x = bytearray(), seed
    while len(out) < n:
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        out += struct.pack("<I", x)
    return bytes(out[:n])


def stock_firmware():
    osos = bytearray(prng(OSOS_LEN, 1))
    osos[0x400:0x400 + len(TEXT)] = TEXT
    aupd = prng(AUPD_LEN, 2)
    aupd_dev = -(-(OSOS_DEV + OSOS_LEN) // 0x200) * 0x200
    f = bytearray(aupd_dev + AUPD_LEN)
    f[0:4] = b"{{~~"
    f[0x100:0x104] = b"]ih["
    struct.pack_into("<I", f, 0x104, 0x4000)
    struct.pack_into("<H", f, 0x10a, 2)
    for k, (typ, dev, img) in enumerate((("osos", OSOS_DEV, osos), ("aupd", aupd_dev, aupd))):
        struct.pack_into(fw.ENTRY_FMT, f, 0x4200 + 40 * k, b"ksid", typ.encode()[::-1], 0, dev, len(img),
                         0x28000000, 0, sum(img) & 0xFFFFFFFF, 0x10000, 0xFFFFFFFF)
        f[dev:dev + len(img)] = img
    return bytes(f)


def write_patch(stock_imgs, stem, edits=(), append=None, copies=(), requires=(), conflicts=(), bad_check=False):
    folder = os.path.join(V, "patches", BASE_ID, stem)
    os.makedirs(folder)
    ed = []
    for image, off, new in edits:
        img = stock_imgs[image]
        lo, hi = fw.check_window(off, len(new), len(img))
        h = fw.sha(img[lo:hi]) if not bad_check else fw.sha(b"made for other stock")
        ed.append({"image": image, "offset": "0x%x" % off, "patched": new.hex(),
                   "check": {"offset": "0x%x" % lo, "bytes": hi - lo, "sha256": h}, "why": "vector"})
    ap = []
    if append:
        image, off, blob = append
        with open(os.path.join(folder, "append.hex"), "w") as fh:
            fh.write("".join(blob[i:i + 32].hex() + "\n" for i in range(0, len(blob), 32)))
        ap.append({"image": image, "offset": "0x%x" % off, "bytes": len(blob), "sha256": fw.sha(blob), "file": "append.hex"})
    cp = []
    for image, off, (src_img, so, n, src_sha) in copies:
        cp.append({"image": image, "offset": "0x%x" % off,
                   "from": {"image": src_img, "offset": "0x%x" % so, "bytes": n,
                            "sha256": src_sha or fw.sha(stock_imgs[src_img][so:so + n])}})
    doc = {"format": fw.FORMAT, "id": stem, "author": "ipod-patches", "title": "test vector " + stem,
           "base": BASE_ID, "requires": list(requires), "conflicts": list(conflicts), "status": "test",
           "edits": ed, "append": ap, "copies": cp, "source": {"from": "tools/make_vectors.py"}, "license": "MIT"}
    with open(os.path.join(folder, "patch.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    with open(os.path.join(folder, "README.md"), "w") as fh:
        fh.write("# %s\n\nA test vector; see vectors/cases.json.\n" % stem)


def main():
    if os.path.exists(V):
        shutil.rmtree(V)
    for d in ("bases", "builds", "patches/" + BASE_ID, "catalog", "schema"):
        os.makedirs(os.path.join(V, d))
    f = stock_firmware()
    with open(os.path.join(V, "stock.bin"), "wb") as fh:
        fh.write(f)
    imgs = fw.images(f)
    base = {"format": fw.FORMAT, "id": BASE_ID, "title": "Synthetic stock firmware for the test vectors",
            "maker": "ipod-patches", "version": "1", "models": [], "file": "vectors/stock.bin",
            "bytes": len(f), "sha256": fw.sha(f),
            "images": {t: {"bytes": len(imgs[t]), "sha256": fw.sha(imgs[t]), "addr": "0x28000000",
                           "max_bytes": "0x%x" % (OSOS_MAX if t == "osos" else len(imgs[t]))} for t in imgs}}
    with open(os.path.join(V, "bases", BASE_ID + ".json"), "w") as fh:
        json.dump(base, fh, indent=1)
        fh.write("\n")
    end = OSOS_LEN
    W = write_patch
    W(imgs, "edit", edits=[("osos", 0x100, bytes.fromhex("0000a0e1" * 2))])
    W(imgs, "append", edits=[("osos", 0x200, bytes.fromhex("feffffea"))], append=("osos", end, prng(64, 9)))
    hole = bytearray(prng(48, 10))
    hole[8:8 + 32] = bytes(32)
    W(imgs, "copy", edits=[("aupd", 0x40, bytes.fromhex("01020304"))], append=("osos", end + 0x40, bytes(hole)),
      copies=[("osos", end + 0x40 + 8, ("osos", 0x400, 32, None))])
    W(imgs, "needs-edit", edits=[("osos", 0x300, b"\x11" * 4)], requires=["edit"])
    W(imgs, "overlap", edits=[("osos", 0x104, b"\x22" * 8)])
    W(imgs, "conflicts", edits=[("osos", 0x500, b"\x33" * 4)], conflicts=["edit"])
    W(imgs, "no-room", append=("osos", end + 0x700, prng(0x200, 11)))
    W(imgs, "misaligned", append=("osos", end + 2, prng(16, 12)))
    W(imgs, "stock-mismatch", edits=[("osos", 0x600, b"\x44" * 4)], bad_check=True)
    W(imgs, "copy-source", append=("osos", end + 0x100, bytes(32)),
      copies=[("osos", end + 0x100, ("osos", 0x400, 32, fw.sha(b"not this")))])
    W(imgs, "copy-outside", edits=[("osos", 0x700, b"\x55" * 4)],
      copies=[("osos", 0x800, ("osos", 0x400, 32, None))])
    stolen = bytearray(prng(64, 13))
    stolen[16:48] = imgs["osos"][0x400:0x420]               # 32 stock bytes, published: the scan must fail it
    W(imgs, "carries-stock", append=("osos", end + 0x180, bytes(stolen)))

    def outcome(patches):
        _base = fw.read_base(os.path.join(V, "bases", BASE_ID + ".json"))
        ps = []
        for s in patches:
            p = fw.read_patch(os.path.join(V, "patches", BASE_ID, s))
            p["stem"] = s
            ps.append(p)
        try:
            out = fw.apply(f, _base, ps)
        except fw.PatchError as e:
            return {"refused": e.code}
        return {"bytes": len(out), "sha256": fw.sha(out)}

    sets = [("one edit", ["edit"]), ("edit + append + copy + requires", ["edit", "append", "copy", "needs-edit"]),
            ("requires missing", ["needs-edit"]), ("two patches own a byte", ["edit", "overlap"]),
            ("declared conflict", ["edit", "conflicts"]), ("appended code past the image's room", ["no-room"]),
            ("appended code not 4-byte aligned", ["misaligned"]), ("stock differs from the check window", ["stock-mismatch"]),
            ("copy source isn't in stock", ["copy-source"]), ("copy lands outside the patch's bytes", ["copy-outside"])]
    cases = [{"name": n, "patches": ps, "expect": outcome(ps)} for n, ps in sets]
    cases.append({"name": "firmware that isn't the base", "patches": ["edit"], "stock_change": {"offset": "0x4500", "xor": 1},
                  "expect": {"refused": "base_mismatch"}})
    cases.append({"name": "published stock bytes", "patches": ["carries-stock"], "scan": True,
                  "expect": {"scan_fails": ["carries-stock"]}})
    with open(os.path.join(V, "cases.json"), "w") as fh:
        json.dump({"format": fw.FORMAT, "base": BASE_ID, "stock": "stock.bin", "cases": cases}, fh, indent=1)
        fh.write("\n")
    open(os.path.join(V, "index.json"), "w").write(make_index.text(V))
    for c in cases:
        print("%-40s %s" % (c["name"], c["expect"]))


if __name__ == "__main__":
    main()
