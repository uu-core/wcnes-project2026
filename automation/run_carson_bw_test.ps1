$ErrorActionPreference = "Stop"

# One-click Windows entry point for the d0=28/d1=26 Carson-rule BW validation.
# It builds/flashes the tag once, then tests the receiver BW below / at / above
# the SmartRF ceiling for the theoretical Carson bandwidth.
#
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\automation\run_carson_bw_test.ps1

$RepoRoot = Split-Path -Parent $PSScriptRoot

# --- Local machine configuration ---
$PythonExe = "python"
$SerialPort = "COM3"
$SerialBaud = 115200
$SerialTimeoutSeconds = 20
$CarrierFreqHz = 2450000000

$EnableBuild = $true
$EnableFlash = $true
$Repeats = 3
$TargetPackets = 200
$ReceiverTimeoutSeconds = 180
$PayloadSize = 14

$ClockDiv0 = 28
$ClockDiv1 = 26
$DesiredBaud = 100000

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
    "automation/scripts/run_carson_bw_test.py",
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
    "--repeats", $Repeats,
    "--target-packets", $TargetPackets,
    "--receiver-timeout-s", $ReceiverTimeoutSeconds,
    "--payload-size", $PayloadSize,
    "--d0", $ClockDiv0,
    "--d1", $ClockDiv1,
    "--baud", $DesiredBaud
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
