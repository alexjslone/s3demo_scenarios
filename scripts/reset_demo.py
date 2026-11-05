"""Reset finance/ to the clean deterministic baseline and empty the recovery buckets."""
from __future__ import annotations

import datagen
from common import RANSOM_NOTE_KEY, Ctx, base_parser, load_manifest, log, purge_versions, save_manifest
from seed_dataset import seed_prefix


def empty_bucket(ctx: Ctx, bucket: str) -> int:
    ctx.check_tags(bucket)
    return purge_versions(ctx.s3, bucket, "", noncurrent_only=False)


def main() -> None:
    p = base_parser("Reset the scenario without destroying the stack.", destructive=True)
    p.add_argument("--dataset-profile", default="lite")
    p.add_argument("--prefix-dataset", default="finance")
    p.add_argument("--workers", type=int, default=64)
    ctx = Ctx(a := p.parse_args())
    ctx.check_tags(ctx.data_bucket)
    prof = datagen.load_profile(a.dataset_profile)
    ds = prof["datasets"][a.prefix_dataset]

    n = purge_versions(ctx.s3, ctx.data_bucket, ds["prefix"] + RANSOM_NOTE_KEY, noncurrent_only=False)
    log.info("Removed ransom note versions: %d", n)
    manifest = load_manifest(ctx.manifest_path)
    seed_prefix(ctx, prof["seed"], ds, a.workers, True, manifest)  # force overwrite of damaged objects
    purged = purge_versions(ctx.s3, ctx.data_bucket, ds["prefix"], noncurrent_only=True)
    log.info("Purged %d old/corrupted noncurrent versions under %s", purged, ds["prefix"])
    save_manifest(ctx.manifest_path, manifest)
    for b in (ctx.prefix_bucket, ctx.full_bucket):
        log.info("Emptied %s (%d versions)", b, empty_bucket(ctx, b))
    for stale in ("incident.json", "restore-in-place.json", "restore-prefix.json", "restore-full.json",
                  "copyback-prefix.json", "copyback-full.json"):
        pth = ctx.result_path(stale)
        if pth.exists():
            pth.rename(pth.with_suffix(pth.suffix + ".bak"))
    log.info("Reset done. Consider `demo.ps1 backup` for a fresh recovery point; old post-incident log objects remain.")


if __name__ == "__main__":
    main()
