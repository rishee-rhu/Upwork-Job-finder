"""Gate 0: open the exact job URL and decide whether a freelancer can apply right now.

The classifier works on (final_url, page_title, page_text) so it's testable without a browser.
Search-engine caches are never consulted here: only the live Upwork page counts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import Activity, Client, Job, job_id_from_url, now_utc, parse_relative


class PageState:
    OK = "OK"
    PRIVATE = "PRIVATE"
    UNAVAILABLE = "UNAVAILABLE"
    REDIRECTED = "REDIRECTED"
    MISMATCH = "MISMATCH"
    FILLED = "FILLED"
    BLOCKED = "BLOCKED"  # bot challenge / login wall: state unknown, so not actionable
    ERROR = "ERROR"


PRIVATE_CUES = ("this job is private", "access denied", "only freelancers invited by client",
                "only freelancers invited by the client", "invite-only", "invite only")
UNAVAILABLE_CUES = ("this job is no longer available", "job is no longer available",
                    "this job has been removed", "this job was removed", "job posting has expired",
                    "this job is closed", "no longer accepting proposals", "the job you are looking for")
BLOCKED_CUES = ("just a moment", "verify you are human", "checking your browser", "challenge - upwork",
                "cf-challenge", "enable javascript and cookies", "attention required")
APPLY_CUES = ("apply now", "submit a proposal", "send a proposal")
GENERIC_PATHS = re.compile(r"upwork\.com/(nx/(search|find-work)|freelance-jobs/?$|search/jobs|ab/(account-security/)?login|$)", re.I)


@dataclass
class Verdict:
    state: str
    detail: str = ""
    parsed: dict = field(default_factory=dict)


def _title_matches(expected: str, page_text: str, page_title: str) -> bool:
    if not expected:
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", expected.lower()) if len(w) > 2]
    if not words:
        return True
    hay = (page_title + " " + page_text[:4000]).lower()
    hits = sum(1 for w in words if w in hay)
    return hits / len(words) >= 0.6


def classify(requested_url: str, final_url: str, page_title: str, page_text: str,
             expected_title: str = "", http_status: Optional[int] = None) -> Verdict:
    low = (page_title + "\n" + page_text).lower()
    if any(c in low for c in PRIVATE_CUES):
        return Verdict(PageState.PRIVATE, "private / invite-only / access denied")
    if any(c in low for c in UNAVAILABLE_CUES):
        return Verdict(PageState.UNAVAILABLE, "job no longer available")
    if any(c in low for c in BLOCKED_CUES):
        return Verdict(PageState.BLOCKED, "bot challenge shown; live state not verifiable")
    if http_status and http_status >= 400:
        return Verdict(PageState.ERROR, f"HTTP {http_status}")

    want_id, got_id = job_id_from_url(requested_url), job_id_from_url(final_url)
    if GENERIC_PATHS.search(final_url.split("?")[0]) or (want_id and not got_id):
        return Verdict(PageState.REDIRECTED, f"redirected to {final_url}")
    if want_id and got_id and want_id != got_id:
        return Verdict(PageState.MISMATCH, f"job id {want_id} -> {got_id}")
    if not _title_matches(expected_title, page_text, page_title):
        return Verdict(PageState.MISMATCH, "page title doesn't match listed title")
    if not any(c in low for c in APPLY_CUES):
        if "log in" in low and len(page_text) < 3000:
            return Verdict(PageState.BLOCKED, "login wall; job content not visible")
        return Verdict(PageState.BLOCKED, "no apply button visible; can't confirm it's open")

    parsed = parse_job_page(page_text)
    act: Activity = parsed["activity"]
    if act.hires and (act.freelancers_needed or 1) <= act.hires:
        return Verdict(PageState.FILLED, f"{act.hires} hired, needs {act.freelancers_needed or 1}", parsed)
    return Verdict(PageState.OK, "visible, public, apply button present", parsed)


def _num(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", "").strip().upper()
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _grab(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None


def parse_job_page(text: str, at: Optional[datetime] = None) -> dict:
    """Pull live activity / client stats from a rendered Upwork job page."""
    at = at or now_utc()
    act = Activity()
    prop = _grab(r"proposals:?\s*(less than \d+|\d+\s*(?:to|-)\s*\d+|\d+\+?)", text)
    if prop:
        nums = re.findall(r"\d+", prop)
        act.proposals = 0 if prop.lower().startswith("less") else int(nums[0])
    for attr, pat in (("interviewing", r"interviewing:?\s*(\d+)"), ("invites_sent", r"invites sent:?\s*(\d+)"),
                      ("hires", r"\bhires?:?\s*(\d+)\b"),
                      ("freelancers_needed", r"(?:need(?:s|ed)?\s+)?(\d+)\s+freelancers?(?:\s+needed)?")):
        v = _grab(pat, text)
        if v:
            setattr(act, attr, int(v))
    lv = _grab(r"last viewed by client:?\s*([^\n]+?ago)", text)
    if lv:
        dt = parse_relative(lv, at)
        if dt:
            act.last_viewed_hours = (at - dt).total_seconds() / 3600

    cl = Client()
    low = text.lower()
    if "payment method verified" in low or "payment verified" in low:
        cl.payment_verified = True
    elif "payment method not verified" in low or "payment unverified" in low:
        cl.payment_verified = False
    cl.total_spent = _num(_grab(r"\$([\d.,]+[KM]?)\+?\s*total spent", text))
    hr = _grab(r"(\d+)%\s*hire rate", text)
    cl.hire_rate = float(hr) if hr else None
    cl.hires = int(_grab(r"(\d+)\s*hires?\b", text) or 0) or None
    jp = _grab(r"(\d+)\s*jobs? posted", text)
    cl.jobs_posted = int(jp) if jp else None
    m = re.search(r"(\d(?:\.\d+)?)\s*of\s*(\d+)\s*reviews", text, re.I)
    if m:
        cl.rating, cl.reviews = float(m.group(1)), int(m.group(2))

    posted = None
    pm = re.search(r"posted\s+([^\n]{0,40}?ago|yesterday|last week|last month|last quarter)", text, re.I)
    if pm:
        posted = parse_relative(pm.group(1), at)

    locs = []
    lm = re.search(r"only freelancers located in (?:the )?([^\n]+?) may apply", text, re.I)
    if lm:
        locs = [x.strip() for x in re.split(r",|\bor\b|\band\b", lm.group(1)) if x.strip()]
    return {"activity": act, "client": cl, "posted_at": posted, "allowed_locations": locs}


def apply_verdict(job: Job, v: Verdict, at: Optional[datetime] = None) -> Job:
    """Merge live-page facts over whatever the discovery source said."""
    job.availability, job.availability_detail = v.state, v.detail
    job.observed_at = at or now_utc()
    p = v.parsed
    if not p:
        return job
    for obj_name in ("activity", "client"):
        live, cur = p[obj_name], getattr(job, obj_name)
        for k, val in vars(live).items():
            if val is not None:
                setattr(cur, k, val)
    if p.get("posted_at"):
        job.posted_at = p["posted_at"]
    if p.get("allowed_locations"):
        job.allowed_locations = p["allowed_locations"]
    return job


class BrowserVerifier:
    """Playwright-based verifier. Use a saved logged-in session (see `findjobs login`)
    for the best results; anonymous headless browsers usually hit Upwork's bot challenge,
    which is reported as BLOCKED (never as OK)."""

    def __init__(self, storage_state: Optional[str] = None, headless: bool = True,
                 executable_path: Optional[str] = None, timeout_ms: int = 30000):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        kw = {"headless": headless}
        if executable_path:
            kw["executable_path"] = executable_path
        self._browser = self._pw.chromium.launch(**kw)
        self._ctx = self._browser.new_context(storage_state=storage_state) if storage_state else self._browser.new_context()
        self.timeout_ms = timeout_ms

    def check(self, job: Job) -> Verdict:
        page = self._ctx.new_page()
        try:
            resp = page.goto(job.url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return classify(job.url, page.url, page.title(), page.inner_text("body"),
                             expected_title=job.title, http_status=resp.status if resp else None)
        except Exception as e:  # network error, timeout
            return Verdict(PageState.ERROR, f"{type(e).__name__}: {e}"[:200])
        finally:
            page.close()

    def close(self) -> None:
        self._ctx.close()
        self._browser.close()
        self._pw.stop()


def save_login_state(path: str, executable_path: Optional[str] = None, interactive: bool = True,
                     timeout_s: int = 600) -> bool:
    """Open a visible browser, let the user log in to Upwork, then save cookies.
    interactive=False (web UI) waits until the browser leaves the login pages instead of
    asking for Enter. Returns True if a logged-in session was saved."""
    import time

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        kw = {"headless": False}
        if executable_path:
            kw["executable_path"] = executable_path
        browser = pw.chromium.launch(**kw)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto("https://www.upwork.com/ab/account-security/login")
        ok = True
        if interactive:
            input("Log in to Upwork in the browser window, then press Enter here... ")
        else:
            ok = False
            end = time.time() + timeout_s
            while time.time() < end:
                try:
                    url = page.url
                except Exception:  # window closed
                    break
                if "upwork.com" in url and "/ab/account-security" not in url and "login" not in url:
                    page.wait_for_timeout(3000)  # let post-login redirects settle cookies
                    ok = True
                    break
                page.wait_for_timeout(1000)
        if ok:
            ctx.storage_state(path=path)
        browser.close()
        return ok
