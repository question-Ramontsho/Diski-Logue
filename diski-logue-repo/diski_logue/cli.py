"""
Diski Logue CLI

Usage:
    python -m diski_logue.cli demo                       # build sample data + predict the demo fixture
    python -m diski_logue.cli fetch --competition PL      # pull real data (needs FOOTBALL_DATA_API_KEY)
    python -m diski_logue.cli predict --home <id> --away <id> --competition <code>
    python -m diski_logue.cli record-result --match-id <id> --home-goals 2 --away-goals 1
    python -m diski_logue.cli dashboard
"""
import argparse
import json
import sys

from .storage import db as storage
from .models import team_strength, ensemble
from .explain import explainer
from .data_sources import sample_data


def cmd_demo(args):
    storage.init_db()
    info = sample_data.generate_season(storage, competition_code="SAMPLE", n_rounds=args.rounds)
    print(f"Generated sample season: {json.dumps(info, indent=2)}")

    team_strength.recompute_all_elo(storage, "SAMPLE")

    with storage.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM matches WHERE match_id=?", (info["upcoming_match_id"],)
        ).fetchone()
        home_id, away_id = row["home_team_id"], row["away_team_id"]
        home_name = conn.execute("SELECT name FROM teams WHERE team_id=?", (home_id,)).fetchone()["name"]
        away_name = conn.execute("SELECT name FROM teams WHERE team_id=?", (away_id,)).fetchone()["name"]

    prediction = ensemble.predict_match(storage, "SAMPLE", home_id, away_id, seed=7)
    explanation = explainer.explain_prediction(prediction, home_name, away_name)

    result = {**prediction, **explanation}
    result.pop("_debug", None)
    storage.save_prediction(info["upcoming_match_id"], result)

    print(f"\n=== Prediction: {home_name} vs {away_name} ===")
    print(json.dumps(result, indent=2))
    print(f"\nStored prediction under match_id={info['upcoming_match_id']}")
    print("Try: python -m diski_logue.cli record-result "
          f"--match-id {info['upcoming_match_id']} --home-goals 2 --away-goals 1")


def cmd_fetch(args):
    from .data_sources.football_data_org import FootballDataClient, sync_competition
    storage.init_db()
    client = FootballDataClient()
    result = sync_competition(client, args.competition, storage)
    team_strength.recompute_all_elo(storage, args.competition)
    print(json.dumps(result, indent=2))


def cmd_predict(args):
    storage.init_db()
    with storage.get_conn() as conn:
        home_name = conn.execute("SELECT name FROM teams WHERE team_id=?", (args.home,)).fetchone()["name"]
        away_name = conn.execute("SELECT name FROM teams WHERE team_id=?", (args.away,)).fetchone()["name"]

    prediction = ensemble.predict_match(storage, args.competition, args.home, args.away)
    explanation = explainer.explain_prediction(prediction, home_name, away_name)
    result = {**prediction, **explanation}
    result.pop("_debug", None)

    if args.match_id:
        storage.save_prediction(args.match_id, result)

    print(json.dumps(result, indent=2))


def cmd_record_result(args):
    storage.init_db()
    scoring = storage.record_result_and_score(args.match_id, args.home_goals, args.away_goals)
    if scoring is None:
        print(f"No stored prediction found for match_id={args.match_id}")
        sys.exit(1)
    print(json.dumps(scoring, indent=2))


def cmd_dashboard(args):
    storage.init_db()
    print(json.dumps(storage.dashboard_stats(), indent=2))


def cmd_find_league(args):
    from .data_sources.api_football import ApiFootballClient
    client = ApiFootballClient()
    results = client.find_league(args.search, country=args.country)
    print(json.dumps(results, indent=2))
    if results:
        print("\nFound the league? Add its 'id' to diski_logue/competitions_config.json "
              "under the matching entry's \"league_id\" field.")


def cmd_fetch_api_football(args):
    from .data_sources.api_football import ApiFootballClient, sync_competition
    storage.init_db()
    client = ApiFootballClient()
    result = sync_competition(client, args.code, args.league_id, args.season, storage)
    team_strength.recompute_all_elo(storage, args.code)
    print(json.dumps(result, indent=2))


def cmd_import_csv(args):
    from .data_sources import csv_import
    storage.init_db()
    result = csv_import.import_matches_csv(storage, args.code, args.matches)
    print(f"Matches: {json.dumps(result, indent=2)}")
    if args.scorers:
        result2 = csv_import.import_scorers_csv(storage, args.code, args.scorers)
        print(f"Scorers: {json.dumps(result2, indent=2)}")
    team_strength.recompute_all_elo(storage, args.code)


def cmd_sync_all(args):
    from .scripts import sync_all
    import sys as _sys
    argv_backup = _sys.argv
    _sys.argv = ["sync_all"] + (["--only", args.only] if args.only else [])
    try:
        sync_all.main()
    finally:
        _sys.argv = argv_backup


def main():
    parser = argparse.ArgumentParser(prog="diski_logue")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="Generate sample data and run a full prediction end-to-end")
    p_demo.add_argument("--rounds", type=int, default=8)
    p_demo.set_defaults(func=cmd_demo)

    p_fetch = sub.add_parser("fetch", help="Pull real data from football-data.org")
    p_fetch.add_argument("--competition", required=True, help="e.g. PL, PD, BSA")
    p_fetch.set_defaults(func=cmd_fetch)

    p_predict = sub.add_parser("predict", help="Predict a specific fixture")
    p_predict.add_argument("--home", required=True)
    p_predict.add_argument("--away", required=True)
    p_predict.add_argument("--competition", required=True)
    p_predict.add_argument("--match-id", default=None)
    p_predict.set_defaults(func=cmd_predict)

    p_record = sub.add_parser("record-result", help="Feed back the real result for learning")
    p_record.add_argument("--match-id", required=True)
    p_record.add_argument("--home-goals", type=int, required=True)
    p_record.add_argument("--away-goals", type=int, required=True)
    p_record.set_defaults(func=cmd_record_result)

    p_dash = sub.add_parser("dashboard", help="Show performance dashboard stats")
    p_dash.set_defaults(func=cmd_dashboard)

    p_find = sub.add_parser("find-league", help="Look up an API-Football league ID by name")
    p_find.add_argument("--search", required=True)
    p_find.add_argument("--country", default=None)
    p_find.set_defaults(func=cmd_find_league)

    p_af = sub.add_parser("fetch-api-football", help="Pull data from API-Football for a competition")
    p_af.add_argument("--code", required=True, help="Short code you're assigning, e.g. PSL, AFCON")
    p_af.add_argument("--league-id", type=int, required=True)
    p_af.add_argument("--season", type=int, required=True)
    p_af.set_defaults(func=cmd_fetch_api_football)

    p_csv = sub.add_parser("import-csv", help="Import a league with no API coverage from CSV")
    p_csv.add_argument("--code", required=True, help="Short code, e.g. BW_PREMIER")
    p_csv.add_argument("--matches", required=True)
    p_csv.add_argument("--scorers", default=None)
    p_csv.set_defaults(func=cmd_import_csv)

    p_sync = sub.add_parser("sync-all", help="Sync every competition in competitions_config.json")
    p_sync.add_argument("--only", default=None, help="Comma-separated codes to limit to")
    p_sync.set_defaults(func=cmd_sync_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
