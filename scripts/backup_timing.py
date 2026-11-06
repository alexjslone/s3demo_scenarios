#!/usr/bin/env python3
"""
backup_timing.py: capture and compare backup timing, AWS Backup vs Clumio.

Drop into scripts/ of s3demo_scenarios. Standalone: needs only boto3.

Commands
  aws      Start an on demand AWS Backup job for the data bucket, poll it,
           and record timings. (Replaces or supplements run_backup.py.)
  aws-job  Record timings for an AWS Backup job that already ran (by job id).
  clumio   Record Clumio backup start/end times read from the Clumio UI.
  report   Merge the recorded results into a markdown table.

Examples (PowerShell)
  py scripts\\backup_timing.py aws --demo-id rep1 --env-dir envs\\sandbox
  py scripts\\backup_timing.py clumio --demo-id rep1 `
      --start "2026-11-05 15:40" --end "2026-11-05 15:52" `
      --prefixes finance/,customers/ --manifest manifests\\rep1-baseline.csv
  py scripts\\backup_timing.py report --demo-id rep1

Notes on accuracy
  * AWS Backup's describe_backup_job has no "running since" field. Queue time
    vs run time is derived from polling, so it is accurate to the poll interval.
  * Compare first (full baseline) backup to first backup. Scope differs: AWS
    Backup covers the whole bucket, Clumio only the protected prefixes.
  * Naive timestamps (no timezone) are treated as local machine time.
"""
import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
TERMINAL = {"COMPLETED", "FAILED", "ABORTED", "EXPIRED", "PARTIAL"}


# ---------- helpers ----------

def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(value):
    """Parse an ISO-ish timestamp. Naive values are treated as local time."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()  # attach local tz
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def secs(a, b):
    return round((b - a).total_seconds(), 1) if a and b else None


def fmt_dur(s):
    if s is None:
        return "n/a"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m}m {sec}s" if h else f"{m}m {sec}s"


def throughput(objects, size_bytes, run_seconds):
    if not run_seconds or run_seconds <= 0:
        return None, None
    opm = round(objects / (run_seconds / 60), 1) if objects else None
    mbpm = round((size_bytes / 1_048_576) / (run_seconds / 60), 1) if size_bytes else None
    return opm, mbpm


def out_path(demo_id, tool):
    RESULTS_DIR.mkdir(exist_ok=True)
    return RESULTS_DIR / f"{demo_id}-backup-{tool}.json"


def terraform_outputs(env_dir, demo_id=None):
    """Prefer the cache written by `demo.ps1 up`; fall back to terraform output."""
    cache = ROOT / ".state" / f"{demo_id}.outputs.json" if demo_id else None
    if cache and cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8-sig"))  # tolerate BOM
    else:
        res = subprocess.run(
            ["terraform", f"-chdir={env_dir}", "output", "-json"],
            capture_output=True, text=True, check=True,
        )
        raw = json.loads(res.stdout)
    return {k: v["value"] if isinstance(v, dict) and "value" in v else v for k, v in raw.items()}


def manifest_totals(manifest, prefixes=None):
    """Return (object_count, total_bytes) from baseline manifest CSV.
    Columns expected: key,size,sha256,version_id. Optional prefix filter."""
    if not manifest:
        return None, None
    count = total = 0
    with open(manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["key"]
            if prefixes and not any(key.startswith(p) for p in prefixes):
                continue
            count += 1
            total += int(row["size"])
    return count, total


# ---------- AWS Backup ----------

def aws_collect(client, job_id, first_running_seen=None, submitted=None):
    j = client.describe_backup_job(BackupJobId=job_id)
    created = j.get("CreationDate")
    completed = j.get("CompletionDate")
    size = j.get("BackupSizeInBytes") or 0
    return {
        "tool": "aws_backup",
        "job_id": job_id,
        "state": j["State"],
        "status_message": j.get("StatusMessage"),
        "recovery_point_arn": j.get("RecoveryPointArn"),
        "backup_size_bytes": size,
        "bytes_transferred": j.get("BytesTransferred"),
        "created_utc": iso(created),
        "first_running_seen_utc": iso(first_running_seen),
        "completed_utc": iso(completed),
        "queue_seconds_approx": secs(created, first_running_seen),
        "run_seconds_approx": secs(first_running_seen, completed),
        "total_seconds": secs(created, completed),
        "submitted_by_script_utc": iso(submitted),
    }


def cmd_aws(args):
    import boto3  # imported late so report/clumio work without boto3

    tf = terraform_outputs(args.env_dir, args.demo_id) if not (args.vault and args.role_arn and args.bucket_arn) else {}
    vault = args.vault or tf["backup_vault_name"]
    role = args.role_arn or tf["backup_role_arn"]
    bucket_arn = args.bucket_arn or tf["data_bucket_arn"]
    region = args.region or tf.get("region")
    client = boto3.Session(profile_name=args.profile, region_name=region).client("backup")

    submitted = now_utc()
    job = client.start_backup_job(
        BackupVaultName=vault, ResourceArn=bucket_arn, IamRoleArn=role
    )
    job_id = job["BackupJobId"]
    print(f"Started AWS Backup job {job_id}")

    first_running = None
    while True:
        state = client.describe_backup_job(BackupJobId=job_id)["State"]
        if state == "RUNNING" and first_running is None:
            first_running = now_utc()
            print(f"  RUNNING observed (queued {secs(submitted, first_running)}s)")
        if state in TERMINAL:
            break
        print(f"  state={state}")
        time.sleep(args.poll)

    result = aws_collect(client, job_id, first_running, submitted)
    count, _ = manifest_totals(args.manifest)
    result["objects"] = count
    result["scope"] = "whole bucket"
    opm, mbpm = throughput(count, result["backup_size_bytes"], result["run_seconds_approx"] or result["total_seconds"])
    result["objects_per_min"], result["mb_per_min"] = opm, mbpm
    result["captured_utc"] = iso(now_utc())
    out_path(args.demo_id, "aws").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if result["state"] != "COMPLETED":
        sys.exit(f"Backup ended in state {result['state']}: {result['status_message']}")


def cmd_aws_job(args):
    import boto3

    client = boto3.Session(profile_name=args.profile, region_name=args.region).client("backup")
    result = aws_collect(client, args.job_id)
    result["scope"] = "whole bucket"
    result["objects"], _ = manifest_totals(args.manifest)
    result["note"] = "Collected after the fact; queue and run split unavailable."
    opm, mbpm = throughput(result["objects"], result["backup_size_bytes"], result["total_seconds"])
    result["objects_per_min"], result["mb_per_min"] = opm, mbpm
    result["captured_utc"] = iso(now_utc())
    out_path(args.demo_id, "aws").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


# ---------- Clumio (manual capture from UI) ----------

def cmd_clumio(args):
    start, end = parse_ts(args.start), parse_ts(args.end)
    if end <= start:
        sys.exit("--end must be after --start")
    prefixes = [p.strip() for p in args.prefixes.split(",")] if args.prefixes else None
    count, size = manifest_totals(args.manifest, prefixes)
    if args.objects is not None:
        count = args.objects
    if args.bytes is not None:
        size = args.bytes
    run = secs(start, end)
    opm, mbpm = throughput(count, size, run)
    result = {
        "tool": "clumio",
        "source": "Clumio UI (manual entry)",
        "started_utc": iso(start),
        "completed_utc": iso(end),
        "total_seconds": run,
        "run_seconds_approx": run,
        "scope": ", ".join(prefixes) if prefixes else "as configured",
        "objects": count,
        "backup_size_bytes": size,
        "objects_per_min": opm,
        "mb_per_min": mbpm,
        "evidence": args.evidence,
        "captured_utc": iso(now_utc()),
    }
    out_path(args.demo_id, "clumio").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


# ---------- report ----------

def cmd_report(args):
    rows = []
    for tool, label in (("aws", "AWS Backup"), ("clumio", "Clumio")):
        p = out_path(args.demo_id, tool)
        if p.exists():
            rows.append((label, json.loads(p.read_text())))
    if not rows:
        sys.exit("No timing results found. Run the aws and clumio commands first.")

    lines = [
        f"# Backup timing: {args.demo_id}",
        "",
        "| Method | Scope | Objects | Size (GB) | Queue | Run | Total | Objects/min | MB/min | State |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, r in rows:
        size_gb = round((r.get("backup_size_bytes") or 0) / 1_073_741_824, 2)
        lines.append(
            f"| {label} | {r.get('scope', '')} | {r.get('objects') or 'n/a'} | {size_gb} | "
            f"{fmt_dur(r.get('queue_seconds_approx'))} | {fmt_dur(r.get('run_seconds_approx'))} | "
            f"{fmt_dur(r.get('total_seconds'))} | {r.get('objects_per_min') or 'n/a'} | "
            f"{r.get('mb_per_min') or 'n/a'} | {r.get('state', 'recorded')} |"
        )
    lines += [
        "",
        "Evidence",
        "",
    ]
    for label, r in rows:
        if label == "AWS Backup":
            lines.append(f"* AWS Backup job {r.get('job_id')}, recovery point {r.get('recovery_point_arn')}, "
                         f"created {r.get('created_utc')}, completed {r.get('completed_utc')} (UTC).")
        else:
            lines.append(f"* Clumio started {r.get('started_utc')}, completed {r.get('completed_utc')} (UTC), "
                         f"read from the Clumio UI. Evidence: {r.get('evidence') or 'add a screenshot reference'}.")
    lines += [
        "",
        "Caveats: first (full) backups compared. Scope differs between products. "
        "AWS queue and run split is derived from polling, accurate to the poll interval. "
        "Clumio times were entered manually from the UI.",
    ]
    md = "\n".join(lines) + "\n"
    path = RESULTS_DIR / f"{args.demo_id}-backup-timing.md"
    RESULTS_DIR.mkdir(exist_ok=True)
    path.write_text(md, encoding="utf-8")
    print(md)
    print(f"Wrote {path}")


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("aws")
    a.add_argument("--demo-id", required=True)
    a.add_argument("--env-dir", default=str(ROOT / "envs" / "sandbox"))
    a.add_argument("--vault"); a.add_argument("--role-arn"); a.add_argument("--bucket-arn")
    a.add_argument("--region")
    a.add_argument("--manifest", help="baseline manifest CSV for object counts")
    a.add_argument("--poll", type=int, default=5)
    a.add_argument("--profile", help="AWS CLI/SSO profile")
    a.set_defaults(fn=cmd_aws)

    j = sub.add_parser("aws-job")
    j.add_argument("--demo-id", required=True); j.add_argument("--job-id", required=True)
    j.add_argument("--region"); j.add_argument("--manifest"); j.add_argument("--profile")
    j.set_defaults(fn=cmd_aws_job)

    c = sub.add_parser("clumio")
    c.add_argument("--demo-id", required=True)
    c.add_argument("--start", required=True, help="ISO time from Clumio UI, e.g. 2026-11-05T15:40:00-05:00")
    c.add_argument("--end", required=True)
    c.add_argument("--prefixes", help="comma separated, e.g. finance/,customers/")
    c.add_argument("--manifest"); c.add_argument("--objects", type=int); c.add_argument("--bytes", type=int)
    c.add_argument("--evidence", help="screenshot filename or note")
    c.add_argument("--profile", help=argparse.SUPPRESS)  # accepted for demo.ps1 uniformity
    c.set_defaults(fn=cmd_clumio)

    r = sub.add_parser("report")
    r.add_argument("--demo-id", required=True)
    r.add_argument("--profile", help=argparse.SUPPRESS)
    r.set_defaults(fn=cmd_report)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
