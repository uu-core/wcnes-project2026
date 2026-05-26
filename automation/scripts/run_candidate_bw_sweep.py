#!/usr/bin/env python3
"""Sweep strong d0/d1 candidates across Carson BW -1/0/+1 receiver settings."""

from __future__ import annotations

import argparse
import configparser
import csv
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_campaign import analyze_campaign
from run_scan import parse_bool, run_receiver_capture
from tag_pipeline import run_single


BW_ROLE_ORDER = {
    "below_carson": -1,
    "carson_ceiling": 0,
    "above_carson": 1,
}


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def stop_requested(stop_flag: Path) -> bool:
    return stop_flag.exists()


def raise_if_stop_requested(stop_flag: Path) -> None:
    if stop_requested(stop_flag):
        raise KeyboardInterrupt("Stop requested via stop flag")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_candidates(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Candidate CSV not found: {csv_path}")
    candidates: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        required = {"run_id", "clock_div0", "clock_div1", "desired_baud"}
        if not reader.fieldnames:
            raise ValueError("Candidate CSV has no header")
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"Candidate CSV missing required columns: {sorted(missing)}")

        for idx, row in enumerate(reader, start=1):
            if not any((value or "").strip() for value in row.values()):
                continue
            enabled_text = (row.get("enabled", "1") or "1").strip()
            if enabled_text and not parse_bool(enabled_text):
                continue
            candidates.append(
                {
                    "candidate_index": idx,
                    "candidate_id": (row.get("run_id") or f"candidate_{idx:02d}").strip(),
                    "clock_div0": int((row.get("clock_div0") or "").strip()),
                    "clock_div1": int((row.get("clock_div1") or "").strip()),
                    "desired_baud": int((row.get("desired_baud") or "").strip()),
                    "bw_offsets": (row.get("bw_offsets") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                }
            )
    if not candidates:
        raise ValueError(f"No enabled candidates found in {csv_path}")
    return candidates


def parse_rx_bw_options_khz(coords_ini: Path) -> list[float]:
    parser = configparser.ConfigParser()
    parser.read(coords_ini, encoding="utf-8")
    raw = parser.get("rx_bw", "options_khz", fallback="")
    options = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not options:
        raise RuntimeError(f"No RX bandwidth options found in {coords_ini}")
    return sorted(options)


def bw_role_for_offset(offset: int) -> str:
    if offset == 0:
        return "carson_ceiling"
    if offset == -1:
        return "below_carson"
    if offset == 1:
        return "above_carson"
    if offset < 0:
        return f"below_carson_{abs(offset)}"
    return f"above_carson_{offset}"


def bw_short_label_for_offset(offset: int) -> str:
    if offset == 0:
        return "BW 0"
    return f"BW {offset:+d}"


def choose_bw_points(
    candidate_id: str,
    carson_bw_hz: int,
    options_khz: list[float],
    lower_steps: int = 1,
    upper_steps: int = 1,
    offsets: list[int] | None = None,
) -> list[dict[str, Any]]:
    target_khz = carson_bw_hz / 1000.0
    ceiling_index = next((idx for idx, value in enumerate(options_khz) if value >= target_khz), None)
    if ceiling_index is None:
        raise RuntimeError(f"No SmartRF RX BW option is >= Carson BW {target_khz:.3f} kHz")
    selected_offsets = offsets if offsets is not None else list(range(-lower_steps, upper_steps + 1))
    if not selected_offsets:
        raise ValueError(f"No BW offsets selected for {candidate_id}")
    min_offset = min(selected_offsets)
    max_offset = max(selected_offsets)
    if ceiling_index + min_offset < 0:
        raise RuntimeError(
            f"Cannot choose BW {min_offset:+d} for {candidate_id}: Carson ceiling is too close to first option"
        )
    if ceiling_index + max_offset >= len(options_khz):
        raise RuntimeError(
            f"Cannot choose BW {max_offset:+d} for {candidate_id}: Carson ceiling is too close to last option"
        )

    choices = [
        (offset, bw_role_for_offset(offset), bw_short_label_for_offset(offset), options_khz[ceiling_index + offset])
        for offset in selected_offsets
    ]
    points: list[dict[str, Any]] = []
    for offset, role, short_label, bw_khz in choices:
        bw_hz = int(round(bw_khz * 1000.0))
        bw_token = str(f"{bw_khz:.1f}").replace(".", "k")
        points.append(
            {
                "run_id": f"{candidate_id}_{role}_bw{bw_token}",
                "bw_role": role,
                "bw_offset": offset,
                "bw_short_label": short_label,
                "bw_label": f"{short_label} {bw_khz:.1f} kHz",
                "rx_bandwidth_hz": bw_hz,
                "rx_bandwidth_khz": bw_khz,
            }
        )
    return points


def parse_cc1352_sync_word(packet_generation_c: Path) -> str:
    text = packet_generation_c.read_text(encoding="utf-8")
    match = re.search(r"packet_hdr_1352\s*\[[^\]]*\]\s*=\s*\{([^}]+)\}", text)
    if not match:
        return "unknown"
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    sync_values = values[4:8]
    return " ".join(value.replace("0x", "").zfill(2) for value in sync_values)


def parse_bw_offsets(raw: str) -> list[int] | None:
    text = raw.strip()
    if not text:
        return None
    offsets: list[int] = []
    for item in re.split(r"[;,\s]+", text):
        if not item:
            continue
        offsets.append(int(item))
    return offsets


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
                "candidate_id",
                "candidate_index",
                "bw_role",
                "bw_short_label",
                "bw_label",
                "bw_offset",
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
        csv.writer(fp).writerow(row)


def write_candidate_bar_chart(summary_csv: Path, manifest_csv: Path, output_path: Path) -> None:
    summary_df = pd.read_csv(summary_csv)
    manifest_df = pd.read_csv(manifest_csv)
    meta_cols = [
        "run_id",
        "candidate_id",
        "candidate_index",
        "bw_role",
        "bw_short_label",
        "bw_label",
        "bw_offset",
        "rx_bandwidth_hz",
        "rx_base_freq_hz",
        "carson_bw_hz",
        "center_offset_hz",
        "deviation_hz",
        "f0_hz",
        "f1_hz",
        "clock_div0",
        "clock_div1",
        "desired_baud",
        "carrier_freq_hz",
        "sync_word",
        "payload_size",
        "target_packets",
        "receiver",
    ]
    summary_cols = [
        "run_id",
        "requested_repeat_count",
        "valid_repeat_count",
        "excluded_repeat_count",
        "per_mean",
        "per_std",
        "ber_mean",
        "ber_std",
        "avg_rssi_dbm_mean",
        "avg_rssi_dbm_std",
        "valid_rows_mean",
        "valid_rows_min",
        "valid_rows_max",
    ]
    display_df = (
        manifest_df[meta_cols]
        .drop_duplicates("run_id")
        .merge(summary_df[summary_cols], on="run_id", how="left")
    )
    if "bw_offset" in display_df.columns:
        display_df["role_order"] = pd.to_numeric(display_df["bw_offset"], errors="coerce").fillna(99)
    else:
        display_df["role_order"] = display_df["bw_role"].map(BW_ROLE_ORDER).fillna(99)
    display_df = display_df.sort_values(["candidate_index", "role_order"]).reset_index(drop=True)

    candidate_meta = display_df.drop_duplicates("candidate_id").sort_values("candidate_index")
    candidates = candidate_meta["candidate_id"].tolist()
    role_meta = (
        display_df[["bw_role", "bw_short_label", "role_order"]]
        .drop_duplicates("bw_role")
        .sort_values("role_order")
    )
    roles = role_meta["bw_role"].tolist()
    role_labels = dict(zip(role_meta["bw_role"], role_meta["bw_short_label"]))
    color_values = plt.cm.viridis(np.linspace(0.12, 0.88, max(len(roles), 1)))
    role_colors = {role: color_values[idx] for idx, role in enumerate(roles)}

    x_labels = [
        (
            f"{int(row.clock_div0)}/{int(row.clock_div1)}\n"
            f"fc={row.rx_base_freq_hz/1e6:.2f}M\n"
            f"off={row.center_offset_hz/1e6:.2f}M\n"
            f"dev={row.deviation_hz/1e3:.1f}k\n"
            f"Carson={row.carson_bw_hz/1000.0:.1f}k"
        )
        for row in candidate_meta.itertuples()
    ]

    first = display_df.iloc[0]
    header = (
        "Candidate d0/d1 x RX bandwidth sweep\n"
        f"baud={int(first.desired_baud)} baud | carrier={int(first.carrier_freq_hz)} Hz | receiver={first.receiver}\n"
        f"sync={first.sync_word} | payload={int(first.payload_size)} B | target={int(first.target_packets)} packets\n"
        "bars show mean +/- std | text shows value, BW, and valid repeats"
    )

    metrics = [
        ("per_mean", "per_std", "PER mean [%]", 100.0, "{:.1f}"),
        ("ber_mean", "ber_std", "BER mean [%]", 100.0, "{:.2f}"),
        ("avg_rssi_dbm_mean", "avg_rssi_dbm_std", "RSSI mean [dBm]", 1.0, "{:.1f}"),
    ]

    fig_width = max(13.5, len(candidates) * 2.15)
    fig, axes = plt.subplots(len(metrics), 1, figsize=(fig_width, 12.0), constrained_layout=True)
    if len(metrics) == 1:
        axes = [axes]
    fig.suptitle(header, fontsize=13, fontweight="bold")

    x = np.arange(len(candidates), dtype=float)
    width = min(0.16, 0.82 / max(len(roles), 1))
    offsets = {
        role: (idx - ((len(roles) - 1) / 2.0)) * width
        for idx, role in enumerate(roles)
    }

    for ax, (value_col, std_col, title, scale, fmt) in zip(axes, metrics):
        metric_values = pd.to_numeric(display_df[value_col], errors="coerce").dropna() * scale
        rssi_baseline = float(metric_values.min()) - 2.0 if value_col == "avg_rssi_dbm_mean" and not metric_values.empty else 0.0
        all_values: list[float] = []
        for role in roles:
            values: list[float] = []
            errors: list[float] = []
            valid_counts: list[str] = []
            bw_values: list[str] = []
            for candidate_id in candidates:
                match = display_df[(display_df["candidate_id"] == candidate_id) & (display_df["bw_role"] == role)]
                if match.empty:
                    values.append(np.nan)
                    errors.append(0.0)
                    valid_counts.append("0/0")
                    bw_values.append("")
                    continue
                row = match.iloc[0]
                value = float(row[value_col]) * scale if not pd.isna(row[value_col]) else np.nan
                error = float(row[std_col]) * scale if not pd.isna(row[std_col]) else 0.0
                values.append(value)
                errors.append(error)
                valid_counts.append(f"{int(row.valid_repeat_count)}/{int(row.requested_repeat_count)}")
                bw_values.append(f"{float(row.rx_bandwidth_hz)/1000.0:.1f}k")
                if not pd.isna(value):
                    all_values.append(value)

            bar_positions = x + offsets[role]
            bar_heights = [
                value - rssi_baseline if value_col == "avg_rssi_dbm_mean" and not pd.isna(value) else value
                for value in values
            ]
            bars = ax.bar(
                bar_positions,
                bar_heights,
                width=width,
                bottom=rssi_baseline if value_col == "avg_rssi_dbm_mean" else 0.0,
                yerr=errors,
                label=role_labels[role],
                color=role_colors[role],
                capsize=3,
                edgecolor="white",
                linewidth=0.6,
            )

            for bar, value, valid_count, bw_text in zip(bars, values, valid_counts, bw_values):
                xpos = bar.get_x() + bar.get_width() / 2
                if pd.isna(value):
                    ax.text(xpos, rssi_baseline, "invalid", ha="center", va="bottom", fontsize=7.5, rotation=90)
                else:
                    label = f"{fmt.format(value)}\n{valid_count}"
                    if value_col == "per_mean":
                        label = f"{fmt.format(value)}\n{bw_text}\n{valid_count}"
                    va = "bottom" if value >= 0 else "top"
                    y_pad = 0.02 * (max(all_values) - min(all_values) if len(all_values) > 1 else 1.0)
                    ax.text(
                        xpos,
                        value + y_pad if value >= 0 else value - y_pad,
                        label,
                        ha="center",
                        va=va,
                        fontsize=7.2,
                    )

        ax.set_title(title, fontsize=12)
        ax.set_ylabel(title)
        ax.set_xticks(x, x_labels)
        ax.tick_params(axis="x", labelsize=8.4)
        ax.grid(axis="y", color="#dddddd", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.legend(ncol=min(len(roles), 5), loc="upper right", frameon=False)

        if all_values:
            if value_col == "avg_rssi_dbm_mean":
                ymin = min(all_values) - 2.5
                ymax = max(all_values) + 2.5
                ax.set_ylim(ymin, ymax)
            else:
                ymax = max(all_values) * 1.28 if max(all_values) > 0 else 1.0
                ax.set_ylim(0, ymax)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate d0/d1 x Carson-relative RX BW sweep.")
    parser.add_argument("--candidate-csv", type=Path, default=Path("automation/config/candidate_bw_sweep.csv"))
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
    parser.add_argument("--repeats", default=3, type=int)
    parser.add_argument("--target-packets", default=200, type=int)
    parser.add_argument("--receiver-timeout-s", default=180, type=int)
    parser.add_argument("--payload-size", default=14, type=int)
    parser.add_argument("--bw-lower-steps", default=1, type=int, help="SmartRF BW options below Carson ceiling to test")
    parser.add_argument("--bw-upper-steps", default=1, type=int, help="SmartRF BW options above Carson ceiling to test")
    parser.add_argument("--shuffle-candidates", action="store_true")
    parser.add_argument("--shuffle-bw", action="store_true")
    parser.add_argument("--random-seed", default=0, type=int)
    args = parser.parse_args()
    if args.bw_lower_steps < 0 or args.bw_upper_steps < 0:
        raise ValueError("BW step counts must be non-negative")

    root = Path.cwd()
    candidate_csv = (root / args.candidate_csv).resolve() if not args.candidate_csv.is_absolute() else args.candidate_csv.resolve()
    main_c = (root / args.main_c).resolve() if not args.main_c.is_absolute() else args.main_c.resolve()
    project_dir = (root / args.project_dir).resolve() if not args.project_dir.is_absolute() else args.project_dir.resolve()
    build_dir = (root / args.build_dir).resolve() if not args.build_dir.is_absolute() else args.build_dir.resolve()
    ahk_script = (root / args.receiver_ahk_script).resolve() if not args.receiver_ahk_script.is_absolute() else args.receiver_ahk_script.resolve()
    coords_ini = (root / args.receiver_coords_ini).resolve() if not args.receiver_coords_ini.is_absolute() else args.receiver_coords_ini.resolve()
    results_dir = (root / args.results_dir).resolve() if not args.results_dir.is_absolute() else args.results_dir.resolve()
    stop_flag = (root / args.stop_flag).resolve() if not args.stop_flag.is_absolute() else args.stop_flag.resolve()
    packet_generation_c = root / "project_pico_libs" / "packet_generation.c"

    rng = random.Random(args.random_seed or None)
    candidates = load_candidates(candidate_csv)
    if args.shuffle_candidates:
        rng.shuffle(candidates)
        for idx, candidate in enumerate(candidates, start=1):
            candidate["candidate_index"] = idx
    options_khz = parse_rx_bw_options_khz(coords_ini)
    sync_word = parse_cc1352_sync_word(packet_generation_c)

    total_captures = 0
    for candidate in candidates:
        offsets = parse_bw_offsets(str(candidate.get("bw_offsets", "")))
        bw_count = len(offsets) if offsets is not None else args.bw_lower_steps + args.bw_upper_steps + 1
        total_captures += args.repeats * bw_count
    completed_captures = 0
    started_at = time.monotonic()

    campaign_id = args.campaign_id.strip() or f"candidate_bw_{now_stamp()}"
    campaign_dir = results_dir / campaign_id
    raw_dir = campaign_dir / "raw"
    analysis_dir = campaign_dir / "analysis"
    manifest_csv = campaign_dir / "manifest.csv"
    start_manifest(manifest_csv)

    try:
        for candidate in candidates:
            raise_if_stop_requested(stop_flag)
            candidate_id = str(candidate["candidate_id"])
            d0 = int(candidate["clock_div0"])
            d1 = int(candidate["clock_div1"])
            baud = int(candidate["desired_baud"])
            print(f"[tag] configuring {candidate_id}: d0={d0} d1={d1} baud={baud}")
            tag_serial_log = raw_dir / candidate_id / "tag_setup_serial.txt"
            parsed = run_single(
                main_c_path=main_c,
                project_dir=project_dir,
                build_dir=build_dir,
                elf_name=args.elf_name,
                d0=d0,
                d1=d1,
                desired_baud=baud,
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
            bw_points = choose_bw_points(
                candidate_id,
                carson_bw_hz,
                options_khz,
                lower_steps=args.bw_lower_steps,
                upper_steps=args.bw_upper_steps,
                offsets=parse_bw_offsets(str(candidate.get("bw_offsets", ""))),
            )
            if args.shuffle_bw:
                rng.shuffle(bw_points)
            for point in bw_points:
                print(f"  {point['bw_role']}: {point['rx_bandwidth_khz']:.1f} kHz")

            for repeat_index in range(1, args.repeats + 1):
                print(f"[{candidate_id}] repeat {repeat_index}/{args.repeats}: BW sweep")
                for point in bw_points:
                    raise_if_stop_requested(stop_flag)
                    receiver_raw_log = (
                        raw_dir
                        / candidate_id
                        / point["bw_role"]
                        / f"repeat_{repeat_index:02d}_receiver_raw.txt"
                    )
                    elapsed = time.monotonic() - started_at
                    if completed_captures:
                        eta = (elapsed / completed_captures) * (total_captures - completed_captures)
                    else:
                        eta = 0.0
                    print(
                        f"[{completed_captures + 1}/{total_captures}] "
                        f"{candidate_id} repeat {repeat_index}/{args.repeats} "
                        f"{point['bw_label']} | elapsed {format_duration(elapsed)} | ETA {format_duration(eta)}"
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
                            point["run_id"],
                            d0,
                            d1,
                            baud,
                            args.target_packets,
                            args.receiver_timeout_s,
                            parsed["rx_base_freq_hz"],
                            deviation_hz,
                            parsed["baudrate"],
                            point["rx_bandwidth_hz"],
                            str(tag_serial_log.resolve()),
                            str(receiver_raw_log.resolve()),
                            candidate["notes"],
                            "candidate_bw_sweep",
                            candidate_id,
                            candidate["candidate_index"],
                            point["bw_role"],
                            point["bw_short_label"],
                            point["bw_label"],
                            point["bw_offset"],
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
                    completed_captures += 1

        per_repeat_path, summary_path, plot_path = analyze_campaign(
            manifest_csv=manifest_csv,
            output_dir=analysis_dir,
            payload_size=args.payload_size,
        )
        bar_chart_path = analysis_dir / "candidate_bw_sweep_bars.png"
        write_candidate_bar_chart(summary_path, manifest_csv, bar_chart_path)
        print(f"Saved per-repeat metrics: {per_repeat_path}")
        print(f"Saved summary metrics: {summary_path}")
        print(f"Saved standard comparison plot: {plot_path}")
        print(f"Saved candidate BW bar chart: {bar_chart_path}")
    except KeyboardInterrupt:
        print(f"Stop requested. Exiting at a safe point. If present, clear: {stop_flag}")
    finally:
        print(f"Campaign complete: {campaign_dir}")


if __name__ == "__main__":
    main()
