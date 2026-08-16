"""FastAPI backend for the NBA 2K26 Tendency Generator UI."""
import json
import os
import re
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stats_collector
import mapper
import nba_client as client

UI_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "dist")

app = FastAPI(title="NBA 2K26 Tendency Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

NBA_TEAMS = [
    {"id": 1610612737, "name": "Atlanta Hawks", "abbr": "ATL"},
    {"id": 1610612738, "name": "Boston Celtics", "abbr": "BOS"},
    {"id": 1610612751, "name": "Brooklyn Nets", "abbr": "BKN"},
    {"id": 1610612766, "name": "Charlotte Hornets", "abbr": "CHA"},
    {"id": 1610612741, "name": "Chicago Bulls", "abbr": "CHI"},
    {"id": 1610612739, "name": "Cleveland Cavaliers", "abbr": "CLE"},
    {"id": 1610612742, "name": "Dallas Mavericks", "abbr": "DAL"},
    {"id": 1610612743, "name": "Denver Nuggets", "abbr": "DEN"},
    {"id": 1610612765, "name": "Detroit Pistons", "abbr": "DET"},
    {"id": 1610612744, "name": "Golden State Warriors", "abbr": "GSW"},
    {"id": 1610612745, "name": "Houston Rockets", "abbr": "HOU"},
    {"id": 1610612754, "name": "Indiana Pacers", "abbr": "IND"},
    {"id": 1610612746, "name": "LA Clippers", "abbr": "LAC"},
    {"id": 1610612747, "name": "Los Angeles Lakers", "abbr": "LAL"},
    {"id": 1610612763, "name": "Memphis Grizzlies", "abbr": "MEM"},
    {"id": 1610612748, "name": "Miami Heat", "abbr": "MIA"},
    {"id": 1610612749, "name": "Milwaukee Bucks", "abbr": "MIL"},
    {"id": 1610612750, "name": "Minnesota Timberwolves", "abbr": "MIN"},
    {"id": 1610612740, "name": "New Orleans Pelicans", "abbr": "NOP"},
    {"id": 1610612752, "name": "New York Knicks", "abbr": "NYK"},
    {"id": 1610612760, "name": "Oklahoma City Thunder", "abbr": "OKC"},
    {"id": 1610612753, "name": "Orlando Magic", "abbr": "ORL"},
    {"id": 1610612755, "name": "Philadelphia 76ers", "abbr": "PHI"},
    {"id": 1610612756, "name": "Phoenix Suns", "abbr": "PHX"},
    {"id": 1610612757, "name": "Portland Trail Blazers", "abbr": "POR"},
    {"id": 1610612758, "name": "Sacramento Kings", "abbr": "SAC"},
    {"id": 1610612759, "name": "San Antonio Spurs", "abbr": "SAS"},
    {"id": 1610612761, "name": "Toronto Raptors", "abbr": "TOR"},
    {"id": 1610612762, "name": "Utah Jazz", "abbr": "UTA"},
    {"id": 1610612764, "name": "Washington Wizards", "abbr": "WAS"},
]


@app.get("/api/teams")
def list_teams():
    return sorted(NBA_TEAMS, key=lambda t: t["name"])


@app.get("/api/roster")
def roster(team_id: int, season: str = "2024-25"):
    try:
        return client.fetch_team_roster(team_id, season)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API unavailable — {e}")


class GenerateRequest(BaseModel):
    player_id: int
    player_name: str
    season: str = "2024-25"
    season_type: str = "Regular Season"


@app.post("/api/generate")
def generate(req: GenerateRequest):
    try:
        stats = stats_collector.collect(req.player_id, req.season)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"NBA API unavailable — {e}")

    tendencies = mapper.compute(stats)
    output = mapper.to_2k26_json(tendencies)

    # Save to output/ directory
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", req.player_name.lower()).strip("_")
    st_slug = re.sub(r"[^a-z0-9]+", "_", req.season_type.lower()).strip("_")
    out_path = os.path.join(out_dir, f"{slug}_{req.season}_{st_slug}.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # Raw involvement scores for UI-side roster normalization.
    # These mirror the mapper formulas for Freelance:Touches and Freelance:Shot
    # but are NOT included in the saved file — the external 2K tool reads output only.
    _denom = stats.fga + stats.ast + stats.tov
    _ast_ratio = stats.ast / _denom if _denom > 0 else 0.0
    touch_raw = round(stats.usg_pct, 4)
    shot_raw = round((stats.fga * 0.6 + stats.pts * 0.4) * max(0.60, 1.0 - _ast_ratio), 4)

    return {
        "player_name": req.player_name,
        "season": req.season,
        "season_type": req.season_type,
        "_player_id": req.player_id,
        **output,
        "_touch_raw": touch_raw,
        "_shot_raw": shot_raw,
    }


# Serve built React app (after `npm run build` in ui/)
if os.path.isdir(UI_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(UI_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        return FileResponse(os.path.join(UI_DIST, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
