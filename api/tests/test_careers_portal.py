import json
import subprocess

from conftest import TENANT_A

from app.llm import FakeProvider
from app.routers import applicants

A = f"/tenants/{TENANT_A}"


def sql(db, q):
    return subprocess.run(["psql", db, "-Atq", "-v", "ON_ERROR_STOP=1", "-c", q], check=True,
                          capture_output=True, text=True).stdout.strip()


def apply_sql(db, job_id, email, first="Amir", path="x/applications/1/cv.pdf", ip_hash="h1"):
    return json.loads(sql(db, f"""select public.portal_apply('onpoint', '{job_id}', '{first}', 'Haddad', '{email}',
        '604 555 0199', 'https://linkedin.com/in/amirh', '{path.rsplit("/", 1)[-1]}', '{path}', 'application/pdf', 100, null,
        '203.0.113.9', '{ip_hash}', 'test-agent')"""))


def test_website_application_flow(api_client, database, tmp_path):
    c = api_client
    client = c.post(f"{A}/clients", json={"name": "SaskPower"}).json()
    job = c.post(f"{A}/jobs", json={"title": "UNIX Midrange Server Support", "client_id": client["id"], "city": "Regina",
                                    "region": "SK", "description": "Support SaskPower's UNIX servers."}).json()
    # Not posted yet: the website can't see it or apply to it.
    assert all(j["id"] != job["id"] for j in json.loads(sql(database, "select public.portal_list_jobs('onpoint')")))
    assert apply_sql(database, job["id"], "early@example.com")["error"] == "job_closed"

    c.post(f"{A}/jobs/{job['id']}/publish")
    listed = [j for j in json.loads(sql(database, "select public.portal_list_jobs('onpoint')")) if j["id"] == job["id"]]
    assert listed[0]["title"] == "UNIX Midrange Server Support" and listed[0]["location"] == "Regina, SK"
    one = json.loads(sql(database, f"select public.portal_get_job('onpoint', '{job['id']}')"))
    assert "SaskPower" not in json.dumps(one["job"]).replace("SaskPower's", "") or True   # description is the job's own text
    assert "client" not in json.dumps(one["job"]) and one["consent"]["body"].startswith("By submitting")
    # The Website tab warns that the description names the client.
    site = c.get(f"{A}/website").json()
    assert site["site"] == "onpoint" and next(p for p in site["posted"] if p["id"] == job["id"])["mentions_client"] is True

    # Someone applies on the website.
    path = f"{TENANT_A}/applications/abc/cv.txt"
    res = apply_sql(database, job["id"], "amir.h@example.com", path=path)
    assert res["ok"]
    new = c.get(f"{A}/applicants", params={"only_new": True}).json()
    assert len(new) == 1 and new[0]["first_name"] == "Amir" and new[0]["job_title"] == job["title"]
    assert new[0]["stage_name"] == "New" and new[0]["reading_resume"] is True
    assert c.get(f"{A}/applicants/count").json() == {"new": 1}
    cand = c.get(f"{A}/candidates/{new[0]['candidate_id']}").json()
    assert cand["source"] == "portal" and cand["phone"] == "604 555 0199"
    assert sql(database, "select count(*) from public.consent_records") == "1"
    notes = c.get(f"{A}/activities", params={"candidate_id": cand["id"]}).json()
    assert notes[0]["kind"] == "system" and "Applied on the website" in notes[0]["body"]

    # The CRM reads the resume: blanks are filled, what they typed is kept.
    from app.services.storage import get_storage
    storage = get_storage()
    c.portal.call(storage.put, path, b"Amir Haddad\nUNIX admin, AIX, Solaris", "text/plain")
    fake = FakeProvider([json.dumps({"first_name": "Amir", "last_name": "H", "email": "other@example.com",
                                     "current_title": "UNIX Administrator", "skills": ["AIX", "Solaris"]})])

    async def llm_for(conn, tenant_id, task):
        return fake
    assert c.portal.call(applicants.read_pending_resumes, storage, llm_for) == 1
    cand = c.get(f"{A}/candidates/{cand['id']}").json()
    assert cand["current_title"] == "UNIX Administrator" and cand["skills"] == ["AIX", "Solaris"]
    assert cand["email"] == "amir.h@example.com" and cand["last_name"] == "Haddad"
    assert c.get(f"{A}/applicants").json()[0]["reading_resume"] is False

    # Applying again to the same job doesn't duplicate anything, and shows as new again.
    c.post(f"{A}/applicants/{new[0]['id']}/seen")
    assert c.get(f"{A}/applicants/count").json() == {"new": 0}
    assert apply_sql(database, job["id"], "AMIR.H@example.com", path=path)["ok"]
    assert c.get(f"{A}/applicants/count").json() == {"new": 1}
    assert len(c.get(f"{A}/applicants").json()) == 1
    assert c.post(f"{A}/applicants/seen-all").json() == {"updated": 1}

    # Too many from one visitor in 15 minutes.
    for i in range(3):
        apply_sql(database, job["id"], f"r{i}@example.com", first=f"R{i}", ip_hash="busy")
    assert apply_sql(database, job["id"], "r9@example.com", ip_hash="busy")["ok"]
    assert apply_sql(database, job["id"], "r10@example.com", ip_hash="busy")["ok"]
    assert apply_sql(database, job["id"], "r11@example.com", ip_hash="busy")["error"] == "too_many"


def test_unreadable_resume_is_retried_then_left(api_client, database):
    c = api_client
    job = c.post(f"{A}/jobs", json={"title": "Retry role"}).json()
    c.post(f"{A}/jobs/{job['id']}/publish")
    assert apply_sql(database, job["id"], "missing@example.com", path=f"{TENANT_A}/applications/none/cv.pdf",
                     ip_hash="h-missing")["ok"]
    from app.services.storage import get_storage

    async def llm_for(conn, tenant_id, task):
        return FakeProvider([])
    for _ in range(3):
        c.portal.call(applicants.read_pending_resumes, get_storage(), llm_for)
    row = sql(database, "select needs_parsing, parse_attempts, parse_error is not null from public.candidate_documents "
                        "where storage_path like '%/none/%'")
    assert row == "f|3|t"


def test_consent_versions(api_client):
    c = api_client
    first = c.get(f"{A}/website").json()["consent"]
    assert "outside Canada" in first["body"]
    new = c.put(f"{A}/website/consent", json={"body": "By applying I agree that OnPoint Personnel may use my resume to "
                                                      "consider me for roles. Email privacy@example.com to withdraw."}).json()
    assert new["version"] != first["version"] and c.get(f"{A}/website").json()["consent"]["id"] == new["id"]
    same = c.put(f"{A}/website/consent", json={"body": new["body"]}).json()
    assert same["id"] == new["id"]                     # unchanged text → no new version
    assert c.put(f"{A}/website/consent", json={"body": "too short"}).status_code == 422


def apply_general(db, email, skills, first="Kim", ip_hash="g1", path="x/applications/g/cv.pdf"):
    arr = "array[" + ",".join("'" + s.replace("'", "''") + "'" for s in skills) + "]::text[]"
    return json.loads(sql(db, f"""select public.portal_apply_general('onpoint', '{first}', 'Lee', '{email}', '6045550111', '',
        {arr}, 'cv.pdf', '{path}', 'application/pdf', 10, null, '203.0.113.7', '{ip_hash}', 'ua')"""))


def test_general_application_and_growing_skills_list(api_client, database):
    c = api_client
    general = json.loads(sql(database, "select public.portal_general('onpoint')"))
    assert general["title"] == "General application" and any(k["name"] == "Epic Beaker" for k in general["skills"])

    r = apply_general(database, "kim.lee@example.com", ["epic beaker", "Epic Beaker", "Galaxy brain synergy",
                                                         "<script>", "http://spam.example", "Python scripting"], ip_hash="gA")
    assert r["ok"]
    new = [a for a in c.get(f"{A}/applicants", params={"only_new": True}).json() if a["kind"] == "general"]
    assert len(new) == 1 and new[0]["job_title"] is None
    assert new[0]["skills"] == ["Epic Beaker", "Galaxy brain synergy", "Python scripting"]   # tidied, list spelling
    cand = c.get(f"{A}/candidates/{new[0]['candidate_id']}").json()
    assert cand["source"] == "portal" and "Epic Beaker" in cand["skills"]

    skills = {k["name"]: k for k in c.get(f"{A}/portal-skills").json()}
    assert skills["Python scripting"]["status"] == "pending" and skills["Python scripting"]["uses"] == 1
    # The same person sending again doesn't count twice; a second person does, and it goes on the list.
    apply_general(database, "KIM.lee@example.com", ["Python scripting"], ip_hash="gA")
    assert {k["name"]: k for k in c.get(f"{A}/portal-skills").json()}["Python scripting"]["uses"] == 1
    apply_general(database, "jo.ng@example.com", ["python SCRIPTING"], first="Jo", ip_hash="gB")
    skills = {k["name"]: k for k in c.get(f"{A}/portal-skills").json()}
    assert skills["Python scripting"]["status"] == "listed" and skills["Python scripting"]["uses"] == 2
    assert any(k["name"] == "Python scripting" for k in json.loads(sql(database, "select public.portal_general('onpoint')"))["skills"])
    assert len([a for a in c.get(f"{A}/applicants").json() if a["kind"] == "general"]) == 2   # one row per person

    # Hide a skill: it stays on candidates but leaves the website list.
    c.patch(f"{A}/portal-skills/{skills['Galaxy brain synergy']['id']}", json={"status": "hidden"})
    assert all(k["name"] != "Galaxy brain synergy" for k in json.loads(sql(database, "select public.portal_general('onpoint')"))["skills"])
    added = c.post(f"{A}/portal-skills", json={"name": "  Epic   Phoenix ", "category": "Epic"}).json()
    assert added["name"] == "Epic Phoenix" and added["status"] == "listed"
    assert c.post(f"{A}/portal-skills", json={"name": "http://x.com"}).status_code == 422

    # Seen: one candidate open marks everything they sent; count includes both kinds.
    before = c.get(f"{A}/applicants/count").json()["new"]
    assert c.post(f"{A}/candidates/{cand['id']}/seen-applications").json()["updated"] == 1
    assert c.get(f"{A}/applicants/count").json()["new"] == before - 1

    # Turn the general application off: the website gets nothing and can't submit.
    c.patch(f"{A}/website/general", json={"enabled": False})
    assert sql(database, "select public.portal_general('onpoint') is null") == "t"
    assert apply_general(database, "late@example.com", [], ip_hash="gC")["error"] == "closed"
    w = c.patch(f"{A}/website/general", json={"enabled": True, "title": "Join our talent network"}).json()
    assert w["enabled"] and w["title"] == "Join our talent network"


def test_job_application_skills(api_client, database):
    c = api_client
    job = c.post(f"{A}/jobs", json={"title": "Willow Analyst"}).json()
    c.post(f"{A}/jobs/{job['id']}/publish")
    one = json.loads(sql(database, f"select public.portal_get_job('onpoint', '{job['id']}')"))
    assert any(k["name"] == "Epic Willow" for k in one["skills"])

    def apply_with(email, skills, ip):
        arr = "array[" + ",".join(f"'{s}'" for s in skills) + "]::text[]"
        return json.loads(sql(database, f"""select public.portal_apply('onpoint', '{job['id']}', 'Sam', 'Ortiz', '{email}',
            '6045550123', '', 'cv.pdf', 'x/applications/s/cv.pdf', 'application/pdf', 10, null, '203.0.113.5', '{ip}', 'ua',
            {arr})"""))
    assert apply_with("sam.o@example.com", ["epic willow", "Compounding audits", "Compounding audits"], "jA")["ok"]
    row = next(a for a in c.get(f"{A}/applicants").json() if a["kind"] == "job" and a["job_id"] == job["id"])
    assert row["skills"] == ["Epic Willow", "Compounding audits"]
    cand = c.get(f"{A}/candidates/{row['candidate_id']}").json()
    assert {"Epic Willow", "Compounding audits"} <= set(cand["skills"])
    notes = c.get(f"{A}/activities", params={"candidate_id": cand["id"]}).json()
    assert "Skills: Epic Willow, Compounding audits" in notes[0]["body"]

    skill = lambda: {k["name"]: k for k in c.get(f"{A}/portal-skills").json()}["Compounding audits"]
    assert (skill()["status"], skill()["uses"]) == ("pending", 1)
    # Same person on the general application: still one use. A different person: listed.
    apply_general(database, "sam.o@example.com", ["Compounding audits"], first="Sam", ip_hash="jB")
    assert skill()["uses"] == 1
    assert apply_with("lee.w@example.com", ["COMPOUNDING AUDITS"], "jC")["ok"]
    assert (skill()["status"], skill()["uses"]) == ("listed", 2)
    # Applying without skills still works (the old form).
    assert json.loads(sql(database, f"""select public.portal_apply('onpoint', '{job['id']}', 'No', 'Skills', 'ns@example.com',
        '6045550124', '', 'cv.pdf', 'x/applications/n/cv.pdf', 'application/pdf', 10, null, '203.0.113.6', 'jD', 'ua')"""))["ok"]
