"""Judgment calls Claude makes: dossier -> profile, and per-job fit/evidence/feasibility.

Two backends:
- ApiJudge: calls the Claude API (needs ANTHROPIC_API_KEY or `ant auth login`).
- FileJudge: reads judgments someone else wrote (e.g. Claude Code following the skill),
  keyed by job key. Lets the pipeline run with no API key at all.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .models import Job
from .profile import Profile

MODEL = "claude-opus-5-5"
COMMISSION_CLASSES = ["none", "paid_plus_commission", "base_plus_commission", "meeting_fee_plus_commission",
                      "pure_commission_client_leads", "pure_commission_self_sourced", "vague_commission"]

JUDGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hard_eligible": {"type": "boolean"},
        "failed_requirements": {"type": "array", "items": {"type": "string"}},
        "direct_match": {"type": "integer", "description": "0-20: core work matches what the student can do"},
        "evidence_match": {"type": "integer", "description": "0-20: requirements provable from dossier facts"},
        "differentiation": {"type": "integer", "description": "0-12: uncommon niche intersection the student owns"},
        "requirement_gaps": {"type": "integer", "description": "0-6: 6 = no gaps, 0 = serious gaps"},
        "capability_fit": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "evidence_fit": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "commission_structure": {"type": "string", "enum": COMMISSION_CLASSES},
        "proposal_feasible": {"type": "boolean"},
        "proposal_opener": {"type": "string", "description": "2-3 sentences using only real dossier evidence"},
        "why_selected": {"type": "string"},
        "dossier_evidence": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hard_eligible", "failed_requirements", "direct_match", "evidence_match", "differentiation",
                 "requirement_gaps", "capability_fit", "evidence_fit", "commission_structure", "proposal_feasible",
                 "proposal_opener", "why_selected", "dossier_evidence", "risks"],
    "additionalProperties": False,
}

PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "positioning": {"type": "string"},
        "country": {"type": "string"},
        "years_experience": {"type": ["number", "null"]},
        "languages": {"type": "array", "items": {"type": "string"}},
        "domains": {"type": "array", "items": {"type": "string"}},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "weak_or_unproven": {"type": "array", "items": {"type": "string"}},
        "tools": {"type": "array", "items": {"type": "string"}},
        "differentiators": {"type": "array", "items": {"type": "string"}},
        "search_queries": {"type": "array", "items": {"type": "string"}},
        "allow_commission": {"type": "boolean"},
        "allow_calls": {"type": "boolean"},
    },
    "required": ["name", "positioning", "country", "years_experience", "languages", "domains", "strengths",
                 "evidence", "weak_or_unproven", "tools", "differentiators", "search_queries",
                 "allow_commission", "allow_calls"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = """You screen Upwork jobs for one freelancer. Precision beats volume: a wrong recommendation wastes their Connects and credibility.

Rules:
- A requirement counts as matched only if the dossier facts below prove it. Never invent case studies, tools, AI/automation skills, or recent results.
- hard_eligible=false when the job has a mandatory requirement the student clearly fails (location, timezone/work hours, language, certification, exact years, mandatory recent case studies, required tool expertise, portfolio proof). Proposal writing can't fix a hard requirement.
- Generic keyword overlap is not fit. Score direct_match on the core work, not on shared buzzwords.
- differentiation rewards intersections where the student has uncommon proof (e.g. healthcare + sales). Generic lead gen alone scores low.
- commission_structure: classify pay. "vague_commission" = unlimited-earnings talk with no defined rate.
- proposal_feasible=true only if a persuasive 2-3 sentence opener can be written from real evidence without exaggeration. Write that opener in proposal_opener (first person, as the student). If infeasible, explain why in proposal_opener.
- dossier_evidence: the specific dossier facts you relied on. risks: gaps or red flags.

STUDENT PROFILE (JSON):
"""

PROFILE_SYSTEM = """Extract a freelancer profile from the dossier for an Upwork job-matching system.
- evidence: concrete, verifiable facts only (roles, years, team sizes, domains, results). No marketing fluff.
- weak_or_unproven: skills the dossier claims thinly or not at all but a client might assume (be honest).
- differentiators: uncommon intersections of domain + skill this person can prove.
- search_queries: 15-30 short Upwork search phrases spanning core skills, adjacent skills, and domain niches.
- country: where the freelancer is based. allow_commission/allow_calls: true unless the dossier says otherwise."""


def _job_payload(job: Job) -> str:
    return json.dumps({
        "title": job.title, "description": job.description[:6000], "skills": job.skills,
        "compensation": job.compensation(), "allowed_locations": job.allowed_locations,
        "client_country": job.client.country,
    }, indent=1)


def _clamp(j: dict) -> dict:
    for k, hi in (("direct_match", 20), ("evidence_match", 20), ("differentiation", 12), ("requirement_gaps", 6)):
        j[k] = max(0, min(hi, int(j.get(k, 0))))
    return j


class ApiJudge:
    def __init__(self, profile: Profile, model: str = MODEL, effort: str = "medium", workers: int = 6):
        import anthropic

        self.client = anthropic.Anthropic()
        self.profile, self.model, self.effort, self.workers = profile, model, effort, workers
        self.system = [{"type": "text", "text": JUDGE_SYSTEM + json.dumps(profile.to_dict(), indent=1),
                        "cache_control": {"type": "ephemeral"}}]

    def _call(self, system: Any, user: str, schema: dict, max_tokens: int = 4000) -> dict:
        resp = self.client.beta.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined this request")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("response truncated (max_tokens)")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def judge_one(self, job: Job) -> dict:
        return _clamp(self._call(self.system, "JOB:\n" + _job_payload(job), JUDGMENT_SCHEMA))

    def judge(self, jobs: list[Job]) -> dict[str, dict]:
        out: dict[str, dict] = {}

        def run(j: Job) -> tuple[str, dict]:
            try:
                return j.key, self.judge_one(j)
            except Exception as e:
                return j.key, {"error": f"{type(e).__name__}: {e}"[:300]}

        with ThreadPoolExecutor(self.workers) as ex:
            for k, v in ex.map(run, jobs):
                out[k] = v
        return out


class FileJudge:
    def __init__(self, path: str | Path):
        self.data: dict[str, dict] = json.loads(Path(path).read_text())

    def judge(self, jobs: list[Job]) -> dict[str, dict]:
        return {j.key: _clamp(self.data[j.key]) if j.key in self.data else {"error": "no judgment in file"}
                for j in jobs}


def write_judge_requests(profile: Profile, jobs: list[Job], path: str | Path) -> None:
    """Dump what a judge needs, for Claude Code (or a human) to fill in without the API."""
    Path(path).write_text(json.dumps({
        "instructions": JUDGE_SYSTEM.split("STUDENT PROFILE")[0].strip(),
        "output_schema_per_job": JUDGMENT_SCHEMA,
        "output_format": "JSON object mapping job key -> judgment object",
        "profile": profile.to_dict(),
        "jobs": {j.key: json.loads(_job_payload(j)) for j in jobs},
    }, indent=1))


def extract_profile(dossier_text: str, model: str = MODEL) -> Profile:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=model, max_tokens=8000, system=PROFILE_SYSTEM,
        messages=[{"role": "user", "content": "DOSSIER:\n" + dossier_text}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": PROFILE_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"profile extraction stopped: {resp.stop_reason}")
    return Profile.from_dict(json.loads(next(b.text for b in resp.content if b.type == "text")))

