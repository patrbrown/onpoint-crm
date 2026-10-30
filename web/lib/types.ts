export type Tenant = { id: string; name: string; portal_slug: string; role: string; logo_url?: string | null };
export type Me = { profile: { id: string; email: string; full_name: string | null; is_platform_admin: boolean }; tenants: Tenant[] };

export type Client = {
  id: string; name: string; industry: string | null; website: string | null; city: string | null; region: string | null;
  country: string | null; fee_terms: string | null; status: string; notes: string | null; created_at: string;
};
export type Contact = {
  id: string; client_id: string; first_name: string; last_name: string | null; title: string | null; email: string | null;
  phone: string | null; mobile: string | null; linkedin_url: string | null; is_primary: boolean; is_hiring_manager: boolean;
  notes: string | null;
};
export type Job = {
  id: string; title: string; client_id: string | null; hiring_contact_id: string | null; pipeline_id: string | null;
  reference_code: string | null; description: string | null; location: string | null; city: string | null;
  region: string | null; country: string | null; work_model: string | null; employment_type: string | null;
  salary_min: string | null; salary_max: string | null; rate_min: string | null; rate_max: string | null;
  rate_unit: string | null; currency: string | null; must_have_skills: string[]; nice_to_have_skills: string[];
  systems: string[]; certifications: string[]; openings: number; fee_percent: string | null; status: string;
  priority: string; is_published: boolean; published_at: string | null; hide_client_name: boolean; source: string;
  created_at: string;
};
export type Candidate = {
  id: string; first_name: string; last_name: string | null; email: string | null; phone: string | null;
  linkedin_url: string | null; location: string | null; city: string | null; region: string | null; country: string | null;
  current_title: string | null; current_company: string | null; years_experience: string | null; skills: string[];
  systems: string[]; certifications: string[]; summary: string | null; work_authorization: string | null;
  desired_rate: string | null; availability: string | null; status: string; source: string; created_at: string;
};
export type Stage = { id: string; pipeline_id: string; name: string; position: number; color: string; stage_type: string };
export type Pipeline = { id: string; name: string; is_default: boolean; job_id?: string | null; stages: Stage[]; is_custom?: boolean };
export type Application = {
  id: string; candidate_id: string; job_id: string; stage_id: string | null; first_name: string; last_name: string | null;
  email: string | null; current_title: string | null; job_title: string; stage_name: string | null;
  stage_position: number | null; match_score: number | null; created_at: string; notes: string | null;
};
export type Feedback = {
  id: string; application_id: string; from_name: string | null; overall_rating: number | null;
  recommendation: string | null; scorecard: { criterion: string; rating: number; comment?: string }[];
  strengths: string | null; concerns: string | null; notes: string | null; received_at: string;
};
export type Doc = {
  id: string; file_name: string; kind: string; is_primary: boolean; extracted_text: string | null; created_at: string;
  mime_type: string | null; uploaded_by: string | null; uploaded_by_name: string | null;
};
export type Member = {
  id: string; full_name: string; email: string | null; title: string | null; is_active: boolean; has_login: boolean;
  role: string | null; is_me: boolean;
};
export type Note = {
  id: string; kind: string; body: string | null; created_at: string; updated_at: string | null; author_name: string | null;
  editor_name: string | null; can_edit: boolean; candidate_id: string | null;
};
export type SavedView = { id: string; entity: string; name: string; layout: string; config: Record<string, any>; user_id: string | null };
export type Route = { provider: "anthropic" | "openrouter" | "openai_compatible"; model: string; base_url?: string | null; fallback?: boolean };
export type JevConfig = { instructions?: string; categories?: Record<string, string>; use_corrections?: boolean; body_chars?: number; attachment_chars?: number };
export type Settings = {
  llm_provider: string; llm_model: string; llm_base_url: string | null; email_agent_enabled: boolean;
  email_scan_minutes: number; inbox_mode: "review" | "auto"; auto_approve_threshold: string; ai_scoring_enabled: boolean;
  model_routes: Record<string, Route>; triage_provider: "llm" | "jev"; jev_model: string; jev_config: JevConfig;
  review_below_confidence: string;
};
export type AiStatus = {
  can_edit: boolean; keys: { anthropic: boolean; openrouter: boolean; typesafe: boolean }; local_base_url: string;
  tasks: Record<string, string>; suggestions: Record<string, string[]>;
  jev_defaults: Required<JevConfig>;
};
