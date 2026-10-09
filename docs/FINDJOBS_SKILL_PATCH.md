# FindJobs Skill Patch — Upwork Precision Mode

## Mission
Find high-probability, currently actionable Upwork opportunities based on a student's dossier and Upwork profile. Optimize for successful applications, not result volume.

## Non-Negotiable Order
AVAILABILITY -> FRESHNESS -> HARD ELIGIBILITY -> CAPABILITY -> EVIDENCE -> CLIENT -> COMPETITION -> DIFFERENTIATION -> COMMISSION RISK -> PROPOSAL FEASIBILITY -> RANK.

Never score before availability verification.

## Hard Exclusions
Exclude immediately if any of the following is true:
- private or invite-only
- access denied
- no longer available / closed / removed / expired
- redirects to generic Upwork jobs/search/home
- broken URL
- job ID/title mismatch
- current availability cannot be verified
- stale cached/search result only
- mandatory geography/timezone/language/certification/tool/case-study/profile requirement not met
- already filled unless clearly still hiring multiple

## Freshness Policy
0–6h: highest
6–24h: strong
1–3d: conditional
>3d: normally exclude
weeks/months old: exclude
Track posted_at and observed_at separately.

## Precision Rule
Balanced discovery is allowed, but final results are precision-first.
Return 5–10 strong opportunities rather than a long list of plausible jobs.

## Fit Rules
Score separately:
1. Capability Fit
2. Evidence Fit
3. Opportunity Win Potential

Do not call it true Win Probability until the Upwork profile is available.

## Candidate Evidence Rule
A requirement only counts as a strong match if the dossier/profile can substantiate it.
Do not invent case studies, software expertise, AI engineering, or recent results.

## Client Quality Rule
Use payment verification, hire rate, total spend, hires, ratings/reviews, job-posting behavior, and similar prior hires.

## Competition Rule
Use proposals, interviewing, invites, hires, freelancers needed, and recent client activity together.

## Differentiation Rule
Reward niche intersections where candidate proof is uncommon. Generic keyword matches rank lower.

## Commission Rule
Include commission jobs if allowed by user, but risk-adjust them:
paid base + commission > meeting fee + commission > pure commission with client leads > pure commission self-sourcing > vague/unbounded claims.

## Proposal Feasibility Gate
Only recommend if a strong opening can be written from real candidate evidence without exaggeration.

## Upwork URL Validation
Immediately before final output:
- open exact URL
- actual job visible
- not private
- not unavailable
- no generic redirect
- title/job ID matches
- still actionable
If not, exclude.

## Final Table
Student profile first, then:
Opportunity | Direct Link | Posted | Observed | Availability Verified | Compensation | Client Quality | Competition | Capability Fit | Evidence Fit | Win Potential | Why Selected | Risk/Gap | Verdict

Availability Verified must be YES for every recommended row.

## UX
Run the full workflow end-to-end.
Do not stop for routine approvals.
Ask only when a genuine blocker exists.
