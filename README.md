# Sleeper FFL MCP Server

A small, focused MCP server that connects Claude to your Sleeper fantasy
football league. Read-only — it uses Sleeper's public API, needs no API key,
and cannot make changes to your team.

## Tools (13)

| Tool | What it does |
|---|---|
| `health_check` | Confirms the server is running and configured |
| `get_nfl_state` | Current NFL week / season state |
| `get_league_info` | League settings, scoring, waiver type, trade deadline |
| `get_my_team` | Your starters, bench, taxi, IR, record, FAAB |
| `get_all_rosters` | Every team's full roster |
| `get_standings` | Standings sorted by record and points |
| `get_matchups` | Weekly head-to-head matchups (yours flagged) |
| `get_free_agents` | Unrostered players, trending adds surfaced first |
| `get_trending_players` | League-wide NFL adds/drops (last 48h) |
| `search_player` | Find any player + who rosters them in your league |
| `get_transactions` | Weekly trades/waivers/FAAB bids |
| `get_recent_transactions` | Multi-week transaction history |
| `get_playoff_bracket` | Winners bracket once playoffs start |

## Deploy to Render (one time, ~15 min)

1. Create a GitHub account: https://github.com/signup (skip if you have one)
2. Create a new repo (e.g. `sleeper-ffl-mcp`), upload these 4 files:
   `sleeper_mcp.py`, `requirements.txt`, `render.yaml`, `README.md`
   (GitHub → your repo → "Add file" → "Upload files" works fine — no git
   commands needed.)
3. Create a Render account with "Sign up with GitHub": https://render.com
4. Render dashboard → **New +** → **Web Service** → pick your repo.
   Render reads `render.yaml` and pre-fills everything.
5. When prompted for environment variables, set:
   - `SLEEPER_LEAGUE_ID` = your league ID (the long number in your league URL)
   - `SLEEPER_USERNAME`  = your Sleeper username
6. Deploy. Render gives you a URL like `https://sleeper-ffl-mcp.onrender.com`

## Connect to Claude

1. On a browser go to https://claude.ai/settings/connectors
2. **Add custom connector** → name it `Sleeper FFL` → URL:
   `https://YOUR-RENDER-URL.onrender.com/mcp`
   (note the `/mcp` on the end)
3. Leave Advanced Settings / OAuth blank — not needed.
4. In any chat (including mobile), tap **+** → Connectors → enable it.

## Notes

- **Free-tier sleep:** Render's free plan spins the server down after ~15 min
  idle. The first request after that takes ~30-60 seconds while it wakes up.
  If Claude reports a connection error, wait a minute and retry.
- **Changing leagues/seasons:** update the `SLEEPER_LEAGUE_ID` env var in
  Render (Environment tab) and redeploy. New season = new league ID.
- Player database (~5MB) is fetched from Sleeper once and cached in memory
  for 24h, so most calls are fast.
