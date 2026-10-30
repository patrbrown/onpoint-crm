import io
import json
import zipfile

from conftest import TENANT_A, TENANT_B, USER_B

from app.llm import FakeProvider
from app.routers import uploads

A = f"/tenants/{TENANT_A}"


def test_core_crm_flow(api_client):
    c = api_client
    client = c.post(f"{A}/clients", json={"name": "Fraser Health", "industry": "Healthcare"}).json()
    contact = c.post(f"{A}/contacts", json={"client_id": client["id"], "first_name": "Dana", "last_name": "Lee",
                                            "email": "dana@fraserhealth-demo.ca", "is_hiring_manager": True}).json()
    assert c.get(f"{A}/contacts", params={"client_id": client["id"]}).json()[0]["id"] == contact["id"]

    job = c.post(f"{A}/jobs", json={
        "title": "Epic Ambulatory Analyst", "client_id": client["id"], "hiring_contact_id": contact["id"],
        "employment_type": "contract", "rate_min": 85, "rate_max": 100, "rate_unit": "hour", "currency": "CAD",
        "must_have_skills": ["Epic Ambulatory"], "certifications": ["Epic Certified - Ambulatory"]}).json()
    assert job["status"] == "open" and job["must_have_skills"] == ["Epic Ambulatory"]

    cand = c.post(f"{A}/candidates", json={"first_name": "Ana", "last_name": "Silva", "email": "ana@example.com",
                                           "systems": ["Epic Ambulatory"]}).json()
    app_ = c.post(f"{A}/applications", json={"candidate_id": cand["id"], "job_id": job["id"]}).json()

    pipelines = c.get(f"{A}/pipelines").json()
    stages = pipelines[0]["stages"]
    assert [s["name"] for s in stages][:3] == ["New", "Screening", "Submitted to Client"]
    assert app_["stage_id"] == stages[0]["id"]   # defaults to the first stage

    placed = next(s for s in stages if s["stage_type"] == "placed")
    moved = c.patch(f"{A}/applications/{app_['id']}", json={"stage_id": placed["id"]}).json()
    assert moved["placed_at"] is not None

    listed = c.get(f"{A}/applications", params={"job_id": job["id"]}).json()
    assert listed[0]["stage_name"] == "Placed" and listed[0]["first_name"] == "Ana"

    iv = c.post(f"{A}/interviews", json={"application_id": app_["id"], "interview_type": "video"}).json()
    fb = c.post(f"{A}/interview-feedback", json={
        "application_id": app_["id"], "interview_id": iv["id"], "from_contact_id": contact["id"],
        "overall_rating": 4, "recommendation": "yes",
        "scorecard": [{"criterion": "Epic build", "rating": 5}, {"criterion": "Communication", "rating": 4}]})
    assert fb.status_code == 201 and fb.json()["scorecard"][0]["criterion"] == "Epic build"

    # duplicate candidate email → 409
    assert c.post(f"{A}/candidates", json={"first_name": "X", "email": "ana@example.com"}).status_code == 409
    # unknown fields are rejected, not silently written
    assert c.post(f"{A}/candidates", json={"first_name": "X", "tenant_id": TENANT_B}).status_code == 422


def test_custom_pipeline_and_reorder(api_client):
    c = api_client
    default = c.get(f"{A}/pipelines").json()[0]
    new = c.post(f"{A}/pipelines", params={"copy_from": default["id"]}, json={"name": "Contract fast-track"}).json()
    stages = c.get(f"{A}/stages", params={"pipeline_id": new["id"]}).json()
    assert len(stages) == 8
    reordered = list(reversed([s["id"] for s in sorted(stages, key=lambda s: s["position"])]))
    out = c.put(f"{A}/pipelines/{new['id']}/stage-order", json={"stage_ids": reordered}).json()
    assert [s["id"] for s in out] == reordered
    assert c.put(f"{A}/pipelines/{new['id']}/stage-order", json={"stage_ids": reordered[:3]}).status_code == 422
    renamed = c.patch(f"{A}/stages/{reordered[0]}", json={"name": "Shortlist", "color": "#123456"}).json()
    assert renamed["name"] == "Shortlist"


def test_saved_views(api_client):
    c = api_client
    v = c.post(f"{A}/views", json={"entity": "candidates", "name": "Epic analysts", "layout": "board",
                                    "config": {"filters": {"systems": "Epic"}, "columns": ["name", "stage"]}}).json()
    assert v["config"]["columns"] == ["name", "stage"]
    assert any(x["id"] == v["id"] for x in c.get(f"{A}/views", params={"entity": "candidates"}).json())


def test_publish_job(api_client):
    c = api_client
    job = c.post(f"{A}/jobs", json={"title": "Cerner Analyst"}).json()
    pub = c.post(f"{A}/jobs/{job['id']}/publish").json()
    assert pub["is_published"] and pub["published_at"]


def test_tenant_isolation(api_client):
    c = api_client
    c.post(f"{A}/clients", json={"name": "Only OnPoint sees this"})
    # User A asking for tenant B's data gets nothing (RLS), and cannot write there.
    assert c.get(f"/tenants/{TENANT_B}/clients").json() == []
    assert c.post(f"/tenants/{TENANT_B}/clients", json={"name": "x"}).status_code >= 400


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def parsed(first, last, email):
    return json.dumps({"first_name": first, "last_name": last, "email": email, "current_title": "Epic Analyst",
                       "skills": ["SQL"], "systems": ["Epic Beaker"], "certifications": [], "confidence": 0.9})


def test_single_resume_upload_links_to_job(api_client):
    c = api_client
    fake = FakeProvider([parsed("Raj", "Patel", "raj@example.com")])
    c.app.dependency_overrides[uploads.llm_dep] = lambda: fake
    job = c.post(f"{A}/jobs", json={"title": "Beaker Analyst"}).json()
    r = c.post(f"{A}/candidates/upload", files={"file": ("Raj Patel CV.txt", b"Raj Patel raj@example.com Epic Beaker")},
               data={"job_id": job["id"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] and body["candidate"]["systems"] == ["Epic Beaker"] and body["document"]["is_primary"]
    assert c.get(f"{A}/applications", params={"job_id": job["id"]}).json()[0]["first_name"] == "Raj"


def test_bulk_import_zip_and_csv(api_client):
    c = api_client
    # LLM is called once per resume, in file order of the plan (CSV rows first, then leftover files)
    fake = FakeProvider([parsed("Wrong", "Name", "lee.parsed@example.com"),
                         parsed("Kim", "Nguyen", "kim@example.com")])
    c.app.dependency_overrides[uploads.llm_dep] = lambda: fake
    z = make_zip({"resumes/Lee_Wong_Resume_2026.txt": b"Lee Wong resume", "Kim Nguyen.txt": b"Kim resume",
                  "logo.png": b"x"})
    csv_data = b"First Name,Last Name,Email,Phone\nLee,Wong,lee@example.com,604-555-0100\nNo,Resume,nores@example.com,\n"
    r = c.post(f"{A}/candidates/bulk-import", files={"zip_file": ("batch.zip", z), "csv_file": ("c.csv", csv_data)})
    assert r.status_code == 202, r.text
    started = r.json()
    assert started["status"] == "processing" and started["total"] == 3 and started["skipped"] == 1
    out = wait_for_import(c, started["batch_id"])
    assert out["status"] == "completed_with_errors"   # the skipped logo.png counts as an issue
    assert (out["created_count"], out["updated_count"], out["error_count"]) == (3, 0, 1)
    assert any(i["id"] == started["batch_id"] for i in c.get(f"{A}/candidates/imports").json())
    by_item = {x.get("item"): x for x in out["report"]}
    lee = by_item["Lee_Wong_Resume_2026.txt"]
    assert lee["match"] == "fuzzy" and lee["status"] == "created"
    assert by_item["No Resume"]["warnings"] == ["no resume"]
    assert by_item["Kim Nguyen.txt"]["match"] == "resume_only"
    # CSV values win over what the model parsed
    cands = {x["email"]: x for x in c.get(f"{A}/candidates").json()}
    assert cands["lee@example.com"]["first_name"] == "Lee" and cands["lee@example.com"]["phone"] == "604-555-0100"
    assert "lee.parsed@example.com" not in cands


def wait_for_import(c, batch_id, timeout=20):
    import time
    end = time.time() + timeout
    while time.time() < end:
        b = c.get(f"{A}/candidates/imports/{batch_id}").json()
        if b["status"] != "processing":
            return b
        time.sleep(0.1)
    raise AssertionError("import didn't finish")


def test_bulk_import_progress_is_saved_row_by_row(api_client):
    """A failing resume doesn't lose the ones already done, and progress is visible while it runs."""
    c = api_client
    fake = FakeProvider([parsed("Una", "One", "una@example.com"), "not json", parsed("Tre", "Three", "tre@example.com")])
    c.app.dependency_overrides[uploads.llm_dep] = lambda: fake
    z = make_zip({"a_Una.txt": b"Una", "b_Bad.txt": b"Bad", "c_Tre.txt": b"Tre"})
    started = c.post(f"{A}/candidates/bulk-import", files={"zip_file": ("z.zip", z)}).json()
    out = wait_for_import(c, started["batch_id"])
    assert (out["created_count"], out["error_count"], out["status"]) == (2, 1, "completed_with_errors")
    errs = [r for r in out["report"] if r["status"] == "error"]
    assert errs and "couldn't be read" in errs[0]["error"]
    assert c.post(f"{A}/candidates/bulk-import", files={"zip_file": ("x.zip", b"not a zip")}).status_code == 422


def test_bulk_import_counts_are_right_when_run_in_parallel(api_client, monkeypatch):
    c = api_client
    monkeypatch.setenv("BULK_IMPORT_CONCURRENCY", "4")
    from app.config import get_settings
    get_settings.cache_clear()
    names = [f"Par{i}" for i in range(12)]

    class Slow(FakeProvider):
        async def complete(self, system, user, max_tokens=2000):
            import asyncio
            await asyncio.sleep(0.05)
            n = user.split("Resume text:")[-1].strip()
            from app.llm import LLMResult
            return LLMResult(text=parsed(n, "X", f"{n.lower()}@example.com"), provider="fake", model="fake")

    c.app.dependency_overrides[uploads.llm_dep] = lambda: Slow([])
    z = make_zip({f"{n}.txt": n.encode() for n in names})
    out = wait_for_import(c, c.post(f"{A}/candidates/bulk-import", files={"zip_file": ("p.zip", z)}).json()["batch_id"])
    assert (out["created_count"], out["error_count"], out["status"]) == (12, 0, "completed")


def test_reimport_merges_instead_of_duplicating(api_client):
    c = api_client
    c.post(f"{A}/candidates", json={"first_name": "Sam", "email": "sam@example.com", "skills": ["HL7"]})
    fake = FakeProvider([json.dumps({"first_name": "Sam", "last_name": "Ortiz", "email": "sam@example.com",
                                     "phone": "778", "skills": ["FHIR"], "confidence": 0.8})])
    c.app.dependency_overrides[uploads.llm_dep] = lambda: fake
    body = c.post(f"{A}/candidates/upload", files={"file": ("sam.txt", b"Sam")}).json()
    assert body["created"] is False
    assert body["candidate"]["last_name"] == "Ortiz" and sorted(body["candidate"]["skills"]) == ["FHIR", "HL7"]
