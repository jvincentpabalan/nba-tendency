#!/usr/bin/env python3
"""
Mapper regression checker.

Run after any mapper change to verify canonical players still land
in expected ranges. Uses local cache — no API calls.

Usage:
    python3 scripts/regression.py             # all cases
    python3 scripts/regression.py rose kidd   # filter by label keyword
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from stats_collector import collect
import mapper

# ── Canonical test cases ──────────────────────────────────────────────────────
# Each entry: (label, player_id, season, season_type, checks)
# checks: dict of tendency_key → (lo, hi) expected inclusive range
# Use short tendency keys (the part after the group colon).
# Set lo==hi for an exact value check.
#
# Add new cases here whenever you validate a player's output.

CASES = [
    (
        "Rose 2010-11",
        201565, "2010-11", "Regular Season",
        {
            "Shot Three":         (28, 36),   # drive-first guard, rim_vol discount
            "Drive":              (70, 75),   # at cap — elite rim attacker
            "Shot Under Basket":  (45, 60),   # primary interior threat
            "Spot Up Shot Three": (28, 40),   # takes some spot-up 3s
        },
    ),
    (
        "Kidd 2010-11",
        467, "2010-11", "Regular Season",
        {
            "Shot Three":         (28, 40),   # distributor discount; cap tightened
            "Dish To Open Man":   (40, 58),   # elite passer
            "Touches":            (15, 28),   # low-touch role (distributor)
        },
    ),
    (
        "Boozer 2010-11",
        2430, "2010-11", "Regular Season",
        {
            "Post Hook Right":    (22, 34),   # 0.76 hooks/game, high_raw=1.5
            "Post Up":            (38, 55),   # regular post option
            "Shot Three":         (2,  8),    # non-shooter
        },
    ),
    (
        "Deng 2010-11",
        2736, "2010-11", "Regular Season",
        {
            "Shot Three":           (35, 44),   # above-avg but not specialist; rim_vol discount
            "Spot Up Shot Three":   (40, 52),   # high C&S rate but not at cap (high_raw=8.0)
            "Drive":                (35, 48),   # versatile wing
            "Spot Up Shot Mid-Range": (28, 42), # receives mid-range passes; 76% of mid makes assisted
        },
    ),
    (
        "Dirk 2010-11",
        1717, "2010-11", "Regular Season",
        {
            "Shot Mid-Range":     (38, 45),   # primary mid-range scorer
            "Post Fade Left":     (35, 50),   # dominant fade direction
            "Shot Three":         (18, 28),   # live API: ~2.3 3PA/game (more than mock 0.49)
            "Roll vs. Pop":       (5,  15),   # pure pop screener
        },
    ),
]

# ── Runner ────────────────────────────────────────────────────────────────────

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def short_key(full_key: str) -> str:
    """'Jump Shooting:Shot Three' → 'Shot Three'"""
    return full_key.split(":", 1)[-1] if ":" in full_key else full_key

def find_val(tendencies: dict, short: str):
    """Look up by short key (suffix match)."""
    for k, v in tendencies.items():
        if short_key(k) == short:
            return v
    return None

def run(filter_kws=None):
    cases = CASES
    if filter_kws:
        cases = [c for c in cases if any(kw.lower() in c[0].lower() for kw in filter_kws)]
        if not cases:
            print(f"No cases matched: {filter_kws}")
            return

    total = passed = 0
    col_w = 28

    for label, pid, season, stype, checks in cases:
        print(f"\n{BOLD}{label}{RESET}  (player {pid})")
        try:
            stats = collect(pid, season, stype)
        except Exception as e:
            print(f"  {RED}LOAD ERROR: {e}{RESET}")
            continue

        t = mapper.compute(stats)

        for short, (lo, hi) in checks.items():
            val = find_val(t, short)
            total += 1
            if val is None:
                tag = f"{YELLOW}MISSING{RESET}"
            elif lo <= val <= hi:
                tag = f"{GREEN}✓ {val}{RESET}"
                passed += 1
            else:
                expected = f"[{lo}–{hi}]" if lo != hi else f"{lo}"
                tag = f"{RED}✗ {val}  (expected {expected}){RESET}"

            print(f"  {short:<{col_w}} {tag}")

    print(f"\n{'─'*45}")
    color = GREEN if passed == total else RED
    print(f"{color}{BOLD}{passed}/{total} checks passed{RESET}")

if __name__ == "__main__":
    run(sys.argv[1:] or None)
