"""Seed the data bucket with the deterministic dataset and write the baseline manifest."""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

from tqdm import tqdm

import datagen
from common import Ctx, base_parser, load_manifest, log, save_manifest


def list_versions(s3, bucket: str, prefix: str) -> dict[str, tuple[int, str]]:
    cur = {}
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
        for v in page.get("Versions", []):
            if v["IsLatest"]:
                cur[v["Key"]] = (v["Size"], v["VersionId"])
    return cur


def seed_prefix(ctx: Ctx, seed: int, ds: dict, workers: int, force: bool, manifest: dict) -> tuple[int, int]:
    """Upload one dataset. Returns (objects, bytes). Updates `manifest` in place."""
    existing = {} if force else list_versions(ctx.s3, ctx.data_bucket, ds["prefix"])

    def work(i: int):
        key, size = datagen.key_and_size(seed, ds, i)
        have = existing.get(key)
        if have and (size is None or have[0] == size):
            row = manifest.get(key)
            if row and int(row["size"]) == have[0] and row["version_id"] == have[1]:
                return row
            _, body = datagen.make_body(seed, ds, i)  # need sha for manifest
            if len(body) == have[0] or size is None:
                return {"key": key, "size": have[0], "sha256": hashlib.sha256(body).hexdigest(), "version_id": have[1]}
        _, body = datagen.make_body(seed, ds, i)
        resp = ctx.s3.put_object(Bucket=ctx.data_bucket, Key=key, Body=body, Metadata={"demo-status": "clean"})
        return {"key": key, "size": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "version_id": resp.get("VersionId", "")}

    total_bytes = 0
    chunk = workers * 50
    with ThreadPoolExecutor(max_workers=workers) as ex, tqdm(total=ds["count"], desc=ds["prefix"], unit="obj") as bar:
        for start in range(0, ds["count"], chunk):
            for row in ex.map(work, range(start, min(start + chunk, ds["count"]))):
                manifest[row["key"]] = row
                total_bytes += int(row["size"])
                bar.update(1)
    return ds["count"], total_bytes


def estimate(profile: dict, selected: list[str]) -> None:
    objs = sum(profile["datasets"][n]["count"] for n in selected)
    gb = sum(profile["datasets"][n]["count"] * (profile["datasets"][n]["min_size"] + profile["datasets"][n]["max_size"]) / 2
             for n in selected) / 1e9
    put_cost = objs / 1000 * 0.005
    log.info("Estimate: ~%d objects, ~%.1f GB. PUT cost ~$%.2f, S3 Standard ~$%.2f/month, "
             "AWS Backup warm storage ~$%.2f/month per retained copy (rough, us-east-1 list prices).",
             objs, gb, put_cost, gb * 0.023, gb * 0.05)


def main() -> None:
    p = base_parser("Seed the demo data bucket (deterministic, resumable).")
    p.add_argument("--dataset-profile", default="lite", help="lite | full | path to JSON")
    p.add_argument("--only", nargs="*", help="Dataset names to seed (default: all)")
    p.add_argument("--workers", type=int, default=64)
    ctx = Ctx(a := p.parse_args())
    ctx.check_tags(ctx.data_bucket)
    prof = datagen.load_profile(a.dataset_profile)
    selected = a.only or list(prof["datasets"])
    estimate(prof, selected)
    manifest = load_manifest(ctx.manifest_path)
    for n in selected:
        objs, size = seed_prefix(ctx, prof["seed"], prof["datasets"][n], a.workers, False, manifest)
        log.info("%s: %d objects, %.2f GB", n, objs, size / 1e9)
        save_manifest(ctx.manifest_path, manifest)  # checkpoint after each dataset
    log.info("Manifest: %s (%d rows). Seeded profile=%s", ctx.manifest_path, len(manifest), prof["name"])
    ctx.write_result("seed.json", {"dataset_profile": prof["name"], "datasets": selected,
                                   "objects": len(manifest), "bytes": sum(int(r["size"]) for r in manifest.values())})


if __name__ == "__main__":
    main()
