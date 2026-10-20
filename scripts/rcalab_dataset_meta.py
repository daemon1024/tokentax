"""Finish one rca-lab capture as a dataset entry: meta.json, SHA256SUMS, backup, manifest.

    .venv/bin/python scripts/rcalab_dataset_meta.py data/rcalab/<name> [--no-backup] [--no-latency]
                                                    [--legacy-note "..."] [--fault-bounds S,E]

Reads what the capture driver (`infra/rcalab_capture_dataset.sh`) left in the directory:
meta_raw.json (window bounds, host clock), cluster/*.json (kubectl/docker snapshots), logs + traces.
Older captures (sc-04/sc-06 short format, the sc-10 copies) have no meta_raw.json; their original
meta.json is preserved as meta_raw.json and everything that was not recorded at the time is "unknown".

Nothing here is estimated: a field this script cannot determine from a file is written as "unknown".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tokentax import rcalab_dataset as D  # noqa: E402

MANIFEST = ROOT / "results/datasets/rcalab_manifest.json"
BACKUP_ROOT = Path.home() / "tokentax-backup/rcalab"
HOST_COLLECTOR_CONFIG = ROOT / "infra/rcalab-capture-collector.yaml"
U = "unknown"

# Lab-wide facts of THIS deployment (Phase A of the session that built it), not per capture.
LAB_CONFIG = {
    "deploy_command": "make deploy SINGLE_NODE=1 SEED_SIZE_GB=0 YES=1 (rca-lab @ 585c45a)",
    "single_node": True, "seed_size_gb": 0,
    "app_replicas_scaled_to_1": "kubectl scale deploy -l part-of=rca-lab --replicas=1 (node was at 95% CPU / "
                                "86% memory requests at 2 replicas)",
    "arm64_local_builds": "published images are linux/amd64 only; every rca-lab image was built locally "
                          "for arm64 and side-loaded with `kind load`",
    "chaos_mesh_override": "chaosDaemon.socketPath=/run/containerd/containerd.sock (lab values point at k3s)",
    "telemetry_path": "app SDKs -> in-cluster otel-collector (memory_limiter 400 MiB, batch) -> host "
                      "collector file exporter (infra/rcalab-capture-collector.yaml)",
    "known_export_gaps": "api-gateway (Python, uvicorn --workers 4) exports traces but no log records; "
                         "cart-, review-, recommendation-service and product-catalog do not log request-path "
                         "errors (results/RCA_LAB_CAPTURE.md, source-verified)",
}


def sha(p: Path) -> str:
    return D.sha256_file(p)


def jload(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def bounds_of(raw: dict, override: tuple[int, int] | None) -> dict:
    def pair(a, b):
        s, e = raw.get(a), raw.get(b)
        return (int(s), int(e)) if isinstance(s, int) and isinstance(e, int) else None
    b = {"baseline": pair("baseline_start_ns", "baseline_end_ns"),
         "fault": pair("fault_start_ns", "fault_end_ns"),
         "recovery": pair("recovery_start_ns", "recovery_end_ns")}
    if override:
        b["fault"] = override
    return b


def cluster_block(d: Path) -> dict:
    c = d / "cluster"
    if not c.exists():
        return {"snapshot": U}
    nodes = jload(c / "nodes.json") or {}
    ver = jload(c / "version.json") or {}
    wl = jload(c / "baseline_end_workloads.json") or {}
    pods = jload(c / "baseline_end_pods.json") or {}
    replicas = {f"{i['kind']}/{i['metadata']['name']}": {"spec": i["spec"].get("replicas"),
                                                         "ready": (i.get("status") or {}).get("readyReplicas")}
                for i in wl.get("items", [])}
    images: dict[str, dict] = {}
    for p in pods.get("items", []):
        for cs in (p.get("status") or {}).get("containerStatuses", []) or []:
            img = cs.get("image", U)
            e = images.setdefault(img, {"node_image_id": cs.get("imageID", U), "pods": []})
            e["pods"].append(f"{p['metadata']['namespace']}/{p['metadata']['name']}")
    for img, e in images.items():   # local docker digest, when the image exists on the host
        r = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", img],
                           capture_output=True, text=True)
        e["host_docker_image_id"] = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else U
        e["pods"] = sorted(e["pods"])[:6]
    app = {k: v for k, v in replicas.items() if k.startswith("Deployment/")}
    excluded = sorted(k.split("/", 1)[1] for k, v in app.items() if not v["spec"])
    return {
        "node_count": len(nodes.get("items", [])) or U,
        "kubernetes_version": (ver.get("serverVersion") or {}).get("gitVersion", U),
        "replicas_default_ns": replicas,
        "images": images,
        "excluded_services": excluded,
        **LAB_CONFIG,
    }


def collector_block(d: Path) -> dict:
    c = d / "cluster"
    host = (jload(c / "host_collector_container.json") or [{}])[0] if (c / "host_collector_container.json").exists() else {}
    labcm = jload(c / "lab_collector_configmap.json") or {}
    lab_cfg = json.dumps(labcm.get("data", {}), sort_keys=True) if labcm else ""
    img = (host.get("Config") or {}).get("Image", U)
    return {
        "host_collector_image": img,
        "host_collector_version": img.rsplit(":", 1)[-1] if ":" in img else U,
        "host_collector_image_id": host.get("Image", U),
        "host_collector_config": str(HOST_COLLECTOR_CONFIG.relative_to(ROOT)),
        "host_collector_config_sha256": sha(HOST_COLLECTOR_CONFIG) if HOST_COLLECTOR_CONFIG.exists() else U,
        "lab_collector_config_sha256": hashlib.sha256(lab_cfg.encode()).hexdigest() if lab_cfg else U,
        "lab_collector_config": labcm.get("data", U) if labcm else U,
    }


def loadgen_block(d: Path) -> dict:
    lg = jload(d / "cluster/load_generator.json")
    if not lg:
        return {"settings": U}
    ctr = lg["spec"]["template"]["spec"]["containers"][0]
    return {"image": ctr.get("image", U), "replicas": lg["spec"].get("replicas", U),
            "env": {e["name"]: e.get("value", "(from ref)") for e in ctr.get("env", []) or []},
            "args": ctr.get("args", []), "command": ctr.get("command", []),
            "resources": ctr.get("resources", {})}


def scenario_block(d: Path, scenario: str) -> dict:
    cr = jload(d / "cluster/maintenancejob.json")
    if scenario == "healthy":
        return {"id": "healthy", "cr_spec": None, "mechanism": "no scenario enabled", "expectedSymptoms": []}
    if not cr:
        return {"id": scenario, "cr_spec": U, "mechanism": U, "expectedSymptoms": U}
    s = cr.get("spec", {})
    return {"id": scenario, "cr_spec": s, "displayName": s.get("displayName", U),
            "mechanism": " ".join(str(s.get("description", U)).split()),
            "expectedSymptoms": s.get("expectedSymptoms", U)}


def effect_block(d: Path, raw: dict) -> dict:
    c = d / "cluster"
    return {"verified": raw.get("effect_verified_ns") is not None if "effect_verified_ns" in raw else U,
            "verified_ns": raw.get("effect_verified_ns", U),
            "present_at_end": raw.get("effect_present_at_end", U),
            "fault_ended_by": raw.get("fault_ended_by", U),
            "controller_line": raw.get("controller_line", U),
            "evidence_first": jload(c / "fault_effect_first.json"),
            "evidence_mid": jload(c / "fault_mid_effect.json"),
            "evidence_end": jload(c / "fault_effect_end.json"),
            "evidence_after_recovery": jload(c / "recovery_end_effect.json")}


def write_sums(d: Path) -> dict:
    sums = {}
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            sums[str(p.relative_to(d))] = sha(p)
    (d / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()))
    return sums


def backup(d: Path, name: str) -> str:
    dst = BACKUP_ROOT / name
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(d, dst)
    r = subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=dst, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"backup checksum FAILED for {dst}:\n{r.stdout}{r.stderr}")
    return str(dst)


def update_manifest(entry: dict) -> None:
    """Replace this capture's entry. Locked: the campaign and a manual run may finish at the same time."""
    import fcntl
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data/rcalab/.manifest.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        m = jload(MANIFEST) or {"dataset": "rcalab", "doc": "results/datasets/RCALAB_DATASET.md", "captures": []}
        m["captures"] = [e for e in m["captures"] if e["name"] != entry["name"]] + [entry]
        m["captures"].sort(key=lambda e: e["name"])
        m["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, indent=1) + "\n")
        tmp.replace(MANIFEST)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--no-latency", action="store_true", help="skip per-window root-span latency (multi-day files)")
    ap.add_argument("--compact", action="store_true", help="64-bit-prefix distinct trace counting (multi-day)")
    ap.add_argument("--legacy-note", default="")
    ap.add_argument("--fault-bounds", default="", help="S,E unix ns, for captures whose bounds were derived")
    ap.add_argument("--scenario", default="")
    ap.add_argument("--effect-verified", choices=("true", "false", "unknown"), default="")
    a = ap.parse_args()
    d = (ROOT / a.dir) if not Path(a.dir).is_absolute() else Path(a.dir)
    name = d.name
    rel = str(d.relative_to(ROOT))

    skipped = jload(d / "SKIPPED.json")
    if skipped:
        update_manifest({"name": name, "scenario": skipped.get("scenario", name), "path": rel,
                         "status": "skipped", "reason": skipped.get("reason", U)})
        print(f"{name}: skipped -> manifest")
        return 0

    raw_p = d / "meta_raw.json"
    if not raw_p.exists():          # legacy: keep the original file untouched under a new name
        shutil.copy2(d / "meta.json", raw_p)
    raw = jload(raw_p) or {}
    scenario = a.scenario or raw.get("scenario", name)
    override = tuple(int(x) for x in a.fault_bounds.split(",")) if a.fault_bounds else None
    bounds = bounds_of(raw, override)

    logs = D.find_file(d, "logs")
    traces = D.find_file(d, "traces")
    t0 = time.time()
    lc = D.count_logs(logs, bounds) if logs else U
    sc = D.count_spans(traces, bounds, latency=not a.no_latency, compact=a.compact) if traces else U
    print(f"{name}: counted in {time.time() - t0:.0f}s")

    gt = D.truth_for(scenario, "fault")
    eff = effect_block(d, raw)
    if a.effect_verified:
        eff["verified"] = {"true": True, "false": False, "unknown": U}[a.effect_verified]
    if scenario == "healthy":
        eff["verified"] = "n/a (no scenario enabled)"
    meta = {
        "name": name, "scenario": scenario_block(d, scenario),
        "format": raw.get("format", "legacy"),
        "legacy_note": a.legacy_note or None,
        "ground_truth": gt,
        "windows_unix_ns": {k: (list(v) if v else U) for k, v in bounds.items()},
        "window_seconds": {k: (round((v[1] - v[0]) / 1e9, 1) if v else U) for k, v in bounds.items()},
        "clock": "host wall clock (time.time_ns) at each driver step; records carry the cluster's "
                 "timeUnixNano (same Docker VM clock)",
        "effect": eff,
        "cluster": cluster_block(d), "collector": collector_block(d), "load_generator": loadgen_block(d),
        "files": {"logs": logs.name if logs else U, "traces": traces.name if traces else U,
                  "compression": ("zstd -T8 -6" if logs and logs.suffix == ".zst" else
                                  "gzip -6 (traces), logs uncompressed" if traces and traces.suffix == ".gz"
                                  else "none"),
                  "raw_bytes": raw.get("raw_bytes", U)},
        "counts": {"logs": lc, "spans": sc},
        "raw_driver_meta": raw,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    sums = write_sums(d)
    bk = U if a.no_backup else backup(d, name)

    def brief(k):
        L = lc.get(k) if isinstance(lc, dict) else None
        S = sc.get(k) if isinstance(sc, dict) else None
        if not L and not S:
            return None
        return {"log_records": L and L["log_records"], "error_records": L and L["error_records"],
                "records_with_trace_id": L and L["records_with_trace_id"],
                "spans": S and S["spans"], "traces": S and S["traces"],
                "error_bearing_traces": S and S["error_bearing_traces"],
                "root_span_ms_p99": S and S.get("root_span_ms_p99")}

    update_manifest({
        "name": name, "scenario": scenario, "path": rel, "status": "ok", "format": meta["format"],
        "files": {"logs": logs.name if logs else None, "traces": traces.name if traces else None},
        "sha256": {k: v for k, v in sums.items() if not k.startswith("cluster/")},
        "windows": {k: (list(v) if v else None) for k, v in bounds.items()},
        "culprit_service": gt["culprit_service"], "culprit_component": gt["culprit_component"],
        "fault_class": gt["fault_class"], "effect_verified": eff["verified"],
        "counts": {k: brief(k) for k in ("all", "baseline", "fault", "recovery") if brief(k)},
        "backup": bk, "legacy_note": a.legacy_note or None,
    })
    print(f"{name}: meta.json, SHA256SUMS ({len(sums)} files), backup={bk}, manifest updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
