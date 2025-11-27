#!/usr/bin/env python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path
from typing import Dict, List, Any

DB_PATH = Path(__file__).with_name("print_settings.json")


def load_db() -> Dict[str, List[str]]:
    if not DB_PATH.exists():
        # Start with empty DB if file doesn't exist yet
        return {}
    with DB_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data: Dict[str, List[str]]) -> None:
    with DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved database to {DB_PATH}")


def find_key_case_insensitive(data: Dict[str, Any], name: str) -> str | None:
    """Return the actual key in `data` that matches `name` (case-insensitive)."""
    name_l = name.lower()
    for k in data.keys():
        if k.lower() == name_l:
            return k
    return None


def cmd_list(args: argparse.Namespace) -> None:
    data = load_db()
    if not data:
        print("📂 Database is empty.")
        return
    print("📂 Existing entries:")
    for k in sorted(data.keys(), key=str.lower):
        print(f"  - {k}")


def cmd_show(args: argparse.Namespace) -> None:
    data = load_db()
    key = find_key_case_insensitive(data, args.name)
    if key is None:
        print(f"❌ No entry found for: {args.name}")
        return
    print(f"📘 {key}:")
    for i, rule in enumerate(data[key], start=1):
        print(f"  {i}. {rule}")


def cmd_add(args: argparse.Namespace) -> None:
    data = load_db()
    existing = find_key_case_insensitive(data, args.name)
    if existing is not None:
        print(f"❌ Entry already exists (as '{existing}'). Use 'update' instead.")
        return
    if not args.rule:
        print("❌ You must provide at least one --rule")
        return
    data[args.name] = args.rule
    save_db(data)


def cmd_update(args: argparse.Namespace) -> None:
    data = load_db()
    key = find_key_case_insensitive(data, args.name)
    if key is None:
        print(f"❌ No existing entry for '{args.name}'. Use 'add' instead.")
        return
    if not args.rule:
        print("❌ You must provide at least one --rule")
        return
    data[key] = args.rule
    save_db(data)


def cmd_remove(args: argparse.Namespace) -> None:
    data = load_db()
    key = find_key_case_insensitive(data, args.name)
    if key is None:
        print(f"❌ No entry found for: {args.name}")
        return
    del data[key]
    save_db(data)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Manage print_settings.json (add / remove / modify entries).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # list
    sp = sub.add_parser("list", help="List all entries")
    sp.set_defaults(func_cmd=cmd_list)

    # show
    sp = sub.add_parser("show", help="Show one entry")
    sp.add_argument("name", help="Entry name (case-insensitive)")
    sp.set_defaults(func_cmd=cmd_show)

    # add
    sp = sub.add_parser("add", help="Add a new entry")
    sp.add_argument("name", help="Entry name (e.g. 'singer 3337')")
    sp.add_argument(
        "--rule",
        action="append",
        required=True,
        help="Print rule, e.g. 'monochrome,1-230,duplex,fit,paper=letter'. "
             "Use multiple --rule for multiple lines.",
    )
    sp.set_defaults(func_cmd=cmd_add)

    # update
    sp = sub.add_parser("update", help="Replace rules for an existing entry")
    sp.add_argument("name", help="Entry name (existing)")
    sp.add_argument(
        "--rule",
        action="append",
        required=True,
        help="New rule list (replaces the existing one). "
             "Use multiple --rule for multiple lines.",
    )
    sp.set_defaults(func_cmd=cmd_update)

    # remove
    sp = sub.add_parser("remove", help="Remove an entry")
    sp.add_argument("name", help="Entry name to remove")
    sp.set_defaults(func_cmd=cmd_remove)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func_cmd(args)


if __name__ == "__main__":
    main()

