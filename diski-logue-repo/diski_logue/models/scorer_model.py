"""
Goalscorer Model
Distributes a team's expected-goals (lambda) across its top scorers based on
their season goal-share, then converts "expected goals for this player" into
a first-goalscorer / anytime-goalscorer probability via a Poisson approximation.
"""
import math


def _player_goal_shares(storage, team_id, top_n=5):
    with storage.get_conn() as conn:
        rows = conn.execute(
            "SELECT player_name, goals FROM scorers WHERE team_id=? ORDER BY goals DESC LIMIT ?",
            (team_id, top_n),
        ).fetchall()
    total = sum(r["goals"] for r in rows) or 1
    return [{"player": r["player_name"], "share": r["goals"] / total} for r in rows]


def anytime_scorer_probabilities(storage, team_id, team_lambda, top_n=3):
    shares = _player_goal_shares(storage, team_id, top_n=top_n)
    results = []
    for s in shares:
        player_lambda = team_lambda * s["share"]
        p_score_at_least_once = 1 - math.exp(-player_lambda)  # Poisson(0) complement
        results.append({
            "player": s["player"],
            "anytime_scorer_probability": round(p_score_at_least_once, 4),
        })
    return results


def first_goalscorer_probabilities(storage, home_id, away_id, home_lambda, away_lambda, top_n=3):
    """Approximates P(this player scores THE first goal of the match) as:
       P(player's team scores first) x (player's share of that team's goals)
    P(team scores first) is derived from the two teams' expected-goals rates
    — the team more likely to score early gets proportionally more weight.
    This is a standard simplification ahead of full minute-by-minute
    simulation, which is scoped for v2."""
    total_lambda = home_lambda + away_lambda
    if total_lambda == 0:
        return []

    p_home_scores_first = home_lambda / total_lambda
    p_away_scores_first = 1 - p_home_scores_first

    results = []
    for team_id, p_team_first in ((home_id, p_home_scores_first), (away_id, p_away_scores_first)):
        for s in _player_goal_shares(storage, team_id, top_n=top_n):
            results.append({
                "player": s["player"],
                "first_goalscorer_probability": round(p_team_first * s["share"], 4),
            })

    return sorted(results, key=lambda r: -r["first_goalscorer_probability"])
