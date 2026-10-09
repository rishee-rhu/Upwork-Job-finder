"""findjobs: dossier in, verified Upwork shortlist out.

  python -m findjobs profile dossier.pdf -o profile.json
  python -m findjobs login --state upwork_state.json
  python -m findjobs run --dossier dossier.pdf --apify --state upwork_state.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import pipeline, report
from .profile import Profile, read_dossier_text

DEFAULT_QUERIES = [
    "lead generation", "B2B lead generation", "cold email", "appointment setter", "SDR", "BDR",
    "outbound sales", "business development", "sales closer", "LinkedIn lead generation",
]


def _log(s: str) -> None:
    print(s, file=sys.stderr)


def _have_api_creds() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("ANTHROPIC_PROFILE"))


def cmd_profile(a: argparse.Namespace) -> None:
    from .judge import extract_profile

    p = extract_profile(read_dossier_text(a.dossier))
    p.save(a.output)
    _log(f"Wrote {a.output}. Review it: 'evidence' and 'weak_or_unproven' drive what gets claimed.")


def cmd_login(a: argparse.Namespace) -> None:
    from .verify import save_login_state

    save_login_state(a.state, a.chromium)
    _log(f"Saved Upwork session to {a.state}. Keep it private (it's your login cookie).")


def _load_profile(a: argparse.Namespace, log=_log) -> Profile:
    if a.profile:
        return Profile.load(a.profile)
    if not a.dossier:
        raise ValueError("Need --profile or --dossier.")
    from .judge import extract_profile

    log("Extracting profile from dossier...")
    p = extract_profile(read_dossier_text(a.dossier))
    out = Path(a.out_dir) / "profile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    p.save(out)
    log(f"Profile saved to {out}")
    return p


def execute_run(a: argparse.Namespace, log=_log) -> pipeline.RunResult:
    """Shared by the CLI and the web UI. Writes report.md/html, results.json into a.out_dir."""
    from .judge import ApiJudge, FileJudge, write_judge_requests
    from .models import Job
    from .sources import load_file

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    profile = _load_profile(a, log)

    jobs: list[Job] = []
    for f in a.jobs or []:
        jobs += load_file(f) if not f.endswith(".verified.json") else [
            Job.from_dict(d) for d in json.loads(Path(f).read_text())]
    if a.apify:
        from .sources import apify

        tpl = json.loads(Path(a.apify_input).read_text()) if a.apify_input else None
        queries = a.query or profile.search_queries or DEFAULT_QUERIES
        log(f"Searching Apify with {len(queries)} queries...")
        jobs += apify.search(queries, template=tpl)
        log(f"Apify returned {len(jobs)} jobs.")
    if not jobs:
        raise ValueError("No jobs to screen. Pass --jobs FILE and/or --apify.")

    verifier = None
    if not a.no_verify:
        try:
            from .verify import BrowserVerifier

            verifier = BrowserVerifier(storage_state=a.state, headless=not a.headed,
                                       executable_path=a.chromium or os.environ.get("FINDJOBS_CHROMIUM"))
        except Exception as e:
            log(f"Browser verifier unavailable ({e}). Jobs can't be verified, so none will be recommended.")

    if a.judgments:
        judge = FileJudge(a.judgments)
    elif _have_api_creds() or a.api:
        judge = ApiJudge(profile)
    else:
        judge = None

    try:
        res = pipeline.run(profile, jobs, verifier=verifier, judge=judge, max_results=a.max,
                           show_unverified=a.show_unverified, log=log)
    finally:
        if verifier:
            verifier.close()

    # keep verified state so a second pass (e.g. with judgments) doesn't reopen every page
    keep = [x.job for x in res.shortlist + res.unverified] + res.pending_judgment
    (out / "jobs.verified.json").write_text(json.dumps([j.to_dict() for j in keep], indent=1))

    (out / "judge_requests.json").unlink(missing_ok=True)
    if res.pending_judgment:
        write_judge_requests(profile, res.pending_judgment, out / "judge_requests.json")
        log(f"No judge available: wrote {out / 'judge_requests.json'}. Fill judgments.json, then rerun with\n"
             f"  --jobs {out / 'jobs.verified.json'} --judgments judgments.json")

    (out / "report.md").write_text(report.to_markdown(res, audit=a.audit))
    (out / "report.html").write_text(report.to_html(res, audit=a.audit))
    (out / "results.json").write_text(report.to_json(res))
    log(f"Done: {len(res.shortlist)} actionable. See {out / 'report.md'} / report.html")
    return res


def cmd_run(a: argparse.Namespace) -> None:
    try:
        res = execute_run(a)
    except ValueError as e:
        sys.exit(str(e))
    print(report.to_markdown(res, audit=a.audit))


def cmd_ui(a: argparse.Namespace) -> None:
    from .web import serve

    serve(a.port, a.workspace, open_browser=not a.no_browser)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="findjobs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile", help="extract profile.json from a dossier (.pdf/.docx/.md/.txt)")
    p.add_argument("dossier")
    p.add_argument("-o", "--output", default="profile.json")
    p.set_defaults(fn=cmd_profile)

    p = sub.add_parser("login", help="log in to Upwork once and save the session for verification")
    p.add_argument("--state", default="upwork_state.json")
    p.add_argument("--chromium", help="path to a Chromium binary")
    p.set_defaults(fn=cmd_login)

    p = sub.add_parser("run", help="discover, verify, gate, judge, rank")
    p.add_argument("--profile", help="profile.json")
    p.add_argument("--dossier", help="dossier file (profile extracted with Claude)")
    p.add_argument("--jobs", action="append", help="job export (.json/.csv); repeatable")
    p.add_argument("--apify", action="store_true", help="search live via Apify (APIFY_TOKEN, APIFY_ACTOR)")
    p.add_argument("--apify-input", help="JSON input template for the actor; '{query}' is substituted")
    p.add_argument("--query", action="append", help="override search queries; repeatable")
    p.add_argument("--state", help="saved Upwork login (from `findjobs login`)")
    p.add_argument("--chromium", help="path to a Chromium binary")
    p.add_argument("--headed", action="store_true", help="show the browser while verifying")
    p.add_argument("--no-verify", action="store_true", help="skip live checks (nothing gets recommended)")
    p.add_argument("--show-unverified", action="store_true", help="list good-but-unverifiable jobs separately")
    p.add_argument("--judgments", help="judgments.json written without the API (see judge_requests.json)")
    p.add_argument("--api", action="store_true", help="force Claude API judge")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--audit", action="store_true", help="include every excluded job and why")
    p.add_argument("--out-dir", default="out")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("ui", help="local web interface (http://127.0.0.1:8765)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--workspace", default="workspace", help="where settings, uploads and results live")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_ui)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
