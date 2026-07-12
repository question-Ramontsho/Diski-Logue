"""
Ensemble AI Prediction Engine
Combines Team Strength (Elo), Current Form, and the Poisson/Monte Carlo
Goals Model into final outcome probabilities, per the weighting scheme in
the FIPS architecture doc. v1.0 uses 3 of the 6 specified sub-models
(Context, Tactical Compatibility, and Player Impact are v2.0 — they need
richer data than a free-tier API and match results alone provide). Weights
are renormalized across the models actually in play.

v1.0 weights (renormalized from the doc's 30/25/15/10/10/10):
  Team Strength (Elo): 30 / 65 = 46.2%
  Current Form:        25 / 65 = 38.5%
  Goals Model (Poisson):10 / 65 = 15.4%
"""
from . import team_strength, form_model, goals_model
from .scorer_model import anytime_scorer_probabilities, first_goalscorer_probabilities

WEIGHTS = {"team_strength": 30, "form": 25, "goals": 10}
TOTAL_WEIGHT = sum(WEIGHTS.values())


def _blend(probs_list, weights):
    blended = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for probs, w in zip(probs_list, weights):
        for k in blended:
            blended[k] += probs[k] * w
    total = sum(blended.values())
    return {k: round(v / total, 4) for k, v in blended.items()}


def confidence_score(probs, unpredictability_penalty=0.0):
    """Confidence = how decisively the top outcome beats the rest, penalized
    by an unpredictability factor (data volume, rating closeness, etc.)."""
    sorted_probs = sorted(probs.values(), reverse=True)
    margin = sorted_probs[0] - sorted_probs[1]  # gap between 1st and 2nd choice
    raw_confidence = 0.5 + margin  # 0.5 baseline, up to ~1.0
    return round(max(0.3, min(0.97, raw_confidence - unpredictability_penalty)), 3)


def predict_match(storage, competition_code, home_id, away_id, n_simulations=10000, seed=None):
    # --- Team Strength (Elo) ---
    home_elo = storage.get_team_elo(home_id)
    away_elo = storage.get_team_elo(away_id)
    strength_probs = team_strength.strength_win_draw_loss_probs(home_elo, away_elo)

    # --- Current Form ---
    home_form = form_model.team_form(storage, home_id)
    away_form = form_model.team_form(storage, away_id)
    form_probs = form_model.form_win_draw_loss_probs(home_form, away_form)

    # --- Goals Model / Monte Carlo ---
    ratings, league_avg = goals_model.team_attack_defense_ratings(storage, competition_code)
    home_lambda, away_lambda = goals_model.expected_goals(home_id, away_id, ratings, league_avg)
    sim = goals_model.monte_carlo_simulation(home_lambda, away_lambda, n_runs=n_simulations, seed=seed)
    goals_probs = sim["poisson_outcome_probabilities"]

    # --- Blend ---
    outcome_probs = _blend(
        [strength_probs, form_probs, goals_probs],
        [WEIGHTS["team_strength"], WEIGHTS["form"], WEIGHTS["goals"]],
    )

    # Data-volume based unpredictability penalty: thin match history -> less confidence
    min_matches = min(home_form["matches_considered"], away_form["matches_considered"])
    unpredictability_penalty = 0.0 if min_matches >= 5 else (5 - min_matches) * 0.03
    confidence = confidence_score(outcome_probs, unpredictability_penalty)

    # --- Goalscorers ---
    home_scorers = anytime_scorer_probabilities(storage, home_id, home_lambda)
    away_scorers = anytime_scorer_probabilities(storage, away_id, away_lambda)
    first_scorers = first_goalscorer_probabilities(storage, home_id, away_id, home_lambda, away_lambda)

    predicted_outcome = max(outcome_probs, key=outcome_probs.get)

    return {
        "predicted_outcome": predicted_outcome,
        "outcome_probabilities": outcome_probs,
        "confidence": confidence,
        "expected_goals": {"home": round(home_lambda, 2), "away": round(away_lambda, 2)},
        "most_likely_scoreline": sim["most_likely_scoreline"],
        "top_scorelines": sim["top_scorelines"],
        "markets": {
            "btts_probability": sim["btts_probability"],
            "over_2_5_probability": sim["over_2_5_probability"],
            "under_2_5_probability": sim["under_2_5_probability"],
            "home_clean_sheet_probability": sim["home_clean_sheet_probability"],
            "away_clean_sheet_probability": sim["away_clean_sheet_probability"],
        },
        "goalscorers": {
            "first_goalscorer_top3": first_scorers[:3],
            "home_anytime_scorers": home_scorers,
            "away_anytime_scorers": away_scorers,
        },
        "_debug": {
            "home_elo": round(home_elo, 1), "away_elo": round(away_elo, 1),
            "strength_probs": strength_probs,
            "home_form": home_form, "away_form": away_form,
            "form_probs": form_probs,
            "goals_probs": goals_probs,
            "n_simulations": n_simulations,
        },
    }
