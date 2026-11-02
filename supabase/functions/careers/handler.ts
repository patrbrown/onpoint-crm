// Careers page backend for the agency website (Supabase Edge Function "careers").
//   GET  /careers/embed.js              the widget the website loads
//   GET  /careers/jobs?site=SLUG        published, open jobs (title, location, work type; never the client)
//   GET  /careers/jobs/ID?site=SLUG     one job with its description, the skills list and the consent text
//   POST /careers/apply                 an application (multipart form with the resume)
//   GET  /careers/general?site=SLUG     the general application: intro, skills list, consent text
//   POST /careers/apply-general         a general application (resume, contact details, skills)
// Public by design: turn OFF "Verify JWT" for this function. Every request is checked here instead.
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
  auth: { persistSession: false },
});
const BUCKET = "documents";
const MAX_FILE = 10 * 1024 * 1024;
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type, authorization, apikey, x-client-info",
};

const json = (body: unknown, status = 200, extra: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "content-type": "application/json", ...extra } });

const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/i;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
  const url = new URL(req.url);
  const path = url.pathname.replace(/^.*?\/careers(?=\/|$)/, "") || "/";
  const site = (url.searchParams.get("site") || "").trim();
  try {
    if (req.method === "GET" && path === "/embed.js") {
      return new Response(EMBED_JS, {
        headers: { ...CORS, "content-type": "application/javascript; charset=utf-8", "cache-control": "public, max-age=300" },
      });
    }
    if (req.method === "GET" && path === "/jobs") {
      if (!SLUG.test(site)) return json({ error: "Unknown site" }, 400);
      const { data, error } = await sb.rpc("portal_list_jobs", { p_slug: site });
      if (error) throw error;
      return json({ jobs: data ?? [] }, 200, { "cache-control": "public, max-age=60" });
    }
    const one = path.match(/^\/jobs\/([^/]+)$/);
    if (req.method === "GET" && one) {
      if (!SLUG.test(site) || !UUID.test(one[1])) return json({ error: "Not found" }, 404);
      const { data, error } = await sb.rpc("portal_get_job", { p_slug: site, p_job_id: one[1] });
      if (error) throw error;
      if (!data) return json({ error: "This role is no longer open." }, 404);
      return json(data, 200, { "cache-control": "public, max-age=60" });
    }
    if (req.method === "GET" && path === "/general") {
      if (!SLUG.test(site)) return json({ error: "Unknown site" }, 400);
      const { data, error } = await sb.rpc("portal_general", { p_slug: site });
      if (error) throw error;
      return json(data ? { open: true, ...data } : { open: false }, 200, { "cache-control": "public, max-age=60" });
    }
    if (req.method === "POST" && path === "/apply") return await apply(req, false);
    if (req.method === "POST" && path === "/apply-general") return await apply(req, true);
    return json({ error: "Not found" }, 404);
  } catch (e) {
    console.error(e);
    return json({ error: "Something went wrong on our side. Please try again in a few minutes." }, 500);
  }
});

function kindOf(name: string, head: Uint8Array): { ext: string; mime: string } | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf") && head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46)
    return { ext: "pdf", mime: "application/pdf" };
  if (lower.endsWith(".docx") && head[0] === 0x50 && head[1] === 0x4b)
    return { ext: "docx", mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" };
  return null;
}

async function sha256(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function apply(req: Request, general: boolean): Promise<Response> {
  if (Number(req.headers.get("content-length") || 0) > MAX_FILE + 512 * 1024)
    return json({ error: "Your resume is larger than 10 MB. Please attach a smaller file." }, 413);
  let form: FormData;
  try { form = await req.formData(); } catch { return json({ error: "Please fill in the form and try again." }, 400); }
  const v = (k: string, max = 300) => String(form.get(k) ?? "").trim().slice(0, max);
  if (v("website")) return json({ ok: true });            // honeypot: bots fill hidden fields; pretend it worked

  const site = v("site", 64), jobId = v("job_id", 40);
  const first = v("first_name", 100), last = v("last_name", 100);
  const email = v("email", 254).toLowerCase(), phone = v("phone", 40);
  let linkedin = v("linkedin", 300);
  if (!SLUG.test(site) || (!general && !UUID.test(jobId))) return json({ error: "This role is no longer open." }, 404);
  if (!first || !last) return json({ error: "Please enter your first and last name." }, 400);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return json({ error: "Please enter a valid email address." }, 400);
  if ((phone.match(/\d/g) || []).length < 7) return json({ error: "Please enter a phone number we can reach you on." }, 400);
  if (linkedin && !/^https?:\/\//i.test(linkedin)) linkedin = "https://" + linkedin;
  if (linkedin && !/^https?:\/\/([a-z]{2,3}\.)?linkedin\.com\//i.test(linkedin))
    return json({ error: "The LinkedIn link should be a linkedin.com profile address, or leave it blank." }, 400);
  if (form.get("consent") !== "on") return json({ error: "Please tick the box to agree to how we use your information." }, 400);

  const file = form.get("resume");
  if (!(file instanceof File) || file.size === 0) return json({ error: "Please attach your resume." }, 400);
  if (file.size > MAX_FILE) return json({ error: "Your resume is larger than 10 MB. Please attach a smaller file." }, 413);
  const bytes = new Uint8Array(await file.arrayBuffer());
  const kind = kindOf(file.name, bytes.subarray(0, 8));
  if (!kind) return json({ error: "Please attach your resume as a PDF or Word (.docx) file." }, 400);

  const { data: tenantId, error: tErr } = await sb.rpc("portal_tenant", { p_slug: site });
  if (tErr) throw tErr;
  if (!tenantId) return json({ error: "This role is no longer open." }, 404);

  const ip = (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || req.headers.get("cf-connecting-ip") || "";
  const safe = file.name.replace(/[^\w.\-]+/g, "_").slice(-120) || `resume.${kind.ext}`;
  const path = `${tenantId}/applications/${crypto.randomUUID()}/${safe}`;
  const up = await sb.storage.from(BUCKET).upload(path, bytes, { contentType: kind.mime, upsert: false });
  if (up.error) throw up.error;

  const common = {
    p_slug: site, p_first: first, p_last: last, p_email: email, p_phone: phone,
    p_linkedin: linkedin, p_file_name: file.name.slice(-200), p_storage_path: path, p_mime: kind.mime,
    p_size: file.size, p_consent_version: UUID.test(v("consent_version", 40)) ? v("consent_version", 40) : null,
    p_ip: ip, p_ip_hash: await sha256(`${site}|${ip}`), p_user_agent: req.headers.get("user-agent") || "",
  };
  // Skills arrive as repeated "skills" fields; the database tidies and checks them.
  const skills = form.getAll("skills").map((x) => String(x).slice(0, 80)).filter(Boolean).slice(0, 60);
  const { data, error } = general
    ? await sb.rpc("portal_apply_general", { ...common, p_skills: skills })
    : await sb.rpc("portal_apply", { ...common, p_job_id: jobId, p_skills: skills });
  if (error || !data?.ok) {
    await sb.storage.from(BUCKET).remove([path]);
    if (error) throw error;
    if (data.error === "job_closed") return json({ error: "Sorry, this role has just closed." }, 410);
    if (data.error === "closed") return json({ error: "Sorry, we aren’t taking general applications right now." }, 410);
    if (data.error === "too_many") return json({ error: "We’ve received several applications from you just now. Please wait a few minutes and try again." }, 429);
    throw new Error(`portal_apply: ${data.error}`);
  }
  return json({ ok: true });
}
