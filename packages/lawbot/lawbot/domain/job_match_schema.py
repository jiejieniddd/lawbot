from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobMatchReport(BaseModel):
    match_score: float = Field(ge=0.0, le=1.0, default=0.0)
    matched: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    resume_rewrite: list[str] = Field(default_factory=list)
    interview_prep: list[str] = Field(default_factory=list)
    manual_apply_checklist: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    target_role: str = ""
    jd_skills: list[str] = Field(default_factory=list)
    resume_skills: list[str] = Field(default_factory=list)
    market_skills: list[str] = Field(default_factory=list)
    note: str = ""

    def to_markdown(self) -> str:
        lines = [
            "## 岗位契合度报告",
            "",
            f"**匹配分：** {self.match_score:.0%}" + (f"（{self.target_role}）" if self.target_role else ""),
            "",
            "### 匹配点",
        ]
        if self.matched:
            lines.extend(f"- {x}" for x in self.matched[:8])
        else:
            lines.append("- （暂无明显硬技能重合）")
        lines.extend(["", "### 缺口"])
        if self.gaps:
            lines.extend(f"- {x}" for x in self.gaps[:8])
        else:
            lines.append("- （相对 JD/市场地图缺口较少）")
        lines.extend(["", "### 简历改写建议"])
        for x in (self.resume_rewrite or ["把项目成果量化，并点名 JD 关键词"])[:5]:
            lines.append(f"- {x}")
        lines.extend(["", "### 面试准备清单"])
        for x in (self.interview_prep or ["准备 1–2 个可深挖项目故事"])[:6]:
            lines.append(f"- {x}")
        lines.extend(["", "### 人工投递检查清单", "（不支持自动投递 / 招聘站爬虫）"])
        for x in (
            self.manual_apply_checklist
            or [
                "核对 JD 必需技能与项目是否写进简历",
                "按渠道手工投递并记录进度",
                "勿使用验证码绕过或无人值守自动投递",
            ]
        )[:6]:
            lines.append(f"- {x}")
        if self.note:
            lines.extend(["", f"> {self.note}"])
        lines.extend(["", "职业建议仅供参考，不构成录用承诺"])
        return "\n".join(lines)
