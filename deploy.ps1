#Requires -Version 7.0
<#
.SYNOPSIS
    Checks whether gcloud is already authenticated, auths if not, then deploys daily-brief-viewer.

.DESCRIPTION
    Checks for an active gcloud account. If none is found, runs `gcloud auth login`.
    Pass -ADC to also ensure Application Default Credentials are set.
    Once auth is confirmed, runs the deploy sequence:
      git pull origin main
      gcloud builds submit . --config=viewer/webapp/cloudbuild.yaml
      kubectl rollout restart deployment/daily-brief-viewer -n daily-brief-v2
      kubectl rollout status deployment/daily-brief-viewer -n daily-brief-v2
    Each step stops the script on failure.

.PARAMETER ADC
    Also check/set up Application Default Credentials (gcloud auth application-default login).

.PARAMETER RepoPath
    Path to the repo root containing viewer/webapp/cloudbuild.yaml. Defaults to the current directory.

.EXAMPLE
    .\Ensure-GcloudAuth.ps1

.EXAMPLE
    .\Ensure-GcloudAuth.ps1 -ADC -RepoPath C:\repos\daily-brief
#>

[CmdletBinding()]
param(
    [switch]$ADC,
    [string]$RepoPath = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][scriptblock]$Command
    )

    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Step failed ($Description) with exit code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
}

function Test-GcloudInstalled {
    if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
        Write-Error "gcloud CLI not found on PATH. Install the Google Cloud SDK first."
        exit 1
    }
}

function Test-GcloudAuth {
    $account = gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>$null
    return $account
}

Test-GcloudInstalled

$activeAccount = Test-GcloudAuth

if ($activeAccount) {
    Write-Host "Already authenticated as: $activeAccount" -ForegroundColor Green
}
else {
    Write-Host "No active gcloud account found. Starting login..." -ForegroundColor Yellow
    gcloud auth login
    if ($LASTEXITCODE -ne 0) {
        Write-Error "gcloud auth login failed with exit code $LASTEXITCODE."
        exit $LASTEXITCODE
    }
    $activeAccount = Test-GcloudAuth
    Write-Host "Authenticated as: $activeAccount" -ForegroundColor Green
}

if ($ADC) {
    $adcPath = & gcloud info --format="value(config.paths.legacy_credentials_dir)" 2>$null
    $adcFile = Join-Path (& gcloud info --format="value(config.paths.global_config_dir)") "application_default_credentials.json"

    if (Test-Path $adcFile) {
        Write-Host "Application Default Credentials already present at: $adcFile" -ForegroundColor Green
    }
    else {
        Write-Host "No Application Default Credentials found. Starting ADC login..." -ForegroundColor Yellow
        gcloud auth application-default login
        if ($LASTEXITCODE -ne 0) {
            Write-Error "gcloud auth application-default login failed with exit code $LASTEXITCODE."
            exit $LASTEXITCODE
        }
        Write-Host "Application Default Credentials configured." -ForegroundColor Green
    }
}

# --- Deploy sequence (runs only after auth is confirmed) ---

Push-Location $RepoPath
try {
    Invoke-Step -Description "git pull origin main" -Command {
        git pull origin main
    }

    Invoke-Step -Description "gcloud builds submit (viewer/webapp/cloudbuild.yaml)" -Command {
        gcloud builds submit . --config=viewer/webapp/cloudbuild.yaml
    }

    Invoke-Step -Description "kubectl rollout restart deployment/daily-brief-viewer" -Command {
        kubectl rollout restart deployment/daily-brief-viewer -n daily-brief-v2
    }

    Invoke-Step -Description "kubectl rollout status deployment/daily-brief-viewer" -Command {
        kubectl rollout status deployment/daily-brief-viewer -n daily-brief-v2
    }

    Write-Host "Deploy complete." -ForegroundColor Green
}
finally {
    Pop-Location
}
