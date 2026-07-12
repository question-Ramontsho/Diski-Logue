"""
Diski Logue — API-Football (api-sports.io) client

Confirmed coverage relevant to this project: South Africa Premier Soccer
League, South Africa National First Division, Africa Cup of Nations, FIFA
World Cup, and 1200+ other leagues/cups (source: api-football.com/news).
Botswana's local leagues are NOT confirmed on this API — use csv_import.py
for those instead.

Free tier: 100 requests/day, ALL competitions included (no paywalled leagues
the way football-data.org gates by tier). Get a free key at
https://dashboard.api-football.com (or via RapidAPI).

League IDs are stable across seasons but you have to look them up once —
use `find_league()` below or the CLI's `find-league` command rather than
guessing a numeric ID.

    export API_FOOTBALL_KEY="your_key_here"
    python -m diski_logue.cli find-league --search "Premier Soccer League"
    python -m diski_logue.cli fetch-api-football --code PSL --league-id <id> --season 2025
"""
import os
import time
import requests

BASE_URL = "https://v3.football.api-sports.io"


class ApiFootballClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Set API_FOOTBALL_KEY env var (free key at dashboard.api-football.com)"
            )
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.api_key})

    def _get(self, path, params=None, retries=3):
        url = f"{BASE_URL}{path}"
        for attempt in range(retries):
            resp = self.session.get(url, params=params)
            if resp.status_code == 429:
                time.sleep(30)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                raise RuntimeError(f"API-Football error for {url}: {data['errors']}")
            return data
        raise RuntimeError(f"Failed to fetch {url} after {retries} retries")

    def find_league(self, search: str, country: str = None):
        """Look up a league's numeric ID by name — use this once per
        competition, then hardcode the ID in your competitions config."""
        params = {"search": search}
        if country:
            params["country"] = country
        data = self._get("/leagues", params=params)
        return [
            {
                "id": item["league"]["id"],
                "name": item["league"]["name"],
                "type": item["league"]["type"],
                "country": item["country"]["name"],
                "seasons": [s["year"] for s in item.get("seasons", []) if s.get("coverage", {}).get("fixtures")],
            }
            for item in data.get("response", [])
        ]

    def get_teams(self, league_id: int, season: int):
        data = self._get("/teams", params={"league": league_id, "season": season})
        return [item["team"] for item in data.get("response", [])]

    def get_fixtures(self, league_id: int, season: int, status: str = None):
        params = {"league": league_id, "season": season}
        if status:
            params["status"] = status  # e.g. 'FT' (finished), 'NS' (not started)
        data = self._get("/fixtures", params=params)
        return data.get("response", [])

    def get_topscorers(self, league_id: int, season: int):
        data = self._get("/players/topscorers", params={"league": league_id, "season": season})
        return data.get("response", [])


def sync_competition(client: ApiFootballClient, code: str, league_id: int, season: int, storage):
    """Pull teams + fixtures + top scorers into the local DB, tagged under
    `code` (your chosen short name, e.g. 'PSL', 'AFCON') — same schema as
    the football-data.org sync, so downstream models don't care which
    source a competition came from."""
    teams = client.get_teams(league_id, season)
    for t in teams:
        storage.upsert_team(f"AF{t['id']}", t["name"], code)

    fixtures = client.get_fixtures(league_id, season)
    for f in fixtures:
        status_short = f["fixture"]["status"]["short"]
        status = "FINISHED" if status_short == "FT" else (
            "SCHEDULED" if status_short in ("NS", "TBD") else status_short
        )
        goals = f.get("goals", {})
        storage.upsert_match(
            match_id=f"AF{f['fixture']['id']}",
            competition=code,
            date=f["fixture"]["date"],
            home_id=f"AF{f['teams']['home']['id']}",
            away_id=f"AF{f['teams']['away']['id']}",
            home_goals=goals.get("home"),
            away_goals=goals.get("away"),
            status=status,
        )

    scorers = client.get_topscorers(league_id, season)
    with storage.get_conn() as conn:
        for s in scorers:
            team = s.get("statistics", [{}])[0].get("team", {})
            goals = s.get("statistics", [{}])[0].get("goals", {}).get("total", 0) or 0
            if not team.get("id"):
                continue
            conn.execute(
                """INSERT INTO scorers (team_id, player_name, goals)
                   VALUES (?, ?, ?)
                   ON CONFLICT(team_id, player_name) DO UPDATE SET goals=excluded.goals""",
                (f"AF{team['id']}", s["player"]["name"], goals),
            )

    return {"teams": len(teams), "matches": len(fixtures), "scorers": len(scorers)}
