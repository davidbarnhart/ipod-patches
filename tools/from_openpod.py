#!/usr/bin/env python3
"""Import openpod fix files (format 2, one Markdown file per fix) as format-3
patch folders. Runs on the maintainer's machine: it needs the stock firmware
to hash each edit's check window, and it never copies stock bytes out.

    python3 tools/from_openpod.py --fixes OPENPOD/firmware/1/1.6 --stock iPod_1.1.5.ipsw \\
        --base apple-1g2g-1.5 --source openpod@37b622a [--only a,b]

Writes patches/<base>/<fix>/{patch.json, README.md, append.hex}. README.md is
the fix file's prose without its "For the patcher" block (that block holds
Apple's bytes). Refuses an edit whose `stock` isn't what the firmware holds.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADING = "## For the patcher"
BLOCK = re.compile(r"^%s[ \t]*\n(.*?)^```json[ \t]*\n(.*?)^```[ \t]*$" % re.escape(HEADING), re.S | re.M)
LINE = 32


def cut_stock_runs(edits, appends, blob, imgs, firmware, out_dir):
    """Take every stock run validate.py would fail out of the published bytes
    (zeroed in place) and return `copies` that put it back from the user's
    own firmware at apply time."""
    import validate
    order = [t for t, _ in sorted(fw.read_dir(firmware).items(), key=lambda kv: kv[1][1][3])]
    scan = validate.Scanner([(t, imgs[t]) for t in order])
    copies = []

    def cut(data, image, base_off):
        data = bytearray(data)
        for i, n, name, so in scan.runs(bytes(data)):
            if validate.is_fill(bytes(data[i:i + n])):
                continue
            copies.append({"image": image, "offset": "0x%x" % (base_off + i),
                           "from": {"image": name, "offset": "0x%x" % so, "bytes": n,
                                    "sha256": fw.sha(imgs[name][so:so + n])}})
            data[i:i + n] = bytes(n)
        return bytes(data)

    for e in edits:
        e["patched"] = cut(bytes.fromhex(e["patched"]), e["image"], int(e["offset"], 16)).hex()
    if appends:
        a = appends[0]
        new = cut(blob, a["image"], int(a["offset"], 16))
        with open(os.path.join(out_dir, a["file"]), "w") as fh:
            fh.write("".join(new[i:i + LINE].hex() + "\n" for i in range(0, len(new), LINE)))
        a["sha256"] = fw.sha(new)
    return copies


def convert(path, firmware, base, source):
    text = open(path).read()
    m = BLOCK.search(text)
    if not m:
        raise fw.PatchError("%s has no patcher block" % path)
    doc = json.loads(m.group(2))
    if doc.get("format") != 2:
        raise fw.PatchError("%s: format %r, expected openpod format 2" % (path, doc.get("format")))
    stem = os.path.splitext(os.path.basename(path))[0]
    imgs = fw.images(firmware)
    loads = {t: r[5] for t, (_o, r) in fw.read_dir(firmware).items()}
    if fw.sha(imgs[doc["base"]["image"]]) != doc["base"]["sha256"]:
        raise fw.PatchError("%s was made for a different %s" % (stem, doc["base"]["image"]))
    edits = []
    for e in doc["edits"]:
        img, load = imgs[e["image"]], loads[e["image"]]
        va, stock, new = int(e["at"], 16), bytes.fromhex(e["stock"]), bytes.fromhex(e["patched"])
        off = va - load
        if img[off:off + len(stock)] != stock:
            raise fw.PatchError("%s: stock at 0x%08x isn't what the fix expects" % (stem, va))
        lo, hi = fw.check_window(off, len(new), len(img))
        edits.append({"image": e["image"], "offset": "0x%x" % off, "vaddr": "0x%08x" % va,
                      "patched": new.hex(),
                      "check": {"offset": "0x%x" % lo, "bytes": hi - lo, "sha256": fw.sha(img[lo:hi])},
                      "why": e.get("why", "")})
    out_dir = os.path.join(ROOT, "patches", base["id"], stem)
    os.makedirs(out_dir, exist_ok=True)
    appends = []
    ap = doc.get("append")
    if ap:
        if "file" in ap:
            blob = bytes.fromhex("".join(open(os.path.join(os.path.dirname(path), ap["file"])).read().split()))
        else:
            blob = bytes.fromhex("".join(ap["hex"]))
        if fw.sha(blob) != ap["sha256"]:
            raise fw.PatchError("%s: appended code doesn't match its sha256" % stem)
        at = int(ap["at"], 16)
        with open(os.path.join(out_dir, "append.hex"), "w") as fh:
            fh.write("".join(blob[i:i + LINE].hex() + "\n" for i in range(0, len(blob), LINE)))
        appends.append({"image": "osos", "offset": "0x%x" % (at - loads["osos"]), "vaddr": "0x%08x" % at,
                        "bytes": len(blob), "sha256": fw.sha(blob), "file": "append.hex"})
    copies = cut_stock_runs(edits, appends, blob if ap else b"", imgs, firmware, out_dir)
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), stem)
    patch = {"format": fw.FORMAT, "id": stem, "author": "openpod", "title": title, "base": base["id"],
             "requires": doc["requires"], "conflicts": [], "status": "released",
             "edits": edits, "append": appends, "copies": copies,
             "source": {"from": source, "path": os.path.basename(path), "builder_name": doc["name"]},
             "license": "MIT"}
    with open(os.path.join(out_dir, "patch.json"), "w") as fh:
        json.dump(patch, fh, indent=1)
        fh.write("\n")
    prose = text[:m.start()].rstrip() + "\n"
    with open(os.path.join(out_dir, "README.md"), "w") as fh:
        fh.write(prose)
    return stem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixes", required=True)
    ap.add_argument("--stock", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--only")
    o = ap.parse_args()
    base = fw.read_base(os.path.join(ROOT, "bases", o.base + ".json"))
    firmware = fw.load_firmware(o.stock)
    if fw.sha(firmware) != base["sha256"]:
        sys.exit("--stock is not base %s" % o.base)
    names = sorted(n for n in os.listdir(o.fixes) if n.endswith(".md") and n.lower() != "readme.md")
    if o.only:
        names = [n for n in names if n[:-3] in o.only.split(",")]
    for n in names:
        print("imported", convert(os.path.join(o.fixes, n), firmware, base, o.source))


if __name__ == "__main__":
    main()
