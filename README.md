# s3-demo-scenarios: Scenario 2 (S3 prefix recovery), AWS side

Terraform + Python for the AWS half of the demo: a multi-prefix versioned bucket, whole-bucket AWS Backup,
a **simulated** corruption of `finance/`, three AWS Backup restore paths, integrity proof and a timing
report. The Clumio side (protection group, search, restore) is done in the Clumio UI
(`runbooks/clumio-ui-setup.md`); nothing here automates Clumio.

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

## Quick start
```powershell
$env:AWS_PROFILE = "my-sandbox"
.\demo.ps1 up       -DemoId jsmith01
.\demo.ps1 seed     -DemoId jsmith01 -DatasetProfile lite     # or full (205,000 objects)
.\demo.ps1 backup   -DemoId jsmith01
.\demo.ps1 verify   -DemoId jsmith01 -Label baseline
.\demo.ps1 incident -DemoId jsmith01 -Confirm
.\demo.ps1 post     -DemoId jsmith01
.\demo.ps1 restore  -DemoId jsmith01 -Mode prefix
.\demo.ps1 copyback -DemoId jsmith01 -Source prefix -Confirm
.\demo.ps1 verify   -DemoId jsmith01 -Label aws-prefix
.\demo.ps1 report   -DemoId jsmith01 -ClumioStart 2026-11-05T17:10:00Z -ClumioEnd 2026-11-05T17:14:30Z
.\demo.ps1 reset    -DemoId jsmith01 -Confirm                 # rerun without destroying
.\demo.ps1 down     -DemoId jsmith01 -Confirm                 # deletes recovery points, then destroys
```

`-AwsProfile` is the AWS profile; `-DatasetProfile` is `lite`/`full` (`profiles/*.json`). In the Python scripts
`--profile` is the AWS profile and `--dataset-profile` the dataset size.

## Layout
`envs/sandbox` (root stack, S3 backend with native lockfile, key `scenario-2/<demo_id>.tfstate`),
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
