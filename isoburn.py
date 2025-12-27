#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import subprocess
from pathlib import Path
from typing import List, Optional

ISO_FOLDER = r"C:\Users\benoi\Downloads\Lightscribe"


def list_iso_files(folder: str) -> List[Path]:
    """Return all .iso files in `folder` (non-recursive), sorted by name."""
    p = Path(folder)
    if not p.is_dir():
        return []
    return sorted(
        [f for f in p.iterdir() if f.is_file() and f.suffix.lower() == ".iso"],
        key=lambda x: x.name.lower(),
    )


def find_matches(iso_files: List[Path], partial_name: str) -> List[Path]:
    """Filter ISO files by case-insensitive substring match."""
    q = partial_name.lower().strip()
    return [f for f in iso_files if q in f.name.lower()]


def prompt_for_query() -> str:
    return input("Enter ISO filename (partial match ok): ").strip()


def prompt_pick_match(matches: List[Path]) -> Optional[Path]:
    if not matches:
        return None

    print("\nMatching ISO files:")
    for idx, f in enumerate(matches, start=1):
        print(f"{idx}. {f.name}")

    choice = input("\nEnter the number of the ISO you want to burn: ").strip()
    if not choice.isdigit():
        print("Invalid choice.")
        return None

    n = int(choice)
    if not (1 <= n <= len(matches)):
        print("Choice out of range.")
        return None

    return matches[n - 1]


def run_cmd(cmd: List[str]) -> int:
    print("\nRunning:")
    print("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        print(f"ERROR: Command not found: {cmd[0]}")
        return 127


# ---------------- burners ----------------

def burn_isoburn(iso_path: Path, drive_letter: str = "D:") -> int:
    cmd = [
        "cmd.exe",
        "/c",
        "isoburn.exe",
        "/Q",
        drive_letter,
        str(iso_path.resolve()),
    ]
    return run_cmd(cmd)


def burn_cdburnerxp(iso_path: Path, exe_path: str, device: int) -> int:
    cmd = [
        exe_path,
        "--burn-iso",
        f"-device:{device}",
        f"-file:{iso_path.resolve()}",
    ]
    return run_cmd(cmd)


def burn_cdrecord(iso_path: Path, exe_path: str, dev: str, speed: int) -> int:
    cmd = [
        exe_path,
        "-v",
        f"dev={dev}",
        f"speed={speed}",
        "-dao",
        "-driveropts=burnfree",
        "-data",
        str(iso_path.resolve()),
    ]
    return run_cmd(cmd)


# ---------------- main ----------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select an ISO file and burn it using isoburn, CDBurnerXP, or cdrecord."
    )

    parser.add_argument(
        "--folder",
        default=ISO_FOLDER,
        help=f"Folder containing ISO files (default: {ISO_FOLDER})",
    )

    parser.add_argument(
        "--burner",
        choices=["isoburn", "cdburnerxp", "cdrecord"],
        default="isoburn",
        help="Burner backend to use (default: isoburn).",
    )

    # isoburn
    parser.add_argument(
        "--drive",
        default="D:",
        help='Drive letter for isoburn (default: "D:").',
    )

    # CDBurnerXP
    parser.add_argument(
        "--cdburnerxp",
        default=r"C:\Program Files\CDBurnerXP\cdbxpcmd.exe",
        help="Path to cdbxpcmd.exe (default: Program Files\\CDBurnerXP).",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=0,
        help="Device index for CDBurnerXP (default: 0).",
    )

    # cdrecord
    parser.add_argument(
        "--cdrecord",
        default=r"C:\PortableApps\CDRTools\cdrecord.exe",
        help="Path to cdrecord.exe.",
    )
    parser.add_argument(
        "--dev",
        default="0,0,0",
        help='cdrecord dev value (default: "0,0,0").',
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=32,
        help="cdrecord speed (default: 32).",
    )

    args = parser.parse_args()

    iso_files = list_iso_files(args.folder)
    if not iso_files:
        print(f"No ISO files found in {args.folder}")
        return 1

    query = prompt_for_query()
    matches = find_matches(iso_files, query)

    if not matches:
        print(f"No ISO found containing: {query}")
        return 1

    iso = prompt_pick_match(matches)
    if not iso:
        return 1

    print(f"\nSelected ISO: {iso.name}")

    if args.burner == "isoburn":
        return burn_isoburn(iso, args.drive)

    if args.burner == "cdburnerxp":
        return burn_cdburnerxp(iso, args.cdburnerxp, args.device)

    if args.burner == "cdrecord":
        return burn_cdrecord(iso, args.cdrecord, args.dev, args.speed)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
