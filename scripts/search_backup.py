"""Search indexed AWS Backup recovery points of the data bucket (AWS Backup Search).

Examples:
  search_backup.py --demo-id x --prefix finance/            # every indexed object under finance/
  search_backup.py --demo-id x --contains RANSOM_NOTE.txt   # which recovery points contain the note
Prints per-recovery-point match counts and the elapsed time (record it for the comparison), and writes
results/<demo_id>-search-<label>.json. Recovery points must have IndexStatus ACTIVE to be searched.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter

from common import Ctx, base_parser, fmt_dur, iso, log, utcnow

TERMINAL = {"COMPLETED", "STOPPED", "FAILED"}


def main() -> None:
    p = base_parser("Search indexed S3 backups.")
    p.add_argument("--prefix", help="Object key BEGINS_WITH this value")
    p.add_argument("--contains", help="Object key CONTAINS this value (e.g. RANSOM_NOTE.txt)")
    p.add_argument("--label", default="adhoc")
    p.add_argument("--max-results", type=int, default=100000)
    p.add_argument("--show", type=int, default=10, help="Sample result rows to print")
    p.add_argument("--poll", type=int, default=5)
    p.add_argument("--timeout-min", type=int, default=60)
    ctx = Ctx(a := p.parse_args())
    if not (a.prefix or a.contains):
        raise SystemExit("Give --prefix and/or --contains.")
    arn = ctx.out["data_bucket_arn"]
    bs = ctx.session.client("backupsearch")

    # Recovery points and their index state (so empty results are not mistaken for "clean").
    rps = []
    for page in ctx.backup.get_paginator("list_recovery_points_by_resource").paginate(ResourceArn=arn):
        rps += page["RecoveryPoints"]
    rps.sort(key=lambda r: r["CreationDate"])
    for r in rps:
        log.info("recovery point %s created %s index=%s", r["RecoveryPointArn"].split(":")[-1],
                 iso(r["CreationDate"]), r.get("IndexStatus", "n/a"))
    if not any(r.get("IndexStatus") == "ACTIVE" for r in rps):
        raise SystemExit("No ACTIVE index on any recovery point. Run enable_index.py, then take a backup "
                         "(run_backup.py requests an index) and wait for IndexStatus ACTIVE.")

    filters = []
    if a.prefix:
        filters.append({"Value": a.prefix, "Operator": "BEGINS_WITH"})
    if a.contains:
        filters.append({"Value": a.contains, "Operator": "CONTAINS"})
    start = utcnow()
    job = bs.start_search_job(
        Name=f"s3demo-{a.demo_id}-{a.label}"[:128],
        SearchScope={"BackupResourceTypes": ["S3"], "SourceResourceArns": [arn]},
        ItemFilters={"S3ItemFilters": [{"ObjectKeys": filters}]},
        ClientToken=str(uuid.uuid4()),
    )
    job_id = job["SearchJobIdentifier"]
    log.info("Started search job %s", job_id)
    deadline = time.time() + a.timeout_min * 60
    while True:
        d = bs.get_search_job(SearchJobIdentifier=job_id)
        st = d["Status"]
        log.info("status=%s scanned=%s matched=%s", st, d.get("ItemsScanned"), d.get("ItemsMatched"))
        if st in TERMINAL:
            break
        if time.time() > deadline:
            raise SystemExit("Timed out waiting for search job.")
        time.sleep(a.poll)
    elapsed = (utcnow() - start).total_seconds()
    if st != "COMPLETED":
        raise SystemExit(f"Search job ended {st}: {d.get('StatusMessage')}")

    items, token = [], None
    while len(items) < a.max_results:
        kw = {"SearchJobIdentifier": job_id, "MaxResults": 1000}
        if token:
            kw["NextToken"] = token
        r = bs.list_search_job_results(**kw)
        items += [x["S3ResultItem"] for x in r.get("Results", []) if "S3ResultItem" in x]
        token = r.get("NextToken")
        if not token:
            break
    per_rp = Counter(i.get("BackupResourceArn") for i in items)
    print(f"\nSearch finished in {fmt_dur(elapsed)}: {len(items)} matches (scanned {d.get('ItemsScanned')}).")
    print("Recovery points (oldest first):")
    for r in rps:
        n = per_rp.get(r["RecoveryPointArn"], 0)
        tag = ""
        if a.contains:
            tag = "  <-- CONTAINS match (affected)" if n else "  clean for this search"
        print(f"  {iso(r['CreationDate'])}  index={r.get('IndexStatus', 'n/a'):8}  matches={n}{tag}")
    for i in items[: a.show]:
        print(f"  {i.get('ObjectKey')}  {i.get('ObjectSize')} B  v={i.get('VersionId')}")
    ctx.write_result(f"search-{a.label}.json", {
        "prefix": a.prefix, "contains": a.contains, "search_job_id": job_id, "elapsed_s": elapsed,
        "items_scanned": d.get("ItemsScanned"), "items_matched": len(items),
        "matches_per_recovery_point": dict(per_rp),
        "recovery_points": [{"arn": r["RecoveryPointArn"], "created": iso(r["CreationDate"]),
                             "index_status": r.get("IndexStatus")} for r in rps],
    })


if __name__ == "__main__":
    main()
