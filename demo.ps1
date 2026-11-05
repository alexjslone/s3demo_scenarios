<#
.SYNOPSIS
  Wrapper for the Scenario 2 S3 prefix recovery demo (AWS side).
.EXAMPLE
  .\demo.ps1 up      -DemoId jsmith01
  .\demo.ps1 seed    -DemoId jsmith01 -DatasetProfile lite
  .\demo.ps1 restore -DemoId jsmith01 -Mode prefix
  .\demo.ps1 report  -DemoId jsmith01 -ClumioStart 2026-11-05T17:10:00Z -ClumioEnd 2026-11-05T17:14:30Z
#>
param(
  [Parameter(Mandatory, Position = 0)]
  [ValidateSet('up', 'check', 'seed', 'backup', 'incident', 'post', 'restore', 'copyback', 'verify', 'report', 'reset', 'cleanup', 'down')]
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
  [switch]$Quick,
  [switch]$Deep,
  [switch]$Confirm
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$EnvDir = Join-Path $Root 'envs\sandbox'
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
  'reset'    { Need-Confirm; Run-Py 'reset_demo.py' @('--dataset-profile', $DatasetProfile, '--confirm') }
  'cleanup'  { Need-Confirm; Run-Py 'cleanup_recovery_points.py' @('--confirm') }
  'down'     {
    Need-Confirm; Require-Inputs; Tf-Init
    Run-Py 'cleanup_recovery_points.py' @('--confirm')
    terraform "-chdir=$EnvDir" destroy "-var-file=$TfVars" -input=false -auto-approve
    if ($LASTEXITCODE) { throw 'terraform destroy failed' }
    Remove-Item -ErrorAction SilentlyContinue (Join-Path $StateDir "$DemoId.outputs.json")
  }
}
