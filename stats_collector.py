"""Collect and normalize stats from multiple NBA.com endpoints into a flat dict."""

from dataclasses import dataclass, field
from typing import Optional
import nba_client as client

# synergyplaytypes is defunct server-side (HTTP 500 for all seasons/play types).
# Set to True only if the endpoint ever comes back.
FETCH_SYNERGY = False


@dataclass
class PlayerStats:
    """All stats needed to compute 2K tendencies."""

    # --- Box score (from general splits) ---
    games: int = 0
    minutes: float = 0.0
    usg_pct: float = 0.0      # usage rate (from advanced splits; 0.20 = league avg)
    ast_pct: float = 0.0      # % of teammate FGs assisted while on floor (pace/role adjusted)
    pct_uast_3pm: float = 0.0 # fraction of 3PT makes that were self-created (from scoring splits)
    pct_pts_fb: float = 0.0   # fraction of points scored in transition / fast break
    pts: float = 0.0
    fgm: float = 0.0
    fga: float = 0.0
    fg3m: float = 0.0
    fg3a: float = 0.0
    ftm: float = 0.0
    fta: float = 0.0
    oreb: float = 0.0
    dreb: float = 0.0
    reb: float = 0.0
    ast: float = 0.0
    stl: float = 0.0
    blk: float = 0.0
    tov: float = 0.0
    pf: float = 0.0
    pfd: float = 0.0  # personal fouls drawn

    # --- Shot zone FGA (from shooting splits ShotAreaPlayerDashboard) ---
    fga_restricted: float = 0.0   # Restricted Area
    fga_paint_nonra: float = 0.0  # In The Paint (Non-RA)
    fga_mid: float = 0.0          # Mid-Range
    fga_lc3: float = 0.0          # Left Corner 3
    fga_rc3: float = 0.0          # Right Corner 3
    fga_atb3: float = 0.0         # Above the Break 3

    fgm_restricted: float = 0.0
    fgm_paint_nonra: float = 0.0
    fgm_mid: float = 0.0
    fgm_lc3: float = 0.0
    fgm_rc3: float = 0.0
    fgm_atb3: float = 0.0

    # --- Shot type FGA (from ShotTypeSummaryPlayerDashboard) ---
    fga_alley_oop: float = 0.0
    fga_bank_shot: float = 0.0
    fga_dunk: float = 0.0
    fga_fadeaway: float = 0.0
    fga_finger_roll: float = 0.0
    fga_hook: float = 0.0
    fga_jump_shot: float = 0.0
    fga_layup: float = 0.0
    fga_tip: float = 0.0

    # --- Shot type detail FGA (from ShotTypePlayerDashboard) ---
    fga_step_back: float = 0.0
    fga_driving_layup: float = 0.0
    fga_driving_dunk: float = 0.0
    fga_euro_step: float = 0.0
    fga_putback: float = 0.0
    fga_pullup: float = 0.0       # Explicitly labeled: Pullup Jump, Driving Jump, Running Jump
    fga_running_layup: float = 0.0
    fga_floater: float = 0.0      # Floating Jump shot
    fga_turnaround: float = 0.0            # All turnaround variants (superset)
    fga_turnaround_fadeaway: float = 0.0  # Turnaround Fadeaway subset (post-specific fade)
    # Unassisted 2PT generic "Jump Shot" attempts — the NBA's unlabeled pull-up bucket.
    # For pre-2013, many pull-up mid-range shots land here instead of "Pullup Jump Shot".
    # Computed as: FG2A × PCT_UAST_2PM from the "Jump Shot" row in ShotTypePlayerDashboard.
    fga_uast_2pt_jump: float = 0.0

    # --- Shot chart directional breakdowns ---
    # Mid-range by side: Left Side, Left Side Center, Center, Right Side Center, Right Side
    mid_left: float = 0.0
    mid_left_center: float = 0.0
    mid_center: float = 0.0
    mid_right_center: float = 0.0
    mid_right: float = 0.0

    # Close shots (<8ft, non-RA paint) by side
    close_left: float = 0.0
    close_center: float = 0.0
    close_right: float = 0.0

    # 3PT by side (above break only; corners handled by zone)
    three_left: float = 0.0       # Left Corner 3 + Left Side Center ATB3
    three_left_center: float = 0.0
    three_center: float = 0.0     # Above Break 3 center
    three_right_center: float = 0.0
    three_right: float = 0.0      # Right Corner 3 + Right Side Center ATB3

    # --- Synergy play-type frequencies (POSS per game) ---
    synergy_iso: float = 0.0
    synergy_post: float = 0.0
    synergy_spotup: float = 0.0
    synergy_offscreen: float = 0.0
    synergy_transition: float = 0.0
    synergy_cut: float = 0.0
    synergy_pr_ball: float = 0.0   # PnR ball handler
    synergy_pr_roll: float = 0.0   # PnR roll man
    synergy_off_reb: float = 0.0   # Off rebound

    # --- Synergy PPP (points per possession) for quality context ---
    synergy_iso_ppp: float = 0.0
    synergy_post_ppp: float = 0.0

    # --- Assisted/Unassisted split (from AssitedShotPlayerDashboard, all seasons) ---
    unassisted_fgm: float = 0.0   # self-created makes (post + ISO; best pre-tracking ISO proxy)
    assisted_fgm: float = 0.0     # catch-and-shoot / spot-up makes

    # --- Pull-up shooting (from playerdashptshots) ---
    pullup_2pt_fga: float = 0.0
    pullup_3pt_fga: float = 0.0
    catch_shoot_fga: float = 0.0

    # Computed helpers (filled in post-load)
    total_3pt_fga: float = 0.0    # lc3 + rc3 + atb3
    total_fga: float = 0.0        # overall FGA


def _row_to_dict(result_set: list, key_field: str, key_value: str) -> Optional[dict]:
    """Find a row matching key_value in key_field."""
    for row in result_set:
        if row.get(key_field) == key_value:
            return row
    return None


def _sum_field(rows: list, field: str) -> float:
    return sum(float(r.get(field, 0) or 0) for r in rows)


def collect(player_id: int, season: str, season_type: str = "Regular Season") -> PlayerStats:
    """Fetch all data and return a populated PlayerStats."""
    stats = PlayerStats()

    # ── 1. General splits (box score) ─────────────────────────────────────
    try:
        gen = client.fetch_general_splits(player_id, season, season_type)
        overall = client.parse_result_set(gen, "OverallPlayerDashboard")
        if overall:
            row = overall[0]
            stats.games   = int(row.get("GP", 0) or 0)
            stats.minutes = float(row.get("MIN", 0) or 0)
            stats.pts     = float(row.get("PTS", 0) or 0)
            stats.fgm     = float(row.get("FGM", 0) or 0)
            stats.fga     = float(row.get("FGA", 0) or 0)
            stats.fg3m    = float(row.get("FG3M", 0) or 0)
            stats.fg3a    = float(row.get("FG3A", 0) or 0)
            stats.ftm     = float(row.get("FTM", 0) or 0)
            stats.fta     = float(row.get("FTA", 0) or 0)
            stats.oreb    = float(row.get("OREB", 0) or 0)
            stats.dreb    = float(row.get("DREB", 0) or 0)
            stats.reb     = float(row.get("REB", 0) or 0)
            stats.ast     = float(row.get("AST", 0) or 0)
            stats.stl     = float(row.get("STL", 0) or 0)
            stats.blk     = float(row.get("BLK", 0) or 0)
            stats.tov     = float(row.get("TOV", 0) or 0)
            stats.pf      = float(row.get("PF", 0) or 0)
            stats.pfd     = float(row.get("PFD", 0) or 0)
    except Exception as e:
        print(f"  Warning: could not fetch general splits ({e})")

    # ── 1b. Advanced splits (USG_PCT, AST_PCT) ───────────────────────────
    try:
        adv = client.fetch_advanced_splits(player_id, season, season_type)
        overall_adv = client.parse_result_set(adv, "OverallPlayerDashboard")
        if overall_adv:
            stats.usg_pct = float(overall_adv[0].get("USG_PCT", 0) or 0)
            stats.ast_pct = float(overall_adv[0].get("AST_PCT", 0) or 0)
    except Exception as e:
        print(f"  Warning: could not fetch advanced splits ({e})")

    # ── 1c. Scoring splits (PCT_UAST_3PM, PCT_PTS_FB) ────────────────────
    try:
        sc = client.fetch_scoring_splits(player_id, season, season_type)
        overall_sc = client.parse_result_set(sc, "OverallPlayerDashboard")
        if overall_sc:
            stats.pct_uast_3pm = float(overall_sc[0].get("PCT_UAST_3PM", 0) or 0)
            stats.pct_pts_fb   = float(overall_sc[0].get("PCT_PTS_FB",   0) or 0)
    except Exception as e:
        print(f"  Warning: could not fetch scoring splits ({e})")

    # ── 2. Shooting splits ────────────────────────────────────────────────
    try:
        sh = client.fetch_shooting_splits(player_id, season, season_type)

        # Shot zones
        areas = client.parse_result_set(sh, "ShotAreaPlayerDashboard")
        zone_map = {r["GROUP_VALUE"]: r for r in areas}

        def zone(name, field):
            return float((zone_map.get(name) or {}).get(field, 0) or 0)

        stats.fga_restricted  = zone("Restricted Area", "FGA")
        stats.fgm_restricted  = zone("Restricted Area", "FGM")
        stats.fga_paint_nonra = zone("In The Paint (Non-RA)", "FGA")
        stats.fgm_paint_nonra = zone("In The Paint (Non-RA)", "FGM")
        stats.fga_mid         = zone("Mid-Range", "FGA")
        stats.fgm_mid         = zone("Mid-Range", "FGM")
        stats.fga_lc3         = zone("Left Corner 3", "FGA")
        stats.fgm_lc3         = zone("Left Corner 3", "FGM")
        stats.fga_rc3         = zone("Right Corner 3", "FGA")
        stats.fgm_rc3         = zone("Right Corner 3", "FGM")
        stats.fga_atb3        = zone("Above the Break 3", "FGA")
        stats.fgm_atb3        = zone("Above the Break 3", "FGM")

        # Shot types summary
        shot_types = client.parse_result_set(sh, "ShotTypeSummaryPlayerDashboard")
        type_map = {r["GROUP_VALUE"]: r for r in shot_types}

        def stype(name, field):
            return float((type_map.get(name) or {}).get(field, 0) or 0)

        stats.fga_alley_oop  = stype("Alley Oop", "FGA")
        stats.fga_bank_shot  = stype("Bank Shot", "FGA")
        stats.fga_dunk       = stype("Dunk", "FGA")
        stats.fga_fadeaway   = stype("Fadeaway", "FGA")
        stats.fga_finger_roll= stype("Finger Roll", "FGA")
        stats.fga_hook       = stype("Hook Shot", "FGA")
        stats.fga_jump_shot  = stype("Jump Shot", "FGA")
        stats.fga_layup      = stype("Layup", "FGA")
        stats.fga_tip        = stype("Tip Shot", "FGA")

        # Shot type detail
        detail = client.parse_result_set(sh, "ShotTypePlayerDashboard")
        def detail_sum(*names):
            total = 0.0
            for r in detail:
                if any(n.lower() in r.get("GROUP_VALUE", "").lower() for n in names):
                    total += float(r.get("FGA", 0) or 0)
            return total

        stats.fga_step_back    = detail_sum("Step Back")
        stats.fga_driving_layup= detail_sum("Driving Layup", "Driving Finger Roll", "Driving Reverse Layup", "Running Layup", "Running Reverse Layup")
        stats.fga_driving_dunk = detail_sum("Driving Dunk", "Driving Slam Dunk")
        stats.fga_euro_step    = detail_sum("Euro Step")  # rare in older data
        stats.fga_putback      = detail_sum("Putback", "Tip Shot")
        # "Driving Jump shot" = mid-range pull-up off a drive (stops short of rim).
        # Include alongside traditional pull-ups for Attack Strong denominator.
        stats.fga_pullup       = detail_sum("Pullup Jump", "Pullup Bank", "Driving Jump", "Running Jump")
        stats.fga_floater      = detail_sum("Floating Jump", "Running Hook")
        stats.fga_turnaround          = detail_sum("Turnaround")
        stats.fga_turnaround_fadeaway = detail_sum("Turnaround Fadeaway")

        # Unassisted 2PT generic "Jump Shot" — pull-ups not caught by the labeled subtypes.
        # For pre-2013, the NBA labels many pull-up mid-range shots as plain "Jump Shot"
        # rather than "Pullup Jump Shot". FG2A × PCT_UAST_2PM extracts the self-created portion.
        # Use exact GROUP_VALUE match to avoid capturing labeled subtypes (Pullup, Driving, etc.).
        jump_row = next((r for r in detail if r.get("GROUP_VALUE") == "Jump Shot"), None)
        if jump_row:
            js_fga  = float(jump_row.get("FGA", 0) or 0)
            js_fg3a = float(jump_row.get("FG3A", 0) or 0)
            js_fg2a = max(0.0, js_fga - js_fg3a)
            js_pct_uast = float(jump_row.get("PCT_UAST_2PM", 0) or 0)
            stats.fga_uast_2pt_jump = js_fg2a * js_pct_uast  # season total; normalized below

        # Assisted / Unassisted split — available for all seasons.
        # Note: NBA API has a typo in the result set name ("Assited").
        # FGA column = FGM (only makes are tracked here, not attempts).
        assisted_rows = client.parse_result_set(sh, "AssitedShotPlayerDashboard")
        for row in assisted_rows:
            gv = row.get("GROUP_VALUE", "")
            if gv == "Assisted":
                stats.assisted_fgm = float(row.get("FGM", 0) or 0)
            elif gv == "Unassisted":
                stats.unassisted_fgm = float(row.get("FGM", 0) or 0)

    except Exception as e:
        print(f"  Warning: could not fetch shooting splits ({e})")

    # ── 3. Shot chart (directional breakdowns) ────────────────────────────
    try:
        chart = client.fetch_shot_chart(player_id, season, season_type)
        shots = client.parse_result_set(chart, "Shot_Chart_Detail")

        # Aggregate shot attempts by (zone_basic, zone_area).
        # API returns area with abbreviation suffix e.g. "Left Side(L)" — strip it.
        from collections import defaultdict
        zone_counts = defaultdict(int)
        for s in shots:
            basic = s.get("SHOT_ZONE_BASIC", "")
            area = s.get("SHOT_ZONE_AREA", "")
            area = area.split("(")[0].strip() if "(" in area else area
            zone_counts[(basic, area)] += 1

        def zc(basic, area):
            return float(zone_counts.get((basic, area), 0))

        # Mid-range directional
        stats.mid_left        = zc("Mid-Range", "Left Side")
        stats.mid_left_center = zc("Mid-Range", "Left Side Center")
        stats.mid_center      = zc("Mid-Range", "Center")
        stats.mid_right_center= zc("Mid-Range", "Right Side Center")
        stats.mid_right       = zc("Mid-Range", "Right Side")

        # Close shots (Restricted Area + Paint Non-RA) directional
        stats.close_left   = (zc("Restricted Area", "Left Side")
                              + zc("In The Paint (Non-RA)", "Left Side"))
        stats.close_center = (zc("Restricted Area", "Center")
                              + zc("In The Paint (Non-RA)", "Center"))
        stats.close_right  = (zc("Restricted Area", "Right Side")
                              + zc("In The Paint (Non-RA)", "Right Side"))

        # 3PT directional (corners go to Left/Right, above-break zones to LCenter/Center/RCenter)
        stats.three_left        = (zc("Left Corner 3", "Left Side")
                                   + zc("Above the Break 3", "Left Side"))
        stats.three_left_center = zc("Above the Break 3", "Left Side Center")
        stats.three_center      = zc("Above the Break 3", "Center")
        stats.three_right_center= zc("Above the Break 3", "Right Side Center")
        stats.three_right       = (zc("Right Corner 3", "Right Side")
                                   + zc("Above the Break 3", "Right Side"))

        print(f"  Shot chart: {len(shots)} shots, {len(zone_counts)} zones")
        print(f"  3PT zones: L={stats.three_left:.0f} LC={stats.three_left_center:.0f} "
              f"C={stats.three_center:.0f} RC={stats.three_right_center:.0f} R={stats.three_right:.0f}")
        print(f"  Mid zones: L={stats.mid_left:.0f} LC={stats.mid_left_center:.0f} "
              f"C={stats.mid_center:.0f} RC={stats.mid_right_center:.0f} R={stats.mid_right:.0f}")

    except Exception as e:
        print(f"  Warning: could not fetch shot chart ({e})")

    # ── 4. Synergy play types ─────────────────────────────────────────────
    # FETCH_SYNERGY=False: endpoint is defunct server-side (HTTP 500 all seasons).
    # Skip calls entirely and go straight to fallbacks.
    if FETCH_SYNERGY:
        synergy_map = {
            "Isolation": ("synergy_iso", "synergy_iso_ppp"),
            "Postup": ("synergy_post", "synergy_post_ppp"),
            "Spotup": ("synergy_spotup", None),
            "OffScreen": ("synergy_offscreen", None),
            "Transition": ("synergy_transition", None),
            "Cut": ("synergy_cut", None),
            "PRBallHandler": ("synergy_pr_ball", None),
            "PRRollman": ("synergy_pr_roll", None),
            "OffRebound": ("synergy_off_reb", None),
        }

        for play_type, (poss_attr, ppp_attr) in synergy_map.items():
            try:
                data = client.fetch_synergy_play_type(play_type, season)
                rows = client.parse_result_set(data, "SynergyPlayType")
                # Find this player's row
                player_row = next(
                    (r for r in rows if str(r.get("PLAYER_ID", "")) == str(player_id)),
                    None
                )
                if player_row:
                    poss = float(player_row.get("POSS", 0) or 0)
                    setattr(stats, poss_attr, poss)
                    if ppp_attr:
                        setattr(stats, ppp_attr, float(player_row.get("PPP", 0) or 0))
            except Exception as e:
                print(f"  Warning: could not fetch synergy {play_type} ({e})")

    # ── 5. Pull-up shooting ───────────────────────────────────────────────
    # playerdashptshots / GeneralShooting result set has:
    #   SHOT_TYPE="Pull Ups"       → FG2A (pull-up 2PT), FG3A (pull-up 3PT)
    #   SHOT_TYPE="Catch and Shoot"→ FGA (all catch-and-shoot attempts)
    # Values are already PerGame (this endpoint honors PerMode correctly).
    # Only available from 2013-14 onward; older seasons return empty rows.
    try:
        pu = client.fetch_pullup_shooting(player_id, season, season_type)
        general_rows = client.parse_result_set(pu, "GeneralShooting")
        gen_map = {r.get("SHOT_TYPE", ""): r for r in general_rows}

        def g_field(shot_type, field):
            return float((gen_map.get(shot_type) or {}).get(field, 0) or 0)

        stats.pullup_2pt_fga  = g_field("Pull Ups", "FG2A")
        stats.pullup_3pt_fga  = g_field("Pull Ups", "FG3A")
        stats.catch_shoot_fga = g_field("Catch and Shoot", "FGA")
    except Exception as e:
        print(f"  Warning: could not fetch pull-up shooting ({e})")

    # ── 6. Synergy fallback check ─────────────────────────────────────────────
    synergy_all_zero = not FETCH_SYNERGY or all([
        stats.synergy_iso == 0, stats.synergy_post == 0,
        stats.synergy_spotup == 0, stats.synergy_offscreen == 0,
        stats.synergy_transition == 0, stats.synergy_cut == 0,
        stats.synergy_pr_ball == 0, stats.synergy_pr_roll == 0,
    ])
    if synergy_all_zero and FETCH_SYNERGY:
        print("  Note: synergyplaytypes endpoint unavailable — will use shot-type fallbacks.")

    # ── Normalize shooting-split counts to per-game ───────────────────────
    # The shooting splits endpoint (PerMode=PerGame) returns season TOTALS for
    # FGM/FGA counts, even when box score stats are already per-game. Normalize.
    g = stats.games if stats.games > 0 else 1

    shot_count_fields = [
        "fga_restricted", "fgm_restricted",
        "fga_paint_nonra", "fgm_paint_nonra",
        "fga_mid", "fgm_mid",
        "fga_lc3", "fgm_lc3",
        "fga_rc3", "fgm_rc3",
        "fga_atb3", "fgm_atb3",
        "fga_alley_oop", "fga_bank_shot", "fga_dunk", "fga_fadeaway",
        "fga_finger_roll", "fga_hook", "fga_jump_shot", "fga_layup", "fga_tip",
        "fga_step_back", "fga_driving_layup", "fga_driving_dunk", "fga_euro_step",
        "fga_putback", "fga_pullup", "fga_floater", "fga_turnaround", "fga_turnaround_fadeaway",
        "fga_uast_2pt_jump",
        "unassisted_fgm", "assisted_fgm",
        "mid_left", "mid_left_center", "mid_center", "mid_right_center", "mid_right",
        "close_left", "close_center", "close_right",
        "three_left", "three_left_center", "three_center",
        "three_right_center", "three_right",
        # Note: pullup_2pt_fga / pullup_3pt_fga / catch_shoot_fga are NOT listed here.
        # playerdashptshots honors PerMode=PerGame and returns per-game values directly.
    ]
    for field in shot_count_fields:
        val = getattr(stats, field, 0.0)
        if val > 0:
            setattr(stats, field, val / g)

    # ── Compute helpers ───────────────────────────────────────────────────
    stats.total_3pt_fga = stats.fga_lc3 + stats.fga_rc3 + stats.fga_atb3
    # For seasons where zone data is entirely missing, fall back to box-score fg3a
    if stats.total_3pt_fga == 0 and stats.fg3a > 0:
        stats.total_3pt_fga = stats.fg3a
    stats.total_fga = (stats.fga_restricted + stats.fga_paint_nonra
                       + stats.fga_mid + stats.total_3pt_fga)
    if stats.total_fga == 0 and stats.fga > 0:
        # Fallback: use overall FGA from box score
        stats.total_fga = stats.fga

    # ── Synergy fallbacks (shot-type proxies) ─────────────────────────────
    if synergy_all_zero:
        _compute_synergy_fallbacks(stats)

    return stats


def _compute_synergy_fallbacks(stats: PlayerStats) -> None:
    """
    Estimate synergy play-type frequencies from shot-type data when the
    synergyplaytypes endpoint is unavailable (HTTP 500 / defunct).

    Values are scaled to approximate POSS/game units matching what the
    mapper.py scaling anchors expect. All inputs are already per-game.
    """
    # ── ISO (POSS/game) ───────────────────────────────────────────────────
    # Best proxy for all seasons: unassisted FGM (self-created makes from AssitedShotPlayerDashboard).
    # Unassisted = ISO + post. Subtract estimated post shot volume to isolate ISO.
    # Fallback chain: unassisted_fgm → pullup_2pt_fga (player tracking) → fga_pullup (shot detail)
    if stats.synergy_iso == 0:
        if stats.unassisted_fgm > 0:
            # Estimate unassisted FGA assuming ~48% FG% on self-created shots.
            unassisted_fga = stats.unassisted_fgm / 0.48
            # Post shots (hooks, turnarounds, ~40% of fadeaways) are also unassisted —
            # subtract them to isolate face-up ISO from post-up self-creation.
            post_shot_vol = stats.fga_hook + stats.fga_turnaround + stats.fga_fadeaway * 0.40
            iso_fga = max(0.0, unassisted_fga - post_shot_vol)
            if iso_fga > 0.1:
                stats.synergy_iso = iso_fga * 1.10  # slight upward bump for TOV/FT possessions
        else:
            # No assisted data → fall back to pull-up shot counts.
            pullup_est = stats.pullup_2pt_fga or stats.fga_pullup
            if (pullup_est + stats.fga_step_back) > 0:
                stats.synergy_iso = (pullup_est + stats.fga_step_back * 0.5) * 1.35

    # ── Post (POSS/game) ──────────────────────────────────────────────────
    # Post shots: hook shots + turnarounds + ~40% of fadeaways (rest are mid-range iso).
    # FGA-to-possession multiplier ~1/0.55 (many post poss end in FT draw or TOV, not FGA).
    if stats.synergy_post == 0:
        post_shot_vol = (stats.fga_hook
                        + stats.fga_turnaround
                        + stats.fga_fadeaway * 0.40)
        if post_shot_vol > 0.05:
            stats.synergy_post = post_shot_vol / 0.55

    # ── Spot-up (POSS/game) ───────────────────────────────────────────────
    # For 2013-14+: catch_shoot_fga from player tracking is the best direct proxy.
    # For older seasons: perimeter jump shots that aren't iso/post shots approximate spot-ups.
    if stats.synergy_spotup == 0:
        if stats.catch_shoot_fga > 0:
            stats.synergy_spotup = stats.catch_shoot_fga * 1.20
        else:
            # Older seasons (no player tracking): 3PT zone attempts are overwhelmingly
            # catch-and-shoot spot-ups. Mid-range spot-ups are harder to isolate, so
            # we anchor purely on 3PT volume as a conservative but reliable proxy.
            spot_vol = stats.total_3pt_fga * 0.80
            if spot_vol > 0.05:
                stats.synergy_spotup = spot_vol * 1.20

    # ── Off-screen (POSS/game) ────────────────────────────────────────────
    # 2013-14+: ~25% of catch-and-shoot 3PT attempts come off screens.
    # Pre-2013: no player tracking, so proxy via assisted 3PT volume.
    #   Assisted 3PT makes × assisted_rate ≈ catch-and-shoot 3PT makes.
    #   ~30% of those are off-screen; / 0.55 to convert FGM → POSS estimate.
    #   This is conservative — it can't distinguish a stationary corner spacer
    #   (15% off-screen) from a curl specialist (60%+), so treat as a floor.
    if stats.synergy_offscreen == 0:
        total_3 = stats.total_3pt_fga or stats.fga_atb3
        if stats.catch_shoot_fga > 0:
            denom = max(total_3 + stats.fga_mid, 0.01)
            c_s_3_frac = total_3 / denom
            stats.synergy_offscreen = stats.catch_shoot_fga * c_s_3_frac * 0.25
        elif stats.assisted_fgm > 0 and total_3 > 0:
            _fgm_total = stats.assisted_fgm + stats.unassisted_fgm
            if _fgm_total > 0:
                _assisted_rate = stats.assisted_fgm / _fgm_total
                _est_cs_3pt_makes = total_3 * _assisted_rate
                stats.synergy_offscreen = (_est_cs_3pt_makes * 0.30) / 0.55

    # ── Transition (POSS/game) ────────────────────────────────────────────
    # Running layups are included in fga_driving_layup (can't separate).
    # Leave at 0 — mapper.py uses pct_3 context so transition scores scale to 0,
    # which is acceptable: transition 3PT pull-up tendency defaults low.
    # (Improvement: if a separate running_layup field is added to PlayerStats, use it.)

    # ── Cut (POSS/game) ───────────────────────────────────────────────────
    # Cuts produce close-range uncontested looks: putbacks, alley-oops, finger rolls.
    if stats.synergy_cut == 0:
        cut_vol = (stats.fga_putback
                   + stats.fga_alley_oop
                   + stats.fga_finger_roll * 0.50)
        if cut_vol > 0.02:
            stats.synergy_cut = cut_vol * 1.40

    # synergy_pr_ball / synergy_pr_roll: mapper.py already infers from 3PT profile.
    # synergy_off_reb: mapper.py already falls back to stats.oreb.
