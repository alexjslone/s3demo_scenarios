# s3-demo-scenarios: Scenario 2 (S3 prefix recovery), AWS side

Terraform + Python for the AWS half of the demo: a multi-prefix versioned bucket, whole-bucket AWS Backup,
a **simulated** corruption of `finance/`, three AWS Backup restore paths, integrity proof and a timing
report. The Clumio protection group and continuous backup policy are created, tracked and deleted with
Terraform (`envs/clumio`, driven by `demo.ps1 clumio-up|clumio-status|clumio-down`). Search and restore
are still done in the Clumio UI (`runbooks/clumio-ui-setup.md`).

Assumes an existing sandbox AWS account already connected to Clumio. Everything is scoped by `demo_id`
(names + tags `Project=s3-demo`, `Scenario=scenario-2`, `DemoId`, `Owner`, `ExpiresOn`), so many stacks coexist.

## Prerequisites (Windows / PowerShell)
Terraform >= 1.10, Python 3.11+, AWS CLI v2, Git, and an AWS CLI/SSO profile (`aws sso login --profile <p>`).

```powershell
py -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r scripts\requirements.txt
```

Inputs (in `envs/sandbox/tfvars/<demo_id>.tfvars`, see `example.tfvars`): `region` (same as Clumio connection),
`state_bucket` + `state_region` (EXISTING bucket; use `bootstrap/` only if none exists), `owner`, `expires_on`,
optional `backup_role_arn` (else a per-stack role is created; `shared/` only if stacks should share one role).
Missing values fail fast. Also ensure no SCP/policy blocks `backup:DeleteRecoveryPoint`
(`demo.ps1 check -Deep` verifies this for real).

## Clumio via Terraform
`envs/clumio` builds, per `demo_id`: a Clumio **protection group** that finds `s3demo-<demo_id>-data` by its
`DemoId` tag and **excludes** `app-logs/` (AWS Backup cannot exclude a prefix), a **policy** with a daily
backup plus 15 minute **continuous backup** (31 day retention; Clumio requires 30 to 999 for a daily backup), and the **policy assignment**. It has its own
state (`scenario-2/<demo_id>-clumio.tfstate`, same state bucket), so removing it never touches the bucket or AWS Backup.

Prerequisites: a personal API token (Clumio portal, Access management, API tokens) and the API base URL for your
portal region (`west.portal.clumio.com` = `https://us-west-2.api.clumio.com`, `east.portal.clumio.com` =
`https://us-east-1.api.clumio.com`, `canada` = `https://ca-central-1.ca.api.clumio.com`,
`eu1` = `https://eu-central-1.de.api.clumio.com`, `au` = `https://ap-southeast-2.au.api.clumio.com`).
The token only works against the region it was created in. Never commit it.

```powershell
$env:CLUMIO_API_TOKEN    = "<token>"
$env:CLUMIO_API_BASE_URL = "https://us-east-1.api.clumio.com"
.\demo.ps1 clumio-up     -DemoId jsmith01            # create (run after `up`)
.\demo.ps1 clumio-status -DemoId jsmith01            # track: resources + ids in Terraform state
.\demo.ps1 clumio-down   -DemoId jsmith01 -Confirm   # delete the protection group, policy and assignment
```

Tuning (variables in `envs/clumio/variables.tf`): `excluded_prefixes` (default `["app-logs/"]`), `storage_classes`,
`retention_days`, `continuous_rpo_minutes`. Change a default, then run `clumio-up` again; Terraform shows what changes.
`demo.ps1 down` removes the Clumio resources first, so Clumio is never left pointing at a deleted bucket. The nightly
cleanup workflow only expires AWS stacks; run `clumio-down` for stacks it removed.
Teardown only removes the Clumio objects Terraform created; check in Clumio whether existing backups are retained after
the protection group is deleted before relying on delete-and-redo between runs.

## Quick start
```powershell
$env:AWS_PROFILE = "my-sandbox"
.\demo.ps1 up       -DemoId jsmith01
.\demo.ps1 seed     -DemoId jsmith01 -DatasetProfile lite     # or full (205,000 objects)
.\demo.ps1 clumio-up -DemoId jsmith01                         # needs CLUMIO_API_TOKEN / CLUMIO_API_BASE_URL
.\demo.ps1 backup   -DemoId jsmith01
.\demo.ps1 verify   -DemoId jsmith01 -Label baseline
.\demo.ps1 incident -DemoId jsmith01 -Confirm
.\demo.ps1 post     -DemoId jsmith01
.\demo.ps1 restore  -DemoId jsmith01 -Mode prefix
.\demo.ps1 copyback -DemoId jsmith01 -Source prefix -Confirm
.\demo.ps1 verify   -DemoId jsmith01 -Label aws-prefix
.\demo.ps1 report   -DemoId jsmith01 -ClumioStart 2026-11-05T17:10:00Z -ClumioEnd 2026-11-05T17:14:30Z
.\demo.ps1 reset    -DemoId jsmith01 -Confirm                 # rerun without destroying
.\demo.ps1 down     -DemoId jsmith01 -Confirm                 # removes Clumio resources, deletes recovery points, then destroys
```

`-AwsProfile` is the AWS profile; `-DatasetProfile` is `lite`/`full` (`profiles/*.json`). In the Python scripts
`--profile` is the AWS profile and `--dataset-profile` the dataset size.

## Layout
`envs/sandbox` (root stack, S3 backend with native lockfile, key `scenario-2/<demo_id>.tfstate`),
`envs/clumio` (Clumio protection group + policy, key `scenario-2/<demo_id>-clumio.tfstate`),
`modules/{demo-bucket,aws-backup-s3,recovery-buckets}`, `scripts/`, `profiles/`, `runbooks/`, `results/`, `manifests/`,
optional `bootstrap/` and `shared/`, `.github/workflows` (manual `demo` + nightly expiry cleanup via OIDC; needs
secret `AWS_ROLE_ARN` and vars `AWS_REGION`, `STATE_BUCKET`, `STATE_REGION`).

## Design notes
* Backup vault is a standard vault: no Vault Lock, not air gapped, no deny policy, so the demo is repeatable and teardown works.
* Terraform builds infrastructure only; Python loads data (deterministic, seeded, resumable, baseline manifest in `manifests/`).
* Destructive scripts refuse unless the bucket has `Project=s3-demo` + matching `DemoId` and `--confirm` is given.
* The incident is simulated corruption via remote `put_object` only (no crypto, no local file access). If endpoint security
  still flags activity, work with your security team to allowlist the sandbox/tool rather than evading detection.
* `verify_integrity` downloads every object for sha256 comparison; `--quick` is a size-only shortcut for rehearsals.
* Restore metadata keys (notably the multi-version key `VERSIONS_KEY` in `time_restore.py`) should be rechecked against the
  current AWS Backup "Restore S3 data" docs; `--extra-metadata key=value` is the escape hatch. For continuous recovery
  points, pass `--restore-time`. `run_backup.py` records the on-demand recovery point, which restores use by default.
* The `logs` dataset is gzip; its bytes depend on the local zlib build, which is fine because manifests are generated at seed time.
