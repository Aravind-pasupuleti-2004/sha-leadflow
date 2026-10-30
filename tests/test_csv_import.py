from __future__ import annotations

import io

from sqlalchemy import func

from app.extensions import db
from app.models import Lead

HEADER = "name,phone,email,locality,property_type,project_type,budget_min,budget_max,expected_start,requirements,source,status\r\n"


def csv_bytes(*rows: str) -> io.BytesIO:
    return io.BytesIO((HEADER + "\r\n".join(rows) + "\r\n").encode("utf-8"))


def upload(client, content: io.BytesIO, filename="leads.csv"):
    return client.post(
        "/leads/import",
        data={"csv_file": (content, filename)},
        content_type="multipart/form-data",
    )


def test_csv_import_creates_valid_rows(auth_client):
    content = csv_bytes(
        'Ananya Fictional,9000000101,ananya.fictional@example.com,Indiranagar,Apartment,Full Home Interiors,800000,1200000,2026-12-15,"3BHK, ready to start",Website,New',
        'Rohan Fictional,9000000102,rohan.fictional@example.com,Whitefield,Villa,Full Home Interiors,2000000,3000000,2027-02-01,"Villa interiors",Referral,New',
    )
    response = upload(auth_client, content)
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "2 leads imported" in text
    assert db.session.scalar(db.select(func.count(Lead.id))) == 2
    lead = db.session.scalars(
        db.select(Lead).where(Lead.email == "ananya.fictional@example.com")
    ).one()
    assert lead.normalized_phone == "9000000101"
    assert lead.score > 0
    assert lead.expected_start.isoformat() == "2026-12-15"


def test_csv_import_skips_duplicate_inside_file(auth_client):
    content = csv_bytes(
        'Ananya Fictional,9000000101,ananya.fictional@example.com,Indiranagar,Apartment,Full Home Interiors,800000,1200000,,Ready,Website,New',
        'Ananya Duplicate,9000000103,ANANYA.FICTIONAL@example.com,Indiranagar,Apartment,Full Home Interiors,800000,1200000,,Ready,Website,New',
    )
    response = upload(auth_client, content)
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Skipped duplicate" in text
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1


def test_csv_import_skips_existing_duplicate(auth_client, make_lead):
    make_lead(phone="9000000201", email="existing@example.com")
    content = csv_bytes(
        'Existing Again,9000000202,existing@example.com,,,,,,,Looking again,Website,New'
    )
    response = upload(auth_client, content)
    assert response.status_code == 200
    assert b"Skipped duplicate" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1


def test_csv_import_partial_success_reports_bad_row(auth_client):
    content = csv_bytes(
        'Valid Fictional,9000000301,valid.fictional@example.com,Indiranagar,Apartment,Full Home Interiors,500000,700000,,Ready,Website,New',
        'Invalid Fictional,,,Indiranagar,Apartment,Full Home Interiors,500000,700000,,Ready,Website,New',
    )
    response = upload(auth_client, content)
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "1 lead imported" in text
    assert "at least one contact" in text
    assert db.session.scalar(db.select(func.count(Lead.id))) == 1


def test_csv_import_rejects_unknown_headers(auth_client):
    content = io.BytesIO(b"full_name,phone,email\r\nSomeone,9000000401,someone@example.com\r\n")
    response = upload(auth_client, content)
    assert response.status_code == 400
    assert b"Missing required column" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 0


def test_csv_import_rejects_multiple_bad_values(auth_client):
    content = csv_bytes(
        'Bad Status,9000000501,bad.status@example.com,Indiranagar,Apartment,Full Home Interiors,500000,700000,,Ready,Website,Imaginary'
    )
    response = upload(auth_client, content)
    assert response.status_code == 200
    assert b"Choose a valid lead status" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 0


def test_csv_import_size_limit(auth_client, app):
    app.config["MAX_CSV_BYTES"] = 150
    content = csv_bytes(
        'A Very Long Name For A Fictional Customer,9000000601,long.fictional@example.com,Indiranagar,Apartment,Full Home Interiors,500000,700000,,Ready,Website,New'
    )
    response = upload(auth_client, content)
    assert response.status_code == 400
    assert b"larger than" in response.data
    assert db.session.scalar(db.select(func.count(Lead.id))) == 0


def test_csv_import_rejects_wrong_extension(auth_client):
    content = csv_bytes("Someone,9000000701,someone@example.com,,,,,,,Ready,Website,New")
    response = upload(auth_client, content, filename="leads.txt")
    assert response.status_code == 400
    assert b"Only .csv" in response.data


def test_csv_template_download(auth_client):
    response = auth_client.get("/leads/import/template")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"name,phone,email")
