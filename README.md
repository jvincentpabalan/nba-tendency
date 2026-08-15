# NBA → 2K26 Tendency Generator

Converts real NBA player statistics from [NBA.com](https://www.nba.com/stats) into **NBA 2K26 tendency values** across 83 attributes covering shooting, driving, post game, passing, freelance, and defense.

## Features

- Fetches live stats from NBA.com (no third-party API key needed)
- Covers all seasons from 1996–97 onward
- Synergy play-type fallbacks for pre-2013 seasons (defunct API endpoint)
- React web UI with team/player/season selectors
- **Editable tendencies** — override any computed value before downloading
- CLI mode for scripting or batch use

## Quick Start

### Web UI

```bash
# Install Python dependencies
pip3 install -r requirements.txt

# Start the API server
python3 -m uvicorn api:app --reload --port 8000

# In a second terminal, start the UI dev server
cd ui
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Select a team, player, and season, then click **Generate Tendencies**.

To run with the built UI (no separate dev server):

```bash
cd ui && npm run build && cd ..
python3 -m uvicorn api:app --port 8000
# → open http://localhost:8000
```

### CLI

```bash
python3 main.py --player 1717 --season 2010-11             # Dirk Nowitzki (live API)
python3 main.py --player 2544 --season 2023-24             # LeBron James
python3 main.py --player 1717 --season 2010-11 --mock      # Dirk (no API calls)
python3 main.py --player 2544 --season 2023-24 --output lebron.json
```

Player IDs are from NBA.com (e.g. `1717` = Dirk Nowitzki, `2544` = LeBron James).

## Editing Tendencies

In the web UI, click **Edit Tendencies** after generating to:

- Adjust any value with a number input (0–99)
- See a live bar update as you type
- Reset individual values (↺) or all at once
- Download the final JSON with your edits applied

Edited values are highlighted in red; the downloaded JSON reflects all overrides.

## Architecture

```
api.py                  FastAPI server — /api/teams, /api/roster, /api/generate
main.py                 CLI entrypoint + mock_stats() for offline testing
stats_collector.py      Fetches all NBA.com endpoints → PlayerStats dataclass
nba_client.py           HTTP layer (Homebrew curl + browser headers)
mapper.py               PlayerStats → 83 tendency values
ui/                     React + Vite frontend
```

### Data Flow

```
NBA.com stats API
  └─ stats_collector.collect(player_id, season)
       ├─ playerdashboardbygeneralsplits   (box score)
       ├─ playerdashboardbyshootingsplits  (zones, shot types, assisted split)
       ├─ shotchartdetail                  (directional counts)
       └─ playerdashptshots                (pull-up / catch-and-shoot, 2013-14+)
  └─ mapper.compute(stats) → {tendency_label: value, ...}
  └─ mapper.to_2k26_json(tendencies) → JSON output
```

## Tendency Groups

| Group | Count | Notes |
|-------|------:|-------|
| Jump Shooting | 22 | Shot zones, directional splits, pull-up, spot-up, step-back |
| Layups And Dunks | 11 | Driving layup, dunk types, euro step, floater, putback |
| Driving | 13 | Drive initiation, dribble moves, commitment tendencies |
| Drive Setup | 7 | Triple threat, pump fake, jab step, sizeup |
| Post Game | 16 | Post frequency, hooks, fades, post moves |
| Passing | 3 | Dish, flashy, alley-oop |
| Freelance | 8 | ISO vs defender tiers, roll/pop, shot/touches |
| Defense | 7 | Steal, block, contest, foul |

## Notes on Data Quality

- **2013-14+**: Player tracking data available — pull-up FGA, catch-and-shoot FGA measured directly.
- **Pre-2013**: Tracking data unavailable; dribble-move and ISO tendencies estimated from shot-type detail and the assisted/unassisted split.
- `synergyplaytypes` endpoint is defunct (HTTP 500 for all seasons). ISO, post, spot-up, and cut frequencies are estimated via `_compute_synergy_fallbacks()` in `stats_collector.py`.

## Sample Outputs

Pre-generated JSON files for reference:

| File | Player | Season |
|------|--------|--------|
| `2011_dirk.json` | Dirk Nowitzki | 2010–11 |
| `2011_jterry.json` | Jason Terry | 2010–11 |
| `2011_melo.json` | Carmelo Anthony | 2010–11 |
| `jkidd.json` | Jason Kidd | 2010–11 |

## Requirements

- Python 3.9+
- [Homebrew curl](https://formulae.brew.sh/formula/curl) (`/opt/homebrew/opt/curl/bin/curl`) — required for brotli support; system macOS curl will fail
- Node.js 18+ (UI only)
