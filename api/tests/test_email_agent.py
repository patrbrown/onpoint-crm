"""Email agent tests: a fake Outlook mailbox + a scripted fake LLM, against the real schema with RLS."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import pytest
from conftest import TENANT_A, USER_A

from app.agent import email_agent
from app.agent.email_agent import scan_account
from app.llm import FakeProvider
from app.routers import inbox
from app.services.graph import Attachment, Message, parse_message
from app.services.storage import LocalStorage

A = f"/tenants/{TENANT_A}"
NOW = datetime.now(timezone.utc)


class FakeMailbox:
    def __init__(self, messages):
        self.messages = messages

    async def new_messages(self, since, limit=100):
        return [m for m in self.messages if since is None or m.received_at > since]


def msg(i, subject, body, sender=("hm@fraserhealth-demo.ca", "Dana Leung"), atts=(), minutes_ago=60):
    return Message(id=f"m{i}", internet_message_id=f"<m{i}@x>", conversation_id=f"c{i}", subject=subject,
                   from_address=sender[0], from_name=sender[1], to=["patty@onpoint.example"],
                   received_at=NOW - timedelta(minutes=minutes_ago), body_text=body, has_attachments=bool(atts),
                   attachments=list(atts))


def cls(kind, conf=0.95):
    return json.dumps({"classification": kind, "confidence": conf, "reason": "test"})


JOB = json.dumps({"title": "Epic Willow Pharmacy Analyst", "client_name": "Fraser Health Demo", "reference_code": "FH-555",
                  "hiring_contact": {"name": "Dana Leung", "email": "hm@fraserhealth-demo.ca", "phone": "604-555-0001"},
                  "description": "Build Willow", "employment_type": "contract", "rate_min": "90", "rate_max": 110,
                  "rate_unit": "hour", "currency": "cad", "work_model": "hybrid", "must_have_skills": ["Willow build"],
                  "systems": ["Epic Willow"], "certifications": [], "confidence": 0.9})


def resume(first, last, email, conf=0.95):
    return json.dumps({"first_name": first, "last_name": last, "email": email, "phone": "778-555-0100",
                       "current_title": "Pharmacy Analyst", "systems": ["Epic Willow"], "skills": [], "certifications": [],
                       "confidence": conf})


async def _conn(db):
    conn = await asyncpg.connect(db)
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    return conn


def run_scan(db, tmp_path, messages, responses, *, mode="review"):
    async def go():
        conn = await _conn(db)
        try:
            await conn.execute("update public.tenant_settings set inbox_mode = $2, auto_approve_threshold = 0.9 "
                               "where tenant_id = $1", UUID(TENANT_A), mode)
            acct = await conn.fetchrow(
                """insert into public.mail_accounts (tenant_id, mailbox_address) values ($1, 'patty@onpoint.example')
                   on conflict (tenant_id, mailbox_address) do update set is_enabled = true returning *""", UUID(TENANT_A))
            llm = FakeProvider(responses)
            r = await scan_account(conn, LocalStorage(str(tmp_path / "storage")), llm, FakeMailbox(messages), acct)
            return r, llm
        finally:
            await conn.close()
    return asyncio.run(go())


@pytest.fixture
def fresh_mail(database):
    async def wipe():
        conn = await _conn(database)
        await conn.execute("delete from public.mail_accounts; delete from public.ai_feedback; "
                           "update public.tenant_settings set inbox_mode = 'review'")
        await conn.close()
    asyncio.run(wipe())
    email_agent._attempts.clear()
    yield database


def test_parse_graph_message_html():
    m = parse_message({"id": "1", "subject": "Hi", "from": {"emailAddress": {"address": "A@B.com", "name": "A"}},
                       "receivedDateTime": "2026-10-29T10:00:00Z", "hasAttachments": False,
                       "body": {"contentType": "html", "content": "<p>Hello&nbsp;there</p><br><style>x{}</style>Bye"}})
    assert m.from_address == "a@b.com" and "Hello there" in m.body_text and "x{}" not in m.body_text


def test_review_flow_job_resume_feedback(api_client, fresh_mail, tmp_path):
    db, c = fresh_mail, api_client
    messages = [
        msg(1, "New req: Epic Willow Pharmacy Analyst (FH-555)", "We need a Willow analyst, contract, $90-110/hr."),
        msg(2, "Our weekly newsletter", "Read all about it", sender=("news@vendor.example", "Vendor")),
    ]
    r, llm = run_scan(db, tmp_path, messages, [cls("job_requisition"), JOB, cls("other")])
    assert (r.new, r.queued, r.ignored, r.auto_approved) == (2, 1, 1, 0)

    # Rescanning the same emails does nothing (dedupe), even with no LLM responses scripted.
    r2, _ = run_scan(db, tmp_path, messages, [])
    assert r2.new == 0

    pending = c.get(f"{A}/inbox").json()
    assert pending["ignored_emails"] == 1
    item = pending["items"][0]
    assert item["item_type"] == "job_requisition" and item["subject"].startswith("New req")
    detail = c.get(f"{A}/inbox/{item['id']}").json()
    assert detail["email"]["body_text"].startswith("We need")

    # Approve with one correction: client is created, the sender becomes the hiring contact, job saved.
    final = {**json.loads(JOB), "title": "Epic Willow Inpatient Pharmacy Analyst"}
    res = c.post(f"{A}/inbox/{item['id']}/approve", json={"final": final, "links": {}}).json()
    job = c.get(f"{A}/jobs/{res['entity_id']}").json()
    assert job["title"] == "Epic Willow Inpatient Pharmacy Analyst" and job["source"] == "email"
    assert float(job["rate_min"]) == 90 and job["currency"] == "CAD" and job["systems"] == ["Epic Willow"]
    contact = c.get(f"{A}/contacts/{job['hiring_contact_id']}").json()
    assert contact["email"] == "hm@fraserhealth-demo.ca" and contact["first_name"] == "Dana"
    assert c.post(f"{A}/inbox/{item['id']}/approve", json={"final": final}).status_code == 409   # only once

    # A resume for that job arrives: it's matched to the job by title in the subject.
    att = Attachment("Lee_Wong_Resume.txt", "text/plain", b"Lee Wong\nlee.wong@example.com\nEpic Willow analyst")
    r3, _ = run_scan(db, tmp_path, [msg(3, "Lee Wong for Epic Willow Inpatient Pharmacy Analyst", "See attached",
                                        sender=("lee.wong@example.com", "Lee Wong"), atts=[att], minutes_ago=30)],
                     [cls("resume"), resume("Lee", "Wong", "lee.wong@example.com")])
    assert r3.queued == 1
    item = c.get(f"{A}/inbox").json()["items"][0]
    jobs = [m for m in item["suggested_matches"] if m["type"] == "job"]
    assert jobs and jobs[0]["id"] == job["id"]
    res = c.post(f"{A}/inbox/{item['id']}/approve",
                 json={"final": item["extracted"], "links": {"job_id": job["id"]}, "comment": "good"}).json()
    cand_id = res["entity_id"]
    docs = c.get(f"{A}/candidates/{cand_id}/documents").json()
    assert docs[0]["file_name"] == "Lee_Wong_Resume.txt" and docs[0]["is_primary"]
    apps = c.get(f"{A}/applications", params={"job_id": job["id"]}).json()
    assert apps[0]["first_name"] == "Lee"

    # Interview feedback from the client is matched to that application.
    fb = json.dumps({"candidate_name": "Lee Wong", "job_title": "Willow Pharmacy Analyst", "overall_rating": 4,
                     "recommendation": "yes", "scorecard": [{"criterion": "Willow build", "rating": 5}],
                     "strengths": "Strong build", "concerns": None, "notes": "Next round Tuesday", "confidence": 0.9})
    run_scan(db, tmp_path, [msg(4, "Re: Lee Wong", "Lee was great, let's move forward", minutes_ago=10)],
             [cls("interview_feedback"), fb])
    item = c.get(f"{A}/inbox").json()["items"][0]
    app_match = [m for m in item["suggested_matches"] if m["type"] == "application"][0]
    assert app_match["id"] == apps[0]["id"]
    assert c.post(f"{A}/inbox/{item['id']}/approve", json={"final": item["extracted"]}).status_code == 422  # no link
    c.post(f"{A}/inbox/{item['id']}/approve", json={"final": item["extracted"], "links": {"application_id": app_match["id"]}})
    feedback = c.get(f"{A}/interview-feedback", params={"application_id": apps[0]["id"]}).json()
    assert feedback[0]["recommendation"] == "yes" and feedback[0]["scorecard"][0]["rating"] == 5
    assert feedback[0]["from_contact_id"] == contact["id"]   # the client contact is linked

    done = c.get(f"{A}/inbox", params={"status": "done"}).json()["items"]
    assert len(done) == 3


def test_auto_mode_saves_confident_items_and_holds_the_rest(api_client, fresh_mail, tmp_path):
    db, c = fresh_mail, api_client
    a1 = Attachment("Priya_Shah_CV.txt", "text/plain", b"Priya Shah priya@example.com")
    a2 = Attachment("Theo_Grant_CV.txt", "text/plain", b"Theo Grant")
    r, _ = run_scan(db, tmp_path, [
        msg(10, "Resume", "attached", sender=("priya@example.com", "Priya Shah"), atts=[a1], minutes_ago=50),
        msg(11, "Resume", "attached", sender=("theo@example.com", "Theo Grant"), atts=[a2], minutes_ago=40),
    ], [cls("resume", 0.97), resume("Priya", "Shah", "priya@example.com", 0.96),
        cls("resume", 0.97), resume("Theo", "Grant", None, 0.6)], mode="auto")
    assert (r.auto_approved, r.queued) == (1, 1)     # Theo's extraction wasn't confident enough
    cands = {x["first_name"]: x for x in c.get(f"{A}/candidates").json()}
    assert cands["Priya"]["source"] == "email"
    assert "Theo" not in cands
    pending = c.get(f"{A}/inbox").json()["items"]
    assert [p["extracted"]["first_name"] for p in pending] == ["Theo"]
    # Theo's email: the sender's name matches the resume, so his address was filled in.
    assert pending[0]["extracted"]["email"] == "theo@example.com"


def test_wrong_type_feedback_reprocesses_and_teaches(api_client, fresh_mail, tmp_path):
    db, c = fresh_mail, api_client
    run_scan(db, tmp_path, [msg(20, "Fwd: req for Cerner analyst", "Client wants a Cerner analyst", minutes_ago=5)],
             [cls("resume"), resume("Cerner", "Analyst", None, 0.4)])
    item = c.get(f"{A}/inbox").json()["items"][0]
    fake = FakeProvider([json.dumps({"title": "Cerner Analyst", "client_name": None, "confidence": 0.8})])
    c.app.dependency_overrides[inbox.llm_dep] = lambda: fake
    r = c.post(f"{A}/inbox/{item['id']}/reject", json={"reason": "wrong_type", "correct_type": "job_requisition",
                                                       "comment": "Forwards from Marc are job reqs"}).json()
    assert len(r["new_items"]) == 1
    new = c.get(f"{A}/inbox/{r['new_items'][0]}").json()["item"]
    assert new["item_type"] == "job_requisition" and new["extracted"]["title"] == "Cerner Analyst"

    # The correction is now part of the classification prompt for the next email.
    _, llm = run_scan(db, tmp_path, [msg(21, "Another", "x", sender=("news@vendor.example", "V"), minutes_ago=1)],
                      [cls("other")])
    system_prompt = llm.calls[0][0]
    assert "Past corrections" in system_prompt and "job_requisition" in system_prompt
    assert "Forwards from Marc are job reqs" in system_prompt


def test_ignored_email_can_be_reprocessed(api_client, fresh_mail, tmp_path):
    db, c = fresh_mail, api_client
    run_scan(db, tmp_path, [msg(30, "Quick one", "Can you find me a Meditech analyst?", minutes_ago=3)], [cls("other")])
    ignored = c.get(f"{A}/inbox/ignored").json()
    assert ignored[0]["subject"] == "Quick one"
    fake = FakeProvider([json.dumps({"title": "Meditech Analyst", "confidence": 0.7})])
    c.app.dependency_overrides[inbox.llm_dep] = lambda: fake
    r = c.post(f"{A}/inbox/emails/{ignored[0]['id']}/reprocess",
               json={"reason": "wrong_type", "correct_type": "job_requisition"}).json()
    assert len(r["new_items"]) == 1


def test_failing_email_is_retried_then_skipped(api_client, fresh_mail, tmp_path):
    db = fresh_mail
    m = [msg(40, "Broken", "x", minutes_ago=20), msg(41, "Fine", "y", minutes_ago=10)]
    bad = "not json at all"
    r1, _ = run_scan(db, tmp_path, m, [bad])            # attempt 1: stops, nothing skipped
    assert (r1.errors, r1.new) == (1, 0)
    run_scan(db, tmp_path, m, [bad])                    # attempt 2
    r3, _ = run_scan(db, tmp_path, m, [bad, cls("other")])  # attempt 3: gives up on "Broken", continues to "Fine"
    assert r3.errors == 1 and r3.new == 1
    ignored = api_client.get(f"{A}/inbox/ignored").json()
    assert any(e["subject"] == "Broken" and e["error"] for e in ignored)


def test_null_characters_dont_block_the_inbox(api_client, fresh_mail, tmp_path):
    """Some PDFs (e.g. receipts) and emails contain \\x00, which Postgres refuses to store."""
    att = Attachment("Receipt-2751-9811.txt", "text/plain", b"Receipt\x00 total $10\x00")
    m = msg(90, "Your receipt from OpenRouter\x00", "Thanks\x00 for your purchase", atts=[att], minutes_ago=1)
    r, _ = run_scan(fresh_mail, tmp_path, [m], [cls("other")])
    assert (r.errors, r.new, r.ignored) == (0, 1, 1)
    ignored = api_client.get(f"{A}/inbox/ignored").json()
    assert ignored[0]["subject"] == "Your receipt from OpenRouter"

    # and if the AI echoes a null back in its extraction, it's stripped too
    att2 = Attachment("cv.txt", "text/plain", b"Nul\x00 Person")
    r2, _ = run_scan(fresh_mail, tmp_path, [msg(91, "cv", "attached", atts=[att2], minutes_ago=0)],
                     [cls("resume"), json.dumps({"first_name": "Nul\u0000", "email": "nul@example.com"})])
    assert r2.errors == 0 and r2.queued == 1


def test_files_are_only_stored_for_recruiting_email(api_client, fresh_mail, tmp_path):
    receipt = Attachment("receipt.txt", "text/plain", b"Receipt total $10")
    resume_file = Attachment("Mia_Cho_Resume.txt", "text/plain", b"Mia Cho mia@example.com Epic Cupid")
    run_scan(fresh_mail, tmp_path, [
        msg(95, "Your receipt", "thanks", sender=("billing@vendor.example", "Vendor"), atts=[receipt], minutes_ago=3),
        msg(96, "My resume", "attached", sender=("mia@example.com", "Mia Cho"), atts=[resume_file], minutes_ago=2),
    ], [cls("other"), cls("resume"), json.dumps({"first_name": "Mia", "last_name": "Cho", "email": "mia@example.com"})])

    async def rows():
        conn = await _conn(fresh_mail)
        r = await conn.fetch("select file_name, storage_path, extracted_text from public.email_attachments order by file_name")
        await conn.close()
        return {x["file_name"]: x for x in r}
    r = asyncio.run(rows())
    assert r["receipt.txt"]["storage_path"] is None and "Receipt" in r["receipt.txt"]["extracted_text"]
    assert r["Mia_Cho_Resume.txt"]["storage_path"]
    assert not list((tmp_path / "storage").rglob("receipt.txt"))


def test_correcting_a_skipped_email_fetches_its_file_from_outlook(api_client, fresh_mail, tmp_path):
    from app.routers import inbox

    cv = Attachment("Leo_Park_CV.txt", "text/plain", b"Leo Park leo@example.com")
    run_scan(fresh_mail, tmp_path, [msg(97, "fwd", "fyi", atts=[cv], minutes_ago=1)], [cls("other")])

    class FakeGraph:
        def __init__(self, key): pass
        async def _attachments(self, client, message_id):
            assert message_id == "m97"
            return [cv]

    c = api_client
    c.app.dependency_overrides[inbox.llm_dep] = lambda: FakeProvider(
        [json.dumps({"first_name": "Leo", "last_name": "Park", "email": "leo@example.com"})])
    original = inbox.mailbox_factory
    inbox.mailbox_factory = lambda: FakeGraph
    try:
        email = c.get(f"{A}/inbox/ignored").json()[0]
        out = c.post(f"{A}/inbox/emails/{email['id']}/reprocess", json={"reason": "wrong_type", "correct_type": "resume"}).json()
    finally:
        inbox.mailbox_factory = original
    item = c.get(f"{A}/inbox/{out['new_items'][0]}").json()
    assert item["item"]["extracted"]["first_name"] == "Leo"
    res = c.post(f"{A}/inbox/{item['item']['id']}/approve", json={"final": item["item"]["extracted"]}).json()
    docs = c.get(f"{A}/candidates/{res['entity_id']}/documents").json()
    assert docs and docs[0]["file_name"] == "Leo_Park_CV.txt"
