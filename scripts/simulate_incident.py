"""SIMULATED corruption of one prefix (no encryption, no keys, no local file access).

Every object under the prefix is overwritten via remote S3 put_object with pre-generated
nonsense bytes, tagged demo-status=corrupted, a static ransom note is dropped, and noncurrent
versions under the prefix are purged. Nothing is read from or written to the local disk.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

from common import RANSOM_NOTE_KEY, Ctx, base_parser, iso, list_current, log, purge_versions, utcnow

NOTE = (
    "*** SIMULATED INCIDENT - DEMO ONLY ***\n"
    "The files in this prefix have been overwritten with corrupted data as part of a demonstration.\n"
    "No real encryption took place and no real ransom is requested.\n"
)


def main() -> None:
    p = base_parser("Simulate corruption of a prefix (demo only).", destructive=True)
    p.add_argument("--prefix", default="finance/")
    p.add_argument("--workers", type=int, default=64)
    ctx = Ctx(a := p.parse_args())
    ctx.check_tags(ctx.data_bucket)
    prefix = a.prefix if a.prefix.endswith("/") else a.prefix + "/"
    note_key = prefix + RANSOM_NOTE_KEY
    garble = os.urandom(2048)  # one canned nonsense payload, built once and reused

    keys = [k for k, _ in list_current(ctx.s3, ctx.data_bucket, prefix) if k != note_key]
    log.info("Simulated corruption of %d objects under s3://%s/%s", len(keys), ctx.data_bucket, prefix)
    start = utcnow()

    def corrupt(key: str) -> None:
        ctx.s3.put_object(Bucket=ctx.data_bucket, Key=key, Body=garble, Metadata={"demo-status": "corrupted"})

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(tqdm(ex.map(corrupt, keys), total=len(keys), unit="obj", desc="corrupting"))

    ctx.s3.put_object(Bucket=ctx.data_bucket, Key=note_key, Body=NOTE.encode(), ContentType="text/plain",
                      Metadata={"demo-status": "corrupted"})
    purged = purge_versions(ctx.s3, ctx.data_bucket, prefix, noncurrent_only=True)
    end = utcnow()
    log.info("Purged %d noncurrent versions. Simulated incident finished.", purged)
    ctx.write_result("incident.json", {
        "prefix": prefix, "objects_corrupted": len(keys), "noncurrent_versions_purged": purged,
        "incident_start": iso(start), "incident_end": iso(end),
        "last_clean_point_in_time": iso(start),
        "note": "Pick a Clumio point in time at or before incident_start.",
    })


if __name__ == "__main__":
    main()
