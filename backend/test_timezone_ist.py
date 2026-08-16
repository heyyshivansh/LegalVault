"""
LegalVault Timezone & Timestamp Standardization Test Suite
Verifies:
1. format_utc_iso helper handles aware, naive, and non-UTC datetimes correctly.
2. Newly generated timestamps across all entities (User, Document, Version, Share) are UTC with 'Z'.
3. All API endpoints serialize timestamps to explicit ISO 8601 strings ending in 'Z'.
4. Historical naive database timestamps are treated as UTC and preserved without shifting.
5. Blockchain timestamps remain raw Unix epoch seconds.
"""

import os
import io
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

from main import format_utc_iso
from database import SessionLocal
from models import Document, DocumentVersion, DocumentShare, User, UserRole

BASE_URL = "http://127.0.0.1:8000"


def run_timezone_tests():
    print("=================================================================")
    print("RUNNING TIMEZONE & IST STANDARDIZATION TEST SUITE")
    print("=================================================================")

    # -------------------------------------------------------------
    # 1. UNIT TESTS: format_utc_iso Helper
    # -------------------------------------------------------------
    print("\n[1] Testing format_utc_iso() helper logic...")

    # None
    assert format_utc_iso(None) is None, "None input should return None"

    # Timezone-aware UTC datetime
    aware_utc = datetime(2026, 8, 16, 8, 45, 0, 123456, tzinfo=timezone.utc)
    iso_aware = format_utc_iso(aware_utc)
    assert iso_aware == "2026-08-16T08:45:00.123456Z", f"Expected exact UTC with Z, got {iso_aware}"

    # Naive datetime (simulating historical SQLite row)
    naive_dt = datetime(2026, 8, 16, 8, 45, 0)
    iso_naive = format_utc_iso(naive_dt)
    assert iso_naive == "2026-08-16T08:45:00Z", f"Expected naive to be interpreted as UTC with Z, got {iso_naive}"

    # Non-UTC timezone datetime -> correctly converted to UTC with Z
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_dt = datetime(2026, 8, 16, 14, 15, 0, tzinfo=ist_tz)
    iso_converted = format_utc_iso(ist_dt)
    assert iso_converted == "2026-08-16T08:45:00Z", f"Expected IST 14:15 to convert to UTC 08:45Z, got {iso_converted}"

    print("    [OK] format_utc_iso correctly standardizes all datetime inputs to UTC with 'Z'.")

    # -------------------------------------------------------------
    # 2. AUTHENTICATION & USER SERIALIZATION
    # -------------------------------------------------------------
    print("\n[2] Testing User authentication and created_at serialization...")
    lawyer_login = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "lawyer@legalvault.local", "password": "lawyer123"},
    )
    assert lawyer_login.status_code == 200, f"Login failed: {lawyer_login.text}"
    lawyer_data = lawyer_login.json()
    lawyer_token = lawyer_data["access_token"]
    lawyer_headers = {"Authorization": f"Bearer {lawyer_token}"}
    lawyer_user = lawyer_data["user"]

    if lawyer_user.get("created_at"):
        assert lawyer_user["created_at"].endswith("Z"), f"User created_at '{lawyer_user['created_at']}' must end with 'Z'"

    me_resp = requests.get(f"{BASE_URL}/auth/me", headers=lawyer_headers)
    assert me_resp.status_code == 200, f"GET /auth/me failed: {me_resp.text}"
    me_data = me_resp.json()
    if me_data.get("created_at"):
        assert me_data["created_at"].endswith("Z"), f"GET /auth/me created_at '{me_data['created_at']}' must end with 'Z'"

    # Client user for sharing tests
    client_login = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "client@legalvault.local", "password": "client123"},
    )
    assert client_login.status_code == 200, f"Client login failed: {client_login.text}"
    client_id = client_login.json()["user"]["id"]

    print("    [OK] User model responses correctly serialize created_at with explicit 'Z'.")

    # -------------------------------------------------------------
    # 3. DOCUMENT UPLOAD & LISTING SERIALIZATION
    # -------------------------------------------------------------
    print("\n[3] Testing Document deposit and retrieval timestamp serialization...")
    salt = str(int(time.time()))
    pdf_bytes = f"%PDF-1.4 Timezone Test {salt} %%EOF".encode()

    upload_resp = requests.post(
        f"{BASE_URL}/documents/upload",
        headers=lawyer_headers,
        data={"case_number": f"CASE-TZ-{salt}", "allow_duplicate": "true"},
        files={"file": (f"tz_test_{salt}.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    doc_id = upload_resp.json()["document_id"]

    # Check GET /documents
    docs_list = requests.get(f"{BASE_URL}/documents", headers=lawyer_headers).json()
    target_doc = next((d for d in docs_list if d["id"] == doc_id), None)
    assert target_doc is not None, "Uploaded document must exist in documents list"
    assert target_doc["created_at"] is not None, "created_at must not be null"
    assert target_doc["created_at"].endswith("Z"), f"created_at '{target_doc['created_at']}' must end with 'Z'"

    # Check GET /documents/{id}
    doc_detail = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=lawyer_headers).json()
    assert doc_detail["created_at"].endswith("Z"), f"Document detail created_at '{doc_detail['created_at']}' must end with 'Z'"

    print(f"    [OK] Document #{doc_id} created_at serialized as '{target_doc['created_at']}'")

    # -------------------------------------------------------------
    # 4. VERSION HISTORY TIMESTAMPS
    # -------------------------------------------------------------
    print("\n[4] Testing Document Version History timestamp serialization...")
    v2_bytes = pdf_bytes + b" - Revision 2"
    v2_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        headers=lawyer_headers,
        files={"file": (f"tz_test_{salt}_v2.pdf", io.BytesIO(v2_bytes), "application/pdf")},
    )
    assert v2_resp.status_code == 200, f"Version upload failed: {v2_resp.text}"
    v2_data = v2_resp.json()
    assert v2_data["created_at"].endswith("Z"), f"New version created_at '{v2_data['created_at']}' must end with 'Z'"

    # GET /documents/{id}/versions
    versions_list = requests.get(f"{BASE_URL}/documents/{doc_id}/versions", headers=lawyer_headers).json()
    assert len(versions_list) >= 2, "Expected at least 2 versions"
    for ver in versions_list:
        assert ver["created_at"].endswith("Z"), f"Version {ver['version_number']} created_at '{ver['created_at']}' must end with 'Z'"

    # GET /documents/{id}/versions/1 and /2
    for v_num in [1, 2]:
        v_det = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/{v_num}", headers=lawyer_headers).json()
        assert v_det["created_at"].endswith("Z"), f"Version {v_num} detail created_at '{v_det['created_at']}' must end with 'Z'"

    print(f"    [OK] Version 1 and Version 2 timestamps serialized with explicit 'Z'.")

    # -------------------------------------------------------------
    # 5. DOCUMENT SHARING TIMESTAMPS
    # -------------------------------------------------------------
    print("\n[5] Testing Document Sharing timestamp serialization...")
    share_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_headers,
        json={"shared_with_user_id": client_id},
    )
    assert share_resp.status_code == 200, f"Share failed: {share_resp.text}"
    share_data = share_resp.json()
    assert share_data["created_at"].endswith("Z"), f"Share created_at '{share_data['created_at']}' must end with 'Z'"

    # GET /documents/{id}/shares
    shares_list = requests.get(f"{BASE_URL}/documents/{doc_id}/shares", headers=lawyer_headers).json()
    assert len(shares_list) >= 1
    for s in shares_list:
        assert s["created_at"].endswith("Z"), f"Share list created_at '{s['created_at']}' must end with 'Z'"

    print(f"    [OK] Share creation and share listing timestamps serialized with explicit 'Z'.")

    # -------------------------------------------------------------
    # 6. HISTORICAL NAIVE TIMESTAMP PRESERVATION (NO SHIFT)
    # -------------------------------------------------------------
    print("\n[6] Testing Historical naive timestamp preservation...")
    db = SessionLocal()
    try:
        # Create a historical document with exact naive UTC timestamp
        hist_dt = datetime(2026, 1, 15, 10, 30, 0)
        hist_doc = Document(
            filename=f"historical_record_{salt}.pdf",
            case_number=f"CASE-HIST-{salt}",
            uploaded_by="Advocate Rajesh Sharma",
            owner_id=lawyer_user["id"],
            file_hash=f"mock_hash_{salt}",
            version=1,
            created_at=hist_dt,
        )
        db.add(hist_doc)
        db.commit()
        db.refresh(hist_doc)
        hist_id = hist_doc.id

        # Query through API
        api_hist = requests.get(f"{BASE_URL}/documents/{hist_id}", headers=lawyer_headers).json()
        assert api_hist["created_at"] == "2026-01-15T10:30:00Z", (
            f"Expected '2026-01-15T10:30:00Z', got '{api_hist['created_at']}'"
        )

        # Confirm DB record itself was not altered or shifted
        db_doc = db.query(Document).filter(Document.id == hist_id).first()
        assert db_doc.created_at.year == 2026
        assert db_doc.created_at.month == 1
        assert db_doc.created_at.day == 15
        assert db_doc.created_at.hour == 10
        assert db_doc.created_at.minute == 30
        assert db_doc.created_at.second == 0

        # Clean up historical test row
        db.delete(db_doc)
        db.commit()
    finally:
        db.close()

    print("    [OK] Historical naive database timestamp '2026-01-15 10:30:00' preserved without shifting.")

    # -------------------------------------------------------------
    # 7. BLOCKCHAIN VERIFICATION TIMESTAMPS
    # -------------------------------------------------------------
    print("\n[7] Testing Blockchain Verification timestamp integrity...")
    verify_resp = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_headers)
    assert verify_resp.status_code == 200, f"Verify failed: {verify_resp.text}"
    ver_data = verify_resp.json()
    if ver_data.get("timestamp") is not None:
        # Timestamp must be an integer Unix epoch (seconds)
        assert isinstance(ver_data["timestamp"], int), f"Blockchain timestamp must be int, got {type(ver_data['timestamp'])}"
        assert ver_data["timestamp"] > 1700000000, f"Blockchain timestamp value seems invalid: {ver_data['timestamp']}"

    print(f"    [OK] Blockchain timestamp returned as raw epoch seconds ({ver_data.get('timestamp')}).")

    print("\n=================================================================")
    print("ALL TIMEZONE & IST STANDARDIZATION TESTS PASSED WITH 100% SUCCESS!")
    print("=================================================================")


if __name__ == "__main__":
    run_timezone_tests()
