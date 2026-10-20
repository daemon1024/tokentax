#!/usr/bin/env python3
"""Is an rca-lab scenario's mechanism observably in place RIGHT NOW? Exit 0 = yes. Prints JSON evidence.

    python3 infra/rcalab_effect_check.py <scenario> [--context kind-rca-lab]

The checks are read from the scenario's own CR, action by action, so they follow the scenario rather
than a hand-kept list:

  Workload     the action's Job has >= 1 Running pod (`job-name=<workload.name>`)
  DeployImage  the target Deployment's container runs the action's image (>= 1 pod on it)
  ChaosMesh    >= one object of that chaos kind per action reports AllInjected=True
  Scale        the target Deployment is at the action's replica count, all ready
  DBExec       its Job exists (the statements ran); no stronger generic check exists
  CR           phase == Active  (the operator applied every action)

plus a mechanism check where the CR's own description names one:
  sc-04  information_schema.innodb_trx has a transaction holding row locks
  sc-06  pg_locks has a granted AccessExclusiveLock on products

A capture whose check never passes is still recorded, flagged effect_verified=false; the dataset loader
skips such captures by default (results/RCA_LAB_CAPTURE.md was retracted for exactly this mistake).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def kc(ctx: str, *args: str, ns: str | None = "default") -> str:
    cmd = ["kubectl", "--context", ctx] + (["-n", ns] if ns else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ""


def kj(ctx: str, *args: str, ns: str | None = "default") -> dict:
    out = kc(ctx, *args, "-o", "json", ns=ns)
    try:
        return json.loads(out) if out else {}
    except json.JSONDecodeError:
        return {}


def check(sc: str, ctx: str) -> tuple[bool, dict]:
    cr = kj(ctx, "get", "maintenancejob", sc)
    if not cr:
        return False, {"error": f"no MaintenanceJob {sc}"}
    ev: dict = {"phase": (cr.get("status") or {}).get("phase"), "actions": []}
    ok = ev["phase"] == "Active"
    for a in cr["spec"].get("actions", []):
        t = a["type"]
        item: dict = {"name": a.get("name"), "type": t}
        if t == "Workload":
            job = a["workload"]["name"]
            pods = kj(ctx, "get", "pods", "-l", f"job-name={job}").get("items", [])
            running = [p["metadata"]["name"] for p in pods if p["status"].get("phase") == "Running"]
            item.update(job=job, running_pods=running)
            item["ok"] = bool(running)
        elif t == "DeployImage":
            d = a["deployImage"]
            dep = kj(ctx, "get", "deploy", d["targetRef"]["name"])
            sel = ",".join(f"{k}={v}" for k, v in
                           (dep.get("spec", {}).get("selector", {}).get("matchLabels") or {}).items())
            pods = kj(ctx, "get", "pods", "-l", sel).get("items", []) if sel else []
            on_new = [p["metadata"]["name"] for p in pods
                      if any(c.get("image") == d["image"] for c in p["spec"]["containers"])]
            spec_imgs = [c.get("image") for c in dep.get("spec", {}).get("template", {}).get("spec", {})
                         .get("containers", [])]
            item.update(target=d["targetRef"]["name"], image=d["image"], spec_images=spec_imgs,
                        pods_on_image=on_new,
                        restarts={p["metadata"]["name"]: sum(cs.get("restartCount", 0) for cs in
                                                             p["status"].get("containerStatuses", []) or [])
                                  for p in pods})
            item["ok"] = d["image"] in spec_imgs and bool(on_new)
        elif t == "ChaosMesh":
            kind = a["chaosMesh"]["kind"].lower()
            objs = kj(ctx, "get", kind, "-A", ns=None).get("items", [])
            inj = [o["metadata"]["name"] for o in objs
                   if any(c.get("type") == "AllInjected" and c.get("status") == "True"
                          for c in (o.get("status") or {}).get("conditions", []) or [])]
            item.update(kind=kind, objects=[o["metadata"]["name"] for o in objs], all_injected=inj)
            item["ok"] = bool(inj)
        elif t == "Scale":
            s = a["scale"]
            dep = kj(ctx, "get", "deploy", s["targetRef"]["name"])
            want = int(s["replicas"])
            item.update(target=s["targetRef"]["name"], want=want,
                        spec=dep.get("spec", {}).get("replicas"),
                        ready=(dep.get("status") or {}).get("readyReplicas"))
            item["ok"] = item["spec"] == want and item["ready"] == want
        elif t == "DBExec":
            job = a["dbExec"].get("name", "")
            jobs = kj(ctx, "get", "jobs").get("items", [])
            hits = [j["metadata"]["name"] for j in jobs if job and j["metadata"]["name"].startswith(job)]
            item.update(job_prefix=job, jobs=hits)
            item["ok"] = bool(hits)
        else:
            item["ok"] = False
            item["note"] = f"unknown action type {t}"
        ev["actions"].append(item)
        ok = ok and item["ok"]

    if sc == "sc-04":
        q = ("select count(*) from information_schema.innodb_trx where trx_rows_locked>0 "
             "and trx_mysql_thread_id in (select id from information_schema.processlist "
             "where state='User sleep')")
        out = kc(ctx, "exec", "mysql-pxc-0", "-c", "pxc", "--", "sh", "-c",
                 f'mysql -uroot -p"$(cat /etc/mysql/mysql-users-secret/root)" -N -e "{q}" 2>/dev/null')
        n = int(out.strip()) if out.strip().isdigit() else 0
        ev["mechanism"] = {"stalled_lock_holders": n}
        ok = ok and n > 0
    if sc == "sc-06":
        pod = kc(ctx, "get", "pod", "-l", "postgres-operator.crunchydata.com/role in (master,primary)",
                 "-o", "name").split()
        q = ("select count(*) from pg_locks l join pg_class c on c.oid=l.relation where "
             "c.relname='products' and l.mode='AccessExclusiveLock' and l.granted")
        out = (kc(ctx, "exec", pod[0], "-c", "database", "--", "psql", "-d", "products", "-tAc", q)
               if pod else "")
        n = int(out.strip()) if out.strip().isdigit() else 0
        ev["mechanism"] = {"access_exclusive_on_products": n}
        ok = ok and n > 0
    return ok, ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--context", default="kind-rca-lab")
    a = ap.parse_args()
    ok, ev = check(a.scenario, a.context)
    ev["ok"] = ok
    print(json.dumps(ev))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
