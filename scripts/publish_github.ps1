param(
    [string]$Owner = "D-sudoasd",
    [string]$Repository = "DiffractScout",
    [ValidateSet("private", "public")]
    [string]$Visibility = "private"
)

$ErrorActionPreference = "Stop"
$DryRun = $env:DIFFRACTSCOUT_PUBLISH_DRY_RUN -eq "1"
$Description = "Provenance-first phase scouting and indexed powder diffraction references"
$TargetUrl = "https://github.com/$Owner/$Repository.git"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI is required: https://cli.github.com/" }
gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI authentication failed." }

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path ".git")) { throw "Run this script from the prepared DiffractScout repository." }
if ((git status --porcelain).Length -gt 0) { throw "Refusing to publish a dirty working tree." }

$Branch = (git branch --show-current).Trim()
if (-not $Branch) { throw "Refusing to publish from detached HEAD." }

function Invoke-ExternalStep {
    param(
        [Parameter(Mandatory = $true)][string]$Display,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    if ($DryRun) {
        Write-Host "+ $Display"
        return
    }
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Display" }
}

gh repo view "$Owner/$Repository" *> $null
$RepositoryExists = $LASTEXITCODE -eq 0
if (-not $RepositoryExists) {
    Invoke-ExternalStep -Display "gh repo create $Owner/$Repository --$Visibility" -Action {
        gh repo create "$Owner/$Repository" "--$Visibility" --description $Description
    }
}

$Origin = git remote get-url origin 2>$null
$HasOrigin = $LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($Origin)
$AcceptedOrigins = @(
    "https://github.com/$Owner/$Repository",
    "https://github.com/$Owner/$Repository.git",
    "git@github.com:$Owner/$Repository.git"
)

if (-not $HasOrigin) {
    Invoke-ExternalStep "git remote add origin $TargetUrl" { git remote add origin $TargetUrl }
}
elseif ($AcceptedOrigins -notcontains $Origin.Trim()) {
    Write-Host "Replacing non-target origin: $($Origin.Trim())"
    Invoke-ExternalStep "git remote set-url origin $TargetUrl" { git remote set-url origin $TargetUrl }
}

Invoke-ExternalStep "git push -u origin $Branch" { git push -u origin $Branch }
Invoke-ExternalStep -Display "gh repo edit $Owner/$Repository" -Action {
    gh repo edit "$Owner/$Repository" `
        --description $Description `
        --add-topic materials-science `
        --add-topic crystallography `
        --add-topic powder-diffraction `
        --add-topic xrd `
        --add-topic materials-project `
        --add-topic elasticity `
        --add-topic research-software
}

if ($DryRun) {
    Write-Host "Dry run complete; no repository, remote, or branch was changed."
}
else {
    Write-Host "Published: https://github.com/$Owner/$Repository"
}
