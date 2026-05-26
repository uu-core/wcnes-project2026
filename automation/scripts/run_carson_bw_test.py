#!/usr/bin/env python3
"""Run a focused Carson-rule receiver bandwidth validation experiment.

Fixed tag parameters:
- d0 = 28
- d1 = 26
- baud = 100000

The tag is built/flashed once. Receiver capture is then repeated for three
CC1352 SmartRF RX bandwidth choices: one below the Carson estimate, the ceiling
choice, and one above it.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_campaign import analyze_campaign
from run_scan import run_receiver_capture
from tag_pipeline import run_single


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def stop_requested(stop_flag: Path) -> bool:
    return stop_flag.exists()


def raise_if_stop_requested(stop_flag: Path) -> None:
    if stop_requested(stop_flag):
        raise KeyboardInterrupt("Stop requested via stop flag")


def parse_rx_bw_options_khz(coords_ini: Path) -> list[float]:
    parser = configparser.ConfigParser()
    parser.read(coords_ini, encoding="utf-8")
    raw = parser.get("rx_bw", "options_khz", fallback="")
    options = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not options:
        raise RuntimeError(f"No RX bandwidth options found in {coords_ini}")
    return sorted(options)


def choose_carson_bw_points(carson_bw_hz: int, options_khz: list[float]) -> list[dict[str, Any]]:
    target_khz = carson_bw_hz / 1000.0
    ceiling_index = next((idx for idx, value in enumerate(options_khz) if value >= target_khz), None)
    if ceiling_index is None:
        raise RuntimeError(f"No SmartRF RX BW option is >= Carson BW {target_khz:.3f} kHz")
    if ceiling_index == 0:
        raise RuntimeError("Cannot choose below-Carson BW: Carson ceiling is already the first option")
    if ceiling_index + 1 >= len(options_khz):
        raise RuntimeError("Cannot choose above-Carson BW: Carson ceiling is already the last option")

    choices = [
        ("below_carson", options_khz[ceiling_index - 1]),
        ("carson_ceiling", options_khz[ceiling_index]),
        ("above_carson", options_khz[ceiling_index + 1]),
    ]
    points: list[dict[str, Any]] = []
    for role, bw_khz in choices:
        bw_hz = int(round(bw_khz * 1000.0))
        label = f"{bw_khz:.1f} kHz {role.replace('_', ' ')}"
        run_id = f"d28_d26_bw{str(f'{bw_khz:.1f}').replace('.', 'k')}"
        points.append(
            {
                "run_id": run_id,
                "bw_role": role,
                "rx_bandwidth_hz": bw_hz,
                "rx_bandwidth_khz": bw_khz,
                "bw_label": label,
            }
        )
    return points


def parse_cc1352_sync_word(packet_generation_c: Path) -> str:
    text = packet_generation_c.read_text(encoding="utf-8")
    match = re.search(r"packet_hdr_1352\s*\[[^\]]*\]\s*=\s*\{([^}]+)\}", text)
    if not match:
        return "unknown"
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    # packet_hdr_1352 is 4 preamble bytes + 4 sync bytes + length + seq.
    sync_values = values[4:8]
    return " ".join(value.replace("0x", "").zfill(2) for value in sync_values)


def start_manifest(path: Path) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "campaign_id",
                "repeat_index",
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
                "tag_serial_log",
                "receiver_raw_log",
                "notes",
                "experiment_type",
                "bw_role",
                "bw_label",
                "carson_bw_hz",
                "center_offset_hz",
                "carrier_freq_hz",
                "f0_hz",
                "f1_hz",
                "sync_word",
                "payload_size",
                "receiver",
            ]
        )


def append_manifest_row(path: Path, row: list[Any]) -> None:
    with path.open("a", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(row)


def write_carson_plot(
    summary_csv: Path,
    manifest_csv: Path,
    output_path: Path,
    experiment_meta: dict[str, Any],
) -> None:
    summary_df = pd.read_csv(summary_csv)
    manifest_df = pd.read_csv(manifest_csv)
    display_df = (
        manifest_df[
            [
                "run_id",
                "bw_role",
                "bw_label",
                "rx_bandwidth_hz",
                "carson_bw_hz",
                "center_offset_hz",
                "f0_hz",
                "f1_hz",
            ]
        ]
        .drop_duplicates("run_id")
        .merge(summary_df, on="run_id", how="left")
    )
    role_order = {"below_carson": 0, "carson_ceiling": 1, "above_carson": 2}
    display_df["role_order"] = display_df["bw_role"].map(role_order).fillna(99)
    display_df = display_df.sort_values("role_order").reset_index(drop=True)

    labels = [
        f"{row.bw_label}\n({int(row.valid_repeat_count)}/{int(row.requested_repeat_count)} valid)"
        for row in display_df.itertuples()
    ]
    x = list(range(len(labels)))

    fig = plt.figure(figsize=(13.5, 10), constrained_layout=True)
    grid = fig.add_gridspec(4, 1, height_ratios=[1.0, 2.0, 2.0, 2.0])
    meta_ax = fig.add_subplot(grid[0])
    axes = [fig.add_subplot(grid[i]) for i in range(1, 4)]

    meta_ax.axis("off")
    meta_lines = [
        "Carson rule RX bandwidth validation",
        f"d0/d1: {experiment_meta['d0']}/{experiment_meta['d1']}    baud: {experiment_meta['baud']} baud    receiver: CC1352",
        f"carrier: {experiment_meta['carrier_freq_hz']} Hz    base: {experiment_meta['base_frequency_hz']} Hz    center offset: {experiment_meta['center_offset_hz']} Hz",
        f"f0: {experiment_meta['f0_hz']:.1f} Hz    f1: {experiment_meta['f1_hz']:.1f} Hz    deviation: {experiment_meta['deviation_hz']} Hz",
        f"Carson BW: {experiment_meta['carson_bw_hz']} Hz    sync word: {experiment_meta['sync_word']}    payload: {experiment_meta['payload_size']} B    target: {experiment_meta['target_packets']} packets",
    ]
    meta_ax.text(
        0.01,
        0.98,
        "\n".join(meta_lines),
        va="top",
        ha="left",
        fontsize=10.5,
        family="monospace",
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "#f5f5f5", "edgecolor": "#cccccc"},
    )

    axes[0].bar(x, display_df["per_mean"] * 100.0, yerr=display_df["per_std"].fillna(0.0) * 100.0, color="#c84c4c")
    axes[0].set_ylabel("PER [%]")
    axes[0].set_title("Packet Error Rate")

    axes[1].bar(x, display_df["ber_mean"] * 100.0, yerr=display_df["ber_std"].fillna(0.0) * 100.0, color="#3d7fd6")
    axes[1].set_ylabel("BER [%]")
    axes[1].set_title("Bit Error Rate")

    axes[2].bar(x, display_df["avg_rssi_dbm_mean"], yerr=display_df["avg_rssi_dbm_std"].fillna(0.0), color="#5d9a52")
    axes[2].set_ylabel("RSSI [dBm]")
    axes[2].set_title("Average RSSI")

    for ax in axes:
        ax.set_xticks(x, labels)
        ax.grid(axis="y", color="#dddddd", linewidth=0.7)
        ax.set_axisbelow(True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Carson-rule RX bandwidth validation.")
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
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--repeats", default=5, type=int)
    parser.add_argument("--target-packets", default=200, type=int)
    parser.add_argument("--receiver-timeout-s", default=180, type=int)
    parser.add_argument("--payload-size", default=14, type=int)
    parser.add_argument("--d0", default=28, type=int)
    parser.add_argument("--d1", default=26, type=int)
    parser.add_argument("--baud", default=100000, type=int)
    args = parser.parse_args()

    root = Path.cwd()
    main_c = (root / args.main_c).resolve() if not args.main_c.is_absolute() else args.main_c.resolve()
    project_dir = (root / args.project_dir).resolve() if not args.project_dir.is_absolute() else args.project_dir.resolve()
    build_dir = (root / args.build_dir).resolve() if not args.build_dir.is_absolute() else args.build_dir.resolve()
    ahk_script = (root / args.receiver_ahk_script).resolve() if not args.receiver_ahk_script.is_absolute() else args.receiver_ahk_script.resolve()
    coords_ini = (root / args.receiver_coords_ini).resolve() if not args.receiver_coords_ini.is_absolute() else args.receiver_coords_ini.resolve()
    results_dir = (root / args.results_dir).resolve() if not args.results_dir.is_absolute() else args.results_dir.resolve()
    stop_flag = (root / args.stop_flag).resolve() if not args.stop_flag.is_absolute() else args.stop_flag.resolve()
    packet_generation_c = root / "project_pico_libs" / "packet_generation.c"

    campaign_id = args.campaign_id.strip() or f"carson_bw_{now_stamp()}"
    campaign_dir = results_dir / campaign_id
    raw_dir = campaign_dir / "raw"
    analysis_dir = campaign_dir / "analysis"
    manifest_csv = campaign_dir / "manifest.csv"
    start_manifest(manifest_csv)

    tag_serial_log = raw_dir / "tag_setup_serial.txt"

    try:
        print(f"[tag] configuring d0={args.d0} d1={args.d1} baud={args.baud}")
        parsed = run_single(
            main_c_path=main_c,
            project_dir=project_dir,
            build_dir=build_dir,
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

        center_offset_hz = int(parsed["rx_base_freq_hz"]) - args.carrier_freq_hz
        deviation_hz = int(parsed["deviation_hz"])
        f0_hz = center_offset_hz - deviation_hz
        f1_hz = center_offset_hz + deviation_hz
        carson_bw_hz = int(parsed["rx_bandwidth_hz"])
        sync_word = parse_cc1352_sync_word(packet_generation_c)

        options_khz = parse_rx_bw_options_khz(coords_ini)
        bw_points = choose_carson_bw_points(carson_bw_hz, options_khz)
        print("[receiver] BW points:")
        for point in bw_points:
            print(f"  {point['bw_role']}: {point['rx_bandwidth_khz']:.1f} kHz")

        for repeat_index in range(1, args.repeats + 1):
            print(f"[repeat {repeat_index}/{args.repeats}] starting BW sweep")
            for point in bw_points:
                raise_if_stop_requested(stop_flag)
                run_id = point["run_id"]
                receiver_raw_log = raw_dir / run_id / f"repeat_{repeat_index:02d}_receiver_raw.txt"
                print(
                    f"[repeat {repeat_index}/{args.repeats}] receiver {point['bw_label']}: GUI capture"
                )
                run_receiver_capture(
                    ahk_exe=args.receiver_ahk_exe,
                    ahk_script=ahk_script,
                    coords_ini=coords_ini,
                    base_freq_hz=int(parsed["rx_base_freq_hz"]),
                    data_rate_baud=int(parsed["baudrate"]),
                    deviation_hz=deviation_hz,
                    rx_bw_hz=int(point["rx_bandwidth_hz"]),
                    save_path=receiver_raw_log,
                    timeout_s=args.receiver_timeout_s,
                    target_packets=args.target_packets,
                    stop_flag=stop_flag,
                )
                append_manifest_row(
                    manifest_csv,
                    [
                        campaign_id,
                        repeat_index,
                        run_id,
                        args.d0,
                        args.d1,
                        args.baud,
                        args.target_packets,
                        args.receiver_timeout_s,
                        parsed["rx_base_freq_hz"],
                        deviation_hz,
                        parsed["baudrate"],
                        point["rx_bandwidth_hz"],
                        str(tag_serial_log.resolve()),
                        str(receiver_raw_log.resolve()),
                        point["bw_role"],
                        "carson_bw_validation",
                        point["bw_role"],
                        point["bw_label"],
                        carson_bw_hz,
                        center_offset_hz,
                        args.carrier_freq_hz,
                        f0_hz,
                        f1_hz,
                        sync_word,
                        args.payload_size,
                        "CC1352",
                    ],
                )

        per_repeat_path, summary_path, plot_path = analyze_campaign(
            manifest_csv=manifest_csv,
            output_dir=analysis_dir,
            payload_size=args.payload_size,
        )
        custom_plot = analysis_dir / "carson_bw_validation.png"
        write_carson_plot(
            summary_csv=summary_path,
            manifest_csv=manifest_csv,
            output_path=custom_plot,
            experiment_meta={
                "d0": args.d0,
                "d1": args.d1,
                "baud": args.baud,
                "carrier_freq_hz": args.carrier_freq_hz,
                "base_frequency_hz": parsed["rx_base_freq_hz"],
                "center_offset_hz": center_offset_hz,
                "f0_hz": f0_hz,
                "f1_hz": f1_hz,
                "deviation_hz": deviation_hz,
                "carson_bw_hz": carson_bw_hz,
                "sync_word": sync_word,
                "payload_size": args.payload_size,
                "target_packets": args.target_packets,
            },
        )
        print(f"Saved per-repeat metrics: {per_repeat_path}")
        print(f"Saved summary metrics: {summary_path}")
        print(f"Saved standard comparison plot: {plot_path}")
        print(f"Saved Carson BW plot: {custom_plot}")
    except KeyboardInterrupt:
        print(f"Stop requested. Exiting at a safe point. If present, clear: {stop_flag}")
    finally:
        print(f"Campaign complete: {campaign_dir}")


if __name__ == "__main__":
    main()
