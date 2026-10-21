# ESPN Fantasy Basketball — daily pull + weekly win probability

A GitHub Action runs `pull.py` every morning (~5am Pacific, with a 7:43am backup). It pulls your league from ESPN,
estimates each team's points for the rest of the matchup, converts that into a win
probability with a z-score, and commits the CSVs to `data/`.

## Setup (about 10 minutes)

1. **Create a private GitHub repo** and push these files to it. Keep it private: the CSVs
   contain your league's team and player data.
2. **Get your league ID.** Open your league on fantasy.espn.com; the URL contains
   `leagueId=12345678`. That number is your league ID.
3. **Get your two ESPN cookies** (needed because the league is private):
   1. In Chrome, log in at https://fantasy.espn.com and open your league.
   2. Press `F12` (Mac: `Cmd+Option+I`) → **Application** tab → **Cookies** →
      `https://fantasy.espn.com`. (Firefox: **Storage** tab → Cookies.)
   3. Copy the value of **`espn_s2`**: a long string, 200+ characters, often with `%2B`
      and `%3D` in it. Copy it exactly as shown; don't decode it.
   4. Copy the value of **`SWID`**: looks like `{ABCD1234-5678-...}`. Include the curly braces.
4. **Add them as repository secrets.** In your repo: **Settings → Secrets and variables →
   Actions → Secrets → New repository secret**:

   | Secret name      | Value                         |
   |------------------|-------------------------------|
   | `ESPN_LEAGUE_ID` | your league ID                |
   | `ESPN_S2`        | the `espn_s2` cookie value    |
   | `ESPN_SWID`      | the `SWID` cookie, with `{}`  |

5. **Optional variables** (same page, **Variables** tab). All have defaults:

   | Variable    | Default     | Meaning                                                    |
   |-------------|-------------|------------------------------------------------------------|
   | `ESPN_YEAR` | `2027`      | ESPN names a season by the year it ends: 2026-27 = 2027    |
   | `SD_PCT`    | `0.25`      | Each team's standard deviation as a fraction               |
   | `SD_BASIS`  | `remaining` | Apply `SD_PCT` to expected **remaining** points or **total** |
   | `MIN_FPPG`  | `25`        | Floor on every player's projected fantasy points per game  |
   | `PRIOR_GAMES` | `5`       | How many games the projection / last-season basis is worth |
   | `MAX_PER_DAY` | `10`      | Most players counted on any one day                        |
   | `MATCHUP_END` | *(unset)* | Last day of the current matchup, `YYYY-MM-DD`; only if the summary's dates are wrong. Delete it after that week. |

6. **Run it once by hand:** **Actions** tab → *Daily ESPN pull* → **Run workflow**.
   The run page shows a win-probability table; the CSVs appear in `data/`.

**Cookie maintenance:** the cookies are tied to your ESPN login. If you log out or ESPN
forces a re-login, they can stop working and the run fails with a 401. Repeat
step 3 and update the two secrets. Never put them in code or commit them.

## The model

For each matchup, every morning:

```
banked              = ESPN's live matchup score (already includes points from dropped players)
expected_remaining  = Σ over each remaining day of the matchup:
                        best legal lineup from the CURRENT roster among players with a game,
                        each worth FPPG × P(plays)
expected_total      = banked + expected_remaining
σ_team              = 0.25 × expected_remaining          (SD_BASIS=remaining, default)
z                   = (expected_total_A − expected_total_B) / √(σ_A² + σ_B²)
P(A wins)           = Φ(z)
```

- **FPPG** blends a pre-season basis with this season's games:
  - *basis* = average of ESPN's season projection and last season's FPPG (whichever exist,
    both scored with your league's settings)
  - *this season* = last-30-day FPPG (season FPPG until then)
  - blend = (games played × this season + 5 × basis) ÷ (games played + 5). At 0 games it's
    all basis, at 5 games 50/50, and by 20 games it's 80% this season. Change the 5 with
    `PRIOR_GAMES`.
  - **floor of 25** (`MIN_FPPG`): streamers are usually short-term pickups filling in for an
    injured starter, so their averages understate what they'll score in that role.
  `rosters.csv` shows every input next to the final `fppg_model` column.
- **Matchup days:** from today through the matchup's last Sunday. Multi-week matchups
  (All-Star break) are handled from your league settings. If ESPN's dates ever differ, set
  `MATCHUP_END`. The run summary prints the dates it used.
- **P(plays)** comes from ESPN's injury status: active and day-to-day 1.0, out 0
  (0.8 once the expected return date passes). Tune these in `model.py`.
- **Daily cap of 10** (`MAX_PER_DAY`): each day, every available player with a game is
  ranked by expected points and the top 10 count. If 13 play, the best 10 count; if 8 play,
  all 8 count. Positions are ignored.
- **Why σ on remaining by default:** banked points are certain, so the uncertainty should
  shrink to zero as the week ends. With `SD_BASIS=total`, σ stays large even on Sunday
  night, and a 40-point lead with one game left would still look close to a coin flip.

## Roster changes mid-week

| Situation | How it's handled |
|---|---|
| A player scores, then gets dropped | His points stay in `banked`, because banked is ESPN's official matchup score, not a sum over today's roster. |
| A pickup played earlier in the week for another team or as a free agent | Only his games **after today** count toward his new team's expected remaining. |
| A player was on the bench when he scored | Not counted: ESPN's score only includes active-lineup points. `player_points.csv` marks bench and IR rows with `counted=False`. |
| A trade | Same as drop + add, on both sides. |
| A game is in progress during a manual run | Its live points are already in ESPN's score, so the model skips any game that has tipped off. |
| Moves you'll make later this week | Can't be known ahead of time. Probabilities update each morning to reflect the new roster. |
| Player history | `history/player_points.csv` credits each day's points to whichever team rostered the player **that day**, so a dropped player's past points stay with the team that earned them. |

## Files in `data/`

| File | Contents |
|---|---|
| `rosters.csv` | Current rosters, injury status, season / last-30 / model FPPG, games left this matchup |
| `schedule.csv` | Every upcoming NBA game for every rostered player |
| `yesterday_points.csv` | Each player's fantasy points yesterday |
| `win_probability.csv` | Today's matchups: banked, expected remaining, expected total, z, win % |
| `history/*.csv` | Growing daily logs of the two files above |

## Limits

- Built for **H2H points** leagues. Category leagues need a different model.
- Weekly games-played caps and acquisition limits aren't modeled.
- The daily cap ignores positions, so on a rare day where many of one position play,
  the projection can count a lineup ESPN wouldn't allow.
- GitHub's scheduler is best-effort: a scheduled run can start late or be skipped when
  GitHub is busy. The workflow has a backup run at 7:43am Pacific for that reason.

## Tests

```
pip install pytest && pytest -q tests
```
