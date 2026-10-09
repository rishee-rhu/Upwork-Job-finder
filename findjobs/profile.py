"""Student profile: loaded from JSON, or extracted from a dossier with Claude."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class UpworkStats:
    job_success_score: Optional[float] = None
    total_earnings: Optional[float] = None
    completed_jobs: Optional[int] = None
    rating: Optional[float] = None
    badges: list[str] = field(default_factory=list)
    hourly_rate: Optional[float] = None


@dataclass
class Profile:
    name: str
    positioning: str
    country: str
    years_experience: Optional[float] = None
    languages: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # concrete, provable facts only
    weak_or_unproven: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    differentiators: list[str] = field(default_factory=list)  # uncommon niche intersections
    search_queries: list[str] = field(default_factory=list)
    allow_commission: bool = True
    allow_calls: bool = True
    min_hourly: Optional[float] = None
    min_fixed: Optional[float] = None
    upwork: Optional[UpworkStats] = None

    @property
    def has_upwork_profile(self) -> bool:
        u = self.upwork
        return bool(u and (u.job_success_score is not None or u.completed_jobs is not None))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        d = dict(d)
        if d.get("upwork"):
            d["upwork"] = UpworkStats(**d["upwork"])
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def summary_md(self) -> str:
        lines = [
            f"**{self.name}**: {self.positioning}",
            f"- Location: {self.country}" + (f" · {self.years_experience:g} yrs experience" if self.years_experience else ""),
            f"- Domains: {', '.join(self.domains) or 'n/a'}",
            f"- Strengths: {', '.join(self.strengths) or 'n/a'}",
            f"- Differentiators: {', '.join(self.differentiators) or 'n/a'}",
            f"- Unproven (won't be claimed): {', '.join(self.weak_or_unproven) or 'n/a'}",
            f"- Prefs: commission {'OK' if self.allow_commission else 'no'}, calls {'OK' if self.allow_calls else 'no'}",
        ]
        return "\n".join(lines)


def read_dossier_text(path: str | Path) -> str:
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
    if suf == ".docx":
        import docx

        return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    return p.read_text(errors="replace")
