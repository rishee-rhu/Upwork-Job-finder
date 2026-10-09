"""Live discovery through an Apify Upwork actor.

Set APIFY_TOKEN and APIFY_ACTOR (e.g. "username~upwork-jobs-scraper"). Actors differ in input
shape, so the input is a template: every string value equal to "{query}" is replaced per query.
Default template is {"query": "{query}", "maxItems": 30}; override with APIFY_INPUT_TEMPLATE
(JSON string) or --apify-input FILE.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from ..models import Job, now_utc
from ..verify import PageState
from . import normalize

DEFAULT_ACTOR = "neatrat/upwork-job-scraper"
# Exact-phrase Upwork search, newest first, last 24h. {qurl} = URL-encoded quoted query.
DEFAULT_TEMPLATE: dict[str, Any] = {
    "rawUrl": "https://www.upwork.com/nx/search/jobs/?q={qurl}&sort=recency&per_page=50",
    "maxJobAge": {"value": 24, "unit": "hours"},
}


def _fill(tpl: Any, q: str) -> Any:
    if isinstance(tpl, dict):
        return {k: _fill(v, q) for k, v in tpl.items()}
    if isinstance(tpl, list):
        return [_fill(v, q) for v in tpl]
    if isinstance(tpl, str):
        return tpl.replace("{qurl}", urllib.parse.quote(f'"{q}"')).replace("{query}", q)
    return tpl


def search(queries: list[str], actor: Optional[str] = None, token: Optional[str] = None,
           template: Optional[dict] = None, timeout: int = 300, max_items: int = 30,
           log: Optional[Callable[[str], None]] = None) -> list[Job]:
    actor = (actor or os.environ.get("APIFY_ACTOR") or DEFAULT_ACTOR).replace("/", "~")
    token = token or os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("Apify needs APIFY_TOKEN.")
    if template is None:
        env_tpl = os.environ.get("APIFY_INPUT_TEMPLATE")
        template = json.loads(env_tpl) if env_tpl else DEFAULT_TEMPLATE
    url = (f"https://api.apify.com/v2/acts/{urllib.parse.quote(actor, safe='~')}"
           f"/run-sync-get-dataset-items?timeout={timeout}&maxItems={max_items}")
    jobs: list[Job] = []
    for q in queries:
        body = json.dumps(_fill(template, q)).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 30) as r:
                items = json.loads(r.read())
        except Exception as e:  # one slow or failed search shouldn't lose the others
            if log:
                log(f"  search {q!r} failed: {type(e).__name__}: {e}"[:200])
            continue
        if log:
            log(f"  {len(items)} jobs for {q!r}")
        seen_at = now_utc()
        for it in items:
            j = normalize(it, f"apify:{actor}")
            if j:
                j.query = j.query or q
                # A live search only lists public, open jobs, so being returned now is proof of availability.
                if not (it.get("hasHired") is True):
                    j.availability, j.observed_at = PageState.OK, seen_at
                    j.availability_detail = "returned by a live Apify search"
                jobs.append(j)
    return jobs
