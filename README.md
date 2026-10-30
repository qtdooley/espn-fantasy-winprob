# ESPN Fantasy Basketball — daily pull + weekly win probability

A GitHub Action runs `run_all.py` every morning before 9am Pacific (see Timing). For
every league in `leagues.json` it pulls ESPN, estimates each team's points for the rest of
the matchup, converts that into a win probability with a z-score, and commits the CSVs to
`data/<league>/`. Optionally it also publishes a web page and emails the results.

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

## More leagues

Edit `leagues.json` (pencil icon on GitHub). One line per league:

```json
[
  {"slug": "main",    "league_id": 403382108},
  {"slug": "league2", "league_id": 87654321}
]
```

- `slug`: short name, lowercase. Used for the data folder `data/<slug>/` and `EMAIL_TO`.
- `name` (optional): display name; otherwise ESPN's league name is used.
- `cookies` (optional): leave it out if you're in the league with the same ESPN login,
  since the same two cookies work for every league you're in. If the league belongs to a
  different ESPN account, add `"cookies": "2"` and create secrets `ESPN_S2_2` and
  `ESPN_SWID_2` from that account.

A league that fails (bad ID, no access) doesn't stop the others. The run shows red and
the log names the league.

## Shareable web page (GitHub Pages)

**Free GitHub accounts can only publish Pages from a public repo.** The choice:

- **Make the repo public** (Settings → General → Danger Zone → Change visibility). Your
  cookies and email password are secrets: they stay encrypted and never appear in the
  code, logs, or page. What becomes visible: the code, `leagues.json` (league IDs alone
  don't grant access to a private ESPN league), and the CSVs in `data/` (rosters and
  win odds).
- **Or keep it private with GitHub Pro** (about $4/month), which allows Pages on private repos.

Either way, the page itself is public to anyone with the link.

To turn it on:
1. Settings → **Pages** → under "Build and deployment", set **Source** to **GitHub Actions**.
2. Settings → Secrets and variables → Actions → **Variables** tab → New variable:
   `ENABLE_SITE` = `true`.
3. Run the workflow. The page goes live at `https://<your-username>.github.io/<repo-name>/`.
   The deploy job's box on the run page links to it.

## Timing

GitHub's own scheduler has been starting runs 3–10 hours late, so the workflow asks for a
run every 30 minutes from 4:07 to 8:37am Pacific (3:07–7:37 in winter). The first run that
gets today's data does the work and sends the email. Later scheduled runs see that and stop
within seconds. Manual and external-trigger runs always run in full.

The email waits until ESPN has rolled over to the new day, so last night's scores are final.
After 8:30am it sends regardless.

### Guaranteed time: trigger from cron-job.org (free)

1. **Make a token:** github.com → your photo → Settings → Developer settings →
   Personal access tokens → **Fine-grained tokens** → Generate new token.
   - Repository access: **Only select repositories** → this repo
   - Permissions → Repository permissions → **Actions: Read and write**
   - Set the longest expiration offered and note the date; renew it before then.
2. **Create the job** at cron-job.org (free account) → Create cronjob:
   - URL: `https://api.github.com/repos/<you>/<repo>/actions/workflows/daily.yml/dispatches`
   - Schedule: every day at 6:30, time zone America/Los_Angeles
   - Advanced → Request method **POST**, headers:
     `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
     `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
   - Request body: `{"ref":"main"}`
3. Click **Test run**. A `204` response means it worked, and a new run appears in the
   Actions tab within seconds, labeled as manually run by you.

### Performance vs projection (web page only)

Each league on the page has a collapsed **Performance vs projection** section. Nothing
loads until someone opens it, then only the chosen week.

- **Team table:** over/under for each finished day and the week so far. Team actual =
  points that counted (active lineup); team projection = that morning's top 10 projected
  players. Blue = over, red = under, darker = bigger.
- **Click a team** for its players: whole week or one day, sorted by the biggest miss either
  way. Player numbers include bench games, tagged "bench".
- How it works: each morning's run saves every player's projection for that day to
  `history/projections.csv` (first run of the day wins, so it can't be rewritten after the
  games). The next morning's actual scores are compared against it. Tracking starts the
  day you install this; earlier days have no saved projection.

## Daily email (Gmail)

Each league gets one email per day, sent BCC so recipients don't see each other's
addresses. The backup run won't send a second copy.

1. Turn on **2-Step Verification** for the Gmail account you'll send from
   (myaccount.google.com → Security).
2. Create an **app password**: myaccount.google.com/apppasswords → name it
   "fantasy" → copy the 16-character password. Google blocks your normal password for this.
3. Add three **secrets**:

   | Secret | Value |
   |---|---|
   | `EMAIL_USER` | the Gmail address that sends |
   | `EMAIL_APP_PASSWORD` | the 16-character app password |
   | `EMAIL_TO` | who gets what, one line per group (below) |

   `EMAIL_TO` format:
   ```
   main: friend1@gmail.com, friend2@yahoo.com
   league2: coworker@company.com
   you@gmail.com
   ```
   A line starting with a league's slug only gets that league. A line without a prefix
   gets every league.
4. Optional **variable** `EMAIL_DAYS`, for example `Mon,Thu`, to email only on those days.
   The default is every day.

**Run workflow** has an *email* choice: `auto` (once a day), `always` (send now, even if
already sent today), or `never`.

Gmail allows about 500 emails a day from a personal account, far more than this needs.

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

## Files in `data/<league>/`

The first time this runs, files from the old one-league layout (directly in `data/`) are
moved into `data/<first league's slug>/`, history included.

| File | Contents |
|---|---|
| `rosters.csv` | Current rosters, injury status, season / last-30 / model FPPG, games left this matchup |
| `schedule.csv` | Every upcoming NBA game for every rostered player |
| `yesterday_points.csv` | Each player's fantasy points yesterday |
| `win_probability.csv` | Today's matchups: banked, expected remaining, expected total, z, win % |
| `history/*.csv` | Growing daily logs of the two files above |
| `history/projections.csv` | Each morning's per-player projection for that day (for performance vs projection) |
| `meta.json` | League name, matchup dates, last update (used by the page and email) |
| `last_email.txt` | Date that league's email last went out |

## Limits

- Built for **H2H points** leagues. Category leagues need a different model.
- Weekly games-played caps and acquisition limits aren't modeled.
- The daily cap ignores positions, so on a rare day where many of one position play,
  the projection can count a lineup ESPN wouldn't allow.
- GitHub's scheduler is best-effort; see **Timing** for how this copes and how to
  guarantee the time.

## Tests

```
pip install pytest && pytest -q tests
```
