#!/usr/bin/env python3
"""Tag-side helpers for the MVP automation path.

Scope is intentionally narrow:
- patch only the tag experiment entry macros in `carrier-receiver-baseband/main.c`
- optionally build and flash
- parse the CC1352 receiver target settings from tag serial output
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Tuple

CC1352_TARGET_PATTERNS = {
    "rx_base_freq_hz": re.compile(r"base_frequency:\s*(\d+)", re.IGNORECASE),
    "baudrate": re.compile(r"data_rate:\s*(\d+)", re.IGNORECASE),
    "deviation_hz": re.compile(r"deviation:\s*(\d+)", re.IGNORECASE),
    "rx_bandwidth_hz": re.compile(r"rx_bandwidth_min:\s*(\d+)", re.IGNORECASE),
}

LEGACY_CC2500_PATTERNS = {
    "rx_base_freq_hz": re.compile(r"set\s+rx\s+f_carrier.*\]\s*(\d+)", re.IGNORECASE),
    "deviation_hz": re.compile(r"set\s+rx\s+f_dev:.*\]\s*(\d+)", re.IGNORECASE),
    "baudrate": re.compile(r"set\s+rx\s+r_data:.*\]\s*(\d+)", re.IGNORECASE),
    "rx_bandwidth_hz": re.compile(r"set\s+rx\s+bw:.*\]\s*(\d+)", re.IGNORECASE),
}

DEFINE_PATTERNS = {
    "CLOCK_DIV0": re.compile(r"^\s*#define\s+CLOCK_DIV0\s+\d+", re.MULTILINE),
    "CLOCK_DIV1": re.compile(r"^\s*#define\s+CLOCK_DIV1\s+\d+", re.MULTILINE),
    "DESIRED_BAUD": re.compile(r"^\s*#define\s+DESIRED_BAUD\s+\d+", re.MULTILINE),
}


def replace_define(source: str, key: str, value: int) -> str:
    pat = DEFINE_PATTERNS[key]
    replacement = f"#define {key:<16} {value}"
    updated, count = pat.subn(replacement, source, count=1)
    if count != 1:
        raise RuntimeError(f"Failed to update {key}; matched {count} lines")
    return updated


def update_main_c(main_c_path: Path, d0: int, d1: int, baud: int) -> None:
    text = main_c_path.read_text(encoding="utf-8")
    text = replace_define(text, "CLOCK_DIV0", d0)
    text = replace_define(text, "CLOCK_DIV1", d1)
    text = replace_define(text, "DESIRED_BAUD", baud)
    main_c_path.write_text(text, encoding="utf-8")


def run_cmd(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=str(cwd), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(args)}")


def run_cmd_capture(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _emit_tool_output(proc: subprocess.CompletedProcess[str]) -> None:
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n")


def build_tag(project_dir: Path, build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which("nmake"):
        run_cmd(["cmake", "-G", "NMake Makefiles", ".."], cwd=build_dir)
        run_cmd(["nmake"], cwd=build_dir)
        return

    if shutil.which("ninja"):
        run_cmd(["cmake", "-G", "Ninja", ".."], cwd=build_dir)
        run_cmd(["ninja"], cwd=build_dir)
        return

    raise RuntimeError("No supported build tool found. Install nmake (Visual Studio Build Tools) or ninja.")


def flash_tag(build_dir: Path, elf_name: str, picotool_path: str) -> None:
    elf_path = build_dir / elf_name
    if not elf_path.exists():
        raise FileNotFoundError(f"ELF not found: {elf_path}")

    max_attempts = 4
    reboot_wait_s = 2.5
    retry_wait_s = 3.0
    last_error_details = ""

    for attempt in range(1, max_attempts + 1):
        print(f"[flash] attempt {attempt}/{max_attempts}: forcing Pico into BOOTSEL mode")
        reboot_proc = run_cmd_capture([picotool_path, "reboot", "-f", "-u"], cwd=build_dir)
        _emit_tool_output(reboot_proc)
        time.sleep(reboot_wait_s)

        print(f"[flash] attempt {attempt}/{max_attempts}: loading {elf_path.name}")
        load_proc = run_cmd_capture([picotool_path, "load", str(elf_path)], cwd=build_dir)
        _emit_tool_output(load_proc)
        if load_proc.returncode == 0:
            reboot_back_proc = run_cmd_capture([picotool_path, "reboot"], cwd=build_dir)
            _emit_tool_output(reboot_back_proc)
            if reboot_back_proc.returncode != 0:
                raise RuntimeError(
                    "Flash succeeded, but reboot back to application mode failed: "
                    f"{' '.join([picotool_path, 'reboot'])}"
                )
            return

        last_error_details = (
            f"Command failed ({load_proc.returncode}): {picotool_path} load {elf_path}\n"
            f"{load_proc.stdout}{load_proc.stderr}"
        ).strip()
        if attempt < max_attempts:
            print(f"[flash] attempt {attempt}/{max_attempts} failed; waiting {retry_wait_s:.1f}s before retry")
            time.sleep(retry_wait_s)

    raise RuntimeError(
        "Flash failed after multiple attempts. The Pico likely never reached BOOTSEL cleanly.\n"
        "Check the USB cable/port, close other serial tools, and try reconnecting the board.\n"
        f"{last_error_details}"
    )


def parse_settings_from_lines_with_patterns(lines: list[str], patterns: dict[str, re.Pattern[str]]) -> Dict[str, int]:
    parsed: Dict[str, int] = {}
    for line in lines:
        for key, pat in patterns.items():
            m = pat.search(line)
            if m:
                parsed[key] = int(m.group(1))
    missing = [k for k in patterns.keys() if k not in parsed]
    if missing:
        raise RuntimeError(f"Missing parsed fields from serial output: {missing}")
    return parsed


def parse_settings_from_lines(lines: list[str]) -> Dict[str, int]:
    try:
        return parse_settings_from_lines_with_patterns(lines, CC1352_TARGET_PATTERNS)
    except RuntimeError:
        # Backward compatibility for old firmware logs. New automation should
        # use CC1352 target settings, not CC2500 quantized register values.
        return parse_settings_from_lines_with_patterns(lines, LEGACY_CC2500_PATTERNS)


def read_serial_settings(port: str, baud: int, timeout_s: int, log_file: Path) -> Dict[str, int]:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyserial is required: pip install pyserial") from exc

    deadline = time.time() + timeout_s
    lines: list[str] = []
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with serial.Serial(port, baudrate=baud, timeout=0.3) as ser, log_file.open("w", encoding="utf-8") as fp:
        while time.time() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore").rstrip("\r\n")
            lines.append(line)
            fp.write(line + "\n")
            fp.flush()
            if "CC1352 receiver target settings" in line or "set rx f_carrier" in line:
                # keep reading a bit more to capture the other receiver fields
                time.sleep(0.8)
            try:
                return parse_settings_from_lines(lines)
            except RuntimeError:
                pass

    raise RuntimeError("Timeout waiting for final set rx receiver settings from tag serial output")


def run_single(
    main_c_path: Path,
    project_dir: Path,
    build_dir: Path,
    elf_name: str,
    d0: int,
    d1: int,
    desired_baud: int,
    serial_port: str,
    serial_baud: int,
    serial_timeout_s: int,
    carrier_freq_hz: int,
    enable_build: bool,
    enable_flash: bool,
    picotool_path: str,
    serial_log_file: Path,
) -> Dict[str, int]:
    # Keep the tag-side contract explicit: one run updates one parameter set,
    # then returns the receiver settings derived from the tag's own serial output.
    update_main_c(main_c_path, d0, d1, desired_baud)

    if enable_build:
        build_tag(project_dir, build_dir)

    if enable_flash:
        flash_tag(build_dir, elf_name, picotool_path)

    time.sleep(2)

    parsed = read_serial_settings(serial_port, serial_baud, serial_timeout_s, serial_log_file)
    if int(parsed["rx_base_freq_hz"]) <= 0:
        raise RuntimeError(
            "Parsed CC1352 base_frequency is zero or invalid. "
            "Rebuild/flash the tag so it prints a valid CC1352 receiver target block."
        )
    return parsed


def _cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one tag update/build/flash/serial-parse cycle")
    p.add_argument("--main-c", required=True, type=Path)
    p.add_argument("--project-dir", required=True, type=Path)
    p.add_argument("--build-dir", required=True, type=Path)
    p.add_argument("--elf-name", default="carrier_receiver_baseband.elf")
    p.add_argument("--d0", required=True, type=int)
    p.add_argument("--d1", required=True, type=int)
    p.add_argument("--baud", required=True, type=int)
    p.add_argument("--serial-port", required=True)
    p.add_argument("--serial-baud", default=115200, type=int)
    p.add_argument("--serial-timeout-s", default=20, type=int)
    p.add_argument("--carrier-freq-hz", required=True, type=int)
    p.add_argument("--picotool-path", default="picotool")
    p.add_argument("--enable-build", action="store_true")
    p.add_argument("--enable-flash", action="store_true")
    p.add_argument("--serial-log-file", required=True, type=Path)
    p.add_argument("--output-json", required=True, type=Path)
    return p.parse_args()


def main() -> None:
    args = _cli()
    result = run_single(
        main_c_path=args.main_c,
        project_dir=args.project_dir,
        build_dir=args.build_dir,
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
        serial_log_file=args.serial_log_file,
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
