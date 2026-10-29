"""Jev (TypeSafe AI's "System One" model) for email triage.

Jev doesn't write text: it answers typed questions about a `state` with calibrated probabilities.
We ask one Choice question, "which kind of email is this?", and use the probability of every option:
the top option decides the type, and the probabilities feed automatic mode and the "unsure" safety net.

API (docs.typesafe.ai): POST {base}/systemone with {model, state, questions}; answers keyed by question id.
Choice answers carry `choice`, `probabilities` and `confidence`. 401 = bad key, 422 = invalid request,
429/529 = busy (retry with backoff)."""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings

CLASSES = ("job_requisition", "resume", "interview_feedback", "client_correspondence", "candidate_reply", "other")

DEFAULT_CONFIG: dict[str, Any] = {
    "instructions": (
        "This is an email received by a recruiter at a healthcare IT staffing agency. Using the `subject`, `body` "
        "and `attachments`, which one of these best describes the email?"
    ),
    "categories": {
        "job_requisition": "A client, hiring manager or partner asking the agency to fill a role: a job description, "
                           "a requisition, or 'we need a…'. Includes reqs forwarded by a colleague.",
        "resume": "A candidate's resume or CV being sent: a candidate applying, or someone referring or forwarding "
                  "a candidate.",
        "interview_feedback": "A client giving feedback on a candidate they interviewed or reviewed.",
        "client_correspondence": "Other business with a client: scheduling, rates, contracts, invoices, start dates.",
        "candidate_reply": "A candidate replying about a process already underway: availability, questions, "
                           "accepting or declining.",
        "other": "Anything else: newsletters, job-board alerts, marketing, recruiters pitching candidates in bulk, "
                 "internal or personal email.",
    },
    "use_corrections": True,
    "body_chars": 6000,
    "attachment_chars": 1500,
}


class JevError(Exception):
    pass


@dataclass
class Triage:
    classification: str
    confidence: float          # probability of the chosen type
    probabilities: dict[str, float]
    model: str


def merged_config(stored: dict | None) -> dict:
    """The tenant's settings over the defaults (so new defaults appear, and edits are kept)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    stored = stored or {}
    for k, v in stored.items():
        if k == "categories" and isinstance(v, dict):
            cfg["categories"].update({c: d for c, d in v.items() if c in CLASSES and isinstance(d, str) and d.strip()})
        elif k in cfg and v not in (None, ""):
            cfg[k] = v
    return cfg


def build_request(cfg: dict, model: str, subject: str, sender: str, body: str,
                  attachments: list[tuple[str, str]], corrections: list[str]) -> dict:
    instructions = cfg["instructions"].strip()
    if cfg.get("use_corrections") and corrections:
        instructions += "\nThe recruiter has corrected similar emails before:\n" + "\n".join(f"- {c}" for c in corrections[:12])
    state = {
        "from": sender,
        "subject": subject,
        "body": body[: int(cfg["body_chars"])],
        "attachments": [{"name": n, "excerpt": (t or "")[: int(cfg["attachment_chars"])]} for n, t in attachments[:5]],
    }
    return {
        "model": model,
        "state": state,
        "questions": {"email_type": {"type": "choice", "instructions": instructions, "criteria": cfg["categories"]}},
    }


class JevClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.typesafe_api_key
        self.base_url = (base_url or s.typesafe_base_url).rstrip("/")
        if not self.api_key:
            raise JevError("TYPESAFE_API_KEY is not set in .env")

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(4):
                r = await client.request(method, f"{self.base_url}{path}", json=json, headers=headers)
                if r.status_code in (429, 529, 502, 503) and attempt < 3:
                    await asyncio.sleep(float(r.headers.get("Retry-After") or 2 ** attempt))
                    continue
                break
        if r.status_code == 401:
            raise JevError("TypeSafe rejected the API key. Check TYPESAFE_API_KEY in .env.")
        if r.status_code == 422:
            raise JevError(f"Jev didn't accept the request: {r.text[:300]}")
        if r.status_code >= 400:
            raise JevError(f"Jev returned {r.status_code}: {r.text[:300]}")
        return r.json()

    async def models(self) -> list[str]:
        data = await self._request("GET", "/models")
        items = data.get("data", data.get("models", data)) if isinstance(data, dict) else data
        return [m.get("id", m) if isinstance(m, dict) else str(m) for m in (items or [])]

    async def classify(self, request: dict) -> Triage:
        data = await self._request("POST", "/systemone", request)
        ans = (data.get("answers") or {}).get("email_type") or {}
        probs = {k: float(v) for k, v in (ans.get("probabilities") or {}).items()}
        choice = ans.get("choice")
        if choice not in CLASSES:
            raise JevError(f"Unexpected Jev answer: {str(ans)[:200]}")
        return Triage(choice, float(probs.get(choice, ans.get("confidence") or 0)), probs, data.get("model", request["model"]))
