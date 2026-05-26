#!/usr/bin/env python3
"""Run one hardware automation demo capture without campaign analysis.

This is intentionally small for presentation/video recording:
one tag configuration -> build/flash -> serial parse -> SmartRF GUI capture.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_scan import run_receiver_capture
from tag_pipeline import run_single


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def parse_rx_bw_options_khz(coords_ini: Path) -> list[float]:
    parser = configparser.ConfigParser()
    parser.read(coords_ini, encoding="utf-8")
    raw = parser.get("rx_bw", "options_khz", fallback="")
    options = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not options:
        raise RuntimeError(f"No RX bandwidth options found in {coords_ini}")
    return sorted(options)


def choose_rx_bw_hz(min_bw_hz: int, options_khz: list[float], offset: int) -> tuple[int, float]:
    target_khz = min_bw_hz / 1000.0
    ceiling_index = next((idx for idx, value in enumerate(options_khz) if value >= target_khz), None)
    if ceiling_index is None:
        raise RuntimeError(f"No SmartRF RX BW option is >= {target_khz:.1f} kHz")
    selected_index = ceiling_index + offset
    if selected_index < 0 or selected_index >= len(options_khz):
        raise RuntimeError(f"BW offset {offset:+d} is outside SmartRF option list")
    selected_khz = options_khz[selected_index]
    return int(round(selected_khz * 1000.0)), selected_khz


def write_manifest(path: Path, row: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "campaign_id",
                "run_id",
                "clock_div0",
                "clock_div1",
                "desired_baud",
                "target_packets",
                "receiver_timeout_s",
                "rx_base_freq_hz",
                "deviation_hz",
                "rx_data_rate_baud",
                "rx_bandwidth_hz",
                "rx_bandwidth_khz",
                "bw_offset",
                "tag_serial_log",
                "receiver_raw_log",
                "notes",
            ]
        )
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one video demo automation capture.")
    parser.add_argument("--d0", default=34, type=int)
    parser.add_argument("--d1", default=32, type=int)
    parser.add_argument("--baud", default=100000, type=int)
    parser.add_argument("--bw-offset", default=1, type=int)
    parser.add_argument("--serial-port", required=True)
    parser.add_argument("--serial-baud", default=115200, type=int)
    parser.add_argument("--serial-timeout-s", default=20, type=int)
    parser.add_argument("--carrier-freq-hz", default=2450000000, type=int)
    parser.add_argument("--main-c", type=Path, default=Path("carrier-receiver-baseband/main.c"))
    parser.add_argument("--project-dir", type=Path, default=Path("carrier-receiver-baseband"))
    parser.add_argument("--build-dir", type=Path, default=Path("carrier-receiver-baseband/build"))
    parser.add_argument("--elf-name", default="carrier_receiver_baseband.elf")
    parser.add_argument("--picotool-path", default="picotool")
    parser.add_argument("--enable-build", action="store_true")
    parser.add_argument("--enable-flash", action="store_true")
    parser.add_argument("--receiver-ahk-exe", default="AutoHotkey.exe")
    parser.add_argument("--receiver-ahk-script", type=Path, default=Path("automation/gui/smartrf_mvp.ahk"))
    parser.add_argument("--receiver-coords-ini", type=Path, default=Path("automation/gui/smartrf_coords.ini"))
    parser.add_argument("--results-dir", type=Path, default=Path("automation/results"))
    parser.add_argument("--stop-flag", type=Path, default=Path("automation/stop.flag"))
    parser.add_argument("--target-packets", default=200, type=int)
    parser.add_argument("--receiver-timeout-s", default=180, type=int)
    parser.add_argument("--campaign-id", default="")
    args = parser.parse_args()

    root = Path.cwd()
    campaign_id = args.campaign_id.strip() or f"video_demo_{now_stamp()}"
    campaign_dir = (root / args.results_dir / campaign_id).resolve()
    raw_dir = campaign_dir / "raw"
    tag_serial_log = raw_dir / "tag_serial.txt"
    receiver_raw_log = raw_dir / "receiver_raw.txt"
    manifest_csv = campaign_dir / "manifest.csv"
    stop_flag = (root / args.stop_flag).resolve() if not args.stop_flag.is_absolute() else args.stop_flag.resolve()

    if stop_flag.exists():
        stop_flag.unlink()

    run_id = f"d{args.d0}_d{args.d1}_b{args.baud}_bw{args.bw_offset:+d}".replace("+", "plus").replace("-", "minus")
    print(f"[video demo] tag {run_id}: d0={args.d0} d1={args.d1} baud={args.baud}")
    parsed = run_single(
        main_c_path=(root / args.main_c).resolve(),
        project_dir=(root / args.project_dir).resolve(),
        build_dir=(root / args.build_dir).resolve(),
        elf_name=args.elf_name,
        d0=args.d0,
        d1=args.d1,
        desired_baud=args.baud,
        serial_port=args.serial_port,
        serial_baud=args.serial_baud,
        serial_timeout_s=args.serial_timeout_s,
        carrier_freq_hz=args.carrier_freq_hz,
        enable_build=args.enable_build,
        enable_flash=args.enable_flash,
        picotool_path=args.picotool_path,
        serial_log_file=tag_serial_log,
    )

    rx_bw_hz, rx_bw_khz = choose_rx_bw_hz(
        min_bw_hz=int(parsed["rx_bandwidth_hz"]),
        options_khz=parse_rx_bw_options_khz((root / args.receiver_coords_ini).resolve()),
        offset=args.bw_offset,
    )
    print(
        "[video demo] receiver: "
        f"freq={parsed['rx_base_freq_hz']} Hz, "
        f"rate={parsed['baudrate']} baud, "
        f"deviation={parsed['deviation_hz']} Hz, "
        f"BW={rx_bw_khz:.1f} kHz"
    )

    run_receiver_capture(
        ahk_exe=args.receiver_ahk_exe,
        ahk_script=(root / args.receiver_ahk_script).resolve(),
        coords_ini=(root / args.receiver_coords_ini).resolve(),
        base_freq_hz=int(parsed["rx_base_freq_hz"]),
        data_rate_baud=int(parsed["baudrate"]),
        deviation_hz=int(parsed["deviation_hz"]),
        rx_bw_hz=rx_bw_hz,
        save_path=receiver_raw_log,
        timeout_s=args.receiver_timeout_s,
        target_packets=args.target_packets,
        stop_flag=stop_flag,
    )

    write_manifest(
        manifest_csv,
        [
            campaign_id,
            run_id,
            args.d0,
            args.d1,
            args.baud,
            args.target_packets,
            args.receiver_timeout_s,
            parsed["rx_base_freq_hz"],
            parsed["deviation_hz"],
            parsed["baudrate"],
            rx_bw_hz,
            f"{rx_bw_khz:.1f}",
            args.bw_offset,
            str(tag_serial_log),
            str(receiver_raw_log),
            "single video demo; no analysis generated",
        ],
    )

    print(f"[video demo] saved raw receiver log: {receiver_raw_log}")
    print(f"[video demo] saved manifest: {manifest_csv}")
    print(f"[video demo] complete: {campaign_dir}")


if __name__ == "__main__":
    main()
