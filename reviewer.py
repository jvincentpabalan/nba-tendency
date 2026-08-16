"""
reviewer.py — Map computed tendency values to their guide tier labels.

Library usage:
    from reviewer import review, format_review
    rows = review(output["tendencies"])
    print(format_review(rows, title="Bynum 2010-11"))

CLI usage:
    python3 reviewer.py <tendency_json_file>
    python3 reviewer.py output/bynum_2011.json
"""

import json
import os
import sys
from typing import Optional

GUIDE_PATH = os.path.join(os.path.dirname(__file__), "ui", "src", "data", "tendency_guide.json")


def _load_guide() -> dict:
    with open(GUIDE_PATH) as f:
        return json.load(f)


def get_tier(entry: dict, value: int) -> Optional[str]:
    """
    Return the tier label that contains value.

    Tiers have gaps between them (e.g. [0-5], [10-15] with nothing at 6-9).
    Values in a gap return the LOWER adjacent tier's label — the value hasn't
    reached the next tier yet. Values below all tiers or above all tiers
    return the nearest boundary label.
    """
    tiers = entry.get("tiers", [])
    if not tiers:
        return None

    # Direct match
    for tier in tiers:
        lo, hi = tier["range"]
        if lo <= value <= hi:
            return tier["label"]

    # Below all tiers
    if value < tiers[0]["range"][0]:
        return tiers[0]["label"]

    # Above all tiers
    if value > tiers[-1]["range"][1]:
        return tiers[-1]["label"]

    # Value is in a gap between two tiers — return the lower adjacent tier
    for i in range(len(tiers) - 1):
        if tiers[i]["range"][1] < value < tiers[i + 1]["range"][0]:
            return tiers[i]["label"]

    return tiers[-1]["label"]


def _parse_norm(nba_norm: Optional[str]) -> Optional[tuple]:
    """Parse '30–45' or '30-45' into (30, 45)."""
    if not nba_norm:
        return None
    for sep in ["\u2013", "-"]:   # en-dash then hyphen
        if sep in nba_norm:
            parts = nba_norm.split(sep)
            try:
                return int(parts[0].strip()), int(parts[1].strip())
            except (ValueError, IndexError):
                return None
    return None


def _norm_flag(value: int, norm: Optional[tuple]) -> str:
    if norm is None:
        return ""
    lo, hi = norm
    if value < lo:
        return "below norm"
    if value > hi:
        return "above norm"
    return "in norm"


def review(tendencies: dict, guide: Optional[dict] = None) -> list:
    """
    Annotate a tendencies dict with tier labels from the guide.

    Args:
        tendencies: The 'tendencies' dict from the 2K26 JSON output.
                    Maps key → {value, group, ...}.
        guide:      Pre-loaded guide dict. Loaded from disk if None.

    Returns:
        List of row dicts, one per tendency, in input order:
          key, value, group, tier, nba_norm, cap, norm_flag, at_cap, in_guide
    """
    if guide is None:
        guide = _load_guide()

    rows = []
    for key, info in tendencies.items():
        value = int(info["value"])
        group = info.get("group") or (key.split(":")[0] if ":" in key else key)
        entry = guide.get(key)

        if entry:
            tier = get_tier(entry, value)
            nba_norm = entry.get("nba_norm")
            cap = entry.get("cap")
            norm_pair = _parse_norm(nba_norm)
            norm_flag = _norm_flag(value, norm_pair)
            # AT CAP: cap must be the upper bound of the scale.
            # Guard against tendencies like Drive Right where cap=30 is
            # a minimum (left-lean floor), not an upper bound — in those
            # cases the last tier's max exceeds cap so we skip the flag.
            tiers = entry.get("tiers", [])
            cap_is_upper = cap is not None and tiers and cap >= tiers[-1]["range"][1]
            at_cap = cap_is_upper and value >= cap
        else:
            tier = None
            nba_norm = None
            cap = None
            norm_flag = ""
            at_cap = False

        rows.append({
            "key": key,
            "value": value,
            "group": group,
            "tier": tier,
            "nba_norm": nba_norm,
            "cap": cap,
            "norm_flag": norm_flag,
            "at_cap": at_cap,
            "in_guide": entry is not None,
        })
    return rows


def format_review(rows: list, title: str = "") -> str:
    """Format annotated rows into a readable text report."""
    lines = []
    if title:
        lines.append(f"{'=' * 70}")
        lines.append(f"  {title}")
        lines.append(f"{'=' * 70}")
        lines.append("")

    current_group = None
    for row in rows:
        if row["group"] != current_group:
            if current_group is not None:
                lines.append("")
            current_group = row["group"]
            lines.append(f"── {current_group} {'─' * max(0, 60 - len(current_group))}")

        short = row["key"].split(":", 1)[-1] if ":" in row["key"] else row["key"]
        value_str = str(row["value"]).rjust(3)
        tier_str = row["tier"] if row["tier"] else "(no guide entry)"

        # Norm/cap context string
        ctx_parts = []
        if row["nba_norm"]:
            ctx_parts.append(f"norm {row['nba_norm']}")
        if row["cap"] is not None:
            ctx_parts.append(f"cap {row['cap']}")
        ctx = f"  [{', '.join(ctx_parts)}]" if ctx_parts else ""

        # Status flag
        if row["at_cap"]:
            flag = "  ★ AT CAP"
        elif row["norm_flag"] == "above norm":
            flag = "  ↑ above norm"
        elif row["norm_flag"] == "below norm":
            flag = "  ↓ below norm"
        else:
            flag = ""

        lines.append(f"  {short:<42} {value_str}  {tier_str:<45}{ctx}{flag}")

    return "\n".join(lines)


def format_summary(rows: list) -> str:
    """Return a short bulleted summary of the most notable tendencies."""
    cap_hits    = [r for r in rows if r["at_cap"]]
    above_norm  = [r for r in rows if r["norm_flag"] == "above norm" and not r["at_cap"]]
    below_norm  = [r for r in rows if r["norm_flag"] == "below norm"]
    no_guide    = [r for r in rows if not r["in_guide"]]

    lines = []
    lines.append("── Summary ────────────────────────────────────────────────────────")

    if cap_hits:
        lines.append(f"\n  At cap ({len(cap_hits)}):")
        for r in cap_hits:
            short = r["key"].split(":", 1)[-1]
            lines.append(f"    {short} = {r['value']}  ({r['tier']})")

    if above_norm:
        lines.append(f"\n  Above NBA norm ({len(above_norm)}):")
        for r in above_norm[:8]:
            short = r["key"].split(":", 1)[-1]
            lines.append(f"    {short} = {r['value']}  ({r['tier']})  [norm {r['nba_norm']}]")

    if below_norm:
        lines.append(f"\n  Below NBA norm ({len(below_norm)}):")
        for r in below_norm[:8]:
            short = r["key"].split(":", 1)[-1]
            lines.append(f"    {short} = {r['value']}  ({r['tier']})  [norm {r['nba_norm']}]")

    if no_guide:
        lines.append(f"\n  No guide entry ({len(no_guide)}) — values are estimates only:")
        for r in no_guide:
            short = r["key"].split(":", 1)[-1]
            lines.append(f"    {short} = {r['value']}")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    if len(sys.argv) < 2:
        print("Usage: python3 reviewer.py <tendency_json_file>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    tendencies = data.get("tendencies", {})
    if not tendencies:
        print("No 'tendencies' key found in JSON.", file=sys.stderr)
        sys.exit(1)

    player_id = data.get("_player_id", "?")
    season    = data.get("_season", "?")
    title = f"Player {player_id}  |  Season {season}  |  {os.path.basename(path)}"

    rows = review(tendencies)
    print(format_review(rows, title=title))
    print()
    print(format_summary(rows))


if __name__ == "__main__":
    _cli()
