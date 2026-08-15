# NBA → 2K26 Tendency Generator

Converts real NBA player statistics from NBA.com's stats API into NBA 2K26 tendency values using the methodology defined in the ATD Committee Master Tendency Scale CSV (local copy: `~/Downloads/ATD Committee Official Master Tendency - ATD Committe Master Tendency Scale (1).csv`).

## Usage

```bash
python3 main.py --player 1717 --season 2010-11             # Dirk Nowitzki (live API)
python3 main.py --player 2544 --season 2023-24             # LeBron James
python3 main.py --player 1717 --season 2010-11 --mock      # Dirk mock data (no API calls)
python3 main.py --player 2544 --season 2023-24 --output lebron.json
```

Player IDs are from NBA.com (e.g. `1717` = Dirk Nowitzki, `2544` = LeBron James).
Season format: `YYYY-YY` (e.g. `2010-11`).

## File Overview

| File | Purpose |
|------|---------|
| `nba_client.py` | HTTP layer — curl subprocess with NBA.com headers, retry/bail logic |
| `stats_collector.py` | Fetches all endpoints, normalizes to per-game, returns `PlayerStats`; synergy fallbacks |
| `mapper.py` | Maps `PlayerStats` → 83 tendency values in 8 groups |
| `main.py` | CLI entrypoint, `mock_stats()` for offline testing |

## Architecture

```
main.py
  └─ stats_collector.collect(player_id, season) → PlayerStats
       ├─ nba_client.fetch_general_splits()        # box score (PTS/AST/REB/STL/BLK/PF/FTA)
       ├─ nba_client.fetch_shooting_splits()       # shot zones + shot types + assisted split
       ├─ nba_client.fetch_shot_chart()            # directional counts (L/LC/C/RC/R per zone)
       ├─ nba_client.fetch_synergy_play_type() ×9  # DEFUNCT — always fails, fallbacks run instead
       └─ nba_client.fetch_pullup_shooting()       # GeneralShooting: pull-up FG2A/FG3A, C&S FGA
       └─ _compute_synergy_fallbacks(stats)        # fills synergy fields from shot-type proxies
  └─ mapper.compute(stats) → dict[label, value]
  └─ mapper.to_2k26_json(tendencies) → JSON output
```

---

## NBA.com API — Critical Implementation Details

### Transport
- **Must use Homebrew curl**: `/opt/homebrew/opt/curl/bin/curl`. System macOS curl uses LibreSSL which lacks brotli support (fails with rc=56). Homebrew curl has brotli/zstd.
- **HTTP/2 required**: `--http2` flag. Without it, NBA.com blocks with HTTP 000.
- **Full browser headers required**: `Sec-Ch-Ua`, `Sec-Fetch-Dest/Mode/Site`, `Connection: keep-alive`, `Origin`, `Referer`, `x-nba-stats-origin`, `x-nba-stats-token`, `User-Agent`. Missing any of these causes blocks.
- **URL encoding**: Use `quote_via=quote` in `urlencode()`. Default uses `+` for spaces; NBA API requires `%20`.
- **Timeout**: 10 seconds max per request (`--max-time 10`).
- **Rate limiting**: 1.5s delay between requests (`REQUEST_DELAY`). Aggressive testing gets the IP rate-limited for ~10–15 minutes. Use `--mock` when iterating on mapper logic.

### Empty response handling
When a request returns rc=0 but empty stdout (server returned HTTP 500 with empty body), **do not retry** — break immediately. This is server-side rejection (not a transient error). Retrying wastes 6+ seconds per endpoint.

### Per-game normalization — important asymmetry
- `playerdashboardbygeneralsplits` (box score): already returns per-game values ✓
- `playerdashboardbyshootingsplits` (shot zones, types, assisted split): returns **season totals** even with `PerMode=PerGame` — must divide by `stats.games`
- `playerdashptshots` (pull-up/C&S): returns **per-game** values correctly — do NOT divide by games
- Shot chart individual shots: are totals, divided by games

---

## Endpoint Status

### Working endpoints
| Endpoint | Result sets used |
|----------|-----------------|
| `playerdashboardbygeneralsplits` | `OverallPlayerDashboard` |
| `playerdashboardbyshootingsplits` | `ShotAreaPlayerDashboard`, `ShotTypeSummaryPlayerDashboard`, `ShotTypePlayerDashboard`, `AssitedShotPlayerDashboard` |
| `shotchartdetail` | `Shot_Chart_Detail` |
| `playerdashptshots` | `GeneralShooting` |

### Dead endpoints (HTTP 500 / empty body — do not retry)
- `synergyplaytypes` — completely defunct server-side for all seasons and all play types
- `playerdashptpass`, `playerdashptreb`, `leaguedashptstats` — also returning 500/redirect errors

### `playerdashptshots` parsing details
The correct result set is **`GeneralShooting`** (not `PullUpShooting` which doesn't exist).

| SHOT_TYPE value | Field to read | Maps to |
|---|---|---|
| `"Pull Ups"` | `FG2A` | `pullup_2pt_fga` |
| `"Pull Ups"` | `FG3A` | `pullup_3pt_fga` |
| `"Catch and Shoot"` | `FGA` | `catch_shoot_fga` |

**Only available from 2013-14 onward.** Returns empty rows for older seasons.

### `playerdashboardbyshootingsplits` — `AssitedShotPlayerDashboard`
Note the NBA API has a typo in the result set name: **"Assited"** (not "Assisted").
- `GROUP_VALUE="Assisted"` → `FGM` column = assisted makes (FGA = FGM here, only makes tracked)
- `GROUP_VALUE="Unassisted"` → `FGM` column = self-created makes

---

## Shot Type Detail — Key Fields

From `ShotTypePlayerDashboard` in shooting splits (available all seasons, season totals ÷ games):

| `PlayerStats` field | Shot types summed |
|---|---|
| `fga_driving_layup` | "Driving Layup", "Driving Finger Roll", "Driving Reverse Layup", "Running Layup", "Running Reverse Layup" |
| `fga_driving_dunk` | "Driving Dunk", "Driving Slam Dunk" |
| `fga_euro_step` | "Euro Step" |
| `fga_pullup` | "Pullup Jump", "Pullup Bank", **"Driving Jump"**, **"Running Jump"** |
| `fga_floater` | "Floating Jump", "Running Hook" |
| `fga_step_back` | "Step Back Jump shot" |
| `fga_turnaround` | all "Turnaround *" variants |
| `fga_fadeaway` | "Fadeaway Jump Shot", "Fadeaway Bank shot" (from ShotTypeSummaryPlayerDashboard) |
| `fga_putback` | "Putback Layup Shot" + "Tip Shot" |

**Important**: `fga_pullup` includes `"Driving Jump shot"` (mid-range pull-up off a drive, stops short of rim). This is needed for `Attack Strong On Drive` denominator — without it, pre-2013 players get a flat 90.

---

## Synergy Fallbacks

`synergyplaytypes` is defunct. `_compute_synergy_fallbacks()` in `stats_collector.py` runs after all API fetches when all synergy fields are still 0. Fills in:

| Field | Fallback logic |
|---|---|
| `synergy_iso` | **Primary**: `unassisted_fgm / 0.48` → subtract post shot volume → × 1.10. **Fallback**: `(pullup_2pt_fga or fga_pullup + fga_step_back × 0.5) × 1.35` |
| `synergy_post` | `(fga_hook + fga_turnaround + fga_fadeaway × 0.40) / 0.55` |
| `synergy_spotup` | **2013-14+**: `catch_shoot_fga × 1.20`. **Pre-2013**: `total_3pt_fga × 0.80 × 1.20` |
| `synergy_offscreen` | `catch_shoot_fga × 3PT_fraction × 0.25` |
| `synergy_cut` | `(fga_putback + fga_alley_oop + fga_finger_roll × 0.5) × 1.40` |
| `synergy_transition` | Left at 0 (running layups not separable from driving layups) |
| `synergy_pr_ball/roll` | mapper.py infers from 3PT profile when `pr_total < 0.5 poss/game` |
| `synergy_off_reb` | mapper.py falls back to `stats.oreb` |

### Why `unassisted_fgm` is the best ISO proxy
`unassisted_fgm` (from `AssitedShotPlayerDashboard`) = self-created makes. Available for **all seasons** unlike player tracking. Represents ISO + post-up combined; subtract post shot volume to isolate face-up ISO. A player with 37% unassisted rate (Dirk 2010-11) reads as a moderate self-creator; 60%+ = high ISO; 10-15% = catch-and-shoot specialist.

---

## Data Quality by Era

| Era | Quality | Notes |
|---|---|---|
| 2013-14+ | Good | Player tracking gives real `pullup_2pt_fga`/`catch_shoot_fga`; unassisted data available |
| Pre-2013 | Moderate | Player tracking empty; synergy fallbacks use shot type detail + unassisted split |

For pre-2013, the most reliable fields are: shot zones, shot types (including pullup/step-back/turnaround/fadeaway), directional data, box score, and the unassisted/assisted split. ISO and dribble-move tendencies are estimated rather than measured.

---

## Tendency Groups and Caps

All caps are sourced from the ATD Committee Master Tendency Scale CSV, **row 20** (with row 19 for a few exceptions). Never exceed the cap — `_scale()`'s `out_high` parameter IS the cap.

### Jump Shooting
Shot Under Basket (85), Shot Close (60), Shot Mid-Range (45), Shot Three (75), directional mid/close/3PT splits (same cap as parent), Spot-Up Mid (55), Off-Screen Mid (50), Spot-Up Three (75), Off-Screen Three (65), Contested Jumper Mid/Three (55), Stepback Mid (55), Stepback Three (60), Spin Jumper (45), Transition Pull-Up Three (50), Drive Pull-Up Mid (70), Drive Pull-Up Three (50), Use Glass (45), Step Through Shot (50).

### Layups And Dunks
Driving Layup (80), Standing Dunk (85), Driving Dunk (80), Flashy Dunk (70), Alley-Oop (85), Putback (70), Crash (65), Spin Layup (70), Hop Step Layup (65), Euro Step Layup (75), Floater (75).

### Driving
Drive (75), Spot-Up Drive (70), Off-Screen Drive (60), Drive Right (fixed 50), Crossover (60), Spin (50), Step Back (55), Half Spin (45), Double Crossover (40), Behind The Back (50), Hesitation (65), In And Out (65), No Driving Dribble Move (90), Attack Strong On Drive (90).

### Drive Setup
Triple Threat Shoot (55), Pump Fake (55), Jab Step (55), Idle (65), Setup With Sizeup (55), Setup With Hesitation (55), No Setup Dribble (85).

### Passing
Dish To Open Man (65), Flashy Pass (60), Alley-Oop Pass (65).

### Freelance
Roll vs. Pop (85), Spot vs. Cut (85), Iso vs. Elite (50), Iso vs. Good (60), Iso vs. Average (70), Iso vs. Poor (75), Play Discipline (90), Shot (75), Touches (75), Transition Spot Up (no hard cap).

### Post Game
Post Up (85), Post Back Down (80), Aggressive Backdown (70), Post Face Up (60), Post Spin (55), Post Drive (55), Post Drop Step (60), Shoot From Post (75), Hook Left/Right (50), Fade Left/Right (50), Shimmy/Hop/Up-And-Under (45), Step Back Shot (50).

### Defense
Pass Interception (85), On-Ball Steal (85), Block Shot (85), Contest Shot (85), Take Charge (35), Foul (95), Hard Foul (45).

---

## Key Mapper Patterns

### Linear scaling
```python
def _scale(value, low_raw, high_raw, out_low=5, out_high=45, floor=5) -> int:
    ratio = (value - low_raw) / (high_raw - low_raw)
    ratio = max(0.0, min(1.0, ratio))
    return int(max(floor, min(out_high, round(out_low + ratio * (out_high - out_low)))))
```
`out_high` = absolute cap from guide. `floor` defaults to 5. Values below `low_raw` → `out_low`.

### ISO frequency derivation
```python
iso_freq  = stats.synergy_iso   # from fallback: unassisted_fgm based
post_freq = stats.synergy_post  # from fallback: hook + turnaround + fadeaway based
faceup_iso = max(0.0, iso_freq - post_freq * 0.3)
```
`faceup_iso` drives all dribble-move tendencies. Post overlap is subtracted so post-heavy players don't get inflated crossover/hesitation values.

### Attack Strong On Drive
```python
rim_finish_vol = fga_driving_layup + fga_driving_dunk + fga_euro_step + fga_floater
pullup_vol = pullup_2pt_fga or fga_pullup   # fga_pullup includes "Driving Jump shot"
total_drive_vol = max(rim_finish_vol + pullup_vol, 1.0)
rim_commit_ratio = rim_finish_vol / total_drive_vol
→ _scale(rim_commit_ratio, 0.15, 0.90, 20, 90)
```
Without `fga_pullup` in the denominator, pre-2013 players default to 90 (every player looks like they always finish at rim).

### Directional splits
```python
def _dir_split(left, lc, center, rc, right, base, cap) -> tuple:
    # Dominant zone = base; others scaled proportionally; floor=5; all clamped to cap
```
Used for mid (5 zones), close (3 zones), 3PT (5 zones). Shot chart `SHOT_ZONE_BASIC` + `SHOT_ZONE_AREA` fields drive this.

### Roll vs. Pop fallback
```python
pr_total = synergy_pr_roll + synergy_pr_ball
if pr_total > 0.5:
    roll_frac = synergy_pr_roll / pr_total
else:
    # Infer: high 3PT + high post = pop
    roll_frac = max(0.0, 1.0 - pct_3 / 0.25 - post_freq / 10) * 0.6
→ _scale(roll_frac, 0, 1, 5, 85)   # 5=pure pop, 85=pure roll
```

---

## Formula Design Principles

Each formula should reflect what the **CSV definition** says the tendency *controls*, not what's correlated:

- **Drive**: willingness to initiate a drive (not finishing location). Proxy: drive-outcome FGA + `faceup_iso × 0.3`.
- **Crash**: contact-fall outcomes during finishing (not rebounding). Proxy: `fga_driving_layup × fta_rate`.
- **Attack Strong On Drive**: commitment to continue to rim once drive begins (not FTA rate). Proxy: `rim_finish_vol / total_drive_vol`.
- **No Driving Dribble Move**: straight-line drives (no setup move). Proxy: `fga_driving_layup / (fga_driving_layup + fga_euro_step + fga_floater)`.

---

## Mock Data (Dirk Nowitzki 2010–11)

`mock_stats()` in `main.py` — representative per-game values for Dirk's 2010-11 season (73 games). Use with `--mock` when iterating on mapper logic without hitting the API.

Key mock values and what they should produce:
- `fga_mid = 9.14`, `fga_fadeaway = 2.05` → Shot Mid-Range ≈ 43, Post Fade ≈ 28
- `synergy_post = 5.5`, `synergy_iso = 3.5` → Post Up ≈ 49, Iso vs Poor ≈ 36
- `synergy_pr_roll = 0.0` → Roll vs. Pop = 5 (pure pop)
- `fga_step_back = 0.49` → Stepback Jumper Mid ≈ 35

**Note**: mock data sets synergy fields directly, bypassing fallbacks. Live data uses fallbacks which produce slightly different (often lower) synergy estimates — this is expected and not a bug.

---

## Known Limitations / Future Work

1. **`synergy_transition`** — always 0. Running layups (transition) are bundled into `fga_driving_layup` and can't be separated. Transition Pull-Up Three and Transition Spot Up tendencies are always floored.

2. **Pre-2013 ISO underestimation** — dribble-move tendencies (Crossover, Hesitation, etc.) may be lower than reality because `pullup_2pt_fga` is unavailable and the unassisted-based proxy includes post-up self-creation.

3. **`synergy_pr_ball / synergy_pr_roll`** — always uses the 3PT-profile inference fallback since `synergyplaytypes` is defunct. A player who is actually a roll man but shoots 3s will be incorrectly read as a pop screener.

4. **Spot-Up Mid-Range for pre-2013** — estimated from `total_3pt_fga` only (3PT shots anchor the spot-up proxy). Mid-range catch-and-shoot contributions are not captured.

5. **`Drive Pull Up Mid-Range`** — for pre-2013, uses `fga_pullup` (ShotTypePlayerDashboard) which is a narrower definition than player tracking's `pullup_2pt_fga`. Values will be lower than reality.

6. **`mock_stats()` is not updated** — `pullup_2pt_fga` in mock is set to 3.0 (direct player tracking value) but the live path for 2010-11 gets 0 (no tracking data) and falls back to `fga_pullup`. The mock produces different tendency values than the live API for the same season — document this when comparing.
