#!/usr/bin/env python3
"""Write index.json: every published file's path, size and sha256 (SPEC.md
"Index"). A client fetches index.json first, then only the files whose sha256
it doesn't already hold, and checks each against it.

    python3 tools/make_index.py            # write it
    python3 tools/make_index.py --check    # exit 1 if it isn't current
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLISHED = ("bases", "builds", "catalog", "patches", "schema")
FORMAT = 3


def files(root=ROOT):
    out = []
    for top in PUBLISHED:
        for d, _dirs, names in os.walk(os.path.join(root, top)):
            for n in names:
                path = os.path.join(d, n)
                data = open(path, "rb").read()
                out.append({"path": os.path.relpath(path, root).replace(os.sep, "/"),
                            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return sorted(out, key=lambda f: f["path"])


def build(root=ROOT):
    return {"format": FORMAT, "files": files(root)}


def text(root=ROOT):
    return json.dumps(build(root), indent=1) + "\n"


def stale(root=ROOT):
    """None if index.json is current, else what differs."""
    path = os.path.join(root, "index.json")
    if not os.path.exists(path):
        return "missing"
    have = json.load(open(path))
    want = build(root)
    if have == want:
        return None
    a = {f["path"]: f["sha256"] for f in have.get("files", [])}
    b = {f["path"]: f["sha256"] for f in want["files"]}
    diff = sorted(set(a) ^ set(b)) + sorted(p for p in set(a) & set(b) if a[p] != b[p])
    return ", ".join(diff[:5]) + (" ..." if len(diff) > 5 else "")


if __name__ == "__main__":
    if "--check" in sys.argv:
        s = stale(sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else ROOT)
        print("index.json: %s" % (s or "current"))
        sys.exit(1 if s else 0)
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else ROOT
    open(os.path.join(root, "index.json"), "w").write(text(root))
    print("index.json: %d files" % len(build(root)["files"]))
