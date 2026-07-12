"""
Explainable Prediction Engine
Turns the ensemble's internal debug numbers into a ranked list of factors
and a plain-language explanation — the "why" behind every prediction.
"""


def _factor_strength(value_home, value_away, label, higher_is_home_favoring=True):
    diff = value_home - value_away
    magnitude = abs(diff)
    if not higher_is_home_favoring:
        diff = -diff
    favors = "home" if diff > 0 else ("away" if diff < 0 else "neutral")
    return {"factor": label, "magnitude": round(magnitude, 3), "favors": favors}


def build_factors(prediction, home_name, away_name):
    dbg = prediction["_debug"]
    factors = [
        _factor_strength(dbg["home_elo"], dbg["away_elo"], "Team strength (Elo rating)"),
        _factor_strength(dbg["home_form"]["ppg"], dbg["away_form"]["ppg"], "Recent form (points per game)"),
        _factor_strength(
            prediction["expected_goals"]["home"], prediction["expected_goals"]["away"],
            "Expected goals (attack vs defense matchup)"
        ),
        _factor_strength(dbg["home_form"]["gf_avg"], dbg["home_form"]["ga_avg"],
                          f"{home_name} scoring vs conceding trend"),
        _factor_strength(dbg["away_form"]["gf_avg"], dbg["away_form"]["ga_avg"],
                          f"{away_name} scoring vs conceding trend"),
    ]
    factors.sort(key=lambda f: -f["magnitude"])
    return factors


def natural_language_explanation(prediction, home_name, away_name, factors):
    outcome = prediction["predicted_outcome"]
    probs = prediction["outcome_probabilities"]
    conf = prediction["confidence"]

    outcome_text = {
        "home": f"{home_name} to win",
        "away": f"{away_name} to win",
        "draw": "a draw",
    }[outcome]

    top_factor = factors[0]
    favored_team = home_name if top_factor["favors"] == "home" else (
        away_name if top_factor["favors"] == "away" else "neither side"
    )

    lines = [
        f"Diski Logue favors {outcome_text} "
        f"(Home {probs['home']*100:.0f}% / Draw {probs['draw']*100:.0f}% / Away {probs['away']*100:.0f}%), "
        f"with a confidence score of {conf:.2f}.",
        f"The strongest factor is '{top_factor['factor']}', which leans toward {favored_team}.",
        f"Expected goals: {home_name} {prediction['expected_goals']['home']} — "
        f"{prediction['expected_goals']['away']} {away_name}. "
        f"Most likely scoreline: {prediction['most_likely_scoreline']}.",
    ]

    if conf < 0.55:
        lines.append(
            "Confidence is relatively low — the two sides are closely matched and/or "
            "one team has limited recent match history, which increases unpredictability."
        )

    return " ".join(lines)


def explain_prediction(prediction, home_name, away_name):
    factors = build_factors(prediction, home_name, away_name)
    explanation = natural_language_explanation(prediction, home_name, away_name, factors)
    return {
        "top_factors": factors[:5],
        "explanation": explanation,
    }
