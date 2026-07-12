"""
Diski Logue — Sample Data Generator

Generates a synthetic league season (teams + finished results + scorers +
one upcoming fixture) so the whole pipeline can be exercised without network
access. Statistically it's built from Poisson-distributed goals around
per-team "true strength" ratings, so the models have real signal to find —
this isn't just noise.
"""
import random
from datetime import datetime, timedelta

TEAM_NAMES = [
    "Gaborone United", "Township Rollers", "Jwaneng Galaxy", "Orapa United",
    "Mochudi Wanderers", "Security Systems FC", "BDF XI", "Notwane FC",
    "Molepolole Bees", "Sua Flamingoes", "Extension Gunners", "Uniao Flamengo",
]


def _true_strengths(seed=42):
    rng = random.Random(seed)
    return {name: rng.uniform(0.7, 1.6) for name in TEAM_NAMES}  # attack multiplier


def generate_season(storage, competition_code="SAMPLE", n_rounds=8, seed=42):
    """Round-robin-ish schedule, each team plays ~n_rounds matches."""
    rng = random.Random(seed)
    strengths = _true_strengths(seed)
    team_ids = {name: f"S{idx:03d}" for idx, name in enumerate(TEAM_NAMES)}

    for name, tid in team_ids.items():
        storage.upsert_team(tid, name, competition_code)

    base_date = datetime(2026, 1, 5)
    match_counter = 0
    fixtures = []
    for rnd in range(n_rounds):
        shuffled = TEAM_NAMES[:]
        rng.shuffle(shuffled)
        pairs = list(zip(shuffled[::2], shuffled[1::2]))
        for home, away in pairs:
            match_counter += 1
            fixtures.append((rnd, home, away))

    for rnd, home, away in fixtures:
        match_date = base_date + timedelta(days=7 * rnd)
        home_lambda = 1.35 * strengths[home] / strengths[away]  # home advantage baked in
        away_lambda = 0.95 * strengths[away] / strengths[home]
        home_goals = _poisson_sample(rng, home_lambda)
        away_goals = _poisson_sample(rng, away_lambda)
        match_id = f"SM{match_counter:04d}{rnd}{TEAM_NAMES.index(home)}"
        storage.upsert_match(
            match_id=match_id,
            competition=competition_code,
            date=match_date.strftime("%Y-%m-%dT15:00:00Z"),
            home_id=team_ids[home],
            away_id=team_ids[away],
            home_goals=home_goals,
            away_goals=away_goals,
            status="FINISHED",
        )
        match_counter += 1

    # A handful of top scorers per team, roughly proportional to attack strength
    with storage.get_conn() as conn:
        for name, tid in team_ids.items():
            n_scorers = rng.randint(2, 4)
            total_goals_pool = max(3, int(strengths[name] * 12))
            shares = _random_shares(rng, n_scorers, total_goals_pool)
            for i, goals in enumerate(shares):
                conn.execute(
                    """INSERT INTO scorers (team_id, player_name, goals)
                       VALUES (?, ?, ?)
                       ON CONFLICT(team_id, player_name) DO UPDATE SET goals=excluded.goals""",
                    (tid, f"{name} Striker {i+1}", goals),
                )

    # One upcoming fixture to predict: first two teams alphabetically for determinism
    upcoming_home, upcoming_away = TEAM_NAMES[0], TEAM_NAMES[1]
    upcoming_id = "SM_UPCOMING_001"
    storage.upsert_match(
        match_id=upcoming_id,
        competition=competition_code,
        date=(base_date + timedelta(days=7 * n_rounds)).strftime("%Y-%m-%dT15:00:00Z"),
        home_id=team_ids[upcoming_home],
        away_id=team_ids[upcoming_away],
        status="SCHEDULED",
    )

    return {
        "teams": len(TEAM_NAMES),
        "finished_matches": match_counter - 1,
        "upcoming_match_id": upcoming_id,
        "upcoming_fixture": f"{upcoming_home} vs {upcoming_away}",
    }


def _poisson_sample(rng, lam):
    # Knuth's algorithm — no numpy dependency needed for this
    L = pow(2.718281828, -lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def _random_shares(rng, n, total):
    cuts = sorted(rng.sample(range(1, total), n - 1)) if n > 1 and total > n else []
    bounds = [0] + cuts + [total]
    shares = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
    return [max(1, s) for s in shares]
