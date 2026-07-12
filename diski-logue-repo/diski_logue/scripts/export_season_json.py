"""
Export enriched season data to docs/data/season.json for the static website.

Runs the same aggregation the CLI uses (Elo, form, attack/defense ratings)
ONCE server-side (here, or in the GitHub Action), then hands the browser
pre-aggregated per-team stats. The browser still does the LIVE part itself:
given any two teams the visitor picks, it runs the Monte Carlo simulation,
blends the ensemble, and generates the explanation on the fly — that's the
part that has to feel "live," and it's cheap enough to run instantly in JS.

Usage:
    python -m diski_logue.scripts.export_season_json --competition SAMPLE
    python -m diski_logue.scripts.export_season_json --competition PL --fetch
"""
import argparse
import json
from pathlib import Path

from ..storage import db as storage
from ..models import team_strength, form_model, goals_model
from ..data_sources import sample_data

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "data"


def export(competition_code: str, output_name: str = None):
    output_name = output_name or competition_code
    team_strength.recompute_all_elo(storage, competition_code)
    ratings, league_avg = goals_model.team_attack_defense_ratings(storage, competition_code)

    with storage.get_conn() as conn:
        teams = conn.execute(
            "SELECT team_id, name FROM teams WHERE competition=?", (competition_code,)
        ).fetchall()

    teams_out = []
    for t in teams:
        team_id, name = t["team_id"], t["name"]
        elo = storage.get_team_elo(team_id)
        form = form_model.team_form(storage, team_id)
        r = ratings.get(team_id, {"attack": 1.0, "defense": 1.0, "matches": 0})

        with storage.get_conn() as conn:
            scorer_rows = conn.execute(
                "SELECT player_name, goals FROM scorers WHERE team_id=? ORDER BY goals DESC LIMIT 5",
                (team_id,),
            ).fetchall()
        total_goals = sum(s["goals"] for s in scorer_rows) or 1
        scorers = [
            {"player": s["player_name"], "goals": s["goals"], "share": round(s["goals"] / total_goals, 4)}
            for s in scorer_rows
        ]

        teams_out.append({
            "id": team_id,
            "name": name,
            "elo": round(elo, 1),
            "form": {
                "ppg": round(form["ppg"], 3),
                "gf_avg": round(form["gf_avg"], 3),
                "ga_avg": round(form["ga_avg"], 3),
                "matches_considered": form["matches_considered"],
            },
            "attack": round(r["attack"], 4),
            "defense": round(r["defense"], 4),
            "scorers": scorers,
        })

    teams_out.sort(key=lambda t: t["name"])

    with storage.get_conn() as conn:
        last_match = conn.execute(
            "SELECT MAX(date) as d FROM matches WHERE competition=? AND status='FINISHED'",
            (competition_code,),
        ).fetchone()

    payload = {
        "competition": competition_code,
        "league_avg_goals": round(league_avg, 4),
        "generated_at_last_match": last_match["d"],
        "teams": teams_out,
    }

    output_path = OUTPUT_DIR / f"{output_name}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {len(teams_out)} teams to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition", required=True)
    parser.add_argument("--fetch", action="store_true", help="Pull fresh data from football-data.org first")
    parser.add_argument("--rounds", type=int, default=10, help="Only used with --sample")
    parser.add_argument("--sample", action="store_true", help="Generate synthetic data first (for local testing)")
    args = parser.parse_args()

    storage.init_db()

    if args.sample:
        sample_data.generate_season(storage, competition_code=args.competition, n_rounds=args.rounds)
    elif args.fetch:
        from ..data_sources.football_data_org import FootballDataClient, sync_competition
        client = FootballDataClient()
        sync_competition(client, args.competition, storage)

    export(args.competition)


if __name__ == "__main__":
    main()
