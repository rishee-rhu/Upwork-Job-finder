---
name: findjobs
description: Find currently-open, high-win-potential Upwork jobs for a student from their dossier. Use when the user shares a dossier/CV/profile and asks for Upwork jobs, a shortlist, or opportunities to apply to.
---

# FindJobs (Upwork precision mode)

Spec: `docs/HANDOFF.md`. Code: `findjobs/`. Never recommend a job whose live Upwork page wasn't verified as open.

## Run it end to end, without stopping for routine approvals

1. **Profile.** If the user gave a dossier:
   - With Claude API creds (`ANTHROPIC_API_KEY`): `python -m findjobs profile <dossier> -o out/profile.json`
   - Otherwise read the dossier yourself and write `out/profile.json` matching `examples/profile.somya.json`. Put only provable facts in `evidence`; put anything thin in `weak_or_unproven`.
2. **Discover jobs.** Preferred: `--apify` (needs `APIFY_TOKEN`, `APIFY_ACTOR`). Otherwise collect candidate URLs with WebSearch (`site:upwork.com/jobs` + each `search_queries` entry) into `out/jobs.json` (fields: title, url, description, posted_at). Search results are discovery only.
3. **Run the pipeline.**
   ```
   python -m findjobs run --profile out/profile.json --jobs out/jobs.json [--apify] --state upwork_state.json --audit --out-dir out
   ```
   - Verification needs a browser that can see Upwork. Cloud containers get Upwork's bot challenge, so every job comes back BLOCKED and nothing gets recommended. Tell the user that plainly; it must run on their machine after `python -m findjobs login`.
4. **No API key?** The run writes `out/judge_requests.json`. Judge each job yourself following its `instructions` and `output_schema_per_job`, write `out/judgments.json` (job key -> judgment), then rerun:
   ```
   python -m findjobs run --profile out/profile.json --jobs out/jobs.verified.json --judgments out/judgments.json --out-dir out
   ```
5. **Report.** Show `out/report.md`. Every row in the actionable table must say Availability Verified = YES. Don't promote anything from "Not verified live".

## Rules you must keep when judging
- No invented case studies, tools, AI skills or results.
- Mandatory requirement the student fails -> `hard_eligible: false`.
- Generic keyword overlap isn't fit; niche intersections (e.g. healthcare + SDR) earn differentiation.
- `proposal_feasible` only if an honest 2-3 sentence opener exists; write it.
- Ask the user something only when a real blocker can't be resolved from the dossier or data.
