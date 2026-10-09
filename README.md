# FindJobs: Upwork opportunity finder

Dossier in, short list of **currently open** Upwork jobs the student can realistically win out. It's built from `docs/HANDOFF.md`.

Pipeline order (nothing is scored before its live page is checked):

```
discover -> dedupe -> freshness pre-filter -> OPEN LIVE PAGE (private? gone? redirect? filled?)
-> freshness -> location/budget -> competition -> commission red flags
-> Claude judgment (eligibility, capability, evidence, differentiation, honest proposal opener)
-> score /100 -> APPLY NOW / APPLY / REVIEW -> top 5-10
```

## Setup (your own machine)

```bash
pip install -r requirements.txt
python -m playwright install chromium
export ANTHROPIC_API_KEY=...          # profile extraction + fit judgment
export APIFY_TOKEN=... APIFY_ACTOR=... # live job search (any Upwork scraper actor)
python -m findjobs login              # log in to Upwork once; saves upwork_state.json
```

## Use: web interface (easiest)

```bash
python -m findjobs ui
```

This opens http://127.0.0.1:8765 with 4 steps:
1. **Settings:** Anthropic key, Apify token and actor, and a "Log in to Upwork" button.
2. **Profile:** upload a dossier and extract it, or pick an example. Edit the JSON before saving.
3. **Find jobs:** Apify queries and/or an uploaded jobs file, plus run options.
4. **Results:** live log, funnel numbers and the report inline. If there's no Claude key, it also has a download/upload loop for judgments.

Keys and files stay in `workspace/` on your machine. The server only listens on localhost.

## Use: command line

```bash
python -m findjobs run --dossier somya.pdf --apify --state upwork_state.json --audit
```

Output lands in `out/`: `report.md`, `report.html`, `results.json` and `profile.json`.

Other inputs:
- `--profile profile.json`: skip extraction. See `examples/profile.somya.json`. Edit `evidence` and `weak_or_unproven` by hand if needed; they control what Claude is allowed to claim.
- `--jobs export.json|csv`: jobs from anywhere (scraper export, a saved search). Field names are auto-mapped.
- `--query "healthcare sales"`: override search queries.
- `--apify-input input.json`: actor input template; `"{query}"` gets substituted.

No API key? The run writes `out/judge_requests.json`. Have Claude Code (see `.claude/skills/findjobs/SKILL.md`) or anyone else fill in `judgments.json`, then rerun with `--jobs out/jobs.verified.json --judgments judgments.json`.

Try it offline:

```bash
python -m findjobs run --profile examples/profile.somya.json --jobs examples/jobs.sample.json \
  --judgments examples/judgments.sample.json --no-verify --show-unverified --audit
```

## Why live verification needs your machine

Upwork shows anonymous datacenter browsers a bot challenge. When that happens the verifier marks the job `BLOCKED`, and BLOCKED jobs are **never** recommended. Run it from your own computer with a logged-in session (`findjobs login`). Add `--headed` if you want to watch it work.

Upwork's terms restrict automated access. Keep volume low, use your own account, and stay within what Upwork allows.

## Scoring (100)

| Part | Pts | Source |
|---|---|---|
| Direct requirement match | 20 | Claude |
| Provable evidence match | 20 | Claude |
| Differentiation | 12 | Claude |
| Client quality | 12 | live page: payment verified, spend, hire rate, rating |
| Competition | 12 | live page: proposals, interviewing, invites, last viewed |
| Upwork profile | 10 | profile `upwork` stats (neutral 5 until supplied) |
| Requirement gaps | 6 | Claude |
| Freshness | 5 | posted time |
| Commercial | 3 | rate / budget |

Commission adjustments run from 0 (paid + commission) down to -15 (pure commission, self-sourced leads). Vague "unlimited earnings" jobs are excluded. The metric reads **Opportunity Win Potential** until `upwork` stats (JSS, jobs, rating) are added to the profile. After that it becomes **Candidate Win Score**.

## Tests

```bash
pytest -q
```

Covers every case in `docs/REGRESSION_TESTS.json`. It also drives the real Playwright verifier against a local fake of Upwork pages (private, gone, redirected, open).
