# Clumio UI checklist (manual; not automated)

The AWS sandbox account is already connected to Clumio. Do these in the Clumio console.

1. Confirm the account connection is healthy and the new bucket `s3demo-<demo_id>-data` appears in
   inventory (rescan if needed).
2. Create a protection group with prefix filters `finance/` and `customers/`, add the data bucket, and
   assign a policy with frequency and retention comparable to the AWS Backup plan (daily, 7 days).
3. Wait for the first Clumio backup to complete **before** running the incident.
4. Capture the first backup timing (run after step 3, ideally started alongside the AWS Backup job):
   * Open the backup/activity view for the protection group, note the first backup's start and end
     time (with timezone) and take a screenshot of it, e.g. `results/<demo_id>-clumio-backup.png`.
   * Record it: `.\demo.ps1 backup-timing -DemoId <id> -TimingAction clumio -ClumioStart "<start>" -ClumioEnd "<end>" -Evidence clumio-backup.png`
     (prefer ISO with offset, e.g. `2026-11-05T15:40:00-05:00`; naive times are read as local machine time).
   * Run the AWS side with `-TimingAction aws`, then `-TimingAction report` to write
     `results/<demo_id>-backup-timing.md`.
5. During the demo:
   * Global Search for `RANSOM_NOTE.txt` to find the blast radius and the last clean point in time
     (`results/<demo_id>-incident.json` has `last_clean_point_in_time`).
   * Choose a point in time at or before that, recover `finance/` (Backtrack in place if enabled,
     otherwise a prefix restore).
   * Note the start and end times (UTC) for `report`.
   * Afterwards run `.\demo.ps1 verify -DemoId <id> -Label clumio` (the leftover ransom note, if any,
     is reported as "extra" and does not fail the check).
