"""Discovery sources. Everything they return is discovery-only until verify.py checks it."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from ..models import Activity, Client, Job, parse_dt


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        cur: Any = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", []):
            return cur
    return None


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,.]+\s*[KkMm]?", str(v))
    if not m:
        return None
    s = m.group(0).replace(",", "").strip()
    mult = {"k": 1e3, "m": 1e6}.get(s[-1].lower(), 1)
    try:
        return float(s.rstrip("KkMm")) * mult
    except ValueError:
        return None


def _i(v: Any) -> Optional[int]:
    x = _f(v)
    return int(x) if x is not None else None


def _b(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "yes", "1", "verified")


def normalize(raw: dict, source: str) -> Optional[Job]:
    """Map a scraper/export record (any common field naming) onto Job."""
    url = _first(raw, "url", "link", "jobUrl", "job_url", "jobLink", "href")
    if not url:
        return None
    if url.startswith("/"):
        url = "https://www.upwork.com" + url
    hourly = _first(raw, "hourlyRate", "hourly_rate", "hourlyBudget", "budget.hourly")
    for k in ("job", "jobDetails", "node"):
        if isinstance(raw.get(k), dict):
            raw = {**raw[k], **raw}
    hmin = _f(_first(raw, "hourlyMin", "hourly_min", "hourlyBudgetMin", "hourly.min", "budget.hourlyMin"))
    hmax = _f(_first(raw, "hourlyMax", "hourly_max", "hourlyBudgetMax", "hourly.max", "budget.hourlyMax"))
    if hourly and not (hmin or hmax):
        nums = [float(x.replace(",", "")) for x in re.findall(r"[\d.,]+", str(hourly))]
        hmin, hmax = (nums[0], nums[-1]) if nums else (None, None)
    budget = _f(_first(raw, "budget.amount", "fixedPrice", "fixed_price", "budget", "amount"))
    jt = str(_first(raw, "jobType", "job_type", "type", "paymentType") or "").lower()
    rng = _first(raw, "budget")
    if "hour" in jt and isinstance(rng, str) and not (hmin or hmax):  # e.g. "10 - 20"
        nums = [float(x.replace(",", "")) for x in re.findall(r"[\d.,]+", rng) if x.strip(".,")]
        if nums:
            hmin, hmax = nums[0], nums[-1]
    job_type = "hourly" if ("hour" in jt or hmin or hmax) else ("fixed" if ("fix" in jt or budget) else None)
    skills = _first(raw, "skills", "tags", "attrs") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    skills = [s if isinstance(s, str) else str(_first(s, "name", "prettyName") or s) for s in skills]

    client = Client(
        country=_first(raw, "clientLocation", "client.country", "clientCountry", "client_country", "client.location.country", "country"),
        payment_verified=_b(_first(raw, "client.paymentVerified", "paymentVerified", "payment_verified", "client.payment_verified")),
        total_spent=_f(_first(raw, "client.totalSpent", "clientTotalSpent", "total_spent", "client.total_spent", "client.spent")),
        hire_rate=_f(_first(raw, "clientHireRatePercent", "client.hireRate", "hireRate", "hire_rate", "client.hire_rate")),
        hires=_i(_first(raw, "client.hires", "clientHires", "client.totalHires")),
        jobs_posted=_i(_first(raw, "client.jobsPosted", "jobsPosted", "client.jobs_posted", "client.totalJobs")),
        rating=_f(_first(raw, "client.rating", "clientRating", "client.feedback")),
        reviews=_i(_first(raw, "client.reviews", "clientReviews", "client.reviewsCount")),
    )
    act = Activity(
        proposals=_i(_first(raw, "proposals", "proposalsCount", "totalApplicants", "applicants", "activity.proposals")),
        interviewing=_i(_first(raw, "interviewing", "activity.interviewing")),
        invites_sent=_i(_first(raw, "invitesSent", "invites_sent", "activity.invitesSent")),
        hires=_i(_first(raw, "hires", "activity.hires", "totalHired")) or (1 if raw.get("hasHired") is True else None),
        freelancers_needed=_i(_first(raw, "freelancersNeeded", "freelancers_needed", "activity.freelancersNeeded")),
    )
    locs = _first(raw, "allowedApplicantCountries", "allowedLocations", "allowed_locations", "preferredLocations") or []
    if isinstance(locs, str):
        locs = [x.strip() for x in locs.split(",") if x.strip()]
    return Job(
        url=url,
        title=str(_first(raw, "title", "jobTitle", "name") or ""),
        description=str(_first(raw, "description", "snippet", "body", "jobDescription") or ""),
        posted_at=parse_dt(_first(raw, "absoluteDate", "posted_at", "postedAt", "publishedOn", "publishedAt", "createdOn",
                                  "createdAt", "date", "postedOn", "posted")),
        job_type=job_type, hourly_min=hmin, hourly_max=hmax,
        budget=budget if job_type == "fixed" else None,
        skills=skills, allowed_locations=list(locs), client=client, activity=act,
        source=source, query=_first(raw, "query", "searchQuery"),
    )


def load_file(path: str | Path) -> list[Job]:
    """Load jobs from .json (list or {items: [...]}) or .csv."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open(newline="") as f:
            rows: Iterable[dict] = list(csv.DictReader(f))
    else:
        data = json.loads(p.read_text())
        rows = (data.get("items") or data.get("jobs") or []) if isinstance(data, dict) else data
    return [j for j in (normalize(r, f"file:{p.name}") for r in rows) if j]


def dedupe(jobs: Iterable[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for j in jobs:
        prev = seen.get(j.key)
        # keep the record with more data
        if prev is None or len(j.description) > len(prev.description):
            seen[j.key] = j
    return list(seen.values())
