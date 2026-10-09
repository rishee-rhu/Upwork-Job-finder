"""Runs the gates in the order the handoff mandates:
AVAILABILITY -> FRESHNESS -> HARD ELIGIBILITY -> CAPABILITY -> EVIDENCE -> CLIENT -> COMPETITION
-> DIFFERENTIATION -> COMMISSION RISK -> PROPOSAL FEASIBILITY -> RANK
Nothing is scored before its live page has been verified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from . import gates
from .gates import Exclusion
from .models import Job, now_utc
from .profile import Profile
from .sources import dedupe
from .verify import PageState, apply_verdict

APPLY_NOW, APPLY, REVIEW = "APPLY NOW", "APPLY", "REVIEW"


@dataclass
class Scored:
    job: Job
    judgment: dict
    parts: dict[str, float]
    total: float
    verdict: str
    client_note: str
    competition_note: str
    verified: bool = True


@dataclass
class Excluded:
    job: Job
    gate: str
    reason: str


@dataclass
class RunResult:
    profile: Profile
    shortlist: list[Scored] = field(default_factory=list)
    unverified: list[Scored] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    pending_judgment: list[Job] = field(default_factory=list)
    started_at: datetime = field(default_factory=now_utc)
    metric_name: str = "Opportunity Win Potential"
    stats: dict[str, Any] = field(default_factory=dict)


COMMISSION_PENALTY = {
    "none": 0, "paid_plus_commission": 0, "base_plus_commission": 0, "meeting_fee_plus_commission": -2,
    "pure_commission_client_leads": -6, "pure_commission_self_sourced": -15,
}


def _verify(jobs: list[Job], verifier: Any, at: datetime, reuse_minutes: float,
            log: Callable[[str], None]) -> None:
    for i, j in enumerate(jobs, 1):
        if j.observed_at and j.availability and at - j.observed_at <= timedelta(minutes=reuse_minutes):
            continue
        if verifier is None:
            j.availability, j.availability_detail = None, "no verifier configured"
            continue
        v = verifier.check(j)
        apply_verdict(j, v, now_utc())
        log(f"  verify {i}/{len(jobs)} {v.state:<11} {j.title[:60]}")


def _deterministic_gates(job: Job, profile: Profile, at: datetime, strict_availability: bool) -> Optional[str]:
    if strict_availability:
        gates.gate_availability(job)
    elif job.availability not in (None, PageState.OK, PageState.BLOCKED, PageState.ERROR):
        gates.gate_availability(job)  # known-dead jobs are always out
    gates.gate_freshness(job, at)
    gates.gate_location(job, profile)
    gates.gate_budget_floor(job, profile)
    gates.gate_competition(job)
    return gates.commission_precheck(job, profile)


def _judgment_gates(j: dict) -> None:
    if "error" in j:
        raise Exclusion("judgment", j["error"])
    if not j["hard_eligible"]:
        raise Exclusion("eligibility", "; ".join(j["failed_requirements"]) or "fails a mandatory requirement")
    if j["capability_fit"] == "Low":
        raise Exclusion("capability", "core work outside what the student can do")
    if j["evidence_fit"] == "Low":
        raise Exclusion("evidence", "fit can't be substantiated from the dossier")
    if j["commission_structure"] == "vague_commission":
        raise Exclusion("commission", "undefined commission / 'unlimited earnings'")
    if not j["proposal_feasible"]:
        raise Exclusion("proposal", "no honest, persuasive opener possible: " + j["proposal_opener"][:160])


def _score(job: Job, j: dict, profile: Profile, at: datetime, commission_class: Optional[str]) -> Scored:
    client_pts, client_note = gates.client_points(job)
    comp_pts, comp_note = gates.competition_points(job)
    parts = {
        "direct_match": j["direct_match"], "evidence_match": j["evidence_match"],
        "differentiation": j["differentiation"], "client": client_pts, "competition": comp_pts,
        "profile": gates.profile_points(profile), "requirement_gaps": j["requirement_gaps"],
        "freshness": gates.freshness_points(job, at), "commercial": gates.commercial_points(job, commission_class),
    }
    cs = j["commission_structure"]
    parts["commission_adj"] = COMMISSION_PENALTY.get(cs, 0)
    total = max(0.0, min(100.0, sum(parts.values())))
    age = job.age_hours(at) or 999
    if total >= 75 and age <= 24 and cs not in ("pure_commission_client_leads", "pure_commission_self_sourced"):
        verdict = APPLY_NOW
    elif total >= 62:
        verdict = APPLY
    elif total >= 50:
        verdict = REVIEW
    else:
        verdict = ""
    if cs in ("pure_commission_client_leads", "pure_commission_self_sourced") and verdict:
        verdict = REVIEW
    return Scored(job, j, parts, round(total, 1), verdict, client_note, comp_note)


def run(profile: Profile, jobs: list[Job], *, verifier: Any = None, judge: Any = None,
        at: Optional[datetime] = None, max_results: int = 10, show_unverified: bool = False,
        reuse_verification_minutes: float = 60, log: Callable[[str], None] = lambda s: None) -> RunResult:
    at = at or now_utc()
    res = RunResult(profile=profile, started_at=at)
    if profile.has_upwork_profile:
        res.metric_name = "Candidate Win Score"
    jobs = dedupe(jobs)
    res.stats["discovered"] = len(jobs)

    # Cheap freshness pre-filter on source data so we don't open 200 stale pages.
    pre: list[Job] = []
    for j in jobs:
        try:
            if j.posted_at:
                gates.gate_freshness(j, at)
            pre.append(j)
        except Exclusion as e:
            res.excluded.append(Excluded(j, e.gate, e.reason))

    log(f"Verifying {len(pre)} jobs against live Upwork pages...")
    _verify(pre, verifier, at, reuse_verification_minutes, log)

    survivors: list[tuple[Job, Optional[str]]] = []
    for j in pre:
        try:
            survivors.append((j, _deterministic_gates(j, profile, at, strict_availability=not show_unverified)))
        except Exclusion as e:
            res.excluded.append(Excluded(j, e.gate, e.reason))
    res.stats["passed_deterministic"] = len(survivors)

    if judge is None:
        res.pending_judgment = [j for j, _ in survivors]
        return res

    log(f"Judging fit for {len(survivors)} jobs...")
    judgments = judge.judge([j for j, _ in survivors])
    scored: list[Scored] = []
    for j, cc in survivors:
        jd = judgments.get(j.key, {"error": "missing judgment"})
        try:
            _judgment_gates(jd)
        except Exclusion as e:
            res.excluded.append(Excluded(j, e.gate, e.reason))
            continue
        s = _score(j, jd, profile, at, cc)
        if not s.verdict:
            res.excluded.append(Excluded(j, "rank", f"score {s.total} below bar"))
            continue
        s.verified = j.availability == PageState.OK
        scored.append(s)

    order = {APPLY_NOW: 0, APPLY: 1, REVIEW: 2}
    scored.sort(key=lambda s: (order[s.verdict], -s.total))
    res.shortlist = [s for s in scored if s.verified][:max_results]
    res.unverified = [s for s in scored if not s.verified][:max_results]
    res.stats["shortlisted"] = len(res.shortlist)
    return res
