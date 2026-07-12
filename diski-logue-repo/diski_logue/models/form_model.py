"""
Current Form Model (weight: 25% of the outcome ensemble)
Looks at each team's last N finished matches: points-per-game, goals-for
trend, goals-against trend. Recent matches are weighted more heavily via
exponential decay so a hot/cold streak actually moves the needle.
"""


def _decayed_ppg_and_goals(matches, team_id, decay=0.85):
    """matches: list of dicts from storage.get_team_recent_matches (most recent first)."""
    if not matches:
        return {"ppg": 1.3, "gf_avg": 1.2, "ga_avg": 1.2}  # neutral prior

    weight_sum, points_sum, gf_sum, ga_sum = 0.0, 0.0, 0.0, 0.0
    for i, m in enumerate(matches):
        w = decay ** i
        is_home = m["home_team_id"] == team_id
        gf = m["home_goals"] if is_home else m["away_goals"]
        ga = m["away_goals"] if is_home else m["home_goals"]

        if gf > ga:
            pts = 3
        elif gf == ga:
            pts = 1
        else:
            pts = 0

        weight_sum += w
        points_sum += w * pts
        gf_sum += w * gf
        ga_sum += w * ga

    return {
        "ppg": points_sum / weight_sum,
        "gf_avg": gf_sum / weight_sum,
        "ga_avg": ga_sum / weight_sum,
    }


def team_form(storage, team_id, limit=10):
    matches = storage.get_team_recent_matches(team_id, limit=limit)
    stats = _decayed_ppg_and_goals(matches, team_id)
    stats["matches_considered"] = len(matches)
    return stats


def form_win_draw_loss_probs(home_form, away_form):
    """Converts points-per-game gap into a W/D/L distribution via a simple
    logistic mapping, mirroring the shape of the Elo model but driven by
    short-term form rather than long-term rating."""
    ppg_gap = home_form["ppg"] - away_form["ppg"]  # range roughly -3..3
    home_edge = 1.0 / (1.0 + pow(2.718281828, -ppg_gap))  # sigmoid, 0..1

    draw_prob = max(0.20, 0.32 - abs(ppg_gap) * 0.05)
    home_prob = home_edge * (1 - draw_prob)
    away_prob = (1 - home_edge) * (1 - draw_prob)
    total = home_prob + draw_prob + away_prob
    return {"home": home_prob / total, "draw": draw_prob / total, "away": away_prob / total}
