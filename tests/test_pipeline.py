"""Covers docs/REGRESSION_TESTS.json plus the scoring/ranking rules."""
import json
from pathlib import Path

from findjobs import pipeline
from findjobs.models import Activity
from findjobs.verify import PageState, Verdict

ROOT = Path(__file__).resolve().parents[1]


def judgment(**kw):
    base = dict(hard_eligible=True, failed_requirements=[], direct_match=16, evidence_match=15, differentiation=5,
                requirement_gaps=5, capability_fit="High", evidence_fit="High", commission_structure="none",
                proposal_feasible=True, proposal_opener="I built and ran a 7-person lead-gen team...",
                why_selected="core outbound work", dossier_evidence=["7-8 person team"], risks=[])
    base.update(kw)
    return base


class DictJudge:
    def __init__(self, by_key):
        self.by_key = by_key

    def judge(self, jobs):
        return {j.key: self.by_key.get(j.key, judgment()) for j in jobs}


class FakeVerifier:
    """Maps job key -> page state, mimicking what the live page shows."""

    def __init__(self, states=None):
        self.states = states or {}
        self.calls = 0

    def check(self, job):
        self.calls += 1
        return Verdict(self.states.get(job.key, PageState.OK), "fake")


def run(profile, jobs, now, states=None, judgments=None, **kw):
    return pipeline.run(profile, jobs, verifier=FakeVerifier(states), judge=DictJudge(judgments or {}), at=now, **kw)


def gates_for(res):
    return {e.job.key: e.gate for e in res.excluded}


def test_regression_file_is_covered():
    cases = json.loads((ROOT / "docs" / "REGRESSION_TESTS.json").read_text())["regression_tests"]
    assert len(cases) == 7  # each one has a test below


def test_private_unavailable_redirect_excluded_before_scoring(profile, now, mk):
    jobs = [mk(1), mk(2), mk(3), mk(4)]
    states = {jobs[0].key: PageState.PRIVATE, jobs[1].key: PageState.UNAVAILABLE, jobs[2].key: PageState.REDIRECTED}
    res = run(profile, jobs, now, states)
    g = gates_for(res)
    assert g[jobs[0].key] == g[jobs[1].key] == g[jobs[2].key] == "availability"
    assert [s.job.key for s in res.shortlist] == [jobs[3].key]
    assert all(s.verified and s.job.availability == PageState.OK for s in res.shortlist)


def test_search_snippet_looks_fine_but_live_page_private(profile, now, mk):
    # source data claims a fresh, low-competition job; the live page says private
    j = mk(1, activity=Activity(proposals=0, interviewing=0))
    res = run(profile, [j], now, {j.key: PageState.PRIVATE})
    assert res.shortlist == [] and gates_for(res)[j.key] == "availability"


def test_unverifiable_never_recommended(profile, now, mk):
    j = mk(1)
    res = run(profile, [j], now, {j.key: PageState.BLOCKED})
    assert res.shortlist == []
    res2 = pipeline.run(profile, [mk(2)], verifier=None, judge=DictJudge({}), at=now)
    assert res2.shortlist == []


def test_show_unverified_lists_separately(profile, now, mk):
    j = mk(1)
    res = run(profile, [j], now, {j.key: PageState.BLOCKED}, show_unverified=True)
    assert res.shortlist == [] and [s.job.key for s in res.unverified] == [j.key]


def test_old_jobs_excluded_and_never_opened(profile, now, mk):
    old = [mk(1, hours_old=24 * 60), mk(2, hours_old=24 * 120)]
    v = FakeVerifier()
    res = pipeline.run(profile, old, verifier=v, judge=DictJudge({}), at=now)
    assert v.calls == 0 and set(gates_for(res).values()) == {"freshness"}


def test_only_jobs_posted_today(profile, now, mk):
    today = mk(1, hours_old=23)
    yesterday = mk(2, hours_old=30, activity=Activity(proposals=0, interviewing=0))  # great stats don't rescue it
    undated = mk(3)
    undated.posted_at = None
    res = run(profile, [today, yesterday, undated], now)
    g = gates_for(res)
    assert g[yesterday.key] == "freshness" and g[undated.key] == "freshness"
    assert [s.job.key for s in res.shortlist] == [today.key]
    # the window is configurable
    res2 = run(profile, [mk(4, hours_old=30)], now, max_age_hours=72)
    assert len(res2.shortlist) == 1


def test_missing_mandatory_case_studies_excluded(profile, now, mk):
    j = mk(1, title="SaaS SDR - must show 3 recent case studies")
    jd = {j.key: judgment(hard_eligible=False, failed_requirements=["3 recent SaaS case studies with metrics"])}
    res = run(profile, [j], now, judgments=jd)
    assert gates_for(res)[j.key] == "eligibility"


def test_infeasible_proposal_excluded(profile, now, mk):
    j = mk(1)
    res = run(profile, [j], now, judgments={j.key: judgment(proposal_feasible=False, proposal_opener="would need to invent AI work")})
    assert gates_for(res)[j.key] == "proposal"


def test_healthcare_niche_beats_generic_lead_gen(profile, now, mk):
    generic = mk(1, title="Lead Generation Expert")
    niche = mk(2, title="Healthcare Staffing SDR")
    jd = {generic.key: judgment(differentiation=2), niche.key: judgment(differentiation=11)}
    res = run(profile, [generic, niche], now, judgments=jd)
    assert [s.job.key for s in res.shortlist] == [niche.key, generic.key]


def test_location_restriction(profile, now, mk):
    us_only = mk(1, allowed_locations=["United States"])
    india_ok = mk(2, allowed_locations=["U.S.", "India"])
    asia = mk(3, allowed_locations=["Asia"])
    res = run(profile, [us_only, india_ok, asia], now)
    assert gates_for(res) == {us_only.key: "eligibility"}


def test_vague_commission_excluded(profile, now, mk):
    j = mk(1, description="Commission role with unlimited earning potential! Close deals.")
    res = run(profile, [j], now)
    assert gates_for(res)[j.key] == "commission"


def test_pure_commission_self_sourced_capped(profile, now, mk):
    j = mk(1, description="20% commission only, you source your own leads", job_type=None, hourly_min=None, hourly_max=None)
    res = run(profile, [j], now, judgments={j.key: judgment(commission_structure="pure_commission_self_sourced")})
    assert all(s.verdict == pipeline.REVIEW for s in res.shortlist)


def test_heavy_competition_skipped(profile, now, mk):
    j = mk(1, activity=Activity(proposals=50, interviewing=8))
    res = run(profile, [j], now)
    assert gates_for(res)[j.key] == "competition"


def test_dedupe_by_job_id(profile, now, mk):
    a = mk(1)
    b = mk(1)
    b.url += "?referrer=google"
    res = run(profile, [a, b], now)
    assert res.stats["discovered"] == 1


def test_no_judge_returns_pending(profile, now, mk):
    res = pipeline.run(profile, [mk(1)], verifier=FakeVerifier(), judge=None, at=now)
    assert len(res.pending_judgment) == 1 and res.shortlist == []


def test_metric_name_upgrades_with_upwork_stats(profile, now, mk):
    from findjobs.profile import UpworkStats

    assert run(profile, [mk(1)], now).metric_name == "Opportunity Win Potential"
    profile.upwork = UpworkStats(job_success_score=95, completed_jobs=12, rating=4.9)
    assert run(profile, [mk(1)], now).metric_name == "Candidate Win Score"
