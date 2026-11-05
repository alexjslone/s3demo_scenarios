"""Write legitimate app-logs/ objects AFTER the incident so recovery can be shown not to touch them."""
from __future__ import annotations

import gzip
import hashlib
import os

from common import Ctx, base_parser, iso, log, utcnow


def main() -> None:
    p = base_parser("Write post-incident app-logs objects.")
    p.add_argument("--count", type=int, default=300)
    ctx = Ctx(a := p.parse_args())
    ctx.check_tags(ctx.data_bucket)
    stamp = utcnow().strftime("%Y%m%dT%H%M%S")
    items = []
    for i in range(a.count):
        key = f"app-logs/post-incident/{stamp}-{i:05d}.log.gz"
        body = gzip.compress(f"post-incident log {i} {os.urandom(64).hex()}\n".encode() * 20, mtime=0)
        r = ctx.s3.put_object(Bucket=ctx.data_bucket, Key=key, Body=body, Metadata={"demo-status": "post-incident"})
        items.append({"key": key, "size": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                      "version_id": r.get("VersionId", "")})
    prev = (ctx.read_result("post-incident.json") or {}).get("objects", [])
    ctx.write_result("post-incident.json", {"written_at": iso(utcnow()), "objects": prev + items})
    log.info("Wrote %d post-incident objects", len(items))


if __name__ == "__main__":
    main()
