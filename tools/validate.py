#!/usr/bin/env python3
"""Check the repository: every patch, base and build file is well formed,
index.json is current, and (with --stock) no published byte run is Apple's.

    python3 tools/validate.py                         # structure + index (what CI runs)
    python3 tools/validate.py --stock FIRMWARE        # also the Apple-bytes scan and the build
                                                      # reproduction, for the base that file is
    python3 tools/validate.py --stock F --json OUT    # every run found, for diffing against
                                                      # another implementation of the scan

THE APPLE-BYTES SCAN (SPEC.md "No stock bytes"). The published bytes of a
patch are each edit's `patched` bytes and each appended file. Stock seeds are
the 16-byte windows of every image of the base at 4-aligned offsets; the
published bytes are scanned at every byte offset; a seed hit grows forward
byte by byte against the first stock copy holding it (images in directory
order) and the scan resumes after the run. A run of 16 bytes or more FAILS
unless it is fill: its 4-aligned words (from the run's start) are at most 3
distinct values, or its bytes at most 6 distinct values (zeros, 0xff, nop
sleds, small-integer tables). Bytes a patch needs from stock go in `copies`,
which the patcher reads from the user's own firmware. These are the rules of
openpod's fwtools/apple_runs.py (firmware session, 2026-10-29), so the two
can be compared run for run.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw  # noqa: E402
import make_index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 16
MIN_RUN = 16
PATCH_KEYS = {"format", "id", "author", "title", "base", "requires", "conflicts", "status",
              "edits", "append", "copies", "source", "license"}


def listdir(root, *parts):
    """A folder's names, sorted; none if it's absent (git keeps no empty folders)."""
    path = os.path.join(root, *parts)
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def fail(errors, msg):
    errors.append(msg)


def is_fill(run):
    words = {run[k:k + 4] for k in range(0, len(run) - 3, 4)}
    return len(words) <= 3 or len(set(run)) <= 6


class Scanner:
    def __init__(self, stock_images):
        self.stock = stock_images            # [(name, bytes)] in directory order
        self.seeds = {}
        for name, img in stock_images:
            for o in range(0, len(img) - SEED + 1, 4):
                self.seeds.setdefault(img[o:o + SEED], (name, o))
        self.by_name = dict(stock_images)

    def runs(self, new):
        """[(offset in new, length, stock image, stock offset)] of every shared run >= MIN_RUN."""
        out, i = [], 0
        while i + SEED <= len(new):
            hit = self.seeds.get(new[i:i + SEED])
            if not hit:
                i += 1
                continue
            name, o = hit
            img, n = self.by_name[name], SEED
            while i + n < len(new) and o + n < len(img) and new[i + n] == img[o + n]:
                n += 1
            if n >= MIN_RUN:
                out.append((i, n, name, o))
            i += n
        return out


def published_pieces(p):
    """(label, bytes) of everything a patch publishes, as openpod's tool labels them."""
    pieces = [("append", b"".join(a["blob"] for a in p["append"]))]
    for e in p["edits"]:
        pieces.append(("edit@0x%08x" % (e["vaddr"] if e["vaddr"] is not None else e["offset"]), e["patched"]))
    return pieces


def check_structure(errors, root):
    bases = {}
    for n in listdir(root, "bases"):
        b = fw.read_base(os.path.join(root, "bases", n))
        if b.get("format") != fw.FORMAT or b.get("id") + ".json" != n:
            fail(errors, "bases/%s: format 3 with id = its file name" % n)
        bases[b["id"]] = b
    patches = {}
    for base_id in listdir(root, "patches"):
        if base_id not in bases:
            fail(errors, "patches/%s: no bases/%s.json" % (base_id, base_id))
            continue
        base = bases[base_id]
        for stem in listdir(root, "patches", base_id):
            folder = os.path.join(root, "patches", base_id, stem)
            where = "patches/%s/%s" % (base_id, stem)
            try:
                p = fw.read_patch(folder)
            except (fw.PatchError, KeyError, ValueError) as e:
                fail(errors, "%s: %s" % (where, e))
                continue
            raw = json.load(open(os.path.join(folder, "patch.json")))
            extra, missing = set(raw) - PATCH_KEYS, PATCH_KEYS - set(raw)
            if extra or missing:
                fail(errors, "%s: keys %s missing, %s unknown" % (where, sorted(missing), sorted(extra)))
            if p["id"] != stem or p["base"] != base_id:
                fail(errors, "%s: id and base must be its folder names" % where)
            if not os.path.exists(os.path.join(folder, "README.md")):
                fail(errors, "%s: no README.md" % where)
            for e in p["edits"]:
                info = base["images"].get(e["image"])
                co, cn, _ = e["check"]
                if info is None:
                    fail(errors, "%s: edit in %s, which base %s has no image of" % (where, e["image"], base_id))
                elif not (co <= e["offset"] and e["offset"] + len(e["patched"]) <= co + cn) or cn < min(fw.CHECK_MIN, info["bytes"]):
                    fail(errors, "%s: the check window at +0x%x doesn't cover its edit with >= %d bytes" % (where, e["offset"], fw.CHECK_MIN))
            p["stem"] = stem
            patches[(base_id, stem)] = p
    for (base_id, stem), p in patches.items():
        for r in p["requires"] + p["conflicts"]:
            if (base_id, r) not in patches:
                fail(errors, "patches/%s/%s names %s, which isn't a patch for that base" % (base_id, stem, r))
    builds = {}
    for n in listdir(root, "builds"):
        doc = json.load(open(os.path.join(root, "builds", n)))
        for s in doc["patches"]:
            if (doc["base"], s) not in patches:
                fail(errors, "builds/%s: no patch %s for base %s" % (n, s, doc["base"]))
        builds[n] = doc
    return bases, patches, builds


def hex_in_prose(text):
    """Byte strings written as hex in prose: runs of >= 32 hex digits, spaces allowed."""
    out = []
    for m in re.finditer(r"(?:[0-9a-fA-F]{2}[ ]?){16,}", text):
        out.append(bytes.fromhex(m.group(0).replace(" ", "")))
    return out


def run(root, stock=None, json_out=None, say=print):
    """Every check on the repository at `root`. Returns the list of problems."""
    errors = []
    bases, patches, builds = check_structure(errors, root)
    stale = make_index.stale(root)
    if stale:
        fail(errors, "index.json is not current (%s); run tools/make_index.py" % stale)
    say("structure: %d bases, %d patches, %d builds" % (len(bases), len(patches), len(builds)))
    if stock:
        firmware = fw.load_firmware(stock)
        base = next((b for b in bases.values() if b["sha256"] == fw.sha(firmware)), None)
        if base is None:
            fail(errors, "--stock %s is none of the bases" % stock)
            return errors
        imgs = fw.images(firmware)
        order = [t for t, _ in sorted(fw.read_dir(firmware).items(), key=lambda kv: kv[1][1][3])]
        scan = Scanner([(t, imgs[t]) for t in order])
        rows, bad = [], 0
        for (bid, stem), p in sorted(patches.items()):
            if bid != base["id"]:
                continue
            found = []
            pieces = published_pieces(p)
            prose = open(os.path.join(p["folder"], "README.md")).read()
            pieces += [("README.md#%d" % k, b) for k, b in enumerate(hex_in_prose(prose))]
            for label, data in pieces:
                for (i, n, name, so) in scan.runs(data):
                    triv = is_fill(data[i:i + n])
                    rows.append(dict(fix=stem, piece=label, offset=i, length=n, image=name, stock_offset=so, trivial=triv))
                    if not triv:
                        found.append((label, i, n, name, so))
            if found:
                bad += 1
                label, i, n, name, so = max(found, key=lambda f: f[2])
                fail(errors, "%s: %d run(s) of stock bytes, %d B in all (longest %d B at %s+0x%x = %s +0x%x)" % (
                    stem, len(found), sum(f[2] for f in found), n, label, i, name, so))
        say("stock-bytes scan vs %s: %d patches with runs >= %d B; %d fill runs allowed"
            % (base["id"], bad, MIN_RUN, sum(r["trivial"] for r in rows)))
        if json_out:
            json.dump(dict(min=MIN_RUN, rows=sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))),
                      open(json_out, "w"), indent=0, sort_keys=True)
        for n, doc in sorted(builds.items()):
            if doc["base"] != base["id"]:
                continue
            _d, b, ps = fw.read_build(os.path.join(root, "builds", n), root)
            try:
                out = fw.apply(firmware, b, ps)
            except fw.PatchError as e:
                fail(errors, "builds/%s: %s" % (n, e))
                continue
            ok = fw.sha(out) == doc["result"]["sha256"] and len(out) == doc["result"]["bytes"]
            say("build %s: %s (%s)" % (n, "reproduced byte for byte" if ok else "DIFFERS", fw.sha(out)[:16]))
            if not ok:
                fail(errors, "builds/%s: result sha256 %s, expected %s" % (n, fw.sha(out), doc["result"]["sha256"]))
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", help="a stock firmware file named by a base: scan it and reproduce its builds")
    ap.add_argument("--json", help="with --stock: every run found, as JSON")
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    o = ap.parse_args()
    errors = run(o.root, o.stock, o.json)
    for e in errors:
        print("FAIL " + e)
    print("%s: %d problem(s)" % ("FAIL" if errors else "PASS", len(errors)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
