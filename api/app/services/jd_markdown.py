"""Turn a job description file (Word, PDF, text) into clean Markdown, word for word.

This is deliberately not done by the AI: a JD should be copied exactly, not summarised or reworded,
and a long JD is cheaper and more reliable to convert directly."""
from __future__ import annotations

import io
import re
from pathlib import PurePath

BULLET = re.compile(r"^\s*([•●▪◦‣∙·○■□➢➤►\-–—*]|\d+[.)])\s+")
JD_NAME = re.compile(r"(\bjd\b|job|description|posting|position|role|req|requisition|vacancy|opportunity)", re.I)
NOT_JD_NAME = re.compile(r"(resume|résumé|\bcv\b|logo|signature|image\d*|invoice|contract|nda|agreement|msa)", re.I)
CONVERTIBLE = {".docx", ".pdf", ".txt", ".md"}


def _docx_to_md(data: bytes) -> str:
    import mammoth
    from markdownify import markdownify

    html = mammoth.convert_to_html(io.BytesIO(data)).value
    md = markdownify(html, heading_style="ATX", bullets="-", strip=["img", "a"])
    return md


def _heading_like(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 70 or BULLET.match(s) or s.endswith((".", ",", ";")):
        return False
    words = s.rstrip(":").split()
    if len(words) > 8:
        return False
    return s.endswith(":") or (s.isupper() and len(s) > 3) or (s.istitle() and len(words) <= 5)


def _text_to_md(text: str) -> str:
    """PDFs and plain text have no structure, so infer headings, bullets and paragraphs."""
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n")]
    out: list[str] = []
    para: list[str] = []

    def flush():
        if para:
            out.append(" ".join(para))
            out.append("")
            para.clear()

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            continue
        if m := BULLET.match(s):
            flush()
            out.append("- " + s[m.end():].strip())
            continue
        if _heading_like(s):
            flush()
            if out and out[-1] != "":
                out.append("")
            out.append("## " + s.rstrip(":").strip())
            out.append("")
            continue
        if out and out[-1].startswith("- ") and not para and s[0].islower():
            out[-1] += " " + s            # wrapped bullet line
            continue
        para.append(s)
    flush()
    return "\n".join(out)


def tidy(md: str) -> str:
    md = md.replace("\xa0", " ")
    md = re.sub(r"\*\*\s*\*\*", "", md)                 # empty bold from Word formatting
    md = re.sub(r"(?m)^(#+ .*?)\s*\*\*$", r"\1", md)
    md = re.sub(r"(?m)^#+\s*\*\*(.+?)\*\*\s*$", lambda m: "## " + m.group(1).strip(), md)
    md = re.sub(r"(?m)^\*\*([^*\n]{2,70}?):?\*\*\s*$", lambda m: "## " + m.group(1).strip(), md)  # bold-only lines
    md = re.sub(r"(?m)^(#+ .+)\n(?=[^\n])", r"\1\n\n", md)       # blank line after every heading
    md = re.sub(r"(?m)^[ \t]+$", "", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def to_markdown(file_name: str, data: bytes) -> str:
    ext = PurePath(file_name).suffix.lower()
    if ext == ".docx":
        return tidy(_docx_to_md(data))
    if ext == ".pdf":
        from pypdf import PdfReader

        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        return tidy(_text_to_md(text))
    if ext == ".md":
        return tidy(data.decode("utf-8", errors="replace"))
    if ext == ".txt":
        return tidy(_text_to_md(data.decode("utf-8", errors="replace")))
    raise ValueError(f"Can't convert {ext or file_name} to a job description; use Word, PDF or text")


def pick_jd_attachments(names: list[str]) -> list[str]:
    """Which attachments of a job-requisition email are the job description(s)."""
    usable = [n for n in names if PurePath(n).suffix.lower() in CONVERTIBLE and not NOT_JD_NAME.search(n)]
    named = [n for n in usable if JD_NAME.search(PurePath(n).stem)]
    return named or (usable if len(usable) <= 2 else [])
