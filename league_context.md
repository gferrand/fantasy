# Kick & Run League Context

This file is the canonical human-readable configuration for the fantasy advisor. Dynamic API responses and derived reports belong under `data/` and `reports/`; they must not silently replace the static facts here.

## Manager and league identity

| Variable | Value |
| --- | --- |
| League ID | `1378147559444348928` |
| League name | `Kick & Run` |
| Sport | `clubsoccer:epl` |
| Season | `2026` (2026/27) |
| Season type | `regular` |
| League status | `in_season` |
| Teams | `12` |
| My team | `Los Blancos` |
| Sleeper username | `TioG` |
| Sleeper user ID | `1127171221277331456` |
| Previous league ID | `1126746363301117952` |

## Sleeper API

Sleeper's public API requires no authentication. Network access is required, and requests should use a normal descriptive user-agent.

Base API:

```text
https://api.sleeper.app/v1
```

Core endpoints:

```text
GET /league/{league_id}
GET /league/{league_id}/users
GET /league/{league_id}/rosters
GET /league/{league_id}/drafts
GET /players/clubsoccer:epl
GET /state/clubsoccer:epl
```

Working 2026 EPL stats endpoint:

```text
https://api.sleeper.com/stats/clubsoccer:epl/2026?season_type=regular
```

The equivalent `api.sleeper.app/v1/stats/...` route returned 404; use `api.sleeper.com/stats/...` for this stats route.

For scheduled recaps, fetch the live league, users, rosters, state, player metadata, and stats JSON on every run. The live league `scoring_settings` object is authoritative; static summaries and the roster table below are fallback context only.

Manager league-history validation endpoint:

```text
GET /user/{user_id}/leagues/clubsoccer:epl/2026
```

## Draft

| Variable | Value |
| --- | --- |
| Draft ID | `1378147559456903168` |
| Type | `auction` |
| Status | `complete` |
| Budget | `250` |
| Rounds | `16` |

The public draft endpoint returned auction metadata but not individual auction prices.

## Roster and league settings

Roster positions:

```text
F F M M M D D D GK FM_FLEX MD_FLEX BN BN BN BN BN
```

| Setting | Value |
| --- | --- |
| Waiver budget | `100` |
| Waiver type | `2` |
| Daily waivers | Disabled |
| Waiver clear days | `1` |
| Trade deadline | Week `30` |
| Playoff teams | `4` |
| Playoff week start | Week `32` |
| Reserve slots | `2` |

## Scoring summary

This league does not use standard FPL scoring. The exact raw scoring map is expected at:

```text
data/sleeper_current_league.json
```

Important fetched values:

| Category | Values |
| --- | --- |
| Goals | M/D/F: `9`; GK: `10` |
| Assists | M/D/F/GK: `6–7`, position-dependent |
| Key passes | M/D/GK/F: `2` |
| Shots on target | M/D/F/GK: `2` |
| Tackles / successful actions | Generally `1` |
| Interceptions | Generally `1` |
| Blocks | Generally `1` |
| Aerial wins | Generally `0.5–1` |
| Clean sheets | D: `6`; M: `1`; GK: `8`, position-dependent |
| Penalty won | `8` |
| Penalty missed | `-4` |
| Yellow card | `-1` |
| Red card | `-7` |
| Own goal | `-5` |

Historical points were calculated by matching `pos_{position}_*` scoring keys against Sleeper/Opta stat fields. Future scoring analysis must use the raw league scoring map, not standard FPL assumptions.

## Current Los Blancos roster

| Player | Club | Eligibility | Availability |
| --- | --- | --- | --- |
| Mohamed Belloumi | HUL | F | — |
| Micky van de Ven | TOT | D | Out |
| Bernd Leno | FUL | GK | — |
| Harvey Barnes | NEW | M | — |
| Antoine Semenyo | MCI | F | — |
| Kevin Schade | BRE | F/M | — |
| Yoane Wissa | NEW | F | — |
| Nathan Collins | BRE | D | — |
| Mikkel Damsgaard | BRE | M | — |
| Jean-Philippe Mateta | CRY | F | — |
| Bukayo Saka | ARS | F/M | — |
| Ian Maatsen | AVL | D | — |
| Jake O'Brien | EVE | D | — |
| Ferdi Kadioglu | BHA | D | — |
| Granit Xhaka | SUN | M | — |
| Abdukodir Khusanov | MCI | D | — |
| Igor Jesus | NFO | F | — |

## Current-player-pool rules

The reconstructed baseline was:

```text
Los Blancos roster: 17 players
Total rostered players: 199
Active current EPL pool: 987
Available current EPL players: 790
Available MID-eligible players: 273
Unresolved Sleeper player-ID joins: 0
```

The active EPL pool is defined as:

```text
Sleeper player ID
+ active status
+ EPL competition tag
+ current 2026/27 Premier League club whitelist
+ external transfer/news overrides
```

Current 2026/27 Premier League club whitelist:

```text
ARS AVL BOU BRE BHA CHE CRY EVE FUL HUL
IPS LIV LEE MCI MUN NEW NFO SUN TOT COV
```

Known transfer overrides:

| Player | Override |
| --- | --- |
| Mohamed Salah | Exclude: transferred from Liverpool to Trabzonspor |
| Leandro Trossard | Exclude: transferred from Arsenal to Beşiktaş |

Sleeper's `competitions` field can be stale. Never recommend a player solely because Sleeper labels them EPL-eligible.

## Injury and availability overrides

| Player | Status / policy |
| --- | --- |
| Xavi Simons | Sleeper `Out`; Tottenham confirmed ruptured ACL and surgery. Do not treat as a normal waiver target. |
| Joelinton | Sleeper `Out`; verify current reporting before any recommendation. |
| David Brooks | Sleeper `GTD`; verify current reporting before lineup advice. |
| Micky van de Ven | Current Los Blancos roster lists `Out`; verify latest status before lineup advice. |

## Source and freshness policy

1. Use Sleeper for league state, roster ownership, positions, status flags, and player IDs.
2. Use authoritative current-club, club, league, or reputable news sources to verify transfers, injuries, suspensions, and expected availability.
3. Prefer the newest source available and record the retrieval date in dynamic data and reports.
4. If current-club or injury status cannot be verified, label the recommendation uncertain and do not present it as a confident target.
5. All advice is advisory. The manager makes the final decision and executes any action manually.
