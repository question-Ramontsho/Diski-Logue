"""
Diski Logue — football-data.org client

Free tier docs: https://www.football-data.org/documentation/quickstart
Get a free API key at https://www.football-data.org/client/register

NOTE: This sandbox's network is restricted to package registries, so this
client can't be exercised live here. Run it on your own machine:

    export FOOTBALL_DATA_API_KEY="your_key_here"
    python -m diski_logue.cli fetch --competition PL

It writes straight into the same SQLite schema used by sample_data.py, so
every downstream model, the ensemble, and the CLI work identically whether
the data came from here or from the synthetic generator.
"""
import os
import time
import requests

BASE_URL = "https://api.football-data.org/v4"


class FootballDataClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("FOOTBALL_DATA_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Set FOOTBALL_DATA_API_KEY env var (get a free key at "
                "football-data.org/client/register)"
            )
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": self.api_key})

    def _get(self, path, params=None, retries=3):
        url = f"{BASE_URL}{path}"
        for attempt in range(retries):
            resp = self.session.get(url, params=params)
            if resp.status_code == 429:  # free tier: 10 req/min
                time.sleep(60)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"Failed to fetch {url} after {retries} retries")

    def get_competition_teams(self, competition_code: str):
        """e.g. 'PL' (Premier League), 'BSA' (Brasileirao), 'PD' (La Liga)"""
        data = self._get(f"/competitions/{competition_code}/teams")
        return data.get("teams", [])

    def get_competition_matches(self, competition_code: str, status: str = None,
                                 date_from: str = None, date_to: str = None):
        params = {}
        if status:
            params["status"] = status  # SCHEDULED | FINISHED | LIVE
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        data = self._get(f"/competitions/{competition_code}/matches", params=params)
        return data.get("matches", [])

    def get_competition_scorers(self, competition_code: str, limit: int = 20):
        data = self._get(f"/competitions/{competition_code}/scorers", params={"limit": limit})
        return data.get("scorers", [])

    def get_team(self, team_id: int):
        return self._get(f"/teams/{team_id}")


def sync_competition(client: FootballDataClient, competition_code: str, storage):
    """Pull teams + finished/scheduled matches + scorers into the local DB."""
    teams = client.get_competition_teams(competition_code)
    for t in teams:
        storage.upsert_team(str(t["id"]), t["name"], competition_code)

    matches = client.get_competition_matches(competition_code)
    for m in matches:
        score = m.get("score", {}).get("fullTime", {})
        storage.upsert_match(
            match_id=str(m["id"]),
            competition=competition_code,
            date=m["utcDate"],
            home_id=str(m["homeTeam"]["id"]),
            away_id=str(m["awayTeam"]["id"]),
            home_goals=score.get("home"),
            away_goals=score.get("away"),
            status=m["status"],
        )

    scorers = client.get_competition_scorers(competition_code)
    with storage.get_conn() as conn:
        for s in scorers:
            conn.execute(
                """INSERT INTO scorers (team_id, player_name, goals)
                   VALUES (?, ?, ?)
                   ON CONFLICT(team_id, player_name) DO UPDATE SET goals=excluded.goals""",
                (str(s["team"]["id"]), s["player"]["name"], s.get("goals", 0)),
            )

    return {"teams": len(teams), "matches": len(matches), "scorers": len(scorers)}
