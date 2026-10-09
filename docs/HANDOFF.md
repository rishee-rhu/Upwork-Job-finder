# FindJobs / Upwork Opportunity Finder — Handoff

## Objective
Build or update the FindJobs skill so it returns only Upwork opportunities that are:
1. currently actionable,
2. genuinely relevant to the student,
3. supportable with real evidence from the dossier/profile,
4. commercially sensible,
5. and have a comparatively high chance of success.

The system must optimize for **precision and win potential**, not the number of jobs returned.

## Current Student Example
Sample dossier: Somya Kumar
Primary positioning: AI-Powered Sales & Lead Generation Consultant
Background: ~12 years, US/UK/Europe-facing work
Relevant domains: healthcare, medical records/case management, IT sales, locum doctor recruiting, mortgage lead generation
Strengths: closing, client-facing sales, recruiting, outbound lead generation, managing a 7–8 person lead-gen team
Constraints: limited recent public case studies; newer hands-on AI tool experience
Search preference: Worldwide, no hourly/fixed-price minimum, commission roles allowed, calling/Zoom roles allowed, Balanced discovery but precision-first final shortlist.

## Critical Failure Found
Public/search-engine indexed Upwork URLs were being treated as live opportunities even when they were:
- private/invite-only,
- no longer available,
- expired,
- or redirecting to the generic Upwork jobs page.

The user manually clicked several previously recommended jobs and found:
- Opportunity 1: "Access denied — This job is private. Only freelancers invited by client can view this job."
- Opportunity 2: "This job is no longer available."
- Opportunity 3: "This job is no longer available."
- Opportunity 4: "This job is no longer available."
- Opportunity 7: no valid actionable job link / generic redirect.

This is now a hard workflow defect that must be fixed.

## Governing Rule
**Do not recommend a job unless the freelancer can currently apply to it and the candidate has a realistically strong chance of being considered.**

## Mandatory Workflow

### Gate 0 — Applyability / Availability
This happens BEFORE fit scoring.

Hard-exclude any job that is:
- private,
- invite-only,
- access denied,
- no longer available,
- closed,
- removed,
- expired,
- redirected to a generic Upwork page,
- broken or mismatched URL,
- stale search-engine result whose current state cannot be verified,
- job ID/title mismatch,
- already hired/closed unless explicitly hiring multiple and still open.

A cached/search-engine page is discovery-only. It is never sufficient proof that the job is actionable.

If current availability cannot be verified, do not put the job in the recommended table.

### Gate 1 — Freshness
Preferred:
- 0–6 hours: highest priority
- 6–24 hours: strong
- 1–3 days: only if competition/client activity remains attractive
- >3 days: normally exclude unless unusually strong (e.g. <5 proposals, client still active, multiple hires, exact niche fit)
- weeks/months old: exclude from normal recommendations

Store both:
- source posted time
- observed/retrieved time

### Gate 2 — Hard Candidate Eligibility
Exclude before scoring when the candidate clearly fails a mandatory requirement such as:
- geography/location restriction,
- timezone or work-hour restriction,
- required language,
- mandatory certification,
- mandatory years of exact experience,
- mandatory recent case studies,
- mandatory software/tool expertise,
- mandatory portfolio proof,
- profile requirements the candidate does not meet.

Do not assume proposal writing can overcome a hard requirement.

### Gate 3 — Capability Fit
Can the student actually do the core work?

For Somya, high-fit clusters include:
- lead generation,
- B2B prospecting,
- SDR/BDR,
- appointment setting,
- outbound sales,
- cold email,
- LinkedIn outreach,
- cold calling,
- qualification,
- sales closing,
- recruiting/staffing business development,
- healthcare/medical sales or outreach,
- CRM/pipeline follow-up.

Do not over-score generic keyword overlap.

### Gate 4 — Evidence Fit
Can the proposal substantiate the fit using actual dossier/profile evidence?

Strong evidence for Somya:
- ~12 years international client-facing experience,
- healthcare/case-management background,
- locum recruiting/compliance,
- IT sales,
- built/ran a 7–8 person lead-generation team,
- strongest stated skill: closing,
- historical priced-per-result experience.

Weak / not proven:
- advanced AI engineering,
- deep data engineering,
- sophisticated cold-email infrastructure at scale,
- large recent SaaS case-study portfolio,
- advanced automation claims unless specifically evidenced elsewhere.

If a strong proposal cannot be written without exaggeration, exclude or heavily downgrade.

### Gate 5 — Client Quality
Evaluate:
- payment verification,
- hire rate,
- total spend,
- number of hires,
- reviews/rating,
- number of jobs posted,
- whether the client repeatedly posts but rarely hires,
- similar prior hires,
- whether client behavior indicates genuine hiring intent.

High-fit job + poor client quality can still be a bad opportunity.

### Gate 6 — Competition / Job Activity
Evaluate together:
- proposal count,
- interviewing count,
- invites,
- hires,
- number of freelancers required,
- client last viewed / recent activity when available.

Examples:
- <5 proposals + 0 interviewing = strong
- 10 proposals + 6 interviewing = much harder
- 50+ proposals + many interviewing = usually skip
- already hired = normally exclude

### Gate 7 — Differentiation
Reward intersections where the candidate has uncommon proof.

For Somya:
- healthcare + SDR/sales,
- recruiting/staffing + outbound/business development,
- lead generation + closing,
- US/UK-facing sales + India-based delivery.

Generic "lead generation" alone should rank below these intersections.

### Gate 8 — Commission Risk Adjustment
Commission roles are allowed, but not treated equally:
- hourly/fixed + commission: normal
- base + commission: acceptable
- pay-per-qualified-meeting + commission: acceptable if economics are clear
- pure commission with client-provided qualified leads: review
- pure commission where freelancer must source all leads: major penalty
- vague "unlimited earning potential" / undefined commission: exclude

### Gate 9 — Proposal Feasibility Test
Before surfacing a job, test:
"Can we write a persuasive opening 2–3 sentences using only real candidate evidence?"

If no, do not recommend.

### Gate 10 — Precision-First Final Shortlist
Search can be broad ("Balanced"), but final output must be precision-first.

Prefer 5–10 high-confidence jobs over 20 plausible jobs.

Do not show low-quality SKIPs unless requested for audit/debugging.

## Scoring Model
Use separate dimensions, not one overloaded "Fit" score.

Suggested:
- Direct requirement match: 20
- Provable evidence match: 20
- Differentiation: 12
- Client hiring intent/quality: 12
- Competition/activity: 12
- Upwork profile competitiveness: 10
- Requirement gaps: 6
- Freshness: 5
- Commercial quality: 3
TOTAL = 100

Until the actual Upwork profile is available, call the final metric:
**Opportunity Win Potential**
not "win probability."

Once profile data (JSS, earnings, reviews, badges, hourly rate, completed jobs, portfolio, specialized profile, etc.) is available, upgrade to a true Candidate Win Score.

## Search Architecture
Use multiple controlled search clusters, not one query.

Core:
- lead generation
- B2B lead generation
- cold email
- email outreach
- appointment setter
- appointment setting
- SDR
- BDR
- outbound sales
- business development
- prospecting
- sales closer
- LinkedIn lead generation

AI/automation adjacent:
- AI lead generation
- sales automation
- outreach automation
- Apollo
- Instantly
- Lemlist
- Sales Navigator
- CRM outreach

Domain advantage:
- healthcare lead generation
- healthcare sales
- medical staffing
- medical recruiting
- locum recruiting
- staffing lead generation
- healthcare appointment setter
- recruiting business development

Deduplicate by Upwork job ID / canonical URL.

## Final Output Format
Start with Student Profile summary.

Then only actionable jobs in a table:
- Opportunity
- Direct Upwork Link
- Posted
- Observed/Retrieved
- Availability Verified (must be YES)
- Compensation
- Client Country
- Client Quality
- Proposals / Competition
- Capability Fit
- Evidence Fit
- Opportunity Win Potential
- Why Selected
- Dossier Evidence
- Risk / Gap
- Verdict

Verdicts:
- APPLY NOW
- APPLY
- REVIEW
Normally do not surface SKIP jobs.

## Validation Requirement
Before returning any job:
1. Open/verify the exact current job URL.
2. Confirm the actual job is visible.
3. Confirm it is not private/invite-only.
4. Confirm it is not "no longer available."
5. Confirm it does not redirect to generic search/home.
6. Confirm the title/job ID match.
7. Confirm it is still actionable at observed time.

If any check fails -> exclude before scoring.

## Retrieval Architecture
Preferred:
Live Upwork-compatible retrieval / Apify actor / browser-based current verification
-> deduplicate
-> availability gate
-> freshness gate
-> candidate hard eligibility
-> capability/evidence scoring
-> client/competition scoring
-> proposal-feasibility test
-> precision shortlist

Avoid:
Google/Bing cached/indexed pages -> scoring -> recommend

Search-engine indexes may be used for discovery only, never current-state verification.

## Known Example Errors / Regression Tests
The new skill should fail these jobs before scoring:
1. Job page displays "Access denied" / private / invited freelancers only.
2. Job page displays "This job is no longer available."
3. URL redirects to generic Upwork jobs/search page.
4. Search engine shows an old description but logged-in page is closed/private.
5. Job posted months/quarters ago in a workflow intended for fresh opportunities.

The new skill should not ask the user to manually discover these defects.

## User Experience Rules
- Run end-to-end without stopping at every stage.
- Only ask questions when a genuine blocker cannot be resolved from dossier/profile/data.
- Do not make the user act as QA for stale/broken opportunities.
- Be transparent when live availability cannot be verified.
- Do not claim fresh/live status based only on cached indexing.
