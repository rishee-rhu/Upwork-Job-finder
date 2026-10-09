import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from findjobs.models import Activity, Client, Job  # noqa: E402
from findjobs.profile import Profile  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def profile():
    return Profile.load(ROOT / "examples" / "profile.somya.json")


def make_job(n: int, title: str = "B2B Lead Generation Specialist", hours_old: float = 3, **kw) -> Job:
    j = Job(url=f"https://www.upwork.com/jobs/~01{n:016d}", title=title,
            description=kw.pop("description", "Need outbound lead gen and appointment setting for US clients."),
            posted_at=NOW - timedelta(hours=hours_old), job_type="hourly", hourly_min=10, hourly_max=20,
            client=kw.pop("client", Client(country="United States", payment_verified=True, total_spent=25000,
                                           hire_rate=70, rating=4.9, reviews=20, hires=15, jobs_posted=20)),
            activity=kw.pop("activity", Activity(proposals=3, interviewing=0, invites_sent=1)))
    for k, v in kw.items():
        setattr(j, k, v)
    return j


@pytest.fixture
def mk():
    return make_job
