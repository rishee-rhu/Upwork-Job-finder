"""Deterministic gates and score components (everything that doesn't need judgment)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import Job
from .profile import Profile
from .verify import PageState

COUNTRY_ALIASES = {
    "us": "united states", "u.s.": "united states", "usa": "united states", "united states of america": "united states",
    "uk": "united kingdom", "u.k.": "united kingdom", "great britain": "united kingdom", "england": "united kingdom",
    "uae": "united arab emirates",
}
REGIONS = {
    "asia": {"india", "pakistan", "bangladesh", "philippines", "indonesia", "vietnam", "sri lanka", "nepal", "malaysia", "thailand"},
    "europe": {"united kingdom", "germany", "france", "spain", "italy", "netherlands", "poland", "ireland", "portugal"},
    "americas": {"united states", "canada", "mexico", "brazil", "argentina", "colombia"},
    "north america": {"united states", "canada", "mexico"},
}


def _country(s: str) -> str:
    s = s.strip().lower().rstrip(".")
    return COUNTRY_ALIASES.get(s, s)


class Exclusion(Exception):
    def __init__(self, gate: str, reason: str):
        super().__init__(f"{gate}: {reason}")
        self.gate, self.reason = gate, reason


# ---------- Gate 0: availability ----------
def gate_availability(job: Job) -> None:
    if job.availability != PageState.OK:
        state = job.availability or "UNVERIFIED"
        raise Exclusion("availability", f"{state}: {job.availability_detail or 'live page not checked'}")


# ---------- Gate 1: freshness ----------
def freshness_points(job: Job, at: Optional[datetime] = None) -> float:
    h = job.age_hours(at)
    if h is None:
        return 0
    return 5 if h <= 6 else 4 if h <= 24 else 2 if h <= 72 else 1


DEFAULT_MAX_AGE_HOURS = 24  # students can only act on jobs posted today


def gate_freshness(job: Job, at: Optional[datetime] = None, max_hours: float = DEFAULT_MAX_AGE_HOURS) -> None:
    h = job.age_hours(at)
    if h is None:
        raise Exclusion("freshness", "posted time unknown, can't confirm it's from today")
    if h > max_hours:
        ago = f"{h:.0f} hours" if h < 48 else f"{h / 24:.0f} days"
        raise Exclusion("freshness", f"posted {ago} ago (limit {max_hours:g}h)")


# ---------- Gate 2 (deterministic part): hard eligibility ----------
def gate_location(job: Job, profile: Profile) -> None:
    if not job.allowed_locations:
        return
    me = _country(profile.country)
    allowed = {_country(x) for x in job.allowed_locations}
    if "worldwide" in allowed or me in allowed:
        return
    if any(me in REGIONS.get(a, set()) for a in allowed):
        return
    raise Exclusion("eligibility", f"location restricted to {', '.join(job.allowed_locations)}")


def gate_budget_floor(job: Job, profile: Profile) -> None:
    if profile.min_hourly and job.job_type == "hourly" and job.hourly_max and job.hourly_max < profile.min_hourly:
        raise Exclusion("eligibility", f"max ${job.hourly_max:g}/hr below floor ${profile.min_hourly:g}")
    if profile.min_fixed and job.job_type == "fixed" and job.budget and job.budget < profile.min_fixed:
        raise Exclusion("eligibility", f"budget ${job.budget:g} below floor ${profile.min_fixed:g}")


# ---------- Gate 8 pre-check: commission ----------
COMMISSION_RE = re.compile(r"commission", re.I)
PURE_COMMISSION_RE = re.compile(r"(commission[- ]only|100\s*%\s*commission|commission[- ]based only|no (base|fixed|hourly) (pay|salary|rate)|"
                                r"pure(ly)? commission|only commission|paid (only )?on commission)", re.I)
VAGUE_RE = re.compile(r"unlimited earning|uncapped earning|earn as much as you want|sky'?s the limit|unlimited income", re.I)
HAS_NUMBER_RE = re.compile(r"(\d+\s*%|\$\s*\d+)")


def commission_precheck(job: Job, profile: Profile) -> Optional[str]:
    """Returns a coarse commission class, or raises for clearly unacceptable cases."""
    text = f"{job.title}\n{job.description}"
    if not COMMISSION_RE.search(text) and not VAGUE_RE.search(text):
        return None
    if not profile.allow_commission and PURE_COMMISSION_RE.search(text):
        raise Exclusion("commission", "pure commission and student doesn't accept commission")
    if VAGUE_RE.search(text) and not HAS_NUMBER_RE.search(text):
        raise Exclusion("commission", "vague 'unlimited earnings' with no defined commission")
    return "pure_commission" if PURE_COMMISSION_RE.search(text) else "has_commission"


# ---------- Gate 5: client quality (0-12) ----------
def client_points(job: Job) -> tuple[float, str]:
    c = job.client
    known = [v for v in (c.payment_verified, c.total_spent, c.hire_rate, c.rating) if v is not None]
    if not known:
        return 5.0, "client data missing"
    pts, notes = 0.0, []
    if c.payment_verified:
        pts += 3; notes.append("pay verified")
    elif c.payment_verified is False:
        notes.append("payment NOT verified")
    if c.total_spent is not None:
        pts += 3 if c.total_spent >= 10_000 else 2 if c.total_spent >= 1_000 else 1 if c.total_spent > 0 else 0
        notes.append(f"${c.total_spent:,.0f} spent")
    if c.hire_rate is not None:
        pts += 3 if c.hire_rate >= 50 else 1.5 if c.hire_rate >= 20 else 0
        notes.append(f"{c.hire_rate:.0f}% hire rate")
    if c.rating is not None and (c.reviews or 0) >= 1:
        pts += 2 if c.rating >= 4.5 else 1 if c.rating >= 4 else 0
        notes.append(f"{c.rating:.1f}★ ({c.reviews})")
    if (c.jobs_posted or 0) >= 5 and not c.hires and not c.total_spent:
        pts -= 3; notes.append(f"{c.jobs_posted} posts, no hires")
    else:
        pts += 1
    return max(0.0, min(12.0, pts)), ", ".join(notes)


# ---------- Gate 6: competition (0-12) ----------
def competition_points(job: Job) -> tuple[float, str]:
    a = job.activity
    if a.proposals is None and a.interviewing is None:
        return 5.0, "activity unknown"
    pts, notes = 0.0, []
    if a.proposals is not None:
        p = a.proposals
        pts += 6 if p < 5 else 5 if p < 10 else 3.5 if p < 20 else 2 if p < 50 else 0
        notes.append(f"{p}{'+' if p >= 50 else ''} proposals")
    else:
        pts += 3
    if a.interviewing is not None:
        i = a.interviewing
        pts += 4 if i == 0 else 3 if i <= 2 else 1.5 if i <= 5 else 0
        notes.append(f"{i} interviewing")
    else:
        pts += 2
    if a.invites_sent is not None:
        pts += 1 if a.invites_sent <= 5 else 0
        notes.append(f"{a.invites_sent} invites")
    if a.last_viewed_hours is not None:
        pts += 1 if a.last_viewed_hours <= 24 else 0
        notes.append(f"client viewed {a.last_viewed_hours:.0f}h ago")
    return max(0.0, min(12.0, pts)), ", ".join(notes)


def gate_competition(job: Job) -> None:
    a = job.activity
    if a.hires and (a.freelancers_needed or 1) <= a.hires:
        raise Exclusion("competition", "already hired")
    if (a.proposals or 0) >= 50 and (a.interviewing or 0) >= 5:
        raise Exclusion("competition", f"{a.proposals}+ proposals and {a.interviewing} interviewing")


# ---------- commercial (0-3) and profile competitiveness (0-10) ----------
def commercial_points(job: Job, commission_class: Optional[str]) -> float:
    if job.job_type == "hourly" and job.hourly_max:
        return 3 if job.hourly_max >= 15 else 2 if job.hourly_max >= 8 else 1
    if job.job_type == "fixed" and job.budget:
        return 3 if job.budget >= 300 else 2 if job.budget >= 100 else 1
    if commission_class == "pure_commission":
        return 0.5
    return 1.5


def profile_points(profile: Profile) -> float:
    if not profile.has_upwork_profile:
        return 5.0  # neutral until real Upwork stats exist
    u = profile.upwork
    pts = 0.0
    if u.job_success_score is not None:
        pts += 4 if u.job_success_score >= 90 else 3 if u.job_success_score >= 80 else 1
    if u.completed_jobs is not None:
        pts += 3 if u.completed_jobs >= 10 else 2 if u.completed_jobs >= 3 else 1 if u.completed_jobs >= 1 else 0
    if u.rating is not None:
        pts += 2 if u.rating >= 4.8 else 1 if u.rating >= 4.5 else 0
    if u.badges:
        pts += 1
    return min(10.0, pts)
