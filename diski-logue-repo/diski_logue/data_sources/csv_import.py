"""
Diski Logue — Manual CSV Import

Neither football-data.org nor API-Football has confirmed coverage of
Botswana's local leagues. Rather than guess, this gives you a direct path
to feed in results yourself — from league websites, BFA (Botswana Football
Association) bulletins, or your own records — and get the exact same
modeling (Elo, form, Poisson goals, explainability) as every other
competition in this project.

CSV format (finished matches):
    date,home_team,away_team,home_goals,away_goals
    2026-02-01,Township Rollers,Jwaneng Galaxy,2,1
    2026-02-08,Gaborone United,Security Systems FC,0,0

CSV format (top scorers, optional, separate file):
    team,player,goals
    Township Rollers,K. Mothibi,9

Usage:
    python -m diski_logue.data_sources.csv_import \
        --code BW_PREMIER --matches data/bw_premier_matches.csv \
        --scorers data/bw_premier_scorers.csv
"""
import argparse
import csv
import hashlib


def _match_id(code, date, home, away):
    raw = f"{code}|{date}|{home}|{away}"
    return "CSV" + hashlib.md5(raw.encode()).hexdigest()[:12]


def _team_id(code, name):
    return "CSV" + hashlib.md5(f"{code}|{name}".encode()).hexdigest()[:8]


def import_matches_csv(storage, code: str, csv_path: str):
    seen_teams = set()
    n_matches = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"date", "home_team", "away_team", "home_goals", "away_goals"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        for row in reader:
            home_name = row["home_team"].strip()
            away_name = row["away_team"].strip()
            home_id = _team_id(code, home_name)
            away_id = _team_id(code, away_name)

            if home_id not in seen_teams:
                storage.upsert_team(home_id, home_name, code)
                seen_teams.add(home_id)
            if away_id not in seen_teams:
                storage.upsert_team(away_id, away_name, code)
                seen_teams.add(away_id)

            storage.upsert_match(
                match_id=_match_id(code, row["date"], home_name, away_name),
                competition=code,
                date=row["date"],
                home_id=home_id,
                away_id=away_id,
                home_goals=int(row["home_goals"]),
                away_goals=int(row["away_goals"]),
                status="FINISHED",
            )
            n_matches += 1

    return {"teams": len(seen_teams), "matches": n_matches}


def import_scorers_csv(storage, code: str, csv_path: str):
    n = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"team", "player", "goals"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        with storage.get_conn() as conn:
            for row in reader:
                team_id = _team_id(code, row["team"].strip())
                conn.execute(
                    """INSERT INTO scorers (team_id, player_name, goals)
                       VALUES (?, ?, ?)
                       ON CONFLICT(team_id, player_name) DO UPDATE SET goals=excluded.goals""",
                    (team_id, row["player"].strip(), int(row["goals"])),
                )
                n += 1
    return {"scorer_rows": n}


def main():
    from ..storage import db as storage

    parser = argparse.ArgumentParser()
    parser.add_argument("--code", required=True, help="Short competition code, e.g. BW_PREMIER")
    parser.add_argument("--matches", required=True, help="Path to matches CSV")
    parser.add_argument("--scorers", default=None, help="Path to scorers CSV (optional)")
    args = parser.parse_args()

    storage.init_db()
    result = import_matches_csv(storage, args.code, args.matches)
    print(f"Matches: {result}")

    if args.scorers:
        result2 = import_scorers_csv(storage, args.code, args.scorers)
        print(f"Scorers: {result2}")


if __name__ == "__main__":
    main()
