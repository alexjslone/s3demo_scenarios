"""Compare a prefix in a bucket against the baseline manifest by sha256 (or size with --quick)."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

from botocore.exceptions import ClientError
from tqdm import tqdm

from common import RANSOM_NOTE_KEY, Ctx, base_parser, iso, list_current, load_manifest, log, utcnow


def main() -> None:
    p = base_parser("Verify data integrity against the baseline manifest.")
    p.add_argument("--bucket", help="Default: the data bucket (use a recovery bucket name to check restores)")
    p.add_argument("--prefix", default="finance/")
    p.add_argument("--label", default="adhoc", help="aws-inplace | aws-prefix | aws-full | clumio | adhoc")
    p.add_argument("--quick", action="store_true", help="Size-only check (no download). Weaker: not for final proof.")
    p.add_argument("--workers", type=int, default=64)
    p.add_argument("--strict", action="store_true", help="Also fail on extra objects (e.g. leftover ransom note)")
    ctx = Ctx(a := p.parse_args())
    bucket = a.bucket or ctx.data_bucket
    ctx.check_tags(bucket)
    base = {k: r for k, r in load_manifest(ctx.manifest_path).items() if k.startswith(a.prefix)}
    if not base:
        raise SystemExit(f"No baseline rows for prefix {a.prefix} in {ctx.manifest_path}")
    present = dict(list_current(ctx.s3, bucket, a.prefix))
    missing = [k for k in base if k not in present]
    extra = [k for k in present if k not in base]

    def check(key: str) -> str:
        row = base[key]
        if present[key] != int(row["size"]):
            return "corrupted"
        if a.quick:
            return "ok"
        h = hashlib.sha256()
        body = ctx.s3.get_object(Bucket=bucket, Key=key)["Body"]
        for chunk in iter(lambda: body.read(1024 * 1024), b""):
            h.update(chunk)
        return "ok" if h.hexdigest() == row["sha256"] else "corrupted"

    todo = [k for k in base if k in present]
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(tqdm(ex.map(check, todo), total=len(todo), unit="obj", desc="verifying"))
    matched = sum(r == "ok" for r in results)
    corrupted = len(results) - matched

    post_total = post_missing = 0
    post = ctx.read_result("post-incident.json")
    if post:
        for o in post["objects"]:
            post_total += 1
            try:
                ctx.s3.head_object(Bucket=ctx.data_bucket, Key=o["key"])
            except ClientError:
                post_missing += 1

    ok = not missing and not corrupted and not post_missing and not (a.strict and extra)
    print(f"\nbucket={bucket} prefix={a.prefix} mode={'quick' if a.quick else 'sha256'}")
    print(f"  matched   : {matched}/{len(base)}")
    print(f"  missing   : {len(missing)}")
    print(f"  corrupted : {corrupted}")
    print(f"  extra     : {len(extra)}" + (f" (includes {RANSOM_NOTE_KEY})" if any(k.endswith(RANSOM_NOTE_KEY) for k in extra) else ""))
    if post:
        print(f"  post-incident app-logs intact: {post_total - post_missing}/{post_total}")
    print("RESULT:", "PASS" if ok else "FAIL")
    ctx.write_result(f"verify-{a.label}.json", {
        "label": a.label, "bucket": bucket, "prefix": a.prefix, "checked_at": iso(utcnow()), "quick": a.quick,
        "matched": matched, "expected": len(base), "missing": len(missing), "corrupted": corrupted,
        "extra": len(extra), "post_incident_total": post_total, "post_incident_missing": post_missing, "pass": ok})
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
