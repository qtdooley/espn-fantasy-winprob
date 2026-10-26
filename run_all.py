"""
Daily entry point: pull every league in leagues.json, build the web page, send emails.

leagues.json:
  [
    {"slug": "main",    "name": "Main league",   "league_id": 403382108},
    {"slug": "league2", "name": "Second league", "league_id": 12345678, "cookies": "2"}
  ]
  slug     short id used for the data folder (data/<slug>/), page anchor, and EMAIL_TO lines
  cookies  omit to use ESPN_S2 / ESPN_SWID; "2" uses ESPN_S2_2 / ESPN_SWID_2
           (only needed if that league is on a different ESPN account)

One league failing doesn't stop the others; the run is marked failed at the end.
"""

import json
import os
import re
import shutil
import sys
import traceback
from datetime import date
from pathlib import Path

import pull
from report import build_site, send_league_emails

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("ESPN_OUT_DIR") or ROOT / "data")
SITE = ROOT / "site"


def load_leagues():
    path = ROOT / "leagues.json"
    if path.exists():
        raw = json.loads(path.read_text())
    else:  # original single-league setup
        raw = [{"slug": "main", "name": "", "league_id": os.environ.get("ESPN_LEAGUE_ID")}]
    leagues = []
    for i, L in enumerate(raw):
        lid = str(L.get("league_id", "")).strip()
        if not lid.isdigit() or int(lid) == 0:
            print(f"Skipping leagues.json entry {i + 1} ({L.get('name') or L.get('slug')}): "
                  f"league_id '{lid}' isn't a number yet")
            continue
        slug = re.sub(r"[^a-z0-9-]+", "-", (L.get("slug") or L.get("name") or f"league{i+1}").lower()).strip("-")
        leagues.append({**L, "slug": slug, "league_id": int(lid)})
    return leagues


def migrate_single_league_layout(first_slug: str):
    """Old layout kept one league's files directly in data/. Move them to data/<slug>/ once."""
    target = DATA / first_slug
    if (DATA / "win_probability.csv").exists() and not target.exists():
        target.mkdir(parents=True)
        for name in ("rosters.csv", "schedule.csv", "yesterday_points.csv",
                     "win_probability.csv", "history"):
            if (DATA / name).exists():
                shutil.move(str(DATA / name), str(target / name))
        print(f"Moved existing data/ files into data/{first_slug}/ (history kept)")


def main():
    leagues = load_leagues()
    if not leagues:
        sys.exit("No leagues to run: check leagues.json")
    migrate_single_league_layout(leagues[0]["slug"])

    ok, failed = [], []
    for L in leagues:
        sfx = f"_{L['cookies']}" if L.get("cookies") else ""
        try:
            pull.main(league_id=L["league_id"], out_dir=DATA / L["slug"],
                      espn_s2=os.environ.get(f"ESPN_S2{sfx}"),
                      swid=os.environ.get(f"ESPN_SWID{sfx}"),
                      label=L.get("name") or None)
            ok.append(L)
        except Exception:
            failed.append(L)
            print(f"\n*** League '{L['slug']}' ({L['league_id']}) failed ***")
            traceback.print_exc()

    pairs = [(L["slug"], L.get("name", "")) for L in ok]
    if pairs and os.environ.get("ENABLE_SITE", "").lower() == "true":
        print("Site:", build_site(pairs, DATA, SITE))

    site_url = os.environ.get("SITE_URL", "")
    if not site_url and os.environ.get("ENABLE_SITE", "").lower() == "true" and os.environ.get("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
        site_url = f"https://{owner.lower()}.github.io/{repo}/"
    if pairs:
        try:
            for line in send_league_emails(pairs, DATA, date.today(),
                                           mode=os.environ.get("EMAIL_MODE") or "auto",
                                           site_url=site_url,
                                           weekdays=os.environ.get("EMAIL_DAYS", "")):
                print(line)
        except Exception:
            failed.append({"slug": "email"})
            print("\n*** Sending email failed ***")
            traceback.print_exc()

    if failed:
        (ROOT / "failed.txt").write_text(", ".join(f["slug"] for f in failed) + "\n")
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
