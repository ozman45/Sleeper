"""
Sleeper FFL MCP Server
======================
A focused Model Context Protocol server for managing a single Sleeper
fantasy football league. Built with FastMCP. Read-only: uses Sleeper's
public API (no authentication, no API key, cannot modify your team).

Configuration (environment variables):
  SLEEPER_LEAGUE_ID  (required) - your league's ID from the Sleeper URL
  SLEEPER_USERNAME   (required) - your Sleeper username, so "my team"
                                  tools know which roster is yours
  PORT               (optional) - set automatically by Render

Run locally:      python sleeper_mcp.py          (stdio, for Claude Desktop)
Run as web app:   python sleeper_mcp.py http     (for Render / claude.ai)
"""

import os
import sys
import time
import httpx
from fastmcp import FastMCP

BASE = "https://api.sleeper.app/v1"
LEAGUE_ID = os.environ.get("SLEEPER_LEAGUE_ID", "")
USERNAME = os.environ.get("SLEEPER_USERNAME", "")

mcp = FastMCP("Sleeper FFL")

# ---------------------------------------------------------------------------
# HTTP + caching helpers
# ---------------------------------------------------------------------------

_client = httpx.Client(timeout=30.0)
_cache: dict = {}


def _get(path: str, ttl: int = 60):
    """GET a Sleeper API path with a small in-memory TTL cache."""
    now = time.time()
    if path in _cache:
        ts, data = _cache[path]
        if now - ts < ttl:
            return data
    resp = _client.get(f"{BASE}{path}")
    resp.raise_for_status()
    data = resp.json()
    _cache[path] = (now, data)
    return data


def _players(ttl: int = 86400) -> dict:
    """Full NFL player database (large; cached 24h), trimmed to useful fields."""
    now = time.time()
    if "_players" in _cache:
        ts, data = _cache["_players"]
        if now - ts < ttl:
            return data
    raw = _client.get(f"{BASE}/players/nfl", timeout=60.0).json()
    trimmed = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        trimmed[pid] = {
            "name": p.get("full_name")
            or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "pos": p.get("position"),
            "team": p.get("team"),
            "status": p.get("status"),
            "injury": p.get("injury_status"),
            "age": p.get("age"),
            "years_exp": p.get("years_exp"),
            "number": p.get("number"),
        }
    _cache["_players"] = (now, trimmed)
    return trimmed


def _pname(pid, players=None) -> str:
    """player_id -> 'Name (POS, TEAM) [injury]' string."""
    if players is None:
        players = _players()
    p = players.get(str(pid))
    if not p:
        return f"Unknown ({pid})"
    s = f"{p['name']} ({p.get('pos')}, {p.get('team') or 'FA'})"
    if p.get("injury"):
        s += f" [{p['injury']}]"
    return s


def _league_users() -> dict:
    """owner_id -> {username, display_name, team_name}"""
    users = _get(f"/league/{LEAGUE_ID}/users", ttl=3600)
    out = {}
    for u in users:
        out[u["user_id"]] = {
            "username": u.get("username") or u.get("display_name"),
            "display_name": u.get("display_name"),
            "team_name": (u.get("metadata") or {}).get("team_name")
            or u.get("display_name"),
        }
    return out


def _rosters() -> list:
    return _get(f"/league/{LEAGUE_ID}/rosters", ttl=300)


def _my_user_id() -> str:
    user = _get(f"/user/{USERNAME}", ttl=86400)
    return user["user_id"]


def _my_roster() -> dict:
    uid = _my_user_id()
    for r in _rosters():
        if r.get("owner_id") == uid or uid in (r.get("co_owners") or []):
            return r
    raise ValueError(
        f"No roster found for username '{USERNAME}' in league {LEAGUE_ID}. "
        "Check SLEEPER_USERNAME and SLEEPER_LEAGUE_ID env vars."
    )


def _current_week() -> int:
    state = _get("/state/nfl", ttl=3600)
    return int(state.get("week") or state.get("display_week") or 1)


def _fmt_roster(r: dict, users: dict, players: dict) -> dict:
    owner = users.get(r.get("owner_id"), {})
    settings = r.get("settings") or {}
    starters = [str(x) for x in (r.get("starters") or []) if x and x != "0"]
    all_players = [str(x) for x in (r.get("players") or [])]
    bench = [p for p in all_players if p not in starters]
    return {
        "roster_id": r.get("roster_id"),
        "team": owner.get("team_name"),
        "owner": owner.get("display_name"),
        "record": f"{settings.get('wins',0)}-{settings.get('losses',0)}"
        + (f"-{settings.get('ties')}" if settings.get("ties") else ""),
        "points_for": settings.get("fpts", 0),
        "points_against": settings.get("fpts_against", 0),
        "waiver_position": settings.get("waiver_position"),
        "faab_remaining": settings.get("waiver_budget_used") is not None
        and (100 - settings.get("waiver_budget_used", 0))
        or None,
        "starters": [_pname(p, players) for p in starters],
        "bench": [_pname(p, players) for p in bench],
        "taxi": [_pname(p, players) for p in (r.get("taxi") or [])],
        "injured_reserve": [_pname(p, players) for p in (r.get("reserve") or [])],
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool
def health_check() -> dict:
    """Verify the server is running and configured correctly."""
    return {
        "status": "ok",
        "league_id_set": bool(LEAGUE_ID),
        "username_set": bool(USERNAME),
    }


@mcp.tool
def get_nfl_state() -> dict:
    """Current NFL season/week state (season type, current week, etc.)."""
    return _get("/state/nfl", ttl=3600)


@mcp.tool
def get_league_info() -> dict:
    """League name, size, status, scoring settings, and roster positions."""
    lg = _get(f"/league/{LEAGUE_ID}", ttl=3600)
    return {
        "name": lg.get("name"),
        "season": lg.get("season"),
        "status": lg.get("status"),
        "total_teams": lg.get("total_rosters"),
        "roster_positions": lg.get("roster_positions"),
        "scoring_settings": lg.get("scoring_settings"),
        "playoff_teams": (lg.get("settings") or {}).get("playoff_teams"),
        "playoff_week_start": (lg.get("settings") or {}).get("playoff_week_start"),
        "waiver_type": (lg.get("settings") or {}).get("waiver_type"),
        "waiver_budget": (lg.get("settings") or {}).get("waiver_budget"),
        "trade_deadline_week": (lg.get("settings") or {}).get("trade_deadline"),
    }


@mcp.tool
def get_my_team() -> dict:
    """Your full roster: starters, bench, taxi, IR, record, points, FAAB."""
    players = _players()
    users = _league_users()
    return _fmt_roster(_my_roster(), users, players)


@mcp.tool
def get_all_rosters() -> list:
    """Every team's roster in the league (starters, bench, records)."""
    players = _players()
    users = _league_users()
    return [_fmt_roster(r, users, players) for r in _rosters()]


@mcp.tool
def get_standings() -> list:
    """League standings sorted by record then points for."""
    users = _league_users()
    rows = []
    for r in _rosters():
        s = r.get("settings") or {}
        owner = users.get(r.get("owner_id"), {})
        rows.append(
            {
                "team": owner.get("team_name"),
                "owner": owner.get("display_name"),
                "wins": s.get("wins", 0),
                "losses": s.get("losses", 0),
                "ties": s.get("ties", 0),
                "points_for": s.get("fpts", 0),
                "points_against": s.get("fpts_against", 0),
            }
        )
    rows.sort(key=lambda x: (x["wins"], x["points_for"]), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


@mcp.tool
def get_matchups(week: int = 0) -> list:
    """All head-to-head matchups for a week (0 = current week), with scores
    and starters. Your matchup is flagged with is_my_team."""
    if not week:
        week = _current_week()
    players = _players()
    users = _league_users()
    roster_owner = {r["roster_id"]: r.get("owner_id") for r in _rosters()}
    try:
        my_rid = _my_roster().get("roster_id")
    except Exception:
        my_rid = None
    matchups = _get(f"/league/{LEAGUE_ID}/matchups/{week}", ttl=120)
    grouped: dict = {}
    for m in matchups or []:
        grouped.setdefault(m.get("matchup_id"), []).append(m)
    out = []
    for mid, teams in grouped.items():
        entry = {"matchup_id": mid, "week": week, "teams": []}
        for t in teams:
            owner = users.get(roster_owner.get(t["roster_id"]), {})
            entry["teams"].append(
                {
                    "team": owner.get("team_name"),
                    "owner": owner.get("display_name"),
                    "is_my_team": t["roster_id"] == my_rid,
                    "points": t.get("points"),
                    "starters": [_pname(p, players) for p in (t.get("starters") or []) if p and p != "0"],
                }
            )
        out.append(entry)
    return out


@mcp.tool
def get_free_agents(position: str = "", limit: int = 40) -> list:
    """Available (unrostered) players in your league, optionally filtered by
    position (QB, RB, WR, TE, K, DEF). Sorted with currently-trending adds
    first so the most-added waiver targets surface at the top."""
    players = _players()
    rostered = set()
    for r in _rosters():
        for pid in r.get("players") or []:
            rostered.add(str(pid))
    trending = _get("/players/nfl/trending/add?lookback_hours=48&limit=300", ttl=1800)
    trend_rank = {str(t["player_id"]): i for i, t in enumerate(trending or [])}
    pos = position.upper().strip()
    results = []
    for pid, p in players.items():
        if pid in rostered:
            continue
        if not p.get("pos") or p.get("pos") in ("OL", "P", "LS"):
            continue
        if pos and p["pos"] != pos:
            continue
        if p.get("status") not in ("Active", None) and p.get("pos") != "DEF":
            continue
        results.append(
            {
                "player": _pname(pid, players),
                "player_id": pid,
                "age": p.get("age"),
                "trending_rank": trend_rank.get(pid),
            }
        )
    results.sort(key=lambda x: x["trending_rank"] if x["trending_rank"] is not None else 10**9)
    return results[:limit]


@mcp.tool
def get_trending_players(trend_type: str = "add", limit: int = 25) -> list:
    """League-wide NFL trending players over the last 48 hours.
    trend_type: 'add' (waiver pickups) or 'drop' (players being cut)."""
    players = _players()
    data = _get(f"/players/nfl/trending/{trend_type}?lookback_hours=48&limit={limit}", ttl=1800)
    return [
        {"player": _pname(t["player_id"], players), "count": t.get("count")}
        for t in (data or [])
    ]


@mcp.tool
def search_player(name: str) -> list:
    """Find NFL players by (partial) name. Returns id, position, team,
    injury status, and whether/where they're rostered in your league."""
    players = _players()
    users = _league_users()
    owner_of = {}
    for r in _rosters():
        owner = users.get(r.get("owner_id"), {})
        for pid in r.get("players") or []:
            owner_of[str(pid)] = owner.get("team_name")
    q = name.lower().strip()
    hits = []
    for pid, p in players.items():
        if q in (p.get("name") or "").lower():
            hits.append(
                {
                    "player": _pname(pid, players),
                    "player_id": pid,
                    "age": p.get("age"),
                    "years_exp": p.get("years_exp"),
                    "rostered_by": owner_of.get(pid, "FREE AGENT"),
                }
            )
    return hits[:25]


@mcp.tool
def get_transactions(week: int = 0) -> list:
    """League transactions (trades, waivers, free agent moves) for a week
    (0 = current week). Shows who added/dropped whom and FAAB bids."""
    if not week:
        week = _current_week()
    players = _players()
    users = _league_users()
    roster_owner = {r["roster_id"]: r.get("owner_id") for r in _rosters()}

    def team_of(rid):
        return users.get(roster_owner.get(rid), {}).get("team_name", f"roster {rid}")

    txns = _get(f"/league/{LEAGUE_ID}/transactions/{week}", ttl=300)
    out = []
    for t in txns or []:
        entry = {
            "type": t.get("type"),
            "status": t.get("status"),
            "week": week,
            "teams": [team_of(rid) for rid in (t.get("roster_ids") or [])],
            "adds": {
                _pname(pid, players): team_of(rid)
                for pid, rid in (t.get("adds") or {}).items()
            },
            "drops": {
                _pname(pid, players): team_of(rid)
                for pid, rid in (t.get("drops") or {}).items()
            },
        }
        if (t.get("settings") or {}).get("waiver_bid") is not None:
            entry["faab_bid"] = t["settings"]["waiver_bid"]
        if t.get("draft_picks"):
            entry["draft_picks_traded"] = len(t["draft_picks"])
        out.append(entry)
    return out


@mcp.tool
def get_recent_transactions(weeks_back: int = 3) -> list:
    """Transactions across the last several weeks in one call — useful for
    seeing league-wide waiver/trade activity trends."""
    cur = _current_week()
    out = []
    for w in range(max(1, cur - weeks_back + 1), cur + 1):
        for t in get_transactions(week=w):
            out.append(t)
    return out


@mcp.tool
def get_playoff_bracket() -> dict:
    """Playoff winners bracket (only meaningful once playoffs begin)."""
    try:
        bracket = _get(f"/league/{LEAGUE_ID}/winners_bracket", ttl=600)
    except Exception:
        return {"note": "Bracket not available yet."}
    return {"winners_bracket": bracket}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        port = int(os.environ.get("PORT", 8000))
        mcp.run(transport="http", host="0.0.0.0", port=port)
    else:
        mcp.run()
