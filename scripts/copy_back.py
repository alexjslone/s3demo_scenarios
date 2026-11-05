"""Copy a restored prefix from a recovery bucket back over the damaged prefix (server-side copy), timed."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

from common import Ctx, base_parser, fmt_dur, iso, list_current, log, utcnow


def main() -> None:
    p = base_parser("Copy restored data back into the data bucket.", destructive=True)
    p.add_argument("--source", required=True, choices=["prefix", "full"], help="Which recovery bucket")
    p.add_argument("--prefix", default="finance/")
    p.add_argument("--workers", type=int, default=64)
    ctx = Ctx(a := p.parse_args())
    src = ctx.prefix_bucket if a.source == "prefix" else ctx.full_bucket
    ctx.check_tags(src)
    ctx.check_tags(ctx.data_bucket)
    keys = [(k, s) for k, s in list_current(ctx.s3, src, a.prefix)]
    if not keys:
        raise SystemExit(f"Nothing under s3://{src}/{a.prefix}. Run the restore first.")
    log.info("Copying %d objects s3://%s/%s -> s3://%s", len(keys), src, a.prefix, ctx.data_bucket)
    start = utcnow()

    def cp(item):
        k, _ = item
        ctx.s3.copy_object(Bucket=ctx.data_bucket, Key=k, CopySource={"Bucket": src, "Key": k})

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(tqdm(ex.map(cp, keys), total=len(keys), unit="obj", desc="copy back"))
    end = utcnow()
    res = {"source": a.source, "prefix": a.prefix, "objects": len(keys), "bytes": sum(s for _, s in keys),
           "start": iso(start), "end": iso(end), "duration_s": (end - start).total_seconds()}
    ctx.write_result(f"copyback-{a.source}.json", res)
    log.info("Copy back finished in %s", fmt_dur(res["duration_s"]))


if __name__ == "__main__":
    main()
