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
