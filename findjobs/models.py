"""Core data types shared by every stage of the pipeline."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

JOB_ID_RE = re.compile(r"~0?([0-9a-z]{6,})", re.I)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def job_id_from_url(url: str) -> Optional[str]:
    m = JOB_ID_RE.search(url or "")
    return m.group(1).lower() if m else None


def canonical_url(url: str) -> str:
    jid = job_id_from_url(url)
    return f"https://www.upwork.com/jobs/~0{jid}" if jid else (url or "").split("?")[0]


@dataclass
class Client:
    country: Optional[str] = None
    payment_verified: Optional[bool] = None
    total_spent: Optional[float] = None
    hire_rate: Optional[float] = None  # percent 0-100
    hires: Optional[int] = None
    jobs_posted: Optional[int] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None


@dataclass
class Activity:
    proposals: Optional[int] = None  # lower bound when Upwork shows a range ("10 to 15")
    interviewing: Optional[int] = None
    invites_sent: Optional[int] = None
    hires: Optional[int] = None
    freelancers_needed: Optional[int] = None
    last_viewed_hours: Optional[float] = None


@dataclass
class Job:
    url: str
    title: str = ""
    description: str = ""
    posted_at: Optional[datetime] = None
    job_type: Optional[str] = None  # hourly | fixed
    hourly_min: Optional[float] = None
    hourly_max: Optional[float] = None
    budget: Optional[float] = None
    skills: list[str] = field(default_factory=list)
    allowed_locations: list[str] = field(default_factory=list)  # "Only freelancers located in ..."
    client: Client = field(default_factory=Client)
    activity: Activity = field(default_factory=Activity)
    source: str = "unknown"
    query: Optional[str] = None
    # Filled by the verifier
    availability: Optional[str] = None  # see verify.PageState
    availability_detail: str = ""
    observed_at: Optional[datetime] = None

    @property
    def job_id(self) -> Optional[str]:
        return job_id_from_url(self.url)

    @property
    def key(self) -> str:
        return self.job_id or canonical_url(self.url)

    def age_hours(self, at: Optional[datetime] = None) -> Optional[float]:
        if not self.posted_at:
            return None
        return ((at or now_utc()) - self.posted_at).total_seconds() / 3600

    def compensation(self) -> str:
        if self.job_type == "hourly" and (self.hourly_min or self.hourly_max):
            lo, hi = self.hourly_min, self.hourly_max
            return f"${lo:g}-${hi:g}/hr" if lo and hi and lo != hi else f"${(lo or hi):g}/hr"
        if self.budget:
            return f"${self.budget:,.0f} fixed"
        return self.job_type or "not stated"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("posted_at", "observed_at"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        d = dict(d)
        d["client"] = Client(**(d.get("client") or {}))
        d["activity"] = Activity(**(d.get("activity") or {}))
        for k in ("posted_at", "observed_at"):
            if d.get(k):
                d[k] = parse_dt(d[k])
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


def parse_dt(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e12 else v, tz=timezone.utc)
    s = str(v).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return parse_relative(s)


_REL_RE = re.compile(r"(\d+|an?|one)\s*(second|minute|min|hour|hr|day|week|month|quarter|year)s?\s*ago", re.I)
_UNIT_H = {"second": 1 / 3600, "minute": 1 / 60, "min": 1 / 60, "hour": 1, "hr": 1, "day": 24,
           "week": 168, "month": 730, "quarter": 2190, "year": 8760}


def parse_relative(s: str, at: Optional[datetime] = None) -> Optional[datetime]:
    """'Posted 3 hours ago' -> datetime. Returns None when unparseable."""
    from datetime import timedelta

    at = at or now_utc()
    low = s.lower()
    if "just now" in low or "moments ago" in low:
        return at
    if "yesterday" in low:
        return at - timedelta(hours=24)
    if "last week" in low:
        return at - timedelta(days=7)
    if "last month" in low:
        return at - timedelta(days=30)
    if "last quarter" in low:
        return at - timedelta(days=91)
    m = _REL_RE.search(s)
    if not m:
        return None
    n = 1 if m.group(1).lower() in ("a", "an", "one") else int(m.group(1))
    return at - timedelta(hours=n * _UNIT_H[m.group(2).lower()])
