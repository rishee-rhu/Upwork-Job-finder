from findjobs.verify import PageState, classify, parse_job_page

URL = "https://www.upwork.com/jobs/~021234567890abcdef"
OPEN_PAGE = """Healthcare Appointment Setter for Medical Staffing Agency
Posted 2 hours ago
Only freelancers located in the U.S. or India may apply.
We need an SDR to book meetings with hospitals.
Apply now
Activity on this job
Proposals: 5 to 10
Last viewed by client: 1 hour ago
Interviewing: 1
Invites sent: 2
Unanswered invites: 1
About the client
Payment method verified
4.8 of 31 reviews
United States
42 jobs posted
$48K total spent
68% hire rate
27 hires
"""


def test_private_job_excluded():
    v = classify(URL, URL, "Upwork", "Access denied\nThis job is private. Only freelancers invited by client can view this job.")
    assert v.state == PageState.PRIVATE


def test_no_longer_available_excluded():
    v = classify(URL, URL, "Upwork", "This job is no longer available.\nFind similar jobs")
    assert v.state == PageState.UNAVAILABLE


def test_redirect_to_generic_search_excluded():
    v = classify(URL, "https://www.upwork.com/nx/search/jobs/?q=sales", "Find Jobs", "Apply now lots of jobs")
    assert v.state == PageState.REDIRECTED


def test_bot_challenge_is_not_ok():
    v = classify(URL, URL, "Challenge - Upwork", "Just a moment...")
    assert v.state == PageState.BLOCKED


def test_login_wall_is_not_ok():
    v = classify(URL, URL, "Upwork", "Log in to Upwork\nUsername or Email")
    assert v.state == PageState.BLOCKED


def test_id_mismatch():
    other = "https://www.upwork.com/jobs/~02ffffffffffffffff"
    v = classify(URL, other, "x", "Apply now")
    assert v.state == PageState.MISMATCH


def test_title_mismatch():
    v = classify(URL, URL, "Senior Rust Engineer - Upwork", "Senior Rust Engineer\nApply now",
                 expected_title="Healthcare Appointment Setter")
    assert v.state == PageState.MISMATCH


def test_open_job_ok_and_parsed():
    v = classify(URL, URL, "Healthcare Appointment Setter - Upwork", OPEN_PAGE,
                 expected_title="Healthcare Appointment Setter for Medical Staffing Agency")
    assert v.state == PageState.OK
    a, c = v.parsed["activity"], v.parsed["client"]
    assert (a.proposals, a.interviewing, a.invites_sent) == (5, 1, 2)
    assert round(a.last_viewed_hours) == 1
    assert c.payment_verified and c.total_spent == 48000 and c.hire_rate == 68
    assert (c.rating, c.reviews, c.jobs_posted) == (4.8, 31, 42)
    assert v.parsed["allowed_locations"] == ["U.S.", "India"]
    assert v.parsed["posted_at"] is not None


def test_already_filled():
    v = classify(URL, URL, "x", "Some job\nApply now\nHires: 1\nInterviewing: 3")
    assert v.state == PageState.FILLED


def test_proposals_less_than_five():
    assert parse_job_page("Proposals: Less than 5")["activity"].proposals == 0
    assert parse_job_page("Proposals: 50+")["activity"].proposals == 50
