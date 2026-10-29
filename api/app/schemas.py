"""Request bodies. `*Create` = fields allowed on insert; `*Update` = same, all optional (PATCH)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, create_model


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


def partial(model: type[BaseModel], name: str) -> type[BaseModel]:
    fields = {k: (f.annotation | None, None) for k, f in model.model_fields.items()}
    return create_model(name, __base__=_Base, **fields)


class ClientCreate(_Base):
    name: str
    industry: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    fee_terms: str | None = None
    status: Literal["prospect", "active", "inactive"] = "active"
    notes: str | None = None
    owner_id: UUID | None = None


class ContactCreate(_Base):
    client_id: UUID
    first_name: str
    last_name: str | None = None
    title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    mobile: str | None = None
    linkedin_url: str | None = None
    is_primary: bool = False
    is_hiring_manager: bool = False
    notes: str | None = None


class JobCreate(_Base):
    title: str
    client_id: UUID | None = None
    hiring_contact_id: UUID | None = None
    pipeline_id: UUID | None = None
    owner_id: UUID | None = None
    reference_code: str | None = None
    description: str | None = None
    public_description: str | None = None
    location: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    work_model: Literal["onsite", "hybrid", "remote"] | None = None
    employment_type: Literal["permanent", "contract", "contract_to_hire", "temporary"] | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    rate_min: Decimal | None = None
    rate_max: Decimal | None = None
    rate_unit: Literal["hour", "day", "month", "year"] | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    must_have_skills: list[str] = []
    nice_to_have_skills: list[str] = []
    systems: list[str] = []
    certifications: list[str] = []
    openings: int = 1
    fee_percent: Decimal | None = None
    fee_flat: Decimal | None = None
    status: Literal["draft", "open", "on_hold", "filled", "closed", "cancelled"] = "open"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    hide_client_name: bool = True


class CandidateCreate(_Base):
    first_name: str
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    years_experience: Decimal | None = None
    skills: list[str] = []
    systems: list[str] = []
    certifications: list[str] = []
    summary: str | None = None
    work_authorization: str | None = None
    desired_rate: str | None = None
    availability: str | None = None
    status: Literal["active", "placed", "do_not_contact", "archived"] = "active"
    source_detail: str | None = None
    owner_id: UUID | None = None


class ApplicationCreate(_Base):
    candidate_id: UUID
    job_id: UUID
    stage_id: UUID | None = None   # defaults to the first stage of the job's pipeline
    notes: str | None = None


class ApplicationUpdate(_Base):
    stage_id: UUID | None = None
    submitted_to_client_at: datetime | None = None
    placed_at: datetime | None = None
    start_date: date | None = None
    bill_rate: Decimal | None = None
    pay_rate: Decimal | None = None
    placement_fee: Decimal | None = None
    rejection_reason: str | None = None
    notes: str | None = None


class PipelineCreate(_Base):
    name: str
    is_default: bool = False


class StageCreate(_Base):
    pipeline_id: UUID
    name: str
    position: int
    color: str = "#94A3B8"
    stage_type: Literal["active", "placed", "rejected", "withdrawn"] = "active"


class StageReorder(_Base):
    stage_ids: list[UUID]   # in the new order


class SavedViewCreate(_Base):
    entity: Literal["jobs", "candidates", "clients", "contacts", "applications", "inbox"]
    name: str
    layout: Literal["table", "board", "cards"] = "table"
    config: dict = {}
    is_default: bool = False
    shared: bool = False   # True → visible to the whole tenant


class InterviewCreate(_Base):
    application_id: UUID
    round: int = 1
    interview_type: Literal["phone_screen", "video", "onsite", "technical", "panel", "final", "other"] | None = None
    scheduled_at: datetime | None = None
    duration_minutes: int | None = None
    location: str | None = None
    interviewer_contact_ids: list[UUID] = []
    status: Literal["scheduled", "completed", "cancelled", "no_show"] = "scheduled"


class ScorecardItem(_Base):
    criterion: str
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class FeedbackCreate(_Base):
    application_id: UUID
    interview_id: UUID | None = None
    from_contact_id: UUID | None = None
    from_name: str | None = None
    overall_rating: int | None = Field(default=None, ge=1, le=5)
    recommendation: Literal["strong_yes", "yes", "maybe", "no", "strong_no"] | None = None
    scorecard: list[ScorecardItem] = []
    strengths: str | None = None
    concerns: str | None = None
    notes: str | None = None


class ActivityCreate(_Base):
    kind: Literal["note", "call", "email", "meeting", "task"]
    subject: str | None = None
    body: str | None = None
    candidate_id: UUID | None = None
    contact_id: UUID | None = None
    client_id: UUID | None = None
    job_id: UUID | None = None
    application_id: UUID | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None


ClientUpdate = partial(ClientCreate, "ClientUpdate")
ContactUpdate = partial(ContactCreate, "ContactUpdate")
JobUpdate = partial(JobCreate, "JobUpdate")
CandidateUpdate = partial(CandidateCreate, "CandidateUpdate")
StageUpdate = partial(StageCreate, "StageUpdate")
InterviewUpdate = partial(InterviewCreate, "InterviewUpdate")
FeedbackUpdate = partial(FeedbackCreate, "FeedbackUpdate")
ActivityUpdate = partial(ActivityCreate, "ActivityUpdate")
