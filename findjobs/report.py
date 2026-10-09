"""Markdown and HTML output."""
from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime
from typing import Optional

from .pipeline import RunResult, Scored


def _ago(dt: Optional[datetime], at: datetime) -> str:
    if not dt:
        return "?"
    h = (at - dt).total_seconds() / 3600
    return f"{h * 60:.0f}m ago" if h < 1 else f"{h:.0f}h ago" if h < 48 else f"{h / 24:.0f}d ago"


def _cell(s: str) -> str:
    return (s or "").replace("|", "/").replace("\n", " ")


def _row(s: Scored, at: datetime) -> list[str]:
    j, jd = s.job, s.judgment
    return [
        j.title, j.url, _ago(j.posted_at, at),
        j.observed_at.strftime("%Y-%m-%d %H:%M UTC") if j.observed_at else "-",
        "YES" if s.verified else "NO", j.compensation(), j.client.country or "?",
        s.client_note, s.competition_note, jd["capability_fit"], jd["evidence_fit"], f"{s.total:.0f}",
        jd["why_selected"], "; ".join(jd["dossier_evidence"][:3]), "; ".join(jd["risks"][:3]), s.verdict,
    ]


HEADERS = ["Opportunity", "Direct Upwork Link", "Posted", "Observed", "Availability Verified", "Compensation",
           "Client Country", "Client Quality", "Proposals / Competition", "Capability Fit", "Evidence Fit",
           "{metric}", "Why Selected", "Dossier Evidence", "Risk / Gap", "Verdict"]


def to_markdown(r: RunResult, audit: bool = False) -> str:
    at = r.started_at
    hdr = [h.format(metric=r.metric_name) for h in HEADERS]
    out = [f"# Upwork shortlist for {r.profile.name}", f"_Run at {at:%Y-%m-%d %H:%M} UTC_", "",
           "## Student profile", r.profile.summary_md(), ""]
    if not r.profile.has_upwork_profile:
        out += ["> Scores are **Opportunity Win Potential**, not win probability: no Upwork profile stats (JSS, "
                "reviews, earnings) were supplied yet.", ""]
    out.append(f"## Actionable jobs ({len(r.shortlist)})")
    if r.shortlist:
        out += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        for s in r.shortlist:
            row = _row(s, at)
            row[0] = f"[{_cell(row[0])}]({row[1]})"
            out.append("| " + " | ".join(_cell(c) for c in row) + " |")
        out += ["", "### Proposal openers"]
        for s in r.shortlist:
            out += [f"**{s.job.title}** ({s.verdict}, {s.total:.0f})", f"> {s.judgment['proposal_opener']}", ""]
    else:
        out.append("No job passed every gate. That's the system working: nothing below the bar gets recommended.")
    if r.unverified:
        out += ["", f"## Not verified live ({len(r.unverified)})",
                "These scored well but their live Upwork page couldn't be checked. **Don't treat them as open.**", ""]
        for s in r.unverified:
            out.append(f"- [{s.job.title}]({s.job.url}): {s.total:.0f}, {s.verdict} · {s.job.availability_detail}")
    if r.pending_judgment:
        out += ["", f"## Awaiting fit judgment ({len(r.pending_judgment)})",
                "Passed the deterministic gates; run again with a judge (API key or --judgments file)."]
    c = Counter(e.gate for e in r.excluded)
    out += ["", "## Funnel", f"- Discovered (deduped): {r.stats.get('discovered', 0)}",
            f"- Passed availability/freshness/eligibility/competition: {r.stats.get('passed_deterministic', 0)}",
            f"- Shortlisted: {len(r.shortlist)}",
            "- Excluded by gate: " + (", ".join(f"{g} {n}" for g, n in c.most_common()) or "none")]
    if audit and r.excluded:
        out += ["", "## Exclusion audit", "| Job | Gate | Reason |", "|---|---|---|"]
        for e in r.excluded:
            out.append(f"| [{_cell(e.job.title or e.job.url)}]({e.job.url}) | {e.gate} | {_cell(e.reason)} |")
    return "\n".join(out) + "\n"


def to_html(r: RunResult, audit: bool = False) -> str:
    at = r.started_at
    hdr = [h.format(metric=r.metric_name) for h in HEADERS]
    e = html.escape
    rows = []
    for s in r.shortlist:
        c = _row(s, at)
        cells = [f'<a href="{e(c[1])}" target="_blank" rel="noopener">{e(c[0])}</a>', "<a href=\"%s\">open</a>" % e(c[1])]
        cells += [e(x) for x in c[2:]]
        cls = s.verdict.replace(" ", "-").lower()
        cells[-1] = f'<span class="v {cls}">{e(s.verdict)}</span>'
        rows.append("<tr>" + "".join(f"<td>{x}</td>" for x in cells) + "</tr>")
    openers = "".join(f"<div class='op'><b>{e(s.job.title)}</b><p>{e(s.judgment['proposal_opener'])}</p></div>"
                      for s in r.shortlist)
    excl = Counter(x.gate for x in r.excluded)
    audit_html = ""
    if audit and r.excluded:
        audit_html = "<h2>Exclusion audit</h2><table><tr><th>Job</th><th>Gate</th><th>Reason</th></tr>" + "".join(
            f"<tr><td><a href='{e(x.job.url)}'>{e(x.job.title or x.job.url)}</a></td><td>{e(x.gate)}</td><td>{e(x.reason)}</td></tr>"
            for x in r.excluded) + "</table>"
    unver = ""
    if r.unverified:
        unver = "<h2>Not verified live</h2><p class='warn'>Couldn't check these pages. Don't treat them as open.</p><ul>" + "".join(
            f"<li><a href='{e(s.job.url)}'>{e(s.job.title)}</a>: {s.total:.0f} · {e(s.job.availability_detail)}</li>"
            for s in r.unverified) + "</ul>"
    prof = "".join(f"<li>{e(line.lstrip('- '))}</li>" for line in r.profile.summary_md().splitlines()[1:])
    body = (f"<table><thead><tr>{''.join(f'<th>{e(h)}</th>' for h in hdr)}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
            if rows else "<p>No job passed every gate.</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Upwork Shortlist</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--mute:#666;--line:#e3e3e3;--acc:#14804a;--warn:#b25e00;--card:#f7f7f5}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--mute:#aaa;--line:#333;--acc:#3ccf7f;--warn:#f0a040;--card:#1f1f1f}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1600px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}} .mute{{color:var(--mute)}}
.wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{background:var(--card);position:sticky;top:0}} a{{color:var(--acc)}}
.v{{font-weight:600;white-space:nowrap}} .apply-now{{color:var(--acc)}} .review{{color:var(--warn)}} .warn{{color:var(--warn)}}
.op{{background:var(--card);padding:10px 14px;border-radius:8px;margin:8px 0}} .op p{{margin:4px 0 0}}
</style></head><body>
<h1>Upwork shortlist: {e(r.profile.name)}</h1><div class="mute">Run {at:%Y-%m-%d %H:%M} UTC · {len(r.shortlist)} actionable · scores are {e(r.metric_name)}</div>
<h2>Student profile</h2><p><b>{e(r.profile.positioning)}</b></p><ul>{prof}</ul>
<h2>Actionable jobs</h2><div class="wrap">{body}</div>
{"<h2>Proposal openers</h2>" + openers if openers else ""}{unver}
<h2>Funnel</h2><p>Discovered {r.stats.get('discovered', 0)} → passed hard gates {r.stats.get('passed_deterministic', 0)} → shortlisted {len(r.shortlist)}.
Excluded: {e(", ".join(f"{g} {n}" for g, n in excl.most_common()) or "none")}</p>{audit_html}
</body></html>"""


def to_json(r: RunResult) -> str:
    def s2d(s: Scored) -> dict:
        return {"job": s.job.to_dict(), "verdict": s.verdict, "score": s.total, "parts": s.parts,
                "judgment": s.judgment, "verified": s.verified}

    return json.dumps({
        "profile": r.profile.to_dict(), "metric": r.metric_name, "run_at": r.started_at.isoformat(),
        "shortlist": [s2d(s) for s in r.shortlist], "unverified": [s2d(s) for s in r.unverified],
        "excluded": [{"url": x.job.url, "title": x.job.title, "gate": x.gate, "reason": x.reason} for x in r.excluded],
        "stats": r.stats,
    }, indent=1)
