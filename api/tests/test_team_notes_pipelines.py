import json

from conftest import TENANT_A

from app.llm import FakeProvider
from app.routers import uploads

A = f"/tenants/{TENANT_A}"


def parsed(first, email):
    return json.dumps({"first_name": first, "last_name": "Test", "email": email, "skills": [], "confidence": 0.9})


def test_team_members_and_uploaded_by(api_client):
    c = api_client
    team = c.get(f"{A}/team").json()
    me = next(m for m in team if m["is_me"])
    assert me["has_login"] and me["role"] == "owner"
    jo = c.post(f"{A}/team", json={"full_name": "Jo Recruiter", "email": "jo@example.com", "title": "Recruiter"}).json()
    assert not jo["has_login"]
    assert c.post(f"{A}/team", json={"full_name": "Dup", "email": "jo@example.com"}).status_code == 409
    assert c.patch(f"{A}/team/{me['id']}", json={"full_name": "Patty Brown"}).json()["full_name"] == "Patty Brown"
    assert c.patch(f"{A}/team/{me['id']}", json={"is_active": False}).status_code == 422

    # Upload tagged with Jo; default (no tag) is me.
    c.app.dependency_overrides[uploads.llm_dep] = lambda: FakeProvider([parsed("Tag", "tag@example.com"),
                                                                        parsed("Mine", "mine@example.com")])
    r = c.post(f"{A}/candidates/upload", files={"file": ("tag.txt", b"Tag")}, data={"uploaded_by": jo["id"]}).json()
    docs = c.get(f"{A}/candidates/{r['candidate']['id']}/documents").json()
    assert docs[0]["uploaded_by_name"] == "Jo Recruiter"
    r2 = c.post(f"{A}/candidates/upload", files={"file": ("mine.txt", b"Mine")}).json()
    assert c.get(f"{A}/candidates/{r2['candidate']['id']}/documents").json()[0]["uploaded_by_name"] == "Patty Brown"
    assert c.post(f"{A}/candidates/upload", files={"file": ("x.txt", b"x")},
                  data={"uploaded_by": "00000000-0000-0000-0000-000000000999"}).status_code == 422

    # Removing a member hides them from the list but keeps the history.
    c.patch(f"{A}/team/{jo['id']}", json={"is_active": False})
    assert all(m["id"] != jo["id"] for m in c.get(f"{A}/team").json())
    assert any(m["id"] == jo["id"] for m in c.get(f"{A}/team", params={"include_inactive": True}).json())


def test_upload_to_a_chosen_candidate_becomes_their_resume(api_client):
    c = api_client
    cand = c.post(f"{A}/candidates", json={"first_name": "Rae", "email": "rae@example.com"}).json()
    c.post(f"{A}/candidates", json={"first_name": "Other", "email": "other@example.com"})
    # The resume carries someone else's email: it still goes to Rae, without taking that email.
    c.app.dependency_overrides[uploads.llm_dep] = lambda: FakeProvider([parsed("Rae", "rae@example.com"),
                                                                        parsed("Rae", "other@example.com")])
    c.post(f"{A}/candidates/upload", files={"file": ("rae1.txt", b"one")}, data={"candidate_id": cand["id"]})
    r = c.post(f"{A}/candidates/upload", files={"file": ("rae2.txt", b"two")}, data={"candidate_id": cand["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["candidate"]["id"] == cand["id"] and r.json()["candidate"]["email"] == "rae@example.com"
    docs = c.get(f"{A}/candidates/{cand['id']}/documents").json()
    assert [d["file_name"] for d in docs] == ["rae2.txt", "rae1.txt"] and docs[0]["is_primary"] and not docs[1]["is_primary"]


def test_notes_have_author_and_can_be_edited_and_deleted(api_client):
    c = api_client
    team = c.get(f"{A}/team").json()
    me = next(m for m in team if m["is_me"])
    c.patch(f"{A}/team/{me['id']}", json={"full_name": "Patty Brown"})
    cand = c.post(f"{A}/candidates", json={"first_name": "Noa"}).json()
    n = c.post(f"{A}/activities", json={"kind": "note", "body": "Called, interested", "candidate_id": cand["id"]}).json()
    assert n["author_name"] == "Patty Brown" and n["can_edit"] and n["updated_at"] is None
    same = c.patch(f"{A}/activities/{n['id']}", json={"body": "Called, interested"}).json()
    assert same["updated_at"] is None                        # nothing changed → not marked edited
    e = c.patch(f"{A}/activities/{n['id']}", json={"body": "Called, very interested", "kind": "call"}).json()
    assert e["body"] == "Called, very interested" and e["kind"] == "call" and e["editor_name"] == "Patty Brown"
    assert c.get(f"{A}/activities", params={"candidate_id": cand["id"]}).json()[0]["updated_at"]
    assert c.delete(f"{A}/activities/{n['id']}").status_code == 200
    assert c.get(f"{A}/activities", params={"candidate_id": cand["id"]}).json() == []


def test_job_pipeline_can_be_customized_and_reset(api_client):
    c = api_client
    shared = c.get(f"{A}/pipelines").json()[0]
    job = c.post(f"{A}/jobs", json={"title": "Willow Analyst"}).json()
    cand = c.post(f"{A}/candidates", json={"first_name": "Ivy"}).json()
    app_ = c.post(f"{A}/applications", json={"candidate_id": cand["id"], "job_id": job["id"]}).json()
    screening = next(s for s in shared["stages"] if s["name"] == "Screening")
    c.patch(f"{A}/applications/{app_['id']}", json={"stage_id": screening["id"]})

    p = c.get(f"{A}/jobs/{job['id']}/pipeline").json()
    assert p["id"] == shared["id"] and not p["is_custom"]
    own = c.post(f"{A}/jobs/{job['id']}/pipeline/customize").json()
    assert own["is_custom"] and own["id"] != shared["id"] and len(own["stages"]) == len(shared["stages"])
    assert all(x["id"] != own["id"] for x in c.get(f"{A}/pipelines").json())    # not in the shared list
    # The candidate followed to the copied "Screening" stage.
    a = c.get(f"{A}/applications", params={"job_id": job["id"]}).json()[0]
    own_screening = next(s for s in own["stages"] if s["name"] == "Screening")
    assert a["stage_id"] == own_screening["id"]

    # Add a stage for this job only; the shared pipeline is untouched.
    c.post(f"{A}/stages", json={"pipeline_id": own["id"], "name": "Client tech test", "position": len(own["stages"]) + 1})
    assert len(c.get(f"{A}/jobs/{job['id']}/pipeline").json()["stages"]) == len(shared["stages"]) + 1
    assert len(c.get(f"{A}/pipelines").json()[0]["stages"]) == len(shared["stages"])

    # Removing a stage with a candidate in it needs a destination.
    assert c.delete(f"{A}/stages/{own_screening['id']}").status_code == 409
    first = own["stages"][0]
    r = c.delete(f"{A}/stages/{own_screening['id']}", params={"move_to": first["id"]})
    assert r.status_code == 200 and r.json()["moved"] == 1
    after = c.get(f"{A}/jobs/{job['id']}/pipeline").json()["stages"]
    assert [s["position"] for s in after] == list(range(1, len(after) + 1))
    assert c.get(f"{A}/applications", params={"job_id": job["id"]}).json()[0]["stage_id"] == first["id"]

    back = c.post(f"{A}/jobs/{job['id']}/pipeline/reset", json={}).json()
    assert back["id"] == shared["id"] and not back["is_custom"]
    assert c.get(f"{A}/applications", params={"job_id": job["id"]}).json()[0]["stage_id"] == shared["stages"][0]["id"]
