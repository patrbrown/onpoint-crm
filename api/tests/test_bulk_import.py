import io
import zipfile

from app.services import bulk_import as bi


def make_zip(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in names:
            zf.writestr(n, f"Resume of {n}\nemail: x@y.com")
    return buf.getvalue()


def test_read_zip_skips_junk_and_unsupported():
    files, skipped = bi.read_zip(make_zip(["a/Jane_Doe_Resume.pdf", "__MACOSX/._x.pdf", ".DS_Store", "photo.jpg"]))
    assert [f.name for f in files] == ["Jane_Doe_Resume.pdf"]
    assert skipped == [{"file": "photo.jpg", "reason": "unsupported file type"}]


def test_csv_header_normalisation_and_full_name_split():
    rows = bi.read_csv(b"\xef\xbb\xbfFull Name,E-mail,Phone Number,LinkedIn Profile\nMaria de la Cruz,m@x.com,604,li\n")
    assert rows == [{"first_name": "Maria", "last_name": "de la Cruz", "email": "m@x.com", "phone": "604",
                     "linkedin_url": "li"}]


def test_exact_match_by_file_column():
    files, _ = bi.read_zip(make_zip(["cv_0042.docx", "Other.pdf"]))
    plan = bi.plan_import(files, [{"first_name": "Ana", "resume_file": "cv_0042"}], parse_unmatched=False)
    assert plan.rows[0].match == "exact" and plan.rows[0].resume.name == "cv_0042.docx"
    assert plan.skipped_files == [{"file": "Other.pdf", "reason": "no matching CSV row"}]


def test_fuzzy_name_match_strips_noise():
    files, _ = bi.read_zip(make_zip(["JaneDoe_Resume_2026_final.pdf", "John-Smith CV v3.docx"]))
    plan = bi.plan_import(files, [{"first_name": "Jane", "last_name": "Doe"},
                                  {"first_name": "John", "last_name": "Smith"}])
    assert [(r.match, r.resume.name) for r in plan.rows] == [
        ("fuzzy", "JaneDoe_Resume_2026_final.pdf"), ("fuzzy", "John-Smith CV v3.docx")]


def test_name_order_reversed_still_matches():
    files, _ = bi.read_zip(make_zip(["Doe, Jane.pdf"]))
    plan = bi.plan_import(files, [{"first_name": "Jane", "last_name": "Doe"}])
    assert plan.rows[0].match == "fuzzy"


def test_ambiguous_match_is_not_guessed():
    files, _ = bi.read_zip(make_zip(["Jane Doe.pdf", "Jane Doe (1).pdf"]))
    plan = bi.plan_import(files, [{"first_name": "Jane", "last_name": "Doe"}], parse_unmatched=False)
    assert plan.rows[0].resume is None
    assert any("ambiguous" in w for w in plan.rows[0].warnings)


def test_unmatched_rows_and_files_are_reported():
    files, _ = bi.read_zip(make_zip(["Somebody Else.pdf"]))
    plan = bi.plan_import(files, [{"first_name": "Jane", "last_name": "Doe"}])
    assert plan.rows[0].warnings == ["no resume"]
    assert plan.rows[1].match == "resume_only" and plan.rows[1].resume.name == "Somebody Else.pdf"
