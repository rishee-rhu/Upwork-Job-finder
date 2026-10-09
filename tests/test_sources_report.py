import json

from findjobs import pipeline, report
from findjobs.sources import load_file, normalize

from .test_pipeline import DictJudge, FakeVerifier


def test_normalize_common_scraper_shape():
    raw = {"title": "Appointment Setter", "url": "/jobs/~0212345678abcdef",
           "publishedOn": "2026-10-09T08:00:00Z", "hourlyRate": "$10.00-$25.00", "jobType": "Hourly",
           "proposalsCount": "10 to 15", "client": {"country": "USA", "paymentVerified": True,
                                                   "totalSpent": "$12K", "hireRate": "55%"},
           "skills": [{"name": "Cold Calling"}, "Lead Generation"]}
    j = normalize(raw, "test")
    assert j.url == "https://www.upwork.com/jobs/~0212345678abcdef"
    assert (j.job_type, j.hourly_min, j.hourly_max) == ("hourly", 10, 25)
    assert j.activity.proposals == 10
    assert j.client.total_spent == 12000 and j.client.hire_rate == 55 and j.client.payment_verified
    assert j.skills == ["Cold Calling", "Lead Generation"]


def test_load_json_and_csv(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"items": [{"title": "x", "link": "https://www.upwork.com/jobs/~01aaaaaaaaaa"}]}))
    (tmp_path / "b.csv").write_text("title,url,budget\nY,https://www.upwork.com/jobs/~01bbbbbbbbbb,500\n")
    assert load_file(tmp_path / "a.json")[0].title == "x"
    b = load_file(tmp_path / "b.csv")[0]
    assert b.job_type == "fixed" and b.budget == 500


def test_reports_render(profile, now, mk):
    jobs = [mk(1, title="Healthcare SDR"), mk(2, hours_old=24 * 90)]
    res = pipeline.run(profile, jobs, verifier=FakeVerifier(), judge=DictJudge({}), at=now)
    md = report.to_markdown(res, audit=True)
    assert "Healthcare SDR" in md and "| YES |" in md and "freshness" in md
    assert "Opportunity Win Potential" in md
    h = report.to_html(res, audit=True)
    assert "<table>" in h and "Healthcare SDR" in h
    assert json.loads(report.to_json(res))["shortlist"][0]["verified"] is True


def test_normalize_neatrat_upwork_scraper():
    # Shape returned by neatrat/upwork-job-scraper (observed on a real run).
    raw = {"id": "2108518942858345691", "title": "Customer Support Specialist", "description": "Shopify store support.",
           "url": "https://www.upwork.com/jobs/Customer-Support_~022108518942858345691/?referrer_url_path=/nx/search/jobs/",
           "budget": "3 - 5", "relativeDate": "Posted 5 hours ago", "absoluteDate": "2026-10-09T07:24:33.498Z",
           "jobType": "Hourly", "paymentVerified": True, "tags": ["Shopify", "Email Support"], "clientLocation": "USA",
           "clientTotalSpent": 1684, "clientRating": 5, "clientHireRatePercent": 75, "proposals": 41,
           "hasHired": False, "allowedApplicantCountries": None}
    j = normalize(raw, "apify")
    assert j.job_id == "22108518942858345691"
    assert (j.job_type, j.hourly_min, j.hourly_max) == ("hourly", 3, 5)
    assert j.posted_at.hour == 7 and j.client.country == "USA" and j.client.hire_rate == 75
    assert j.activity.proposals == 41 and j.activity.hires is None and j.skills == ["Shopify", "Email Support"]
    assert normalize({**raw, "hasHired": True}, "apify").activity.hires == 1
