"""
Turns each league's CSVs into (a) a static web page and (b) a daily email.

Both use the same markup: one card per matchup with a split win-probability bar.
Home team = blue (left), away team = orange (right); team names and percentages are
always printed, so identity never rests on color alone.
"""

import html
import json
import os
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

HOME, AWAY = "#2a78d6", "#eb6834"            # light-mode series 1 / 2
HOME_DK, AWAY_DK = "#3987e5", "#d95926"      # dark-mode steps of the same hues

CSS = """
:root{--bg:#f4f3ef;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--rule:#e4e2dc;--gap:#fcfcfb;
--home:%(h)s;--away:%(a)s}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#121211;--card:#1a1a19;
--ink:#f0efec;--ink2:#c3c2b7;--rule:#2e2e2c;--gap:#1a1a19;--home:%(hd)s;--away:%(ad)s}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 2px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 14px}
nav a{color:var(--ink2);margin-right:14px;font-size:14px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:14px 16px;margin:10px 0}
.row{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.team{font-weight:600;overflow-wrap:anywhere}.team.r{text-align:right}
.pct{font-variant-numeric:tabular-nums;font-size:20px;font-weight:700}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:0}
.team.r .sw{margin:0 0 0 6px}
.nw{white-space:nowrap}
.bar{display:flex;height:10px;margin:8px 0 6px;border-radius:4px;overflow:hidden;gap:2px;background:var(--gap)}
.bar span{display:block;height:100%%}
.meta{color:var(--ink2);font-size:13px;font-variant-numeric:tabular-nums}
.trend{color:var(--ink2);font-size:12px;margin-top:4px}
.foot{color:var(--ink2);font-size:12px;margin-top:28px;border-top:1px solid var(--rule);padding-top:10px}
""" % {"h": HOME, "a": AWAY, "hd": HOME_DK, "ad": AWAY_DK}


def _e(x) -> str:
    return html.escape(str(x))


def _fmt(x) -> str:
    try:
        return f"{float(x):,.0f}"
    except (TypeError, ValueError):
        return "–"


def load_league(league_dir: Path):
    meta = json.loads((league_dir / "meta.json").read_text())
    wp = pd.read_csv(league_dir / "win_probability.csv")
    hist_path = league_dir / "history" / "win_probability.csv"
    hist = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
    return meta, wp, hist


def _trend(hist, matchup_period, home_team) -> str:
    """'Mon 48% → Tue 55% → Wed 62%' for the home team over this matchup."""
    if hist.empty:
        return ""
    h = hist[(hist["matchup_period"].astype(str) == str(matchup_period))
             & (hist["home_team"] == home_team)].sort_values("run_date")
    if len(h) < 2:
        return ""
    pts = [f"{datetime.fromisoformat(str(d)).strftime('%a')} {p:.0%}"
           for d, p in zip(h["run_date"], h["home_win_prob"].astype(float))]
    return " → ".join(pts[-7:])


def league_section(meta, wp, hist, anchor: str, email: bool = False) -> str:
    start = date.fromisoformat(meta["matchup_start"])
    end = date.fromisoformat(meta["matchup_end"])
    upd = datetime.fromisoformat(meta["updated_at"])
    out = [f'<h2 id="{_e(anchor)}">{_e(meta["league_name"])}</h2>',
           f'<p class="sub">Matchup {_e(meta["matchup_period"])} · {start:%a %b %-d} – {end:%a %b %-d} · '
           f'{meta["days_left"]} day{"s" if meta["days_left"] != 1 else ""} left · '
           f'updated {upd:%a %-I:%M %p} PT</p>']
    if wp.empty:
        out.append('<p class="sub">No matchups this period.</p>')
    for _, r in wp.iterrows():
        ph = float(r["home_win_prob"])
        pa = 1 - ph
        wh = max(ph * 100, 1.5) if ph > 0 else 0
        wa = max(pa * 100, 1.5) if pa > 0 else 0
        tip = (f'{r["home_team"]} {ph:.0%} – {r["away_team"]} {pa:.0%} '
               f'(projected {_fmt(r["home_exp_total"])}–{_fmt(r["away_exp_total"])})')
        if email:  # table-based bar: renders in Gmail / Outlook / Apple Mail
            bar = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                   f'style="margin:8px 0 6px;border-collapse:separate"><tr>'
                   + (f'<td bgcolor="{HOME}" style="height:10px;width:{ph*100:.1f}%;background:{HOME};'
                      f'border-radius:4px 0 0 4px"></td>' if ph > 0 else "")
                   + ('<td style="width:2px"></td>' if 0 < ph < 1 else "")
                   + (f'<td bgcolor="{AWAY}" style="height:10px;background:{AWAY};'
                      f'border-radius:0 4px 4px 0"></td>' if pa > 0 else "")
                   + "</tr></table>")
        else:
            bar = (f'<div class="bar" title="{_e(tip)}" role="img" aria-label="{_e(tip)}">'
                   f'<span style="width:{wh:.1f}%;background:var(--home)"></span>'
                   f'<span style="flex:1;background:var(--away)"></span></div>')
            if ph >= 1:
                bar = bar.replace('<span style="flex:1;background:var(--away)"></span>', "")
            if pa >= 1:
                bar = bar.replace(f'<span style="width:{wh:.1f}%;background:var(--home)"></span>', "")
        trend = _trend(hist, r["matchup_period"], r["home_team"])
        hs = f'<span class="sw" style="background:{HOME if email else "var(--home)"}"></span>'
        as_ = f'<span class="sw" style="background:{AWAY if email else "var(--away)"}"></span>'
        out.append(
            '<div class="card">'
            f'<div class="row"><div class="team">{hs}{_e(r["home_team"])}</div>'
            f'<div class="team r">{_e(r["away_team"])}{as_}</div></div>'
            f'<div class="row"><div class="pct">{ph:.0%}</div><div class="pct">{pa:.0%}</div></div>'
            f'{bar}'
            f'<div class="row meta"><div><span class="nw">Now {_fmt(r["home_banked"])}</span> · '
            f'<span class="nw">Proj {_fmt(r["home_exp_total"])}</span> · '
            f'<span class="nw">{int(r["home_exp_games"])} gm left</span></div>'
            f'<div style="text-align:right"><span class="nw">{int(r["away_exp_games"])} gm left</span> · '
            f'<span class="nw">Proj {_fmt(r["away_exp_total"])}</span> · '
            f'<span class="nw">Now {_fmt(r["away_banked"])}</span></div></div>'
            + (f'<div class="trend">{_e(r["home_team"])} by day: {_e(trend)}</div>' if trend else "")
            + "</div>")
    return "\n".join(out)


def _footer(meta) -> str:
    return (f'<p class="foot">Projection: each remaining day counts the top {meta.get("max_per_day", 10)} '
            f'healthy players with a game (min {meta.get("min_fppg", 25):.0f} pts/game). '
            f'Win % = normal CDF of the projected margin, σ = {float(meta.get("sd_pct", .25)):.0%} of '
            f'projected remaining points per team.</p>')


def page(title: str, body: str, email: bool = False) -> str:
    css = CSS if not email else CSS.split("@media")[0] + CSS.split("}}", 1)[1]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e(title)}</title><style>{css}</style></head>'
            f'<body><div class="wrap">{body}</div></body></html>')


def build_site(leagues, data_dir: Path, site_dir: Path) -> Path:
    """leagues: list of (slug, display_name). Writes site_dir/index.html."""
    site_dir.mkdir(parents=True, exist_ok=True)
    sections, nav, last_meta = [], [], {}
    for slug, _ in leagues:
        d = data_dir / slug
        if not (d / "meta.json").exists():
            continue
        meta, wp, hist = load_league(d)
        last_meta = meta
        nav.append(f'<a href="#{_e(slug)}">{_e(meta["league_name"])}</a>')
        sections.append(league_section(meta, wp, hist, slug))
    body = ("<h1>Fantasy win probabilities</h1>"
            + (f"<nav>{''.join(nav)}</nav>" if len(nav) > 1 else "")
            + "".join(sections) + (_footer(last_meta) if last_meta else ""))
    (site_dir / "index.html").write_text(page("Fantasy Win Odds", body))
    (site_dir / ".nojekyll").write_text("")
    return site_dir / "index.html"


# ------------------------------------------------------------------ email

def parse_recipients(text: str) -> dict:
    """
    EMAIL_TO secret, one line per group:
        main: a@x.com, b@y.com      -> only the league with slug "main"
        league2: c@z.com
        me@x.com                    -> no prefix: every league
    Returns {slug or "*": [emails]}.
    """
    out = {}
    for line in (text or "").replace(";", ",").splitlines():
        line = line.strip()
        if not line:
            continue
        key = "*"
        if ":" in line and "@" not in line.split(":", 1)[0]:
            key, line = (s.strip() for s in line.split(":", 1))
        out.setdefault(key, []).extend(a.strip() for a in line.split(",") if "@" in a)
    return out


def send_league_emails(leagues, data_dir: Path, today: date, mode: str = "auto",
                       site_url: str = "", weekdays: str = "") -> list:
    """Send each league's email at most once per day. Returns list of status strings."""
    user, pw = os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_APP_PASSWORD")
    rcpts = parse_recipients(os.environ.get("EMAIL_TO", ""))
    if mode == "never":
        return ["email: skipped (mode=never)"]
    if not (user and pw and rcpts):
        return ["email: not configured (EMAIL_USER / EMAIL_APP_PASSWORD / EMAIL_TO secrets)"]
    allowed = {d.strip()[:3].lower() for d in weekdays.split(",") if d.strip()}
    if mode == "auto" and allowed and today.strftime("%a").lower() not in allowed:
        return [f"email: skipped, {today:%a} not in EMAIL_DAYS"]

    status = []
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw.replace(" ", ""))
        for slug, _ in leagues:
            d = data_dir / slug
            to = sorted(set(rcpts.get(slug, []) + rcpts.get("*", [])))
            if not to or not (d / "meta.json").exists():
                continue
            stamp = d / "last_email.txt"
            if mode == "auto" and stamp.exists() and stamp.read_text().strip() == str(today):
                status.append(f"email {slug}: already sent today")
                continue
            meta, wp, hist = load_league(d)
            link = (f'<p><a href="{_e(site_url)}">Open the live page →</a></p>' if site_url else "")
            body = league_section(meta, wp, hist, slug, email=True) + link + _footer(meta)
            msg = EmailMessage()
            msg["Subject"] = f"{meta['league_name']}: win odds, {today:%a %b %-d}"
            msg["From"] = user
            msg["To"] = user          # recipients go in Bcc so addresses stay private
            msg["Bcc"] = ", ".join(to)
            lines = [f"{r.home_team} {float(r.home_win_prob):.0%} – {r.away_team} {float(r.away_win_prob):.0%}"
                     for r in wp.itertuples()]
            msg.set_content("\n".join(lines) + (f"\n\n{site_url}" if site_url else ""))
            msg.add_alternative(page(msg["Subject"], body, email=True), subtype="html")
            s.send_message(msg)
            stamp.write_text(str(today))
            status.append(f"email {slug}: sent to {len(to)}")
    return status
