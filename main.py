#!/usr/bin/env python3
"""
NBA → NBA 2K26 Tendency Generator

Usage:
    python main.py --player 1717 --season 2010-11
    python main.py --player 2544 --season 2023-24 --output lebron.json
    python main.py --player 1717 --season 2010-11 --mock   # use cached test data
"""

import argparse
import json
import subprocess
import sys
import os

import stats_collector
import mapper
import reviewer


def parse_args():
    p = argparse.ArgumentParser(
        description="Convert NBA player stats to NBA 2K26 tendencies"
    )
    p.add_argument("--player", type=int, required=True,
                   help="NBA.com player ID (e.g. 1717 for Dirk Nowitzki)")
    p.add_argument("--season", type=str, required=True,
                   help="Season(s) in YYYY-YY format. Comma-separated for multi-season blend "
                        "(e.g. 2010-11,2011-12,2012-13). Seasons are games-weighted.")
    p.add_argument("--output", type=str, default=None,
                   help="Output JSON file path (default: stdout)")
    p.add_argument("--mock", action="store_true",
                   help="Use mock data for testing without hitting the NBA API")
    p.add_argument("--pretty", action="store_true", default=True,
                   help="Pretty-print JSON output (default: true)")
    p.add_argument("--debug", action="store_true",
                   help="Print key stat inputs before computing tendencies")
    p.add_argument("--copy", action="store_true",
                   help="Copy JSON output to clipboard (macOS pbcopy)")
    p.add_argument("--review", action="store_true",
                   help="Print annotated tier-label review instead of raw JSON")
    p.add_argument("--playoffs", action="store_true",
                   help="Use Playoffs stats instead of Regular Season (single season only)")
    p.add_argument("--blend", nargs="?", const=70, type=int, metavar="RS_WEIGHT",
                   help="Blend Regular Season with Playoffs per season. "
                        "Optionally specify RS weight as integer percent (default: 70). "
                        "Example: --blend or --blend 60 (60%% RS / 40%% PO). "
                        "Cannot be combined with --playoffs.")
    return p.parse_args()


def mock_stats(player_id: int, season: str) -> stats_collector.PlayerStats:
    """Return representative mock stats for Dirk Nowitzki 2010-11.

    All shot counts are PER GAME (season totals ÷ 73 games), matching what
    stats_collector.collect() produces after normalization.
    Box score and synergy stats are also per-game.
    """
    s = stats_collector.PlayerStats()
    s.games   = 73
    s.minutes = 37.3
    # Box score (per-game from general splits)
    s.pts  = 23.0
    s.fgm  = 8.3
    s.fga  = 17.3
    s.fg3m = 1.0
    s.fg3a = 2.6
    s.ftm  = 6.2
    s.fta  = 7.0
    s.oreb = 1.4
    s.dreb = 6.8
    s.reb  = 8.1
    s.ast  = 2.7
    s.usg_pct = 0.272   # Basketball-Reference 2010-11 (27.2%)
    s.stl  = 0.9
    s.blk  = 0.6
    s.tov  = 2.1
    s.pf   = 1.9
    s.pfd  = 7.0

    # Shot zones — per-game (season totals ÷ 73)
    s.fga_restricted  = 2.41   # 176/73
    s.fgm_restricted  = 1.63
    s.fga_paint_nonra = 2.30   # 168/73
    s.fgm_paint_nonra = 0.99
    s.fga_mid         = 9.14   # 667/73
    s.fgm_mid         = 4.84
    s.fga_lc3         = 0.34   # 25/73
    s.fgm_lc3         = 0.21
    s.fga_rc3         = 0.18   # 13/73
    s.fgm_rc3         = 0.08
    s.fga_atb3        = 1.77   # 129/73
    s.fgm_atb3        = 0.62

    # Shot types — per-game
    s.fga_alley_oop  = 0.03    # 2/73
    s.fga_bank_shot  = 0.53    # 39/73
    s.fga_dunk       = 0.14    # 10/73
    s.fga_fadeaway   = 2.05    # 150/73
    s.fga_finger_roll= 0.19    # 14/73
    s.fga_hook       = 0.12    # 9/73
    s.fga_jump_shot  = 12.88   # 940/73
    s.fga_layup      = 2.03    # 148/73
    s.fga_tip        = 0.04    # 3/73

    # Shot type detail — per-game
    s.fga_step_back    = 0.49  # 36/73
    s.fga_driving_layup= 0.89  # 65/73
    s.fga_driving_dunk = 0.07  # 5/73
    s.fga_euro_step    = 0.0
    s.fga_putback      = 0.07  # 5/73
    s.fga_pullup       = 0.11  # 8/73
    s.fga_floater      = 0.01  # 1/73
    s.fga_turnaround          = 0.77  # 56/73 — all turnaround variants
    s.fga_turnaround_fadeaway = 0.22  # ~16/73 — back-to-basket fade subset

    # Shot chart directional — per-game (Dirk: center-heavy mid, ATB3 dominant)
    s.mid_left         = s.fga_mid * 0.18
    s.mid_left_center  = s.fga_mid * 0.12
    s.mid_center       = s.fga_mid * 0.35
    s.mid_right_center = s.fga_mid * 0.17
    s.mid_right        = s.fga_mid * 0.18

    close_total = s.fga_restricted + s.fga_paint_nonra
    s.close_left   = close_total * 0.25
    s.close_center = close_total * 0.40
    s.close_right  = close_total * 0.35

    s.three_left         = s.fga_lc3 + s.fga_atb3 * 0.10
    s.three_left_center  = s.fga_atb3 * 0.20
    s.three_center       = s.fga_atb3 * 0.40
    s.three_right_center = s.fga_atb3 * 0.20
    s.three_right        = s.fga_rc3 + s.fga_atb3 * 0.10

    # Synergy play types — per game (possessions)
    s.synergy_iso        = 3.5   # Dirk: frequent isolation scorer
    s.synergy_post       = 5.5   # Primary post-up creator
    s.synergy_spotup     = 1.2
    s.synergy_offscreen  = 0.3
    s.synergy_transition = 0.5
    s.synergy_cut        = 0.2
    s.synergy_pr_ball    = 0.8
    s.synergy_pr_roll    = 0.0   # Dirk pops, never rolls
    s.synergy_off_reb    = s.oreb

    # Pull-up shooting — per-game
    s.pullup_2pt_fga  = 3.0    # Dirk creates off the dribble frequently
    s.pullup_3pt_fga  = 0.3
    s.catch_shoot_fga = 1.0

    s.total_3pt_fga = s.fga_lc3 + s.fga_rc3 + s.fga_atb3
    s.total_fga = s.fga_restricted + s.fga_paint_nonra + s.fga_mid + s.total_3pt_fga
    return s


def _copy_to_clipboard(text: str) -> None:
    import platform
    data = text.encode()
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["pbcopy"], input=data, check=True)
        elif system == "Windows":
            subprocess.run(["clip"], input=data, check=True)
        else:
            # Linux: try xclip, fall back to xsel
            try:
                subprocess.run(["xclip", "-selection", "clipboard"], input=data, check=True)
            except FileNotFoundError:
                subprocess.run(["xsel", "--clipboard", "--input"], input=data, check=True)
        print("\nJSON copied to clipboard.")
    except FileNotFoundError:
        print("\nError: no clipboard tool found. Install xclip or xsel on Linux.", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"\nError copying to clipboard: {e}", file=sys.stderr)


def _collect_one(player_id, season, season_type, mock):
    """Fetch a single season/type, with mock fallback."""
    if mock:
        return mock_stats(player_id, season)
    return stats_collector.collect(player_id, season, season_type)


def _describe_blend(seasons: list, blend_pct, playoffs: bool) -> str:
    """Human-readable description of what was blended."""
    if len(seasons) == 1:
        season_str = seasons[0]
    elif len(seasons) == 2:
        season_str = f"{seasons[0]} / {seasons[1]}"
    else:
        season_str = f"{seasons[0]} – {seasons[-1]} ({len(seasons)} seasons)"

    if blend_pct is not None:
        po_pct = 100 - blend_pct
        return f"{season_str}  [{blend_pct}% RS / {po_pct}% PO blended]"
    if playoffs:
        return f"{season_str}  [Playoffs]"
    return f"{season_str}  [Regular Season]"


def main():
    args = parse_args()

    if args.playoffs and args.blend is not None:
        print("Error: --playoffs and --blend are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    seasons = [s.strip() for s in args.season.split(",")]
    multi_season = len(seasons) > 1

    blend_pct = args.blend  # int (e.g. 70) or None
    rs_weight = blend_pct / 100.0 if blend_pct is not None else None
    po_weight = 1.0 - rs_weight if rs_weight is not None else None

    desc = _describe_blend(seasons, blend_pct, args.playoffs)
    print(f"Generating 2K26 tendencies for player {args.player}")
    print(f"  {desc}")
    print("=" * 60)

    if args.mock and multi_season:
        print("Note: --mock with multiple seasons repeats the same mock data per season.")

    # ── Collect stats (one or more seasons, optionally RS+PO blended) ────────
    season_stats_list = []  # list of PlayerStats
    season_game_counts = []  # RS game counts for multi-season weighting

    for season in seasons:
        if blend_pct is not None:
            # RS + PO blend
            print(f"\n[{season}] Fetching Regular Season...")
            try:
                rs = _collect_one(args.player, season, "Regular Season", args.mock)
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)
                sys.exit(1)

            print(f"[{season}] Fetching Playoffs...")
            try:
                po = _collect_one(args.player, season, "Playoffs", args.mock)
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)
                sys.exit(1)

            if po.games == 0:
                print(f"  Warning: no Playoffs data found for {season} — using Regular Season only.")
                season_stats_list.append(rs)
            else:
                print(f"  Blending {rs.games} RS games ({blend_pct}%) + "
                      f"{po.games} PO games ({100 - blend_pct}%)")
                blended = stats_collector.blend_stats([rs, po], [rs_weight, po_weight])
                blended.games = rs.games  # keep RS games as the multi-season weight anchor
                season_stats_list.append(blended)

            season_game_counts.append(rs.games if rs.games > 0 else 1)

        else:
            season_type = "Playoffs" if args.playoffs else "Regular Season"
            prefix = f"\n[{season}] " if multi_season else ""
            if args.mock:
                print(f"{prefix}Using mock data (--mock flag set)")
            else:
                print(f"{prefix}Fetching stats from NBA.com (this may take ~30 seconds)...")
            try:
                s = _collect_one(args.player, season, season_type, args.mock)
            except Exception as e:
                print(f"\nError fetching stats: {e}", file=sys.stderr)
                print("Tip: Try --mock to test with sample data.", file=sys.stderr)
                sys.exit(1)
            season_stats_list.append(s)
            season_game_counts.append(s.games if s.games > 0 else 1)

    # ── Merge across seasons (games-weighted) ────────────────────────────────
    if multi_season:
        print(f"\nBlending {len(seasons)} seasons (games-weighted: "
              + ", ".join(f"{s}={g}g" for s, g in zip(seasons, season_game_counts))
              + ")...")
        stats = stats_collector.blend_stats(season_stats_list,
                                            [float(g) for g in season_game_counts])
        stats.games = sum(season_game_counts)
    else:
        stats = season_stats_list[0]

    if args.debug:
        print("\n--- Key stat inputs ---")
        print(f"  games={stats.games}  fga={stats.fga:.2f}  fg3a={stats.fg3a:.2f}")
        print(f"  fga_restricted={stats.fga_restricted:.2f}  fga_paint_nonra={stats.fga_paint_nonra:.2f}")
        print(f"  fga_mid={stats.fga_mid:.2f}  total_3pt_fga={stats.total_3pt_fga:.2f}")
        print(f"  total_fga={stats.total_fga:.2f}")
        print(f"  pullup_2pt_fga={stats.pullup_2pt_fga:.2f}  fga_pullup={stats.fga_pullup:.2f}  fga_uast_2pt_jump={stats.fga_uast_2pt_jump:.2f}")
        print(f"  synergy_iso={stats.synergy_iso:.2f}  synergy_post={stats.synergy_post:.2f}")
        print(f"  unassisted_fgm={stats.unassisted_fgm:.2f}  assisted_fgm={stats.assisted_fgm:.2f}")
        print("-" * 40)

    print("\nComputing tendencies...")
    tendencies = mapper.compute(stats)
    output = mapper.to_2k26_json(tendencies)

    # Add metadata
    output["_player_id"] = args.player
    output["_season"] = args.season        # original CLI input (backward compat)
    output["_seasons"] = seasons           # list of all seasons included
    if blend_pct is not None:
        output["_blend"] = {"regular_season_pct": blend_pct, "playoffs_pct": 100 - blend_pct}

    # Review mode: print annotated tier labels instead of raw JSON
    if args.review:
        title = f"Player {args.player}  |  {desc}"
        rows = reviewer.review(output["tendencies"])
        print()
        print(reviewer.format_review(rows, title=title))
        print()
        print(reviewer.format_summary(rows))
        if args.output:
            indent = 2 if args.pretty else None
            json_str = json.dumps(output, indent=indent)
            with open(args.output, "w") as f:
                f.write(json_str)
            print(f"\nJSON also written to {args.output}")
        return

    # Output
    indent = 2 if args.pretty else None
    json_str = json.dumps(output, indent=indent)

    if args.output:
        with open(args.output, "w") as f:
            f.write(json_str)
        print(f"\nOutput written to {args.output}")
    else:
        print("\n" + json_str)

    if args.copy:
        _copy_to_clipboard(json_str)


if __name__ == "__main__":
    main()
