# Diski Logue — FIPS v1.0

An explainable football match prediction engine. "Diski" (SA/Botswana slang
for football) + "Logue" (the reasoning/explanation) — a system that doesn't
just predict, it argues its case.

**Live site:** pick a competition and two teams, get an instant win/draw/loss
call, scoreline, markets (BTTS, Over/Under, clean sheets), likely
goalscorers, and a plain-language explanation — all computed live in the
browser. See "Deploy to GitHub Pages" below.

## What's covered

| Competition | Source | Status |
|---|---|---|
| English Premier League | football-data.org (free) | Ready — just add a key |
| FIFA World Cup | football-data.org (free) | Ready — just add a key |
| South Africa Premier Soccer League | API-Football (free) | Ready — needs a one-time league ID lookup (see below) |
| Africa Cup of Nations (AFCON) | API-Football (free) | Ready — needs a one-time league ID lookup |
| Botswana Premier League | **CSV you maintain** | No API has confirmed coverage of Botswana's local leagues — see "Botswana leagues" below |
| Sample demo league | synthetic, built in | Always available, no setup |

National teams work exactly like club teams in this system — a "team" is
just a name with a match history, so the World Cup and AFCON need no special
handling in the models themselves. The one real difference is that
tournament form is sparse (a team might only have played 2-3 matches this
tournament), which the confidence score already accounts for — it
automatically lowers confidence when a team has fewer than 5 recent matches
on record.

## Fixed: the "right side always wins" bug

Earlier versions had a UX defect (not a math bug) — the team dropdown list
was sorted by Elo rating, and the "Away" dropdown defaulted to the *second
strongest team in the whole league*. If you only ever changed the Home
dropdown, Away would win almost every time — not because of a side bias,
but because it was pinned to a top team the whole time.

Fixed by:
- Sorting the dropdown alphabetically (no correlation between list position
  and team strength)
- Removing the strength-biased default selection
- Adding a **⇄ swap button** so you can flip Home/Away with one click and
  watch the prediction flip with it

There's also a regression test (`tests/test_no_side_bias.js`) that checks,
across every strongly-mismatched pair of teams in the sample data, that the
stronger team is favored **regardless of which dropdown it's placed in**.
Run it with `node tests/test_no_side_bias.js` — it should print `PASS`.

## Repo layout

```
diski-logue-repo/
  diski_logue/                       Python package (the prediction engine + CLI)
    cli.py                            entry point — see `python -m diski_logue.cli --help`
    competitions_config.json          the registry: which competitions to track, from where
    storage/db.py                       SQLite: teams, matches, predictions, scorers
    data_sources/
      football_data_org.py              football-data.org client (PL, WC, and 10 other free leagues)
      api_football.py                   API-Football client (PSL, AFCON, 1200+ other leagues)
      csv_import.py                     manual import for leagues with no API coverage (Botswana)
      sample_data.py                    synthetic data generator (for local testing)
    models/
      team_strength.py                  Elo model (30% weight)
      form_model.py                      current form model (25% weight)
      goals_model.py                     Poisson + Monte Carlo goals/markets engine (10%)
      scorer_model.py                    goalscorer probabilities
      ensemble.py                        combines everything into final predictions
    explain/explainer.py                top factors + natural-language explanation
    scripts/
      export_season_json.py             aggregates one competition -> docs/data/<code>.json
      sync_all.py                       syncs every competition in the registry + writes the manifest
  docs/                               Static website — this is what GitHub Pages serves
    index.html
    style.css
    predict-engine.js                   JS port of the Python ensemble — runs in-browser
    app.js                              UI wiring: competition switcher, fixture picker, results
    data/
      manifest.json                     list of available competitions (auto-generated)
      <CODE>.json                       one file per competition (auto-generated)
  data/                               Your own CSVs for leagues with no API (Botswana etc.)
  tests/test_no_side_bias.js          regression test for the fixed bug
  .github/workflows/update-data.yml   scheduled data refresh + auto-deploy
  requirements.txt
```

## Run the CLI locally

```bash
git clone <your-repo-url>
cd diski-logue-repo
pip install -r requirements.txt

# Try it instantly with synthetic data (no API key needed)
python -m diski_logue.cli demo
```

**Always run these from the repo root** (the folder containing both
`diski_logue/` and `docs/`), not from inside `diski_logue/`.

### Adding real competitions

**Premier League / World Cup (football-data.org):**
```bash
export FOOTBALL_DATA_API_KEY="your_key_here"   # free at football-data.org/client/register
python -m diski_logue.cli fetch --competition PL
```

**PSL / AFCON (API-Football):** first look up the league ID once —
```bash
export API_FOOTBALL_KEY="your_key_here"        # free at dashboard.api-football.com
python -m diski_logue.cli find-league --search "Premier Soccer League" --country "South Africa"
```
Copy the `id` from the result into `diski_logue/competitions_config.json`
under the `PSL` entry's `"league_id"` field. Same process for AFCON
(`find-league --search "Africa Cup of Nations"`). Then:
```bash
python -m diski_logue.cli fetch-api-football --code PSL --league-id <id> --season 2025
```

**Botswana leagues (no API — you're the data source):** create
`data/bw_premier_matches.csv` (and optionally `data/bw_premier_scorers.csv`)
in the format described in `diski_logue/data_sources/csv_import.py`, then:
```bash
python -m diski_logue.cli import-csv --code BW_PREMIER \
  --matches data/bw_premier_matches.csv --scorers data/bw_premier_scorers.csv
```

**Sync everything in the registry at once** (what the GitHub Action runs):
```bash
python -m diski_logue.scripts.sync_all
# or just some competitions:
python -m diski_logue.scripts.sync_all --only PL,BW_PREMIER
```
This writes `docs/data/<CODE>.json` for each competition and
`docs/data/manifest.json`, which the website reads to populate the
competition dropdown. Competitions with no key / no league ID / no CSV yet
are skipped with a clear message — nothing crashes.

### Other CLI commands

```bash
python -m diski_logue.cli predict --home 65 --away 66 --competition PL --match-id 12345
python -m diski_logue.cli record-result --match-id 12345 --home-goals 2 --away-goals 1
python -m diski_logue.cli dashboard
```

## Preview the website locally

```bash
python -m diski_logue.scripts.sync_all --only SAMPLE
cd docs
python -m http.server 8000
# open http://localhost:8000
```

## Deploy to GitHub Pages

1. **Create the repo and push:**
   ```bash
   cd diski-logue-repo
   git init
   git add .
   git commit -m "Diski Logue v1.0"
   git branch -M main
   git remote add origin https://github.com/<your-username>/diski-logue.git
   git push -u origin main
   ```

2. **Enable Pages with GitHub Actions as the source:**
   Repo → **Settings** → **Pages** → under "Build and deployment", set
   **Source** to **GitHub Actions**.

3. **Add your API keys as repo secrets** (Settings → Secrets and variables →
   Actions → New repository secret):
   - `FOOTBALL_DATA_API_KEY` — for Premier League / World Cup
   - `API_FOOTBALL_KEY` — for PSL / AFCON (after you've filled in the
     league IDs in `competitions_config.json` and pushed that change)

   Any competition without a key/ID/CSV is skipped automatically — the site
   stays up, it just shows fewer competitions until you add them.

4. **Trigger the first deploy:** Actions tab → "Update season data and
   deploy site" → **Run workflow**.

5. Your site is live at `https://<your-username>.github.io/diski-logue/`.

## Architecture (mapped to the original FIPS v4.0 doc)

| Doc component | This build |
|---|---|
| AI Data Intelligence Engine | `data_sources/football_data_org.py`, `api_football.py`, `csv_import.py` |
| Data validation | schema-typed SQLite inserts in `storage/db.py` |
| Football Memory | `storage/db.py` — full match history, head-to-head |
| Automated Feature Engineering | `models/form_model.py`, `models/goals_model.py` |
| Team Strength Model (30%) | `models/team_strength.py` — Elo + home advantage + margin-of-victory multiplier |
| Current Form Model (25%) | `models/form_model.py` — decay-weighted PPG and goal trends |
| Goals Model (10%) | `models/goals_model.py` — Poisson attack/defense ratings |
| Monte Carlo Simulation (10,000+ runs) | `goals_model.monte_carlo_simulation()` / `predict-engine.js` |
| Ensemble AI Prediction Engine | `models/ensemble.py` / `predict-engine.js` |
| Explainable Prediction Engine | `explain/explainer.py` / `predict-engine.js` |
| Continuous Learning & Model Governance | `storage/db.py` (`record_result_and_score`, `dashboard_stats`) |

Context Model, Tactical Compatibility Model, and Player Impact Model (35%
combined weight in the original doc) are deferred to v2.0 — they need
injury feeds, formation data, and player-level ratings a results-only API
doesn't provide. The v1.0 ensemble renormalizes weights across the 3 models
actually in play (46.2% / 38.5% / 15.4%).

## Roadmap (v2.0+)

- Multi-Agent AI layer (Scout, Team Analyst, Player Analyst, Tactical
  Analyst, Prediction, Critic, Learning agents)
- Football Knowledge Graph
- Digital Twins for teams, players, managers
- Context Model (injuries, weather, referee, rest days) and Tactical
  Compatibility Model
- Player Impact Model
- Bayesian updating, Graph Neural Networks
- Counterfactual engine ("what if Player X is unavailable?")
- Minute-by-minute match simulation
- Computer vision for tactical analysis, where legally available
- Verified Botswana league data source (if/when one becomes API-accessible)
