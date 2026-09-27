"""Generate a variant of main.py with module-level constants overridden.

    python tools/mkvariant.py variants/nopace.py SELL_PACED=False
    python tools/mkvariant.py variants/pace2.py SELL_PACE=2.0 SELL_PRICE_KEEP=0.4

Rewrites the first assignment of each named constant, so the variant stays a
single self-contained file that bench.py can load directly.
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

SRC = "main.py"


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    dest = sys.argv[1]
    overrides = {}
    for arg in sys.argv[2:]:
        if "=" not in arg:
            sys.exit(f"expected NAME=VALUE, got {arg!r}")
        k, v = arg.split("=", 1)
        overrides[k.strip()] = v.strip()

    with open(SRC, encoding="utf-8") as f:
        lines = f.readlines()

    applied = set()
    for i, line in enumerate(lines):
        for name, val in overrides.items():
            if name in applied:
                continue
            m = re.match(rf"^({re.escape(name)}\s*=\s*)([^#\n]*)(#.*)?$", line)
            if m:
                comment = m.group(3) or ""
                lines[i] = f"{m.group(1)}{val}{('  ' + comment) if comment else ''}\n"
                applied.add(name)

    missing = set(overrides) - applied
    if missing:
        sys.exit(f"constants not found in {SRC}: {', '.join(sorted(missing))}")

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"wrote {dest}  ({', '.join(f'{k}={v}' for k, v in overrides.items())})")


if __name__ == "__main__":
    main()
