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


PERF_CSS = """
:root{--pos:#2a78d6;--neg:#e34948}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--pos:#3987e5;--neg:#e66767}}
details.perf{background:var(--card);border:1px solid var(--rule);border-radius:10px;margin:14px 0 4px}
details.perf>summary{cursor:pointer;padding:12px 16px;font-weight:600;list-style-position:inside}
.perf-body{padding:0 16px 14px}
.ctl{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:2px 0 10px}
.ctl select{max-width:100%}
.ctl select,.chips button{font:inherit;font-size:13px;color:var(--ink);background:var(--bg);
  border:1px solid var(--rule);border-radius:6px;padding:5px 8px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.chips button{cursor:pointer}.chips button[aria-pressed=true]{border-color:var(--ink);font-weight:600}
.legend{color:var(--ink2);font-size:12px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 8px;vertical-align:-1px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.pt{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
.pt th,.pt td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
.pt th{color:var(--ink2);font-weight:600;font-size:12px}
.pt th:first-child,.pt td:first-child{text-align:left;position:sticky;left:0;background:var(--card);
  white-space:normal;min-width:120px;overflow-wrap:break-word}
.pt tr.team{cursor:pointer}.pt tr.team:hover td:first-child{text-decoration:underline}
.pt tr.team td:first-child::before{content:"\\25B8  ";color:var(--ink2)}
.pt tr.team.open td:first-child::before{content:"\\25BE  "}
.pt td.sum{font-weight:700}
.panel{margin-top:10px;background:var(--bg);border:1px solid var(--rule);border-radius:8px;padding:10px 12px}
.panel:empty{display:none}
.panel .pt th:first-child,.panel .pt td:first-child{background:var(--bg)}
.phead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:2px}
.x{font:inherit;font-size:13px;color:var(--ink);background:var(--card);border:1px solid var(--rule);
  border-radius:6px;padding:4px 10px;cursor:pointer}
.tag{font-size:11px;color:var(--ink2);border:1px solid var(--rule);border-radius:4px;padding:0 4px;margin-left:6px}
.empty{color:var(--ink2);font-size:13px}
"""

PERF_JS = r"""
(function () {
  var MINUS = "\u2212";
  function fmt(v) { v = Math.round(v * 10) / 10; return (v > 0 ? "+" : v < 0 ? MINUS : "") + Math.abs(v).toFixed(1); }
  function n0(v) { return Math.round(v).toLocaleString(); }
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    for (var k in (attrs || {})) e.setAttribute(k, attrs[k]);
    [].concat(kids || []).forEach(function (c) { e.append(c && c.nodeType ? c : document.createTextNode(c == null ? "" : c)); });
    return e;
  }
  function day(iso) { var d = new Date(iso + "T12:00:00"); return d.toLocaleDateString("en-US", { weekday: "short", month: "numeric", day: "numeric" }); }
  function tint(v, max) {
    if (!max || !v) return "";
    var pct = Math.round(8 + 37 * Math.min(Math.abs(v) / max, 1));
    return "background:color-mix(in oklab," + (v > 0 ? "var(--pos)" : "var(--neg)") + " " + pct + "%,var(--card))";
  }
  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }

  function deltaCell(p, a, max, cls) {
    var v = a - p;
    var td = el("td", { title: "Projected " + n0(p) + " \u00b7 Actual " + n0(a), class: cls || "" }, fmt(v));
    var s = tint(v, max); if (s) td.setAttribute("style", s);
    return td;
  }

  function playersView(box, wk, tid) {
    var chips = el("div", { class: "chips", role: "group", "aria-label": "Show" });
    var holder = el("div");
    var views = [{ key: "week", label: "Whole week" }].concat(wk.days.map(function (d) { return { key: d.sp, label: d.label }; }));
    function render(key) {
      [].forEach.call(chips.children, function (b) { b.setAttribute("aria-pressed", String(b.dataset.key === String(key))); });
      var rows = (wk.players[tid] || []).map(function (p) {
        if (key === "week") return { name: p.name, p: p.proj, a: p.act, note: p.games + " gm" };
        var d = p.days[key]; if (!d) return null;
        var note = (d[2] === "BE" || d[2] === "IR") ? "bench" : (!d[3] ? "no proj" : "");
        return { name: p.name, p: d[0], a: d[1], note: note };
      }).filter(Boolean).sort(function (x, y) { return Math.abs(y.a - y.p) - Math.abs(x.a - x.p); });
      var max = rows.reduce(function (m, r) { return Math.max(m, Math.abs(r.a - r.p)); }, 0);
      var t = el("table", { class: "pt" }, [el("thead", {}, el("tr", {}, [
        el("th", { scope: "col" }, "Player"), el("th", { scope: "col" }, "Proj"),
        el("th", { scope: "col" }, "Actual"), el("th", { scope: "col" }, "+/" + MINUS)]))]);
      var tb = el("tbody");
      rows.forEach(function (r) {
        tb.append(el("tr", {}, [el("td", {}, [r.name, r.note ? el("span", { class: "tag" }, r.note) : ""]),
          el("td", {}, n0(r.p)), el("td", {}, n0(r.a)), deltaCell(r.p, r.a, max)]));
      });
      t.append(tb);
      holder.replaceChildren(rows.length ? el("div", { class: "scroll" }, t) : el("p", { class: "empty" }, "No games."));
    }
    views.forEach(function (v) {
      var b = el("button", { type: "button", "data-key": v.key, "aria-pressed": "false" }, v.label);
      b.addEventListener("click", function () { render(v.key); });
      chips.append(b);
    });
    box.replaceChildren(el("div", { class: "legend" }, "Sorted by biggest miss either way. Player totals include bench games."), chips, holder);
    render("week");
  }

  function renderWeek(out, wk) {
    var cells = [];
    wk.teams.forEach(function (t) { wk.days.forEach(function (d) { var c = t.days[d.sp]; if (c) cells.push(Math.abs(c[1] - c[0])); }); });
    var dmax = Math.max.apply(null, cells.concat([0]));
    var wmax = Math.max.apply(null, wk.teams.map(function (t) { return Math.abs(t.act - t.proj); }).concat([0]));
    var head = el("tr", {}, [el("th", { scope: "col" }, "Team")]
      .concat(wk.days.map(function (d) { return el("th", { scope: "col" }, d.label); }))
      .concat([el("th", { scope: "col" }, "Week"), el("th", { scope: "col" }, "Proj"), el("th", { scope: "col" }, "Actual")]));
    var tb = el("tbody");
    var panel = el("div", { class: "panel", "aria-live": "polite" });
    wk.teams.forEach(function (t) {
      var tr = el("tr", { class: "team", tabindex: "0", "aria-expanded": "false" }, [el("td", {}, t.name)]);
      wk.days.forEach(function (d) { var c = t.days[d.sp]; tr.append(c ? deltaCell(c[0], c[1], dmax) : el("td", {}, "\u2013")); });
      tr.append(deltaCell(t.proj, t.act, wmax, "sum"), el("td", {}, n0(t.proj)), el("td", {}, n0(t.act)));
      function toggle() {
        var wasOpen = tr.classList.contains("open");
        tb.querySelectorAll("tr.team.open").forEach(function (r) { r.classList.remove("open"); r.setAttribute("aria-expanded", "false"); });
        if (wasOpen) { panel.replaceChildren(); return; }
        tr.classList.add("open"); tr.setAttribute("aria-expanded", "true");
        var close = el("button", { type: "button", class: "x" }, "Close");
        close.addEventListener("click", toggle);
        var box = el("div");
        panel.replaceChildren(el("div", { class: "phead" }, [el("strong", {}, t.name + " \u00b7 players"), close]), box);
        playersView(box, wk, t.id);
        panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
      tr.addEventListener("click", toggle);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      tb.append(tr);
    });
    out.replaceChildren(el("div", { class: "scroll" }, el("table", { class: "pt" }, [el("thead", {}, head), tb])),
      el("p", { class: "legend" }, "Team actual = points that counted (active lineup). Team projection = the top " +
        wk.max_per_day + " projected players each day. Click a team for its players."), panel);
  }

  function init(d) {
    var slug = d.getAttribute("data-league"), body = d.querySelector(".perf-body");
    body.textContent = "Loading\u2026";
    getJSON("data/" + slug + "/perf_index.json").then(function (idx) {
      if (!idx.length) { body.replaceChildren(el("p", { class: "empty" }, "Tracking starts once a full day has both a morning projection and final scores.")); return; }
      var sel = el("select", { "aria-label": "Matchup week" });
      idx.forEach(function (w) {
        sel.append(el("option", { value: String(w.mp) }, "Matchup " + w.mp + " \u00b7 " + day(w.start) +
          (w.end !== w.start ? " \u2013 " + day(w.end) : "") + " (" + w.days + " day" + (w.days > 1 ? "s" : "") + " so far)"));
      });
      var legend = el("span", { class: "legend" }, [el("i", { style: "background:var(--pos)" }), "over projection",
        el("i", { style: "background:var(--neg)" }), "under"]);
      var out = el("div"), cache = {};
      function show() {
        var mp = sel.value; out.textContent = "Loading\u2026";
        (cache[mp] ? Promise.resolve(cache[mp]) : getJSON("data/" + slug + "/perf_" + mp + ".json"))
          .then(function (wk) { cache[mp] = wk; renderWeek(out, wk); })
          .catch(function () { out.textContent = "Couldn't load that week."; });
      }
      sel.addEventListener("change", show);
      body.replaceChildren(el("div", { class: "ctl" }, [sel, legend]), out);
      show();
    }).catch(function () { body.replaceChildren(el("p", { class: "empty" }, "Couldn't load performance data.")); });
  }

  document.querySelectorAll("details.perf").forEach(function (d) {
    d.addEventListener("toggle", function () { if (d.open && !d.dataset.loaded) { d.dataset.loaded = "1"; init(d); } });
  });
})();
"""


def build_site(leagues, data_dir: Path, site_dir: Path) -> Path:
    """leagues: list of (slug, display_name). Writes site_dir/index.html + per-week perf JSON."""
    from perf import build_perf  # local import keeps email-only runs light
    site_dir.mkdir(parents=True, exist_ok=True)
    sections, nav, last_meta = [], [], {}
    for slug, _ in leagues:
        d = data_dir / slug
        if not (d / "meta.json").exists():
            continue
        meta, wp, hist = load_league(d)
        last_meta = meta
        nav.append(f'<a href="#{_e(slug)}">{_e(meta["league_name"])}</a>')
        index, weeks = build_perf(d, int(meta.get("max_per_day", 10)))
        out = site_dir / "data" / slug
        out.mkdir(parents=True, exist_ok=True)
        (out / "perf_index.json").write_text(json.dumps(index))
        for mp, wk in weeks.items():
            (out / f"perf_{mp}.json").write_text(json.dumps(wk))
        sections.append(league_section(meta, wp, hist, slug)
                        + f'<details class="perf" data-league="{_e(slug)}">'
                          f'<summary>Performance vs projection</summary><div class="perf-body"></div></details>')
    body = ("<h1>Fantasy win probabilities</h1>"
            + (f"<nav>{''.join(nav)}</nav>" if len(nav) > 1 else "")
            + "".join(sections) + (_footer(last_meta) if last_meta else ""))
    html_out = page("Fantasy Win Odds", body).replace(
        "</style>", PERF_CSS + "</style>", 1).replace("</body>", f"<script>{PERF_JS}</script></body>", 1)
    (site_dir / "index.html").write_text(html_out)
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
            late = datetime.now().hour * 60 + datetime.now().minute >= 8 * 60 + 30
            if mode == "auto" and meta.get("espn_day") and meta["espn_day"] != str(today) and not late:
                # Very early run: ESPN hasn't moved to today yet, so last night isn't final.
                status.append(f"email {slug}: waiting, ESPN still on {meta['espn_day']}")
                continue
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
