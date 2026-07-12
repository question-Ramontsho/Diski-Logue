"""
Goals Model + Match Simulation Engine (goals model weight: 10% of outcome
ensemble; scorelines/markets are derived entirely from this module).

Approach:
  1. Estimate expected goals (lambda) for each team from their season-long
     goals-for/against averages adjusted by opponent strength and home
     advantage (a simplified Dixon-Coles style attack/defense rating).
  2. Run a Monte Carlo simulation (10,000 runs) sampling independent Poisson
     goal counts per team, per the architecture doc. This produces the full
     scoreline distribution, BTTS, Over/Under 2.5, and clean-sheet
     probabilities empirically rather than analytically — cheap here, but
     the same code path scales cleanly once dependencies (e.g. a
     Dixon-Coles low-score correlation adjustment) are added in v2.
"""
import random
from collections import Counter
from .poisson_utils import poisson_sample

LEAGUE_AVG_GOALS = 1.35  # roughly matches most professional leagues


def team_attack_defense_ratings(storage, competition_code):
    """Simple attack/defense strength relative to league average, from all
    finished matches in the competition."""
    with storage.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE competition=? AND status='FINISHED'",
            (competition_code,),
        ).fetchall()

    gf, ga, played = {}, {}, {}
    league_goals, league_matches = 0, 0
    for m in rows:
        for team_id, scored, conceded in (
            (m["home_team_id"], m["home_goals"], m["away_goals"]),
            (m["away_team_id"], m["away_goals"], m["home_goals"]),
        ):
            gf[team_id] = gf.get(team_id, 0) + scored
            ga[team_id] = ga.get(team_id, 0) + conceded
            played[team_id] = played.get(team_id, 0) + 1
        league_goals += m["home_goals"] + m["away_goals"]
        league_matches += 1

    league_avg = (league_goals / (2 * league_matches)) if league_matches else LEAGUE_AVG_GOALS

    ratings = {}
    for team_id in played:
        n = played[team_id]
        attack = (gf[team_id] / n) / league_avg if league_avg else 1.0
        defense = (ga[team_id] / n) / league_avg if league_avg else 1.0
        ratings[team_id] = {"attack": attack, "defense": defense, "matches": n}
    return ratings, league_avg


def expected_goals(home_id, away_id, ratings, league_avg, home_advantage=1.12):
    home_r = ratings.get(home_id, {"attack": 1.0, "defense": 1.0})
    away_r = ratings.get(away_id, {"attack": 1.0, "defense": 1.0})

    home_lambda = league_avg * home_r["attack"] * away_r["defense"] * home_advantage
    away_lambda = league_avg * away_r["attack"] * home_r["defense"]
    return max(0.15, home_lambda), max(0.15, away_lambda)


def monte_carlo_simulation(home_lambda, away_lambda, n_runs=10000, seed=None):
    rng = random.Random(seed)
    scoreline_counts = Counter()
    btts_count, over25_count = 0, 0
    home_cs, away_cs = 0, 0
    home_wins, draws, away_wins = 0, 0, 0

    for _ in range(n_runs):
        hg = poisson_sample(rng, home_lambda)
        ag = poisson_sample(rng, away_lambda)
        scoreline_counts[(hg, ag)] += 1

        if hg > 0 and ag > 0:
            btts_count += 1
        if hg + ag > 2.5:
            over25_count += 1
        if ag == 0:
            home_cs += 1
        if hg == 0:
            away_cs += 1
        if hg > ag:
            home_wins += 1
        elif hg < ag:
            away_wins += 1
        else:
            draws += 1

    top_scorelines = [
        {"score": f"{h}-{a}", "probability": round(count / n_runs, 4)}
        for (h, a), count in scoreline_counts.most_common(5)
    ]

    return {
        "top_scorelines": top_scorelines,
        "most_likely_scoreline": top_scorelines[0]["score"],
        "btts_probability": round(btts_count / n_runs, 4),
        "over_2_5_probability": round(over25_count / n_runs, 4),
        "under_2_5_probability": round(1 - over25_count / n_runs, 4),
        "home_clean_sheet_probability": round(home_cs / n_runs, 4),
        "away_clean_sheet_probability": round(away_cs / n_runs, 4),
        "poisson_outcome_probabilities": {
            "home": round(home_wins / n_runs, 4),
            "draw": round(draws / n_runs, 4),
            "away": round(away_wins / n_runs, 4),
        },
        "n_simulations": n_runs,
    }
