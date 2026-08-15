"""NBA.com stats API client with proper headers and retry logic."""

import subprocess
import json
import time
from typing import Optional


# Headers that pass NBA.com bot detection (must match a real browser request)
NBA_HEADERS = [
    ("Accept", "application/json, text/plain, */*"),
    ("Accept-Encoding", "gzip, deflate, br, zstd"),
    ("Accept-Language", "en-US,en;q=0.9"),
    ("Connection", "keep-alive"),
    ("Origin", "https://www.nba.com"),
    ("Referer", "https://www.nba.com/"),
    ("Sec-Ch-Ua", '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"'),
    ("Sec-Ch-Ua-Mobile", "?0"),
    ("Sec-Ch-Ua-Platform", '"macOS"'),
    ("Sec-Fetch-Dest", "empty"),
    ("Sec-Fetch-Mode", "cors"),
    ("Sec-Fetch-Site", "same-site"),
    ("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    ("x-nba-stats-origin", "stats"),
    ("x-nba-stats-token", "true"),
]

BASE_URL = "https://stats.nba.com/stats"

# Delay between requests to avoid rate limiting
REQUEST_DELAY = 1.5


def _build_curl_cmd(url: str, params: dict) -> list[str]:
    """Build a curl command with NBA.com headers."""
    from urllib.parse import urlencode, quote
    query = urlencode({k: v for k, v in params.items()}, quote_via=quote)
    full_url = f"{url}?{query}" if query else url

    # Use Homebrew curl (has brotli+zstd support); system curl on macOS uses LibreSSL
    # which lacks brotli, causing rc=56 when the NBA API responds with br encoding.
    CURL = "/opt/homebrew/opt/curl/bin/curl"
    cmd = [CURL, "-s", "--max-time", "10", "--compressed", "--http2"]
    for key, value in NBA_HEADERS:
        cmd += ["-H", f"{key}: {value}"]
    cmd.append(full_url)
    print(f"  GET {full_url}")
    return cmd


def fetch(endpoint: str, params: dict, retries: int = 3) -> dict:
    """Fetch a NBA.com stats endpoint. Returns parsed JSON."""
    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(retries):
        if attempt > 0:
            wait = 2 ** attempt
            print(f"  Retrying {endpoint} in {wait}s (attempt {attempt+1}/{retries})...")
            time.sleep(wait)

        cmd = _build_curl_cmd(url, params)
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            if result.returncode != 0:
                print(f"  curl error (rc={result.returncode}): {result.stderr.strip()}")
            else:
                # rc=0 but empty body = server actively rejected the request (e.g. HTTP 500
                # with no payload). Retrying won't help — bail immediately.
                print(f"  empty response (rc=0) — endpoint rejected, skipping retries")
                break
            continue

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error: {e} — first 200 chars: {result.stdout[:200]!r}")
            continue

    raise RuntimeError(f"Failed to fetch {endpoint} after {retries} attempts")


def parse_result_set(data: dict, name: str) -> list[dict]:
    """Parse a named result set into a list of row dicts."""
    for rs in data.get("resultSets", []):
        if rs["name"] == name:
            headers = rs["headers"]
            return [dict(zip(headers, row)) for row in rs["rowSet"]]
    return []


def fetch_shooting_splits(player_id: int, season: str) -> dict:
    """Fetch shooting split data (zones, types, distances)."""
    print(f"Fetching shooting splits for player {player_id} ({season})...")
    time.sleep(REQUEST_DELAY)
    return fetch("playerdashboardbyshootingsplits", {
        "DateFrom": "", "DateTo": "", "GameSegment": "", "ISTRound": "",
        "LastNGames": 0, "LeagueID": "00", "Location": "", "MeasureType": "Base",
        "Month": 0, "OpponentTeamID": 0, "Outcome": "", "PORound": 0,
        "PaceAdjust": "N", "PerMode": "PerGame", "Period": 0,
        "PlayerID": player_id, "PlusMinus": "N", "Rank": "N",
        "Season": season, "SeasonSegment": "", "SeasonType": "Regular Season",
        "ShotClockRange": "", "VsConference": "", "VsDivision": "",
    })


def fetch_general_splits(player_id: int, season: str) -> dict:
    """Fetch general/traditional stats (PTS, AST, REB, STL, BLK, PF, etc.)."""
    print(f"Fetching general splits for player {player_id} ({season})...")
    time.sleep(REQUEST_DELAY)
    return fetch("playerdashboardbygeneralsplits", {
        "DateFrom": "", "DateTo": "", "GameSegment": "", "ISTRound": "",
        "LastNGames": 0, "LeagueID": "00", "Location": "", "MeasureType": "Base",
        "Month": 0, "OpponentTeamID": 0, "Outcome": "", "PORound": 0,
        "PaceAdjust": "N", "PerMode": "PerGame", "Period": 0,
        "PlayerID": player_id, "PlusMinus": "N", "Rank": "N",
        "Season": season, "SeasonSegment": "", "SeasonType": "Regular Season",
        "ShotClockRange": "", "Split": "general", "VsConference": "", "VsDivision": "",
    })


def fetch_shot_chart(player_id: int, season: str) -> dict:
    """Fetch shot chart detail (individual shots with zone breakdowns)."""
    print(f"Fetching shot chart for player {player_id} ({season})...")
    time.sleep(REQUEST_DELAY)
    return fetch("shotchartdetail", {
        "LeagueID": "00", "Season": season, "SeasonType": "Regular Season",
        "TeamID": 0, "PlayerID": player_id, "GameID": "",
        "Outcome": "", "Location": "", "Month": 0, "SeasonSegment": "",
        "DateFrom": "", "DateTo": "", "OpponentTeamID": 0,
        "VsConference": "", "VsDivision": "", "Position": "",
        "RookieYear": "", "GameSegment": "", "Period": 0,
        "LastNGames": 0, "ContextMeasure": "FGA", "PlayerPosition": "",
        "ContextFilter": "", "OwnTeam": "N",
    })


def fetch_synergy_play_type(play_type: str, season: str) -> dict:
    """Fetch synergy play-type data for a specific play type.

    Play types: Isolation, Postup, Spotup, Handoff, Cut, OffScreen,
                Transition, PRBallHandler, PRRollman, OffRebound, Misc
    """
    print(f"Fetching synergy {play_type} data ({season})...")
    time.sleep(REQUEST_DELAY)
    return fetch("synergyplaytypes", {
        "LeagueID": "00", "PerMode": "PerGame",
        "PlayerOrTeam": "P", "PlayType": play_type,
        "SeasonType": "Regular Season", "Season": season,
        "TypeGrouping": "offensive",
    })


def fetch_team_roster(team_id: int, season: str) -> list[dict]:
    """Fetch team roster for a given season. Returns list of player dicts."""
    import time as _time
    _time.sleep(REQUEST_DELAY)
    data = fetch("commonteamroster", {
        "LeagueID": "00",
        "Season": season,
        "TeamID": team_id,
    })
    players = []
    for rs in data.get("resultSets", []):
        if rs["name"] == "CommonTeamRoster":
            headers = rs["headers"]
            for row in rs["rowSet"]:
                r = dict(zip(headers, row))
                players.append({
                    "player_id": int(r.get("PLAYER_ID", 0)),
                    "player_name": r.get("PLAYER", ""),
                    "position": r.get("POSITION", ""),
                    "number": r.get("NUM", ""),
                })
    return sorted(players, key=lambda p: p["player_name"])


def fetch_pullup_shooting(player_id: int, season: str) -> dict:
    """Fetch pull-up and catch-and-shoot split data."""
    print(f"Fetching pull-up shooting data for player {player_id} ({season})...")
    time.sleep(REQUEST_DELAY)
    return fetch("playerdashptshots", {
        "LeagueID": "00", "PerMode": "PerGame", "Season": season,
        "SeasonType": "Regular Season", "PlayerID": player_id,
        "TeamID": 0, "Outcome": "", "Location": "", "Month": 0,
        "SeasonSegment": "", "DateFrom": "", "DateTo": "",
        "OpponentTeamID": 0, "VsConference": "", "VsDivision": "",
        "GameSegment": "", "Period": 0, "LastNGames": 0,
        "CloseDefDistRange": "", "DribbleRange": "",
        "TouchTimeRange": "", "GeneralRange": "",
    })
