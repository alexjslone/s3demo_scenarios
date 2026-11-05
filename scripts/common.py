"""Shared helpers: terraform outputs, AWS session, tag safety check, manifests, results."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MANIFESTS = ROOT / "manifests"
STATE_CACHE = ROOT / ".state"
ENV_DIR = ROOT / "envs" / "sandbox"

RANSOM_NOTE_KEY = "RANSOM_NOTE.txt"
MANIFEST_FIELDS = ["key", "size", "sha256", "version_id"]

log = logging.getLogger("s3demo")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def base_parser(description: str, destructive: bool = False) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--demo-id", required=True, help="Stack id (lowercase, 3-12 chars)")
    p.add_argument("--profile", default=None, help="AWS CLI/SSO profile (default: AWS_PROFILE)")
    p.add_argument("-v", "--verbose", action="store_true")
    if destructive:
        p.add_argument("--confirm", action="store_true", help="Required: acknowledge this modifies data")
    return p


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


class Ctx:
    """Resolved stack context: outputs + boto3 clients."""

    def __init__(self, args: argparse.Namespace):
        setup_logging(getattr(args, "verbose", False))
        self.demo_id: str = args.demo_id
        if not (3 <= len(self.demo_id) <= 12 and self.demo_id.isalnum() and self.demo_id.islower()):
            sys.exit(f"demo-id '{self.demo_id}' invalid: lowercase letters/digits, 3-12 chars.")
        self.out = load_outputs(self.demo_id)
        self.region: str = self.out["region"]
        self.session = boto3.Session(profile_name=args.profile, region_name=self.region)
        cfg = Config(retries={"max_attempts": 10, "mode": "adaptive"}, max_pool_connections=128)
        self.s3 = self.session.client("s3", config=cfg)
        self.backup = self.session.client("backup", config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))
        self.data_bucket: str = self.out["data_bucket"]
        self.prefix_bucket: str = self.out["recovery_bucket_prefix"]
        self.full_bucket: str = self.out["recovery_bucket_full"]
        self.vault: str = self.out["vault_name"]
        self.role_arn: str = self.out["backup_role_arn"]
        if getattr(args, "confirm", None) is False:
            sys.exit("Refusing to run: this script modifies data. Re-run with --confirm.")

    def check_tags(self, bucket: str) -> None:
        assert_demo_bucket(self.s3, bucket, self.demo_id)

    def result_path(self, name: str) -> Path:
        RESULTS.mkdir(exist_ok=True)
        return RESULTS / f"{self.demo_id}-{name}"

    def write_result(self, name: str, data: dict) -> Path:
        p = self.result_path(name)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("Wrote %s", p)
        return p

    def read_result(self, name: str) -> dict | None:
        p = self.result_path(name)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    @property
    def manifest_path(self) -> Path:
        MANIFESTS.mkdir(exist_ok=True)
        return MANIFESTS / f"{self.demo_id}-baseline.csv"


def load_outputs(demo_id: str) -> dict:
    """Prefer cache written by demo.ps1 up; fall back to live `terraform output -json`."""
    cache = STATE_CACHE / f"{demo_id}.outputs.json"
    raw = None
    if cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8-sig"))  # tolerate BOM from Windows PowerShell
    else:
        try:
            res = subprocess.run(
                ["terraform", f"-chdir={ENV_DIR}", "output", "-json"],
                capture_output=True, text=True, check=True,
            )
            raw = json.loads(res.stdout)
        except (OSError, subprocess.CalledProcessError) as e:
            sys.exit(f"Cannot read outputs for demo_id '{demo_id}' (run `demo.ps1 up` first): {e}")
    out = {k: v["value"] if isinstance(v, dict) and "value" in v else v for k, v in raw.items()}
    if out.get("demo_id") != demo_id:
        sys.exit(f"Outputs belong to demo_id '{out.get('demo_id')}', not '{demo_id}'. Run `demo.ps1 up`.")
    return out


def assert_demo_bucket(s3, bucket: str, demo_id: str) -> None:
    """Refuse to touch any bucket that is not tagged Project=s3-demo and DemoId=<demo_id>."""
    try:
        tags = {t["Key"]: t["Value"] for t in s3.get_bucket_tagging(Bucket=bucket)["TagSet"]}
    except ClientError as e:
        sys.exit(f"Safety check failed: cannot read tags of bucket {bucket}: {e}")
    if tags.get("Project") != "s3-demo" or tags.get("DemoId") != demo_id:
        sys.exit(f"Safety check failed: bucket {bucket} is not tagged Project=s3-demo, DemoId={demo_id}.")


def load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f)}


def save_manifest(path: Path, rows: dict[str, dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for k in sorted(rows):
            w.writerow({f: rows[k][f] for f in MANIFEST_FIELDS})


def list_current(s3, bucket: str, prefix: str):
    """Yield (key, size) for current objects under prefix."""
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            yield o["Key"], o["Size"]


def purge_versions(s3, bucket: str, prefix: str, noncurrent_only: bool, skip_keys=()) -> int:
    """Delete object versions (and delete markers) under prefix. Returns count deleted."""
    batch, deleted = [], 0

    def flush():
        nonlocal batch, deleted
        if batch:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            deleted += len(batch)
            batch = []

    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
        for v in page.get("Versions", []) + page.get("DeleteMarkers", []):
            if v["Key"] in skip_keys:
                continue
            if noncurrent_only and v["IsLatest"]:
                continue
            batch.append({"Key": v["Key"], "VersionId": v["VersionId"]})
            if len(batch) >= 1000:
                flush()
    flush()
    return deleted


def fmt_dur(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h{(s % 3600) // 60:02d}m{s % 60:02d}s" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"
