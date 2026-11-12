# Clumio setup (Terraform) and UI checks

The AWS sandbox account is already connected to Clumio. The protection group, policy and assignment are
created by Terraform (`envs/clumio`); the console is only used to confirm, search and restore.

1. Set credentials (personal API token + the API base URL for your portal region, see README) and create the
   Clumio objects after `demo.ps1 up`:
   ```powershell
   $env:CLUMIO_API_TOKEN    = "<token>"
   $env:CLUMIO_API_BASE_URL = "https://us-east-1.api.clumio.com"
   .\demo.ps1 clumio-up -DemoId <id>
   ```
   This creates protection group `s3demo-<id>-no-logs` (whole bucket except `app-logs/`, matched by the
   bucket's `DemoId` tag) and policy `s3demo-<id>-continuous` (daily backup + 15 minute continuous backup, 31 days).
2. Confirm in the Clumio console: the bucket `s3demo-<id>-data` appears in inventory (rescan if needed), is a member of
   the protection group, and its Continuous backup shows Enabled. Track what Terraform owns with
   `.\demo.ps1 clumio-status -DemoId <id>`.
3. Wait for the first Clumio backup to complete **before** running the incident.
4. Capture the first backup timing (run after step 3, ideally started alongside the AWS Backup job):
   * Open the backup/activity view for the protection group, note the first backup's start and end
     time (with timezone) and take a screenshot of it, e.g. `results/<demo_id>-clumio-backup.png`.
   * Record it: `.\demo.ps1 backup-timing -DemoId <id> -TimingAction clumio -ClumioStart "<start>" -ClumioEnd "<end>" -Evidence clumio-backup.png`
     (prefer ISO with offset, e.g. `2026-11-05T15:40:00-05:00`; naive times are read as local machine time).
     `-TimingPrefixes` defaults to `finance/,customers/,media/` (everything Clumio protects); change it if you
     change `excluded_prefixes` in `envs/clumio`.
   * Run the AWS side with `-TimingAction aws`, then `-TimingAction report` to write
     `results/<demo_id>-backup-timing.md`.
5. Show the difference vs AWS Backup: in a Clumio restore, `app-logs/` is not available to restore (excluded);
   the AWS Backup recovery point for the same bucket contains it.
6. During the demo:
   * Global Search for `RANSOM_NOTE.txt` to find the blast radius and the last clean point in time
     (`results/<demo_id>-incident.json` has `last_clean_point_in_time`).
   * Choose a point in time at or before that, recover `finance/` (Backtrack in place if enabled,
     otherwise a prefix restore).
   * Note the start and end times (UTC) for `report`.
   * Afterwards run `.\demo.ps1 verify -DemoId <id> -Label clumio` (the leftover ransom note, if any,
     is reported as "extra" and does not fail the check).
7. Cleanup: `.\demo.ps1 clumio-down -DemoId <id> -Confirm` removes the Clumio objects only; `demo.ps1 down`
   does this automatically before destroying the AWS stack.
