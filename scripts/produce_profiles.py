"""CLI tool for managing stored produce profiles (Step 7).

Commands:
- warm <names...>: Pre-generates consensus profiles for names and stores them.
- show <name>: Displays stored __manager and __v{N} profiles for a produce name.
- delete <name> [--manager]: Deletes a stored profile (__manager or __v{N}).
- set <name> --file <profile.json>: Validates and stores a manager-corrected profile.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from lastcall_api.ladder.keys import produce_key
from lastcall_api.ladder.profiles import (
    PROFILE_PROMPT_VERSION,
    check_profile,
    resolve_profiles,
)
from lastcall_shared.firestore_store import FirestoreStore
from lastcall_shared.models import ProduceProfile, StageProfile


def get_store() -> FirestoreStore:
    return FirestoreStore()


async def cmd_warm(names: list[str], store: FirestoreStore | None = None) -> None:
    if not names:
        print("Error: No produce names provided.")
        sys.exit(1)

    s = store or get_store()
    print(f"Warming profiles for {len(names)} items: {', '.join(names)}...")
    t0 = time.monotonic()
    deadline = time.monotonic() + 60.0
    profiles, usage, stats = await resolve_profiles(names, store=s, deadline=deadline)
    dur_ms = int((time.monotonic() - t0) * 1000)

    print(f"\nDone in {dur_ms} ms!")
    print(f"Stats: {stats.calls} Gemini vote calls sent | {stats.generated} profiles generated | {stats.fallbacks} fallbacks.")
    print(f"Tokens: {usage.input_tokens} in, {usage.output_tokens} out.")
    for name, p in profiles.items():
        if produce_key(name) == p.name or name == p.name:
            print(f"- {p.name}: key={p.key}, source={p.source}, votes={p.votes}, uncertain={p.uncertain_fields or 'none'}")


async def cmd_show(name: str, store: FirestoreStore | None = None) -> None:
    s = store or get_store()
    pkey = produce_key(name)
    manager_key = f"{pkey}__manager"
    gemini_key = f"{pkey}__v{PROFILE_PROMPT_VERSION}"

    profiles = await s.get_profiles([manager_key, gemini_key])
    if not profiles:
        print(f"No stored profiles found for '{name}' (keys: {manager_key}, {gemini_key}).")
        return

    print(f"=== Stored Profiles for '{name}' (produce_key: '{pkey}') ===")
    if manager_key in profiles:
        print("\n[Manager Override]")
        print(profiles[manager_key].model_dump_json(indent=2))
    else:
        print("\n[Manager Override]: None")

    if gemini_key in profiles:
        print(f"\n[Gemini Consensus Profile (__v{PROFILE_PROMPT_VERSION})]")
        print(profiles[gemini_key].model_dump_json(indent=2))
    else:
        print(f"\n[Gemini Consensus Profile (__v{PROFILE_PROMPT_VERSION})]: None")


async def cmd_delete(name: str, is_manager: bool, store: FirestoreStore | None = None) -> None:
    s = store or get_store()
    pkey = produce_key(name)
    key_to_delete = f"{pkey}__manager" if is_manager else f"{pkey}__v{PROFILE_PROMPT_VERSION}"

    # Verify if exists
    existing = await s.get_profiles([key_to_delete])
    if key_to_delete not in existing:
        print(f"Notice: Profile '{key_to_delete}' did not exist.")
    else:
        await s.delete_profile(key_to_delete)
        print(f"Successfully deleted profile '{key_to_delete}'.")


async def cmd_set(name: str, file_path: str, store: FirestoreStore | None = None) -> None:
    s = store or get_store()
    pkey = produce_key(name)
    path = Path(file_path)
    if not path.is_file():
        print(f"Error: Profile file not found at '{file_path}'.")
        sys.exit(1)

    raw_data = json.loads(path.read_text(encoding="utf-8"))

    # If it's already a full ProduceProfile dict or partial
    raw_data["key"] = f"{pkey}__manager"
    raw_data["name"] = name
    raw_data["source"] = "manager"
    raw_data["prompt_version"] = PROFILE_PROMPT_VERSION
    raw_data["created_at"] = datetime.now(timezone.utc)
    raw_data.setdefault("votes", 1)
    raw_data["uncertain_fields"] = []

    prof = ProduceProfile.model_validate(raw_data)
    checked_prof, corrections = check_profile(prof)

    await s.set_profile(checked_prof)
    print(f"Successfully set manager profile for '{name}' under '{checked_prof.key}'.")
    if corrections:
        print(f"Applied {len(corrections)} standard corrections:")
        for c in corrections:
            print(f"- {c}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage stored produce profiles for Last Call.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # warm
    warm_p = subparsers.add_parser("warm", help="Pre-generate and store profiles.")
    warm_p.add_argument("names", nargs="+", help="Produce names to warm (e.g. banana apple).")

    # show
    show_p = subparsers.add_parser("show", help="Display stored profile(s) for a produce name.")
    show_p.add_argument("name", help="Produce name to show.")

    # delete
    del_p = subparsers.add_parser("delete", help="Delete a stored profile.")
    del_p.add_argument("name", help="Produce name to delete.")
    del_p.add_argument("--manager", action="store_true", help="Delete __manager override instead of __v1.")

    # set
    set_p = subparsers.add_parser("set", help="Set a manager override profile from JSON.")
    set_p.add_argument("name", help="Produce name.")
    set_p.add_argument("--file", required=True, help="Path to profile JSON file.")

    args = parser.parse_args()

    if args.command == "warm":
        asyncio.run(cmd_warm(args.names))
    elif args.command == "show":
        asyncio.run(cmd_show(args.name))
    elif args.command == "delete":
        asyncio.run(cmd_delete(args.name, args.manager))
    elif args.command == "set":
        asyncio.run(cmd_set(args.name, args.file))


if __name__ == "__main__":
    main()
