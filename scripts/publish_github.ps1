param(
    [string]$Owner = "D-sudoasd",
    [string]$Repository = "DiffractScout",
    [ValidateSet("private", "public")]
    [string]$Visibility = "private"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "GitHub CLI is required: https://cli.github.com/" }
gh auth status | Out-Null

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path ".git")) { throw "Run this script from the prepared DiffractScout repository." }
if ((git status --porcelain).Length -gt 0) { throw "Refusing to publish a dirty working tree." }

$Origin = git remote get-url origin 2>$null
if (-not $Origin) {
    gh repo create "$Owner/$Repository" "--$Visibility" --source . --remote origin --push `
        --description "Provenance-first phase scouting and indexed powder diffraction references"
} else {
    Write-Host "origin already exists: $Origin"
}

gh repo edit "$Owner/$Repository" `
    --description "Provenance-first phase scouting and indexed powder diffraction references" `
    --add-topic materials-science `
    --add-topic crystallography `
    --add-topic powder-diffraction `
    --add-topic xrd `
    --add-topic materials-project `
    --add-topic elasticity `
    --add-topic research-software

Write-Host "Published: https://github.com/$Owner/$Repository"
