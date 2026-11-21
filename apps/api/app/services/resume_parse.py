"""Resume text extraction + lightweight structured parse."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lawbot.domain.resume_schema import (
    EducationItem,
    ExperienceItem,
    ProjectItem,
    ResumeProfile,
)

logger = logging.getLogger(__name__)

SKILL_LEXICON = (
    "Python",
    "Java",
    "Go",
    "Golang",
    "JavaScript",
    "TypeScript",
    "React",
    "Vue",
    "FastAPI",
    "Django",
    "Flask",
    "Spring",
    "Docker",
    "Kubernetes",
    "K8s",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "MongoDB",
    "PyTorch",
    "TensorFlow",
    "LangChain",
    "Linux",
    "Git",
    "Nginx",
    "Kafka",
    "RabbitMQ",
    "Elasticsearch",
    "C++",
    "Rust",
    "Node.js",
    "Next.js",
)


class OcrBackend(Protocol):
    def extract_text(self, path: Path) -> str: ...


class NullOcr:
    def extract_text(self, path: Path) -> str:
        raise RuntimeError("OCR backend unavailable")


class TesseractOcr:
    def extract_text(self, path: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("pytesseract/Pillow not installed") from exc
        image = Image.open(path)
        text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        return (text or "").strip()


def get_ocr_backend() -> OcrBackend:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

        return TesseractOcr()
    except Exception:
        return NullOcr()


@dataclass
class ParseResult:
    status: str  # ready | failed_text | failed_ocr | failed
    raw_text: str = ""
    profile: ResumeProfile | None = None
    error: str | None = None


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def extract_docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text).strip()


def extract_skills(text: str) -> list[str]:
    found: list[str] = []
    lower = text.lower()
    for skill in SKILL_LEXICON:
        token = skill.lower()
        if token in lower and skill not in found:
            found.append(skill)
    # Also pick ALLCAPS / Camel tokens near 技能
    for m in re.finditer(r"(?:技能|Skills|TECH)[:：\s]*([^\n]{0,200})", text, re.I):
        chunk = m.group(1)
        for part in re.split(r"[,，/|、\s]+", chunk):
            part = part.strip()
            if 1 < len(part) <= 24 and part not in found and re.search(r"[A-Za-z]", part):
                found.append(part)
    return found[:40]


def extract_intent(text: str) -> str:
    for pat in (
        r"(?:求职意向|意向岗位|意向方向|Target)[:：\s]*([^\n]{2,40})",
        r"(?:应聘|意向)[:：\s]*([^\n]{2,40})",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def structure_from_text(text: str) -> ResumeProfile:
    skills = extract_skills(text)
    intent = extract_intent(text)
    education: list[EducationItem] = []
    for m in re.finditer(
        r"(清华大学|北京大学|浙江大学|上海交通大学|南京大学|复旦大学|[\u4e00-\u9fff]{2,12}大学)",
        text,
    ):
        education.append(EducationItem(school=m.group(1)))
        if len(education) >= 3:
            break
    projects: list[ProjectItem] = []
    for m in re.finditer(r"(?:项目|Project)[:：\s]*([^\n]{2,60})", text, re.I):
        projects.append(ProjectItem(name=m.group(1).strip(), tech=skills[:5]))
        if len(projects) >= 5:
            break
    experience: list[ExperienceItem] = []
    for m in re.finditer(r"(?:实习|工作经历|Experience)[:：\s]*([^\n]{2,80})", text, re.I):
        experience.append(ExperienceItem(description=m.group(1).strip()))
        if len(experience) >= 5:
            break
    summary = text[:500].replace("\n", " ")
    return ResumeProfile(
        education=education,
        projects=projects,
        skills=skills,
        experience=experience,
        intent=intent,
        summary=summary,
    )


def parse_resume_file(path: Path, *, mime: str = "", ocr: OcrBackend | None = None) -> ParseResult:
    suffix = path.suffix.lower()
    mime_l = (mime or "").lower()
    try:
        if suffix == ".pdf" or "pdf" in mime_l:
            raw = extract_pdf_text(path)
            if not raw:
                return ParseResult(status="failed_text", error="PDF extracted empty text")
        elif suffix in {".docx"} or "wordprocessingml" in mime_l or "docx" in mime_l:
            raw = extract_docx_text(path)
            if not raw:
                return ParseResult(status="failed_text", error="DOCX extracted empty text")
        elif suffix == ".png" or mime_l == "image/png":
            backend = ocr or get_ocr_backend()
            if isinstance(backend, NullOcr):
                return ParseResult(
                    status="failed_ocr",
                    error="OCR unavailable (install pytesseract + Tesseract); PNG not parsed",
                )
            try:
                raw = backend.extract_text(path)
            except Exception as exc:
                logger.exception("OCR failed")
                return ParseResult(status="failed_ocr", error=str(exc))
            if not raw:
                return ParseResult(status="failed_ocr", error="OCR returned empty text")
        else:
            return ParseResult(status="failed", error=f"Unsupported type: {suffix or mime}")
        profile = structure_from_text(raw)
        return ParseResult(status="ready", raw_text=raw, profile=profile)
    except Exception as exc:
        logger.exception("resume parse failed path=%s", path)
        return ParseResult(status="failed", error=str(exc))
