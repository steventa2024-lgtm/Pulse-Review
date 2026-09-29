<#
.SYNOPSIS
  Builds dist\PulseReview.exe (single-file, windowed) for PulseReview.
.DESCRIPTION
  1 verify Python 3.11+  2 create/reuse .venv  3 install dependencies inside .venv  4 run the test suite
  5 build with nicegui-pack (PyInstaller)  6 verify the output exists  7 print its path.
  Any failure stops the script with a non-zero exit code and a clear message.
  Requires Windows PowerShell 5.1+. Use -SkipTests only for local experiments.
#>
[CmdletBinding()]
param([switch]$SkipTests, [switch]$Clean)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$AppName = 'PulseReview'

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "BUILD FAILED: $Message" -ForegroundColor Red
    exit 1
}
function Step([string]$Message) { Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Invoke-Checked([string]$What, [scriptblock]$Block) {
    # Windows PowerShell 5.1 turns any native stderr text into a terminating error under 'Stop';
    # judge native commands by their exit code instead.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { Fail "$What failed (exit code $LASTEXITCODE)." }
}

# ---- 1. Python ---------------------------------------------------------------------------------
Step 'Checking Python installation (3.11+ required)'
$pyCmd = $null
foreach ($candidate in @(@('py', '-3.12'), @('py', '-3.11'), @('python'))) {
    if (Get-Command $candidate[0] -ErrorAction SilentlyContinue) {
        $probe = @($candidate) + @('-c', 'import sys; print(sys.version_info >= (3, 11))')
        $exe = $probe[0]; $rest = $probe[1..($probe.Length - 1)]
        $ErrorActionPreference = 'Continue'
        $out = & $exe @rest 2>$null
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True') { $pyCmd = $candidate; break }
    }
}
if (-not $pyCmd) { Fail 'Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ and re-run.' }
Write-Host ("Using: " + ($pyCmd -join ' '))

# ---- 2. venv -----------------------------------------------------------------------------------
Step 'Preparing virtual environment (.venv)'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    $exe = $pyCmd[0]; $rest = @(); if ($pyCmd.Length -gt 1) { $rest = $pyCmd[1..($pyCmd.Length - 1)] }
    Invoke-Checked 'Creating .venv' { & $exe @rest -m venv .venv }
}
if (-not (Test-Path -LiteralPath $venvPython)) { Fail '.venv\Scripts\python.exe was not created.' }

# ---- 3. dependencies ---------------------------------------------------------------------------
Step 'Installing dependencies inside .venv'
Invoke-Checked 'pip upgrade' { & $venvPython -m pip install --upgrade pip --quiet }
Invoke-Checked 'pip install -r requirements.txt' { & $venvPython -m pip install -r requirements.txt --quiet }

# ---- 4. tests ----------------------------------------------------------------------------------
if ($SkipTests) {
    Write-Host 'Skipping tests (-SkipTests).' -ForegroundColor Yellow
} else {
    Step 'Running the test suite'
    Invoke-Checked 'The test suite' { & $venvPython -m pytest -q }
}

# ---- 5. build ----------------------------------------------------------------------------------
Step 'Ensuring the application icon exists'
$icon = Join-Path $PSScriptRoot 'dashboard\assets\icon.ico'
if (-not (Test-Path -LiteralPath $icon)) { Invoke-Checked 'Icon generation' { & $venvPython tools\make_icon.py } }
if (-not (Test-Path -LiteralPath $icon)) { Fail 'dashboard\assets\icon.ico is missing.' }

Step "Building $AppName.exe (nicegui-pack / PyInstaller, single file, windowed)"
$pack = Join-Path $PSScriptRoot '.venv\Scripts\nicegui-pack.exe'
if (-not (Test-Path -LiteralPath $pack)) { Fail 'nicegui-pack.exe was not installed (is nicegui in requirements.txt?).' }
$packArgs = @('--onefile', '--windowed', '--name', $AppName, '--icon', $icon, '--noconfirm',
              '--add-data', "dashboard\assets;dashboard\assets")
if ($Clean) { $packArgs += '--clean' }
$packArgs += 'main.py'
# .venv\Scripts must be first on PATH so nicegui-pack runs the venv's PyInstaller
$env:PATH = (Join-Path $PSScriptRoot '.venv\Scripts') + ';' + $env:PATH
Invoke-Checked 'nicegui-pack' { & $pack @packArgs }

# ---- 6/7. verify + report ----------------------------------------------------------------------
Step 'Verifying output'
$exePath = Join-Path $PSScriptRoot "dist\$AppName.exe"
if (-not (Test-Path -LiteralPath $exePath)) { Fail "Expected output was not produced: $exePath" }
$size = [math]::Round((Get-Item -LiteralPath $exePath).Length / 1MB, 1)
Write-Host ""
Write-Host "BUILD SUCCEEDED" -ForegroundColor Green
Write-Host "Executable: $exePath ($size MB)"
Write-Host "User data will live in: $env:APPDATA\ZeroPulse\PRReviewAgent\"
Write-Host "Note: launch it once on a clean profile to confirm WebView2 / native window behaviour (see README)."
