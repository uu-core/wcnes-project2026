# Automation MVP

This folder contains the Windows-first experiment automation path for the
backscatter setup.

## One input, one runner, minimal outputs

The intended workflow is:

1. Set up the carrier manually before automation starts.
2. Edit `automation/config/scan_plan.csv`.
3. Adjust local machine settings in `automation/run.ps1`, including repeat count.
4. Run `automation/run.ps1`.
5. The runner will:
   - patch tag parameters in `carrier-receiver-baseband/main.c`
   - optionally build and flash the tag
   - read tag serial output
   - parse CC1352 receiver target settings from the tag output
   - launch SmartRF Studio GUI automation
   - repeat the full scan plan for the configured number of rounds
   - save raw logs grouped by `run_id`
   - aggregate PER, BER, and RSSI across repeats
   - generate comparison CSVs and a plot

Outputs are intentionally limited to:

- `automation/results/<campaign_id>/manifest.csv`
- `automation/results/<campaign_id>/raw/<run_id>/repeat_*_tag_serial.txt`
- `automation/results/<campaign_id>/raw/<run_id>/repeat_*_receiver_raw.txt`
- `automation/results/<campaign_id>/analysis/per_repeat.csv`
- `automation/results/<campaign_id>/analysis/summary.csv`
- `automation/results/<campaign_id>/analysis/comparison_metrics.png`

No per-run JSON bridge files are generated.

## Receiver settings source

The automation uses the tag's `CC1352 receiver target settings` block as the
source for SmartRF Studio inputs:

```text
CC1352 receiver target settings:
- base_frequency: <Hz>
- data_rate: <baud>
- deviation: <Hz>
- rx_bandwidth_min: <Hz>
```

These values are the theoretical target values derived from the tag-side
`d0/d1/baud` configuration. SmartRF Studio then selects the closest practical
CC1352 settings through its own GUI controls. The older `set rx ...` lines are
still printed by the firmware for the onboard CC2500 helper path, but they are
CC2500-quantized values and are no longer the preferred automation input.

## Parameter input

Use only `automation/config/scan_plan.csv`.

Required CSV columns:

- `run_id`
- `clock_div0`
- `clock_div1`
- `desired_baud`

Optional CSV columns:

- `target_packets`
- `receiver_timeout_s`
- `enabled`
- `notes`

Example:

```csv
run_id,clock_div0,clock_div1,desired_baud,target_packets,receiver_timeout_s,enabled,notes
d20_d18_b100k,20,18,100000,200,120,1,baseline
d22_d20_b100k,22,20,100000,200,120,1,candidate
```

## Run on Windows

Use the single entry script:

```powershell
powershell -ExecutionPolicy Bypass -File .\automation\run.ps1
```

Before the first run, open `automation/run.ps1` and set:

- `SerialPort`
- `PicotoolPath`
- `AutoHotkeyExe`
- `EnableBuild`
- `EnableFlash`
- `Repeats`

The Python runner is still available if you need it, but the intended daily
entry point is now `automation/run.ps1`.

## Carson bandwidth validation

To validate the Carson-rule receiver bandwidth choice for `d0=28`, `d1=26`,
and `baud=100000`, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\automation\run_carson_bw_test.ps1
```

This focused runner builds/flashes the tag once, reads the CC1352 target
settings from tag serial output, then tests three SmartRF RX Filter BW settings:

- one SmartRF dropdown option below the theoretical Carson bandwidth
- the smallest SmartRF dropdown option greater than or equal to the Carson bandwidth
- one SmartRF dropdown option above that ceiling choice

The dedicated plot is saved as:

- `automation/results/<campaign_id>/analysis/carson_bw_validation.png`

## Candidate d0/d1 plus bandwidth sweep

To retest the strongest `d0/d1` candidates across three receiver bandwidth
choices, edit:

- `automation/config/candidate_bw_sweep.csv`

Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\automation\run_candidate_bw_sweep.ps1
```

For each enabled candidate, the runner builds/flashes the tag once, then tests:

- `BW -1`: one SmartRF RX bandwidth option below the Carson ceiling
- `BW 0`: the smallest SmartRF option greater than or equal to the Carson bandwidth
- `BW +1`: one option above the Carson ceiling

The report-focused grouped bar chart is saved as:

- `automation/results/<campaign_id>/analysis/candidate_bw_sweep_bars.png`

## Stop the run

Two stop paths are supported:

- Press `Ctrl+C` in the PowerShell window running `automation/run.ps1`
- Create `automation/stop.flag`

The runner checks stop requests before each safe step and the SmartRF GUI helper
also watches the same stop flag during RX capture, so receiver collection can
stop cleanly instead of forcing the whole process down.

Assumptions:

- SmartRF Studio is already open on the Packet RX page.
- `automation/gui/smartrf_coords.ini` matches the current GUI layout.
- AutoHotkey is installed and available as `AutoHotkey.exe`, or passed via
  `--receiver-ahk-exe`.

## File responsibilities

- `config/scan_plan.csv`: the only experiment parameter table
- `run.ps1`: the only Windows entry script you should run manually
- `scripts/run_scan.py`: the main experiment runner
- `scripts/analyze_campaign.py`: repeated-run aggregation and plotting
- `scripts/tag_pipeline.py`: tag patch/build/flash/serial helpers
- `gui/smartrf_mvp.ahk`: SmartRF Studio GUI automation
- `gui/smartrf_coords.ini`: machine-specific GUI coordinates
- `results/`: raw experiment outputs
