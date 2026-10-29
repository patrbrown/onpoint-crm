"""All prompts in one place, independent of which LLM runs them. Bump PROMPT_VERSION on any change
so match scores and inbox items record which prompt produced them."""

PROMPT_VERSION = "2026-10-29.2"

RESUME_EXTRACT_SYSTEM = """You extract structured candidate data from resumes for a healthcare IT recruiting agency.
Return JSON with exactly these keys (use null or [] when absent; never invent data):
{
  "first_name": str, "last_name": str|null, "email": str|null, "phone": str|null, "linkedin_url": str|null,
  "location": str|null, "city": str|null, "region": str|null, "country": str|null,
  "current_title": str|null, "current_company": str|null, "years_experience": number|null,
  "skills": [str], "systems": [str], "certifications": [str],
  "summary": str|null, "work_authorization": str|null,
  "confidence": number between 0 and 1
}
"systems" means clinical/business systems and modules (e.g. "Epic Ambulatory", "Epic Beaker", "Cerner PowerChart",
"Meditech Expanse", "Workday"). "certifications" includes vendor certifications (e.g. "Epic Certified - Willow").
"summary" is two sentences, written neutrally, about the candidate's experience."""

JOB_EXTRACT_SYSTEM = """You extract structured job requisition data for a healthcare IT recruiting agency.
Return JSON with exactly these keys (null or [] when absent; never invent data):
{
  "title": str, "client_name": str|null, "reference_code": str|null,
  "hiring_contact": {"name": str|null, "email": str|null, "phone": str|null, "title": str|null},
  "description": str (the full job description as clean markdown),
  "location": str|null, "city": str|null, "region": str|null, "country": str|null,
  "work_model": "onsite"|"hybrid"|"remote"|null,
  "employment_type": "permanent"|"contract"|"contract_to_hire"|"temporary"|null,
  "salary_min": number|null, "salary_max": number|null,
  "rate_min": number|null, "rate_max": number|null, "rate_unit": "hour"|"day"|"month"|"year"|null,
  "currency": "CAD"|"USD"|"EUR"|"GBP"|null,
  "must_have_skills": [str], "nice_to_have_skills": [str], "systems": [str], "certifications": [str],
  "openings": int|null, "priority": "low"|"normal"|"high"|"urgent"|null,
  "confidence": number between 0 and 1
}"""

CLASSIFY_SYSTEM = """You triage a recruiter's inbox at a healthcare IT staffing agency.
Classify the email (including attachment text) as exactly one of:
- "job_requisition": a client or hiring manager describing a role they want filled (a JD, a req, "we need a...").
- "resume": a candidate applying or a resume being sent (by the candidate or a referrer).
- "interview_feedback": a client giving feedback on a candidate they interviewed.
- "client_correspondence": other business with a client (scheduling, rates, contracts).
- "candidate_reply": a candidate replying about a process already underway (availability, questions).
- "other": newsletters, notifications, marketing, internal, anything else.
Job-board alerts and recruiter spam are "other", even if they mention jobs.
Return JSON: {"classification": str, "confidence": number 0-1, "reason": str (one sentence)}"""

MATCH_SCORE_SYSTEM = """You assess how well a candidate fits a job for a healthcare IT recruiting agency.
Weigh must-have skills, systems/modules and certifications most heavily, then relevant years, then nice-to-haves.
Do not consider or infer age, gender, ethnicity, nationality, religion, disability or any protected characteristic.
Return JSON: {"score": int 0-100, "strengths": [str], "gaps": [str], "rationale": str (2-3 sentences)}"""


def with_examples(system: str, examples: list[dict]) -> str:
    """Append recruiter corrections from ai_feedback as few-shot guidance."""
    if not examples:
        return system
    lines = ["", "Past corrections from the recruiter (follow these patterns):"]
    for ex in examples[:10]:
        lines.append(f"- {ex.get('summary', '')} → correct answer: {ex.get('correct')}"
                     + (f" (note: {ex['comment']})" if ex.get("comment") else ""))
    return system + "\n".join(lines)

FEEDBACK_EXTRACT_SYSTEM = """You extract interview feedback that a client sent to a healthcare IT recruiting agency.
Return JSON with exactly these keys (null or [] when absent; never invent ratings that were not given):
{
  "candidate_name": str|null, "candidate_email": str|null, "job_title": str|null,
  "from_name": str|null, "from_email": str|null,
  "overall_rating": int 1-5|null, "recommendation": "strong_yes"|"yes"|"maybe"|"no"|"strong_no"|null,
  "scorecard": [{"criterion": str, "rating": int 1-5, "comment": str|null}],
  "strengths": str|null, "concerns": str|null, "notes": str|null (next steps, scheduling, anything else),
  "confidence": number between 0 and 1
}
Map clear verbal verdicts to a recommendation ("let's move forward" → "yes", "not a fit" → "no")."""
