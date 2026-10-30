#!/usr/bin/env python3
"""Check every published JSON file against its schema (needs `jsonschema`;
CI installs it). Exit 1 on any mismatch.

    python3 tools/check_schemas.py [--root DIR]
"""
import glob
import json
import os
import sys

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else ROOT
    schema = {n: json.load(open(os.path.join(ROOT, "schema", n + ".schema.json")))
              for n in ("patch", "base", "build", "index", "catalog")}
    groups = [("patch", "patches/*/*/patch.json"), ("base", "bases/*.json"), ("build", "builds/*.json"),
              ("index", "index.json"), ("catalog", "catalog/*.json")]
    bad = n = 0
    for kind, pattern in groups:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            n += 1
            try:
                jsonschema.validate(json.load(open(path)), schema[kind])
            except jsonschema.ValidationError as e:
                bad += 1
                print("FAIL %s: %s" % (os.path.relpath(path, root), e.message))
    print("%s: %d files, %d against their schema failed" % ("FAIL" if bad else "PASS", n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
