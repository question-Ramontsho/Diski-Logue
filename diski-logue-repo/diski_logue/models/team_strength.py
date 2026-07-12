"""
Team Strength Model (weight: 30% of the outcome ensemble)
Elo rating updated after every finished match. Standard chess-Elo formula,
tuned with a football-appropriate K-factor and goal-difference multiplier.
"""

K_FACTOR = 24
HOME_ADVANTAGE_ELO = 60  # elo points added to home team's expected-score calc


def expected_score(rating_a, rating_b):
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_elo_after_match(home_elo, away_elo, home_goals, away_goals):
    """Returns (new_home_elo, new_away_elo)."""
    exp_home = expected_score(home_elo + HOME_ADVANTAGE_ELO, away_elo)
    exp_away = 1 - exp_home

    if home_goals > away_goals:
        actual_home, actual_away = 1.0, 0.0
    elif home_goals < away_goals:
        actual_home, actual_away = 0.0, 1.0
    else:
        actual_home, actual_away = 0.5, 0.5

    # Goal-difference multiplier (bigger wins move rating more)
    gd = abs(home_goals - away_goals)
    multiplier = 1.0 if gd <= 1 else (1.5 if gd == 2 else 1.75)

    new_home = home_elo + K_FACTOR * multiplier * (actual_home - exp_home)
    new_away = away_elo + K_FACTOR * multiplier * (actual_away - exp_away)
    return new_home, new_away


def recompute_all_elo(storage, competition_code):
    """Replays finished matches in date order to build current Elo ratings."""
    with storage.get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM matches WHERE competition=? AND status='FINISHED'
               ORDER BY date ASC""",
            (competition_code,),
        ).fetchall()

    ratings = {}
    for m in rows:
        h, a = m["home_team_id"], m["away_team_id"]
        h_elo = ratings.get(h, 1500.0)
        a_elo = ratings.get(a, 1500.0)
        new_h, new_a = update_elo_after_match(h_elo, a_elo, m["home_goals"], m["away_goals"])
        ratings[h] = new_h
        ratings[a] = new_a

    for team_id, elo in ratings.items():
        storage.set_team_elo(team_id, elo)
    return ratings


def strength_win_draw_loss_probs(home_elo, away_elo):
    """Elo-implied W/D/L. Draw probability modeled as a function of rating
    closeness (closer ratings -> higher draw chance), a common heuristic
    since raw Elo only gives a binary expected score."""
    exp_home = expected_score(home_elo + HOME_ADVANTAGE_ELO, away_elo)
    rating_gap = abs((home_elo + HOME_ADVANTAGE_ELO) - away_elo)
    draw_prob = max(0.18, 0.30 - rating_gap / 1000.0)

    home_prob = exp_home * (1 - draw_prob)
    away_prob = (1 - exp_home) * (1 - draw_prob)
    total = home_prob + draw_prob + away_prob
    return {"home": home_prob / total, "draw": draw_prob / total, "away": away_prob / total}
