<#
.SYNOPSIS
  Wrapper for the Scenario 2 S3 prefix recovery demo (AWS side).
.EXAMPLE
  .\demo.ps1 up      -DemoId jsmith01
  .\demo.ps1 seed    -DemoId jsmith01 -DatasetProfile lite
  .\demo.ps1 clumio-up     -DemoId jsmith01    # Clumio protection group + continuous backup policy (Terraform)
  .\demo.ps1 clumio-status -DemoId jsmith01    # what Terraform is tracking in Clumio
  .\demo.ps1 clumio-down   -DemoId jsmith01 -Confirm
  .\demo.ps1 restore -DemoId jsmith01 -Mode prefix
  .\demo.ps1 backup-timing -DemoId jsmith01 -TimingAction aws
  .\demo.ps1 backup-timing -DemoId jsmith01 -TimingAction clumio -ClumioStart '2026-11-05T15:40:00-05:00' -ClumioEnd '2026-11-05T15:52:00-05:00' -Evidence clumio-backup.png
  .\demo.ps1 backup-timing -DemoId jsmith01 -TimingAction report
  .\demo.ps1 report  -DemoId jsmith01 -ClumioStart 2026-11-05T17:10:00Z -ClumioEnd 2026-11-05T17:14:30Z
#>
param(
  [Parameter(Mandatory, Position = 0)]
  [ValidateSet('up', 'check', 'seed', 'backup', 'incident', 'post', 'restore', 'copyback', 'verify', 'report', 'backup-timing', 'reset', 'cleanup', 'down', 'clumio-up', 'clumio-status', 'clumio-down')]
  [string]$Command,
  [Parameter(Mandatory)][ValidatePattern('^[a-z0-9]{3,12}$')][string]$DemoId,
  [string]$AwsProfile,                       # AWS CLI / SSO profile (else AWS_PROFILE)
  [ValidateSet('lite', 'full')][string]$DatasetProfile = 'lite',
  [ValidateSet('in-place', 'prefix', 'full')][string]$Mode,
  [string]$Prefix = 'finance/',
  [string]$Label = 'adhoc',                  # verify: aws-inplace | aws-prefix | aws-full | clumio
  [ValidateSet('prefix', 'full')][string]$Source,   # copyback source bucket
  [string]$ClumioStart,
  [string]$ClumioEnd,
  [ValidateSet('aws', 'aws-job', 'clumio', 'report')][string]$TimingAction,  # backup-timing subcommand
  [string]$JobId,                            # backup-timing aws-job
  [string]$Evidence,                         # backup-timing clumio: screenshot filename or note
  # Prefixes Clumio protects. Default matches envs/clumio (everything except the excluded app-logs/).
  [string]$TimingPrefixes = 'finance/,customers/,media/',
  [switch]$Quick,
  [switch]$Deep,
  [switch]$Confirm
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$EnvDir = Join-Path $Root 'envs\sandbox'
$ClumioDir = Join-Path $Root 'envs\clumio'   # Clumio protection group + policy, own state, see README
$TfVars = Join-Path $EnvDir "tfvars\$DemoId.tfvars"
$StateDir = Join-Path $Root '.state'
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$Py = if (Test-Path $VenvPy) { $VenvPy } else { 'python' }
if ($AwsProfile) { $env:AWS_PROFILE = $AwsProfile }

function Get-TfVar([string]$Name) {
  $m = Select-String -Path $TfVars -Pattern "^\s*$Name\s*=\s*`"([^`"]*)`"" | Select-Object -First 1
  if ($m) { return $m.Matches[0].Groups[1].Value }
  return $null
}
function Require-Inputs {
  if (-not (Test-Path $TfVars)) { throw "Missing $TfVars. Copy envs\sandbox\tfvars\example.tfvars and fill it in." }
  foreach ($k in 'region', 'state_bucket', 'state_region', 'owner', 'expires_on') {
    if (-not (Get-TfVar $k)) { throw "tfvars is missing required value '$k'." }
  }
  if ((Get-TfVar 'demo_id') -ne $DemoId) { throw "demo_id in tfvars does not match -DemoId $DemoId." }
  if (-not $env:AWS_PROFILE -and -not $env:AWS_ACCESS_KEY_ID) { throw "Set AWS_PROFILE (or pass -AwsProfile). Keys are never hardcoded." }
}
function Tf-Init {
  terraform "-chdir=$EnvDir" init -reconfigure -input=false `
    "-backend-config=bucket=$(Get-TfVar 'state_bucket')" `
    "-backend-config=region=$(Get-TfVar 'state_region')" `
    "-backend-config=key=scenario-2/$DemoId.tfstate"
  if ($LASTEXITCODE) { throw 'terraform init failed' }
}
function Require-ClumioEnv {
  if (-not $env:CLUMIO_API_TOKEN -or -not $env:CLUMIO_API_BASE_URL) {
    throw 'Set CLUMIO_API_TOKEN and CLUMIO_API_BASE_URL first (see README, Clumio via Terraform). Tokens are never stored in the repo.'
  }
}
function Clumio-Init {
  terraform "-chdir=$ClumioDir" init -reconfigure -input=false `
    "-backend-config=bucket=$(Get-TfVar 'state_bucket')" `
    "-backend-config=region=$(Get-TfVar 'state_region')" `
    "-backend-config=key=scenario-2/$DemoId-clumio.tfstate"
  if ($LASTEXITCODE) { throw 'terraform init (clumio) failed' }
}
# Resources currently tracked in this demo's Clumio state (empty if the stack was never applied).
function Clumio-Resources {
  # Windows PowerShell 5.1 turns native stderr into a terminating error under 'Stop'; relax it here only.
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  $out = terraform "-chdir=$ClumioDir" state list 2>&1 | ForEach-Object { "$_" }
  $ErrorActionPreference = $prev
  if ($LASTEXITCODE) {
    if (($out -join ' ') -match 'No state file') { return @() }
    throw "terraform state list (clumio) failed: $($out -join ' ')"
  }
  return @($out | Where-Object { $_ })
}
function Clumio-Destroy {
  Require-ClumioEnv
  terraform "-chdir=$ClumioDir" destroy "-var=demo_id=$DemoId" -input=false -auto-approve
  if ($LASTEXITCODE) { throw 'terraform destroy (clumio) failed' }
  Remove-Item -ErrorAction SilentlyContinue (Join-Path $StateDir "$DemoId.clumio.outputs.json")
}
function Run-Py([string]$Script, [string[]]$ScriptArgs) {
  $a = @((Join-Path $Root "scripts\$Script"), '--demo-id', $DemoId) + $ScriptArgs
  if ($AwsProfile) { $a += @('--profile', $AwsProfile) }
  & $Py @a
  if ($LASTEXITCODE) { throw "$Script exited with code $LASTEXITCODE" }
}
function Need-Confirm { if (-not $Confirm) { throw "'$Command' modifies data. Re-run with -Confirm." } }
function ConfirmArg { if ($Confirm) { @('--confirm') } else { @() } }

switch ($Command) {
  'up' {
    Require-Inputs; Tf-Init
    terraform "-chdir=$EnvDir" apply "-var-file=$TfVars" -input=false -auto-approve
    if ($LASTEXITCODE) { throw 'terraform apply failed' }
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    $outJson = (terraform "-chdir=$EnvDir" output -json) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $StateDir "$DemoId.outputs.json"), $outJson, (New-Object System.Text.UTF8Encoding($false)))
    Run-Py 'check_vault_deletable.py' @()
  }
  'check'    { Run-Py 'check_vault_deletable.py' $(if ($Deep) { @('--deep') } else { @() }) }
  'seed'     { Run-Py 'seed_dataset.py' @('--dataset-profile', $DatasetProfile) }
  'backup'   { Run-Py 'run_backup.py' @() }
  'incident' { Need-Confirm; Run-Py 'simulate_incident.py' (@('--prefix', $Prefix, '--confirm')) }
  'post'     { Run-Py 'post_incident_writes.py' @() }
  'restore'  {
    if (-not $Mode) { throw '-Mode in-place|prefix|full is required.' }
    $a = @('--mode', $Mode); if ($Mode -eq 'prefix') { $a += @('--prefixes', $Prefix) }
    Run-Py 'time_restore.py' $a
  }
  'copyback' {
    Need-Confirm
    if (-not $Source) { throw '-Source prefix|full is required.' }
    Run-Py 'copy_back.py' @('--source', $Source, '--prefix', $Prefix, '--confirm')
  }
  'verify'   { Run-Py 'verify_integrity.py' (@('--prefix', $Prefix, '--label', $Label) + $(if ($Quick) { @('--quick') } else { @() })) }
  'report'   {
    $a = @(); if ($ClumioStart -and $ClumioEnd) { $a += @('--clumio-start', $ClumioStart, '--clumio-end', $ClumioEnd) }
    Run-Py 'report.py' $a
  }
  'backup-timing' {
    if (-not $TimingAction) { throw '-TimingAction aws|aws-job|clumio|report is required.' }
    $manifest = Join-Path $Root "manifests\$DemoId-baseline.csv"
    $a = @($TimingAction)   # subcommand must come before --demo-id
    switch ($TimingAction) {
      'aws'     { $a += @('--env-dir', $EnvDir, '--manifest', $manifest) }
      'aws-job' { if (-not $JobId) { throw '-JobId is required.' }; $a += @('--job-id', $JobId, '--manifest', $manifest) }
      'clumio'  {
        if (-not ($ClumioStart -and $ClumioEnd)) { throw '-ClumioStart and -ClumioEnd are required.' }
        $a += @('--start', $ClumioStart, '--end', $ClumioEnd, '--prefixes', $TimingPrefixes, '--manifest', $manifest)
        if ($Evidence) { $a += @('--evidence', $Evidence) }
      }
    }
    $a += @('--demo-id', $DemoId)
    if ($AwsProfile) { $a += @('--profile', $AwsProfile) }
    & $Py (Join-Path $Root 'scripts\backup_timing.py') @a
    if ($LASTEXITCODE) { throw "backup_timing.py exited with code $LASTEXITCODE" }
  }
  'reset'    { Need-Confirm; Run-Py 'reset_demo.py' @('--dataset-profile', $DatasetProfile, '--confirm') }
  'cleanup'  { Need-Confirm; Run-Py 'cleanup_recovery_points.py' @('--confirm') }
  'clumio-up' {
    Require-Inputs; Require-ClumioEnv; Clumio-Init
    terraform "-chdir=$ClumioDir" apply "-var=demo_id=$DemoId" -input=false -auto-approve
    if ($LASTEXITCODE) { throw 'terraform apply (clumio) failed' }
    New-Item -ItemType Directory -Force $StateDir | Out-Null
    $outJson = (terraform "-chdir=$ClumioDir" output -json) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $StateDir "$DemoId.clumio.outputs.json"), $outJson, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Clumio protection group + policy applied for demo '$DemoId'. Track it with: .\demo.ps1 clumio-status -DemoId $DemoId"
  }
  'clumio-status' {
    Require-Inputs; Clumio-Init
    $res = Clumio-Resources
    if (-not $res.Count) { Write-Host "No Clumio resources tracked for demo '$DemoId' (run clumio-up)."; return }
    Write-Host "Clumio resources for demo '$DemoId' (state key scenario-2/$DemoId-clumio.tfstate):"
    $res | ForEach-Object { Write-Host "  $_" }
    terraform "-chdir=$ClumioDir" output
  }
  'clumio-down' {
    Need-Confirm; Require-Inputs; Require-ClumioEnv; Clumio-Init
    if (-not (Clumio-Resources).Count) { Write-Host "Nothing to remove: no Clumio resources for demo '$DemoId'."; return }
    Clumio-Destroy
  }
  'down'     {
    Need-Confirm; Require-Inputs; Tf-Init
    # Remove the Clumio protection group/policy first so Clumio is never left pointing at a deleted bucket.
    Clumio-Init
    if ((Clumio-Resources).Count) { Clumio-Destroy }
    Run-Py 'cleanup_recovery_points.py' @('--confirm')
    terraform "-chdir=$EnvDir" destroy "-var-file=$TfVars" -input=false -auto-approve
    if ($LASTEXITCODE) { throw 'terraform destroy failed' }
    Remove-Item -ErrorAction SilentlyContinue (Join-Path $StateDir "$DemoId.outputs.json")
  }
}
