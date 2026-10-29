"""Bulk candidate import: a ZIP of resumes plus an optional CSV.

Matching rules, in order:
1. CSV has a `resume_file` (or `file`, `filename`, `resume`) column → exact file-name match (case-insensitive,
   extension optional).
2. Otherwise fuzzy-match "First Last" from the CSV against each file name, after stripping noise words
   like "resume", "cv", "final", dates and version numbers. Accepted at a score of 85 or higher, and only if
   no other file scores within 5 points (ambiguous matches are reported, not guessed).
3. Files with no CSV row become candidates parsed from the resume alone (if `parse_unmatched` is on).
4. CSV rows with no file still become candidates, flagged "no resume".
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from rapidfuzz import fuzz

from .text_extract import SUPPORTED

FILE_COLUMNS = ("resume_file", "file", "filename", "file_name", "resume")
NOISE = re.compile(
    r"\b(resume|résumé|cv|curriculum|vitae|final|updated|update|copy|draft|new|latest|v\d+|\d{4}|\d{1,2})\b", re.I
)

# Normalised CSV header → canonical candidate field
HEADER_MAP = {
    "first_name": "first_name", "firstname": "first_name", "first": "first_name", "given_name": "first_name",
    "last_name": "last_name", "lastname": "last_name", "last": "last_name", "surname": "last_name",
    "family_name": "last_name",
    "name": "full_name", "full_name": "full_name", "candidate": "full_name", "candidate_name": "full_name",
    "email": "email", "email_address": "email", "e_mail": "email",
    "phone": "phone", "phone_number": "phone", "mobile": "phone", "cell": "phone",
    "linkedin": "linkedin_url", "linkedin_url": "linkedin_url", "linkedin_profile": "linkedin_url",
    "location": "location", "city": "city", "province": "region", "state": "region", "region": "region",
    "country": "country", "title": "current_title", "current_title": "current_title", "job_title": "current_title",
    "company": "current_company", "current_company": "current_company", "employer": "current_company",
    "skills": "skills", "notes": "summary", "source": "source_detail",
}


@dataclass
class ResumeFile:
    name: str            # file name inside the zip (no folders)
    data: bytes


@dataclass
class ImportRow:
    fields: dict[str, str]
    resume: ResumeFile | None = None
    match: str = "none"         # exact | fuzzy | none | resume_only
    match_score: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    rows: list[ImportRow]
    skipped_files: list[dict[str, str]]   # files we could not use, with reason


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def _stem_tokens(file_name: str) -> str:
    stem = PurePosixPath(file_name).stem
    stem = re.sub(r"[_\-.()\[\]]+", " ", stem)
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)   # JaneDoe → Jane Doe
    stem = NOISE.sub(" ", stem)
    return re.sub(r"\s+", " ", stem).strip().lower()


def read_zip(data: bytes) -> tuple[list[ResumeFile], list[dict[str, str]]]:
    files, skipped = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = PurePosixPath(info.filename).name
            if name.startswith(".") or "__MACOSX" in info.filename:
                continue
            if PurePosixPath(name).suffix.lower() not in SUPPORTED:
                skipped.append({"file": name, "reason": "unsupported file type"})
                continue
            if info.file_size > 20 * 1024 * 1024:
                skipped.append({"file": name, "reason": "larger than 20 MB"})
                continue
            files.append(ResumeFile(name=name, data=zf.read(info)))
    return files, skipped


def read_csv(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        row: dict[str, str] = {}
        for key, value in raw.items():
            if key is None or value is None:
                continue
            nk = _norm_header(key)
            target = HEADER_MAP.get(nk, nk if nk in FILE_COLUMNS else None)
            if target and value.strip():
                row[target] = value.strip()
        if "full_name" in row and "first_name" not in row:
            parts = row.pop("full_name").split()
            row["first_name"] = parts[0]
            if len(parts) > 1:
                row["last_name"] = " ".join(parts[1:])
        row.pop("full_name", None)
        if row:
            rows.append(row)
    return rows


def plan_import(files: list[ResumeFile], csv_rows: list[dict[str, str]] | None,
                parse_unmatched: bool = True, threshold: float = 85, margin: float = 5) -> ImportPlan:
    remaining = {f.name.lower(): f for f in files}
    by_stem = {PurePosixPath(f.name).stem.lower(): f for f in files}
    rows: list[ImportRow] = []

    for fields in csv_rows or []:
        row = ImportRow(fields=dict(fields))
        file_ref = next((fields[c] for c in FILE_COLUMNS if fields.get(c)), None)
        for c in FILE_COLUMNS:
            row.fields.pop(c, None)

        if file_ref:
            ref = PurePosixPath(file_ref).name.lower()
            f = remaining.get(ref) or by_stem.get(PurePosixPath(ref).stem)
            if f and f.name.lower() in remaining:
                row.resume, row.match, row.match_score = f, "exact", 100.0
                remaining.pop(f.name.lower())
            else:
                row.warnings.append(f"resume file '{file_ref}' not found in zip")
        else:
            name = f"{fields.get('first_name', '')} {fields.get('last_name', '')}".strip().lower()
            if name and remaining:
                scored = sorted(
                    ((fuzz.token_sort_ratio(name, _stem_tokens(f.name)), f) for f in remaining.values()),
                    key=lambda x: x[0], reverse=True,
                )
                best_score, best = scored[0]
                runner_up = scored[1][0] if len(scored) > 1 else 0
                if best_score >= threshold and best_score - runner_up >= margin:
                    row.resume, row.match, row.match_score = best, "fuzzy", float(best_score)
                    remaining.pop(best.name.lower())
                elif best_score >= threshold:
                    row.warnings.append(
                        f"ambiguous: '{best.name}' and '{scored[1][1].name}' both match; attach manually")
        if row.resume is None:
            row.warnings.append("no resume")
        rows.append(row)

    skipped: list[dict[str, str]] = []
    for f in remaining.values():
        if parse_unmatched:
            rows.append(ImportRow(fields={}, resume=f, match="resume_only"))
        else:
            skipped.append({"file": f.name, "reason": "no matching CSV row"})
    return ImportPlan(rows=rows, skipped_files=skipped)
