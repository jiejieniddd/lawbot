from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EducationItem(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    period: str = ""


class ProjectItem(BaseModel):
    name: str = ""
    role: str = ""
    description: str = ""
    tech: list[str] = Field(default_factory=list)


class ExperienceItem(BaseModel):
    company: str = ""
    title: str = ""
    period: str = ""
    description: str = ""


class ResumeProfile(BaseModel):
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    intent: str = ""
    summary: str = ""

    def skills_summary(self, *, limit: int = 24) -> str:
        skills = [s.strip() for s in self.skills if s and str(s).strip()]
        if not skills:
            return ""
        return "、".join(skills[:limit])

    def prompt_block(self, *, max_chars: int = 1200) -> str:
        lines = ["【当前简历】"]
        if self.intent:
            lines.append(f"意向：{self.intent}")
        if self.skills:
            lines.append(f"技能：{self.skills_summary()}")
        for edu in self.education[:3]:
            bits = " / ".join(x for x in (edu.school, edu.major, edu.degree, edu.period) if x)
            if bits:
                lines.append(f"教育：{bits}")
        for proj in self.projects[:3]:
            tech = ",".join(proj.tech[:6])
            lines.append(f"项目：{proj.name or '未命名'} {tech}".strip())
        for exp in self.experience[:3]:
            bits = " / ".join(x for x in (exp.company, exp.title, exp.period) if x)
            if bits:
                lines.append(f"经历：{bits}")
        if self.summary:
            lines.append(f"摘要：{self.summary[:400]}")
        text = "\n".join(lines)
        return text[:max_chars]

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ResumeProfile:
        if not data:
            return cls()
        return cls.model_validate(data)
