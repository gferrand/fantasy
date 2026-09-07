# Sleeper EPL Capability Verification

**Audit baseline:** `origin/main` at `ebaa0e0` (2026-09-07). This is a read-only verification record for the Kick & Run league; it is not a promise that every generic Sleeper endpoint works for `clubsoccer:epl`.

## Documentation status

Sleeper's official [API documentation](https://docs.sleeper.com/) describes a read-only public API, requires no token, and documents league, user, roster, transaction, draft, matchup, player, and trending endpoint families. Its examples and sport-specific statements are NFL-centric (including an explicit "only support nfl right now" statement for one user-leagues endpoint). It does not document `clubsoccer:epl`, the stats host, or assert EPL support for the families below. Therefore **official** means the endpoint family appears in that documentation, while **observed EPL** means it was safely read from the live Kick & Run league on the audit date. Observed behavior is not a provider guarantee.

The documented API is read-only. Fantasy must retain its stricter product rule: never issue Sleeper mutations even if an undocumented write path is discovered.

## Live-safe verification

The following `GET`s used league `1378147559444348928` and the live state season/week at audit time. Responses were shape-checked only; no data was persisted or changed.

| Capability family | Endpoint shape | Official status | Live EPL result | Future use / limits |
| --- | --- | --- | --- | --- |
| league settings | `/league/{league_id}` | Documented | 200 object | Authoritative scoring, slots, season, draft ID and settings. |
| league users | `/league/{league_id}/users` | Documented | 200 array, 12 users | Map owner IDs to team names. |
| league rosters | `/league/{league_id}/rosters` | Documented | 200 array, 12 rosters | Authoritative current ownership and roster composition only when this read succeeds. |
| competition state | `/state/clubsoccer:epl` | State family documented, EPL not documented | 200 object | Current season and display week. |
| player catalog | `/players/clubsoccer:epl` | Players family documented, EPL not documented | 200 object, about 2.3 MB | Identity, eligibility, Sleeper club/status metadata. Large: refresh locally or use targeted catalog reads; not per conversational request. |
| season stats | `https://api.sleeper.com/stats/clubsoccer:epl/{season}?season_type=regular` | Undocumented | 200 array, 492 rows | Current Sleeper statistics; `pts_std` is Sleeper-standard only, never Kick & Run points. |
| gameweek stats | `https://api.sleeper.com/stats/clubsoccer:epl/{season}/{week}?season_type=regular` | Undocumented | 200 array (empty for the then-current unplayed week) | Endpoint is observed, but data availability is week-dependent. Use completed weeks only and report empty results. |
| transactions | `/league/{league_id}/transactions/{round}` | Documented | 200 array, 2 records | League activity, adds/drops/trades and state where represented. It does not prove immediate waiver availability. |
| draft picks | `/draft/{draft_id}/picks` | Documented | 200 array, 192 picks | Draft-history context; currently unused by runtime. |
| player trends | `/players/clubsoccer:epl/trending/add` | Documented family, EPL not documented | 200 array | Observed add counts; do not treat global trend as league availability or value. |
| league matchup | `/league/{league_id}/matchups/{week}` | Documented family | 404 | **Unsupported for EPL** at audit time. Do not infer a head-to-head opponent. |

The stats and EPL-specific player/state paths are intentionally classified as **observed but undocumented**, not official. The audit did not test unrelated NFL-only families, projections, or arbitrary query parameters. Those are **unverified** for EPL and must not be exposed until independently verified.

## Operational semantics

- `SleeperClient` is the current shared, resilient read-only HTTP boundary. It validates JSON and retries transient failures; several feature modules still compose their own endpoint sequence over it.
- A successful roster response is required before labeling a player `unrostered_unclassified`. A failed/malformed roster read means ownership is unknown, never unrostered.
- The public API does not distinguish direct free agents from pending waivers. `unrostered_unclassified` is not an instruction that an Add is immediately possible.
- Current club, transfer status, tactical role, availability, and expected minutes are not authoritative Sleeper facts. Treat catalog and stats metadata as stale-able and use current public research when those facts matter.
- Season-stat and weekly-stat payloads are substantial. Future capabilities must bound fields/results and reuse a request-scoped read rather than forwarding raw payloads to a model.
- Existing client retries are per request, not a request-wide deadline. A future capability boundary needs one monotonic whole-operation budget.
