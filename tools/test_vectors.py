#!/usr/bin/env python3
"""Run vectors/cases.json against this repo's implementation (tools/fw.py)
and validator, and check the good builds' bytes independently of fw.py:
each image's checksum, each edit and copy where it should be, and stock
everywhere else. Ends with PASS/FAIL; exit 0 only on PASS.

    python3 tools/test_vectors.py
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw  # noqa: E402
import validate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(ROOT, "vectors")
FAILS = []


def check(ok, what):
    print("  %s %s" % ("ok  " if ok else "FAIL", what))
    if not ok:
        FAILS.append(what)


def independent(stock, out, patches):
    """The patched firmware, judged without fw.apply: images by the directory
    (devOffset/len), checksums by byte sum, owned bytes as published, the rest stock."""
    def dir_of(f):
        ptr, = struct.unpack_from("<I", f, 0x104)
        d = {}
        for k in range(10):
            rec = struct.unpack_from("<4s4sIIIIIIII", f, ptr + 0x200 + 40 * k)
            if rec[0] == b"\0\0\0\0":
                break
            d[rec[1][::-1].decode()] = rec
        return d
    so, do = dir_of(stock), dir_of(out)
    ok = set(so) == set(do)
    for t, rec in do.items():
        img = out[rec[3]:rec[3] + rec[4]]
        ok &= (sum(img) & 0xFFFFFFFF) == rec[7]
        ok &= rec[3] % 0x200 == 0 or t == "osos"
    imgs = {t: bytearray(out[r[3]:r[3] + r[4]]) for t, r in do.items()}
    st = {t: stock[r[3]:r[3] + r[4]] for t, r in so.items()}
    expect = {t: bytearray(b) for t, b in st.items()}
    for p in patches:
        for a in p["append"]:
            e = expect[a["image"]]
            e += bytes(max(0, a["offset"] + len(a["blob"]) - len(e)))
            e[a["offset"]:a["offset"] + len(a["blob"])] = a["blob"]
        for ed in p["edits"]:
            expect[ed["image"]][ed["offset"]:ed["offset"] + len(ed["patched"])] = ed["patched"]
    for p in patches:
        for c in p["copies"]:
            src, s_off, n, _ = c["src"]
            expect[c["image"]][c["offset"]:c["offset"] + n] = st[src][s_off:s_off + n]
    return ok and all(imgs[t] == expect[t] for t in expect)


def main():
    cases = json.load(open(os.path.join(V, "cases.json")))
    stock = bytes(fw.load_firmware(os.path.join(V, cases["stock"])))
    base = fw.read_base(os.path.join(V, "bases", cases["base"] + ".json"))
    print("vectors: %d cases on %s" % (len(cases["cases"]), cases["base"]))
    for c in cases["cases"]:
        if c.get("scan"):
            errs = validate.run(V, os.path.join(V, cases["stock"]), say=lambda *a: None)
            named = sorted({e.split(":")[0] for e in errs})
            check(named == c["expect"]["scan_fails"], "%s: the scan fails exactly %s (got %s)" % (c["name"], c["expect"]["scan_fails"], named))
            continue
        f = bytearray(stock)
        if "stock_change" in c:
            f[int(c["stock_change"]["offset"], 16)] ^= c["stock_change"]["xor"]
        ps = []
        for s in c["patches"]:
            p = fw.read_patch(os.path.join(V, "patches", cases["base"], s))
            p["stem"] = s
            ps.append(p)
        try:
            out = fw.apply(bytes(f), base, ps)
            got = {"bytes": len(out), "sha256": fw.sha(out)}
        except fw.PatchError as e:
            out, got = None, {"refused": e.code}
        check(got == c["expect"], "%s: %s" % (c["name"], c["expect"]))
        if out is not None:
            check(independent(stock, out, ps), "%s: checksums, owned bytes and stock elsewhere hold (judged without fw.apply)" % c["name"])
    print("%s: %d failed" % ("FAIL" if FAILS else "PASS", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
