"""Flag-driven capture loop for the OTel Demo.

Toggles flagd faults and records labeled time-windows over the continuously-growing
data/otel_demo/logs.jsonl. Window = a [start_ns, end_ns] slice; label = the active fault (or normal).
Writes data/otel_demo/manifest.json. Slice + label later with otel_loader.windows_from_manifest.

Prereq: the demo is up with the capture overlay, and patched services are rebuilt for the faults used.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLAGD = ROOT / "otel-demo-src/src/flagd/demo.flagd.json"
MANIFEST = ROOT / "data/otel_demo/manifest.json"

OLJ = "OLJCESPC7Z"  # the product productCatalogFailure targets


def _set_flag(flags: dict, name: str, on: bool) -> None:
    """Enable/disable a fault, handling per-flag mechanics (targeting vs defaultVariant)."""
    f = flags[name]
    if name == "productCatalogFailure":
        f["targeting"] = {"if": [{"==": [{"var": "product_id"}, OLJ]}, "on" if on else "off", "off"]}
    elif name == "paymentFailure":
        f["defaultVariant"] = "100%" if on else "off"
    elif name in ("cartFailure", "adFailure", "kafkaQueueProblems", "recommendationCacheFailure"):
        f["defaultVariant"] = "on" if on else "off"
    else:
        f["defaultVariant"] = "on" if on else "off"


def _write_flags(setter) -> None:
    d = json.loads(FLAGD.read_text())
    setter(d["flags"])
    FLAGD.write_text(json.dumps(d, indent=2))


def _all_off(flags: dict, faults: list[str]) -> None:
    for name in faults:
        _set_flag(flags, name, False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faults", nargs="*", default=["productCatalogFailure"])
    ap.add_argument("--windows", type=int, default=3, help="windows per class")
    ap.add_argument("--window-sec", type=int, default=45)
    ap.add_argument("--warmup-sec", type=int, default=25)
    args = ap.parse_args()

    manifest: list[dict] = []

    def capture_class(label: str, fault: str | None) -> None:
        print(f"[{label}] enabling…")
        _write_flags(lambda flags: (_all_off(flags, args.faults),
                                    _set_flag(flags, fault, True) if fault else None))
        time.sleep(args.warmup_sec)  # flagd hot-reload + load warm-up
        for i in range(args.windows):
            start = time.time_ns()
            time.sleep(args.window_sec)
            end = time.time_ns()
            manifest.append({"label": label, "fault": fault, "start_ns": start, "end_ns": end})
            print(f"  window {i + 1}/{args.windows} [{start}..{end}]")

    # normal baseline first
    capture_class("normal", None)
    for fault in args.faults:
        capture_class("anomalous", fault)

    # leave everything off
    _write_flags(lambda flags: _all_off(flags, args.faults))
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote {MANIFEST.relative_to(ROOT)} with {len(manifest)} windows "
          f"({len({m['label'] for m in manifest})} classes, faults={args.faults})")


if __name__ == "__main__":
    main()
