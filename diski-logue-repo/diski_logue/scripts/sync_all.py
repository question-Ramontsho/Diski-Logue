"""
Diski Logue — Sync All Competitions

Reads competitions_config.json, syncs each competition from its configured
source (football-data.org, API-Football, CSV, or synthetic sample data),
exports each to docs/data/<code>.json, and writes docs/data/manifest.json
so the website knows which competitions are available.

Usage:
    python -m diski_logue.scripts.sync_all
    python -m diski_logue.scripts.sync_all --only PL,WC
"""
import argparse
import json
import os
from pathlib import Path

from ..storage import db as storage
from ..models import team_strength
from . import export_season_json

CONFIG_PATH = Path(__file__).resolve().parent.parent / "competitions_config.json"
MANIFEST_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "data" / "manifest.json"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def load_config():
    with open(CONFIG_PATH) as f:
        data = json.load(f)
    return data["competitions"]


def sync_one(entry):
    code = entry["code"]
    source = entry["source"]

    if source == "sample":
        from ..data_sources import sample_data
        sample_data.generate_season(storage, competition_code=code, n_rounds=entry.get("rounds", 10))
        return True

    if source == "football_data":
        from ..data_sources.football_data_org import FootballDataClient, sync_competition
        if not os.environ.get("FOOTBALL_DATA_API_KEY"):
            print(f"  [{code}] skipped — FOOTBALL_DATA_API_KEY not set")
            return False
        client = FootballDataClient()
        sync_competition(client, entry["param"], storage)
        return True

    if source == "api_football":
        if entry.get("league_id") is None:
            print(f"  [{code}] skipped — league_id not set. Run: "
                  f"python -m diski_logue.cli find-league --search \"{entry['name']}\"")
            return False
        if not os.environ.get("API_FOOTBALL_KEY"):
            print(f"  [{code}] skipped — API_FOOTBALL_KEY not set")
            return False
        from ..data_sources.api_football import ApiFootballClient, sync_competition
        client = ApiFootballClient()
        sync_competition(client, code, entry["league_id"], entry["season"], storage)
        return True

    if source == "csv":
        matches_path = REPO_ROOT / entry["matches_csv"]
        if not matches_path.exists():
            print(f"  [{code}] skipped — {matches_path} not found. "
                  f"Create it (see diski_logue/data_sources/csv_import.py for format).")
            return False
        from ..data_sources import csv_import
        csv_import.import_matches_csv(storage, code, str(matches_path))
        scorers_path = REPO_ROOT / entry.get("scorers_csv", "")
        if entry.get("scorers_csv") and scorers_path.exists():
            csv_import.import_scorers_csv(storage, code, str(scorers_path))
        return True

    print(f"  [{code}] skipped — unknown source '{source}'")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="Comma-separated list of codes to sync (default: all)")
    args = parser.parse_args()

    storage.init_db()
    competitions = load_config()
    if args.only:
        wanted = set(args.only.split(","))
        competitions = [c for c in competitions if c["code"] in wanted]

    manifest_entries = []
    for entry in competitions:
        code = entry["code"]
        print(f"Syncing {code} ({entry['name']}) via {entry['source']}...")
        ok = sync_one(entry)
        if not ok:
            continue

        team_strength.recompute_all_elo(storage, code)
        with storage.get_conn() as conn:
            n_teams = conn.execute("SELECT COUNT(*) c FROM teams WHERE competition=?", (code,)).fetchone()["c"]
        if n_teams == 0:
            print(f"  [{code}] no teams found after sync, skipping export")
            continue

        export_season_json.export(code, output_name=code)
        manifest_entries.append({"code": code, "name": entry["name"], "file": f"data/{code}.json"})

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps({"competitions": manifest_entries}, indent=2))
    print(f"\nWrote manifest with {len(manifest_entries)} competition(s) to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
