$ErrorActionPreference = "Stop"

# One-shot automation demo for presentation/video recording.
# It runs one stable configuration once and does not generate campaign analysis.
#
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\automation\run_video_demo.ps1

$RepoRoot = Split-Path -Parent $PSScriptRoot

# --- Local machine configuration ---
$PythonExe = "python"
$SerialPort = "COM3"
$SerialBaud = 115200
$SerialTimeoutSeconds = 20
$CarrierFreqHz = 2450000000

$EnableBuild = $true
$EnableFlash = $true
$TargetPackets = 200
$ReceiverTimeoutSeconds = 180

# Stable presentation-demo point from the final confirmation set.
$ClockDiv0 = 34
$ClockDiv1 = 32
$DesiredBaud = 100000
$BwOffset = 1

$PicotoolPath = "C:\Users\16143\.pico-sdk\picotool\2.2.0-a4\picotool\picotool.exe"
$AutoHotkeyExe = "AutoHotkey.exe"

$ReceiverAhkScript = Join-Path $RepoRoot "automation\gui\smartrf_mvp.ahk"
$ReceiverCoordsIni = Join-Path $RepoRoot "automation\gui\smartrf_coords.ini"
$ResultsDir = Join-Path $RepoRoot "automation\results"
$StopFlag = Join-Path $RepoRoot "automation\stop.flag"
$MainC = Join-Path $RepoRoot "carrier-receiver-baseband\main.c"
$ProjectDir = Join-Path $RepoRoot "carrier-receiver-baseband"
$BuildDir = Join-Path $RepoRoot "carrier-receiver-baseband\build"

$Args = @(
    "automation/scripts/run_video_demo.py",
    "--d0", $ClockDiv0,
    "--d1", $ClockDiv1,
    "--baud", $DesiredBaud,
    "--bw-offset", $BwOffset,
    "--serial-port", $SerialPort,
    "--serial-baud", $SerialBaud,
    "--serial-timeout-s", $SerialTimeoutSeconds,
    "--carrier-freq-hz", $CarrierFreqHz,
    "--main-c", $MainC,
    "--project-dir", $ProjectDir,
    "--build-dir", $BuildDir,
    "--picotool-path", $PicotoolPath,
    "--receiver-ahk-exe", $AutoHotkeyExe,
    "--receiver-ahk-script", $ReceiverAhkScript,
    "--receiver-coords-ini", $ReceiverCoordsIni,
    "--results-dir", $ResultsDir,
    "--stop-flag", $StopFlag,
    "--target-packets", $TargetPackets,
    "--receiver-timeout-s", $ReceiverTimeoutSeconds
)

if ($EnableBuild) {
    $Args += "--enable-build"
}

if ($EnableFlash) {
    $Args += "--enable-flash"
}

Push-Location $RepoRoot
try {
    if (Test-Path -LiteralPath $StopFlag) {
        Remove-Item -LiteralPath $StopFlag -Force
    }
    & $PythonExe @Args
}
finally {
    Pop-Location
}
