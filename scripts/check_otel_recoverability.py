"""Is the OTel Demo dataset log-recoverable? (the Nezha-analog check)

For the captured windows, verify the fault is recoverable from logs: anomalous windows carry an
ERROR log at the ORIGIN service (product-catalog) that normal windows lack, and the culprit is
distinguishable. This is the check Nezha failed (culprit silent in 26/38 windows).
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax.otel_loader import windows_from_manifest  # noqa: E402

LOGS = ROOT / "data/otel_demo/logs.jsonl"
MANIFEST = ROOT / "data/otel_demo/manifest.json"
ORIGIN = {"productCatalogFailure": "product-catalog", "paymentFailure": "payment",
          "cartFailure": "cart", "adFailure": "ad"}


def main() -> None:
    windows = windows_from_manifest(LOGS, MANIFEST)
    print(f"{len(windows)} windows")
    by_label: dict[str, list] = {}
    for w in windows:
        by_label.setdefault(w.label, []).append(w)

    for label, ws in sorted(by_label.items()):
        print(f"\n[{label}] ({len(ws)} windows)")
        for w in ws:
            errs = [r for r in w.records if r.is_error]
            err_svcs = Counter(r.pod for r in errs)
            origin = ORIGIN.get(w.fault or "", "?")
            origin_errs = err_svcs.get(origin, 0)
            traces = {r.trace_id for r in w.records if r.trace_id}
            err_traces = {r.trace_id for r in errs if r.trace_id}
            print(f"  recs={len(w.records):5d} traces={len(traces):4d} errors={len(errs):3d} "
                  f"err_svcs={dict(err_svcs.most_common(3))} "
                  f"origin({origin})_errs={origin_errs} err_traces={len(err_traces)}")

    # verdict: does the origin error appear in anomalous but not normal?
    print("\n=== RECOVERABILITY VERDICT ===")
    for fault, origin in ORIGIN.items():
        anom = [w for w in windows if w.fault == fault]
        norm = [w for w in windows if w.label == "normal"]
        if not anom:
            continue
        a_origin = sum(1 for w in anom if any(r.is_error and r.pod == origin for r in w.records))
        n_origin = sum(1 for w in norm if any(r.is_error and r.pod == origin for r in w.records))
        ok = a_origin == len(anom) and n_origin == 0
        print(f"  {fault}: origin '{origin}' emits ERROR in {a_origin}/{len(anom)} anomalous, "
              f"{n_origin}/{len(norm)} normal -> {'RECOVERABLE ✓' if ok else 'check'}")


if __name__ == "__main__":
    main()
