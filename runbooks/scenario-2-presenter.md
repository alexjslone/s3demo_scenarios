# Scenario 2 presenter runbook: S3 prefix recovery

All commands: `.\demo.ps1 <cmd> -DemoId <id> [-AwsProfile <profile>]`.

## Terminology
The incident is a **simulated corruption**, not encryption. No keys or crypto are used: every object
under `finance/` is replaced with nonsense bytes by remote S3 API calls and tagged
`demo-status=corrupted`. Say "simulated corruption" to customers.

## Prep
| When | Steps |
|---|---|
| Day before | `up`, `seed -DatasetProfile full`, `backup`, `clumio-up`, confirm in the Clumio UI, first Clumio backup (`runbooks/clumio-ui-setup.md`) |
| Hours before | Full rehearsal incl. all three AWS Backup restore modes; `report` to record timings; `reset -Confirm` |
| Live | See below |
| After | `reset -Confirm` or `down -Confirm` |

Recheck the AWS Backup S3 restore docs before every customer run: behavior changes.

## Running the simulated incident
Pre-reqs: seeded, baseline `backup` completed with index `ACTIVE` (the script waits and prints it), baseline
`verify` PASS, and the first Clumio backup finished. The incident only needs the AWS profile and the demo bucket
(it refuses any bucket not tagged `Project=s3-demo` + matching `DemoId`).
```powershell
.\demo.ps1 search   -DemoId <id> -Prefix finance/ -Label before    # optional: AWS Backup search, healthy state
.\demo.ps1 incident -DemoId <id> -Confirm                          # overwrites finance/*, drops RANSOM_NOTE.txt, purges old versions
.\demo.ps1 post     -DemoId <id>                                   # legit app-logs/ writes after the incident
```
Evidence to capture: `results/<id>-incident.json` (`incident_start` = last clean point). In the console show
`finance/` objects tiny and unreadable, `RANSOM_NOTE.txt` present, and no older versions (versioning cannot help).
Optional AWS "scope the damage" step (a second recovery point containing the corrupted state):
```powershell
.\demo.ps1 backup -DemoId <id> -ResultName backup-post-incident.json   # NEVER omit -ResultName: restores read backup.json
.\demo.ps1 search -DemoId <id> -Contains RANSOM_NOTE.txt -Label scope  # which recovery points are affected
```
Say "simulated corruption" (see Terminology). `reset -Confirm` returns to baseline for a rerun.

## Live flow
1. Baseline: `verify -Label baseline` (PASS).
2. Incident: as above. Show `finance/` damaged, `RANSOM_NOTE.txt` present, old versions purged.
3. Clumio (UI): Global Search `RANSOM_NOTE.txt`, recover `finance/` only. Note UTC start/end.
   `verify -Label clumio` -> `finance/` PASS and post-incident app-logs intact.
4. AWS Backup in place: `restore -Mode in-place` completes but fixes nothing. Re-corrupt for the next steps
   with `incident -Confirm` if Clumio already repaired the data (or run AWS options first, Clumio last).
   `verify -Label aws-inplace` -> FAIL (still corrupted). This confirms restores are non-destructive.
5. AWS Backup honest options (pre-recorded timings are fine):
   * (b) `restore -Mode prefix -Prefix finance/` then `copyback -Source prefix -Confirm`, `verify -Label aws-prefix`.
     Requires knowing the exact prefix (up to 5 keys/prefixes per job). AWS Backup Search (indexed backups) can find
     it first, but it is a separate asynchronous job; time it with `search` and compare, do not assume.
   * (c) `restore -Mode full` then `copyback -Source full -Confirm`, `verify -Label aws-full`.
   * Variant: delete corrupted objects first, then restore in place (destroys evidence; manual).
6. `report -ClumioStart <ISO> -ClumioEnd <ISO>` -> `results/<id>-results.md`.

Order tip: recovery buckets must be empty for each `restore` of that mode; `reset -Confirm` empties them.

## Accuracy guardrails (talk track)
* AWS Backup protects the whole bucket (selection by bucket ARN/tag; no prefix filter). Do NOT claim it
  "can only restore the whole bucket": item-level restore of up to 5 keys/prefixes exists.
* AWS Backup can index S3 backups and search them (`search`): this needs the index enabled on the plan and on
  on-demand jobs (`index`, done by `up`), and only ACTIVE-indexed recovery points are searchable. Do NOT say AWS
  has no search. Compare workflow, time and cross-point-in-time visibility instead, using measured results.
* Restores never overwrite existing objects; a current-version delete marker counts as absent.
* Default restores the latest version per object; a restore parameter allows more versions.
* Source and destination buckets need versioning; restores land in S3 Standard.
* Every timing shown must come from this repo's measured results (date, region, object count, bytes).
