import os
import io
import time
import json
import sqlite3
import hashlib
import sys
import requests
from unittest.mock import patch, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "legalvault.db")


def run_ai_timeline_tests():
    print("=================================================================")
    print("RUNNING LEGALVAULT AI EVIDENCE TIMELINE TEST SUITE")
    print("=================================================================")

    # 1. Authenticate users
    lawyer_a_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "lawyer@legalvault.local", "password": "lawyer123"},
    ).json()
    lawyer_a_token = lawyer_a_resp["access_token"]
    lawyer_a_headers = {"Authorization": f"Bearer {lawyer_a_token}"}
    lawyer_a_id = lawyer_a_resp["user"]["id"]

    lawyer_b_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "lawyer2@legalvault.local", "password": "lawyer123"},
    ).json()
    lawyer_b_token = lawyer_b_resp["access_token"]
    lawyer_b_headers = {"Authorization": f"Bearer {lawyer_b_token}"}

    judge_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "judge@legalvault.local", "password": "judge123"},
    ).json()
    judge_token = judge_resp["access_token"]
    judge_headers = {"Authorization": f"Bearer {judge_token}"}
    judge_id = judge_resp["user"]["id"]

    client_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "client@legalvault.local", "password": "client123"},
    ).json()
    client_token = client_resp["access_token"]
    client_headers = {"Authorization": f"Bearer {client_token}"}
    client_id = client_resp["user"]["id"]

    admin_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "admin@legalvault.local", "password": "admin123"},
    ).json()
    admin_token = admin_resp["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    print("[1] Authentication confirmed across Lawyer, Judge, Client, Admin.")

    # 2. Reset development vault
    reset_resp = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert reset_resp.status_code == 200, f"Vault reset failed: {reset_resp.text}"
    print("[2] Development vault cleanly reset.")

    # 3. Unit test Date Parsing & ISO Normalization
    print("\n[3] Testing ISO Date Parsing & Normalization...")
    from ai_extractor import (
        parse_iso_date,
        normalize_timeline_schema,
        ALLOWED_EVENT_TYPES,
        DEFAULT_EMPTY_TIMELINE,
        MockProvider,
        GeminiProvider,
        AIExtractor,
        AIConfigurationError,
        AIServiceError,
        AITimeoutError,
        AIParsingError,
    )

    assert parse_iso_date("2025-07-03") == "2025-07-03"
    assert parse_iso_date("3 July 2025") == "2025-07-03"
    assert parse_iso_date("03 Jul 2025") == "2025-07-03"
    assert parse_iso_date("22 August 2026") == "2026-08-22"
    assert parse_iso_date("12/08/2026") == "2026-08-12"
    assert parse_iso_date("August 2026") == "2026-08-01"
    assert parse_iso_date("Unknown Date") is None
    assert parse_iso_date("") is None
    print("    ✓ parse_iso_date correctly handles ISO, human-readable, and slash date formats.")

    # 4. Unit test Schema Normalization, Chronological Sorting & Deduplication
    print("\n[4] Testing Timeline Normalization, Chronological Sorting & Duplicate Removal...")
    raw_unordered = {
        "events": [
            {
                "date": "2026-08-22",
                "date_raw": "22 August 2026",
                "event_type": "HEARING",
                "description": "Matter scheduled for hearing.",
                "source_reference": "Hearing on 22 August 2026.",
            },
            {
                "date": "2025-07-03",
                "date_raw": "3 July 2025",
                "event_type": "AGREEMENT",
                "description": "Agreement executed.",
                "source_reference": "Agreement on 3 July 2025.",
            },
            # Exact duplicate of the first event
            {
                "date": "2026-08-22",
                "date_raw": "22 August 2026",
                "event_type": "HEARING",
                "description": "Matter scheduled for hearing.",
                "source_reference": "Hearing on 22 August 2026.",
            },
            # Different event on the same date (should be preserved)
            {
                "date": "2026-08-22",
                "date_raw": "22 August 2026",
                "event_type": "ORDER",
                "description": "Interim injunction order issued.",
                "source_reference": "Order passed on 22 August 2026.",
            },
            {
                "date": "2026-08-12",
                "date_raw": "12 August 2026",
                "event_type": "FILING",
                "description": "Affidavit filed.",
                "source_reference": "Affidavit filed on 12 August 2026.",
            },
        ]
    }

    norm = normalize_timeline_schema(raw_unordered)
    events = norm["events"]
    assert len(events) == 4, f"Expected 4 events after deduplication, got {len(events)}"
    # Check strict chronological order
    assert events[0]["date"] == "2025-07-03"
    assert events[0]["event_type"] == "AGREEMENT"
    assert events[0]["sequence_order"] == 0

    assert events[1]["date"] == "2026-08-12"
    assert events[1]["event_type"] == "FILING"
    assert events[1]["sequence_order"] == 1

    assert events[2]["date"] == "2026-08-22"
    assert events[3]["date"] == "2026-08-22"
    assert {events[2]["event_type"], events[3]["event_type"]} == {"HEARING", "ORDER"}
    assert events[2]["sequence_order"] == 2
    assert events[3]["sequence_order"] == 3
    print("    ✓ Chronological ascending sorting, duplicate elimination, and multiple-event preservation verified.")

    # 5. Unit test MockProvider heuristics and anti-hallucination
    print("\n[5] Testing MockProvider Heuristics & Zero-Hallucination on Non-dated Text...")
    mock_prov = MockProvider()

    test_legal_doc = """
    IN THE DISTRICT COURT OF KANPUR NAGAR
    CIVIL SUIT NO. CIV-2026-104

    ANANYA VERMA (Petitioner)
    V/S
    RAMESH CHANDRA (Respondent)

    AFFIDAVIT

    1. The dispute concerns ancestral agricultural property situated in Kanpur Nagar.
    2. An agreement dated 3 July 2025 was executed between the parties regarding title partition.
    3. The respondent failed to comply, and this evidentiary affidavit was filed on 12 August 2026.
    4. The matter is scheduled for hearing before this Hon'ble Court on 22 August 2026.
    """

    res = mock_prov.extract_timeline(test_legal_doc)
    extracted_events = res["events"]
    assert len(extracted_events) == 3, f"Expected 3 extracted events, got {len(extracted_events)}"
    assert extracted_events[0]["date"] == "2025-07-03"
    assert extracted_events[0]["event_type"] in ["AGREEMENT", "EXECUTION"]
    assert extracted_events[1]["date"] == "2026-08-12"
    assert extracted_events[1]["event_type"] == "FILING"
    assert extracted_events[2]["date"] == "2026-08-22"
    assert extracted_events[2]["event_type"] == "HEARING"
    print("    ✓ MockProvider correctly extracted Agreement (3 Jul 2025), Filing (12 Aug 2026), and Hearing (22 Aug 2026).")

    # Anti-hallucination test on text with NO dates
    no_date_text = "This is a general legal submission regarding general principles of land law without any explicit procedural or calendar dates."
    no_date_res = mock_prov.extract_timeline(no_date_text)
    assert no_date_res["events"] == [], "Expected zero events for text with no dates."
    print("    ✓ Zero events synthesized for non-dated text (anti-hallucination verified).")

    # 5b. Grounded descriptions and contextual classification test (Theft case fixture with multiple same-date events)
    theft_fixture = """
    1. On 4 June 2026, CCTV footage recovered from a nearby building reportedly showed a person entering the store at approximately 11:42 PM.
    2. On 5 June 2026, the theft was reported at Sharma Electronics and an initial complaint was made regarding missing cash of Rs 2,50,000.
    3. On 18 June 2026, the investigation into the theft reported at Sharma Electronics on 5 June 2026 progressed after statements were obtained from two witnesses.
    4. Rohan Mehta was questioned on 18 June 2026, and the investigation remained ongoing regarding the missing funds.
    """
    theft_res = mock_prov.extract_timeline(theft_fixture)
    theft_events = theft_res["events"]
    assert len(theft_events) == 4, f"Expected 4 events in theft fixture, got {len(theft_events)}"
    # 4 June -> OTHER, grounded description
    assert theft_events[0]["date"] == "2026-06-04"
    assert theft_events[0]["event_type"] == "OTHER"
    assert "CCTV footage" in theft_events[0]["description"]
    assert "Documented chronological event." not in theft_events[0]["description"]

    # 5 June -> FILING (complaint reported), grounded description
    assert theft_events[1]["date"] == "2026-06-05"
    assert theft_events[1]["event_type"] == "FILING"
    assert "theft was reported" in theft_events[1]["description"].lower()

    # 18 June Event 1 -> OTHER (investigation progression), grounded description
    assert theft_events[2]["date"] == "2026-06-18"
    assert theft_events[2]["event_type"] == "OTHER"
    assert "investigation" in theft_events[2]["description"].lower()

    # 18 June Event 2 -> OTHER (questioning), distinct event preserved on the same date
    assert theft_events[3]["date"] == "2026-06-18"
    assert theft_events[3]["event_type"] == "OTHER"
    assert "questioned" in theft_events[3]["description"].lower()
    print("    ✓ Grounded contextual descriptions, non-FILING investigation classification, and multiple same-date events verified.")

    # 6. Unit test GeminiProvider error handling
    print("\n[6] Testing Gemini Provider Exception Isolation...")
    # Missing API key
    try:
        gemini_missing = GeminiProvider(api_key="")
        gemini_missing.extract_timeline(test_legal_doc)
        assert False, "Expected AIConfigurationError for missing API key"
    except AIConfigurationError:
        print("    ✓ AIConfigurationError raised when GEMINI_API_KEY is missing.")

    # Malformed JSON response
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "THIS IS NOT VALID JSON"}]}}]
        }
        mock_post.return_value = mock_resp

        gemini_prov = GeminiProvider(api_key="mock-api-key")
        try:
            gemini_prov.extract_timeline(test_legal_doc)
            assert False, "Expected AIParsingError for malformed JSON"
        except AIParsingError:
            print("    ✓ AIParsingError raised when Gemini returns non-JSON payload.")

    # 7. End-to-End API Workflow: Document V1 & Timeline Generation
    print("\n[7] Testing End-to-End Document V1 Creation & Timeline Generation...")
    doc_v1_text = test_legal_doc.encode("utf-8")
    upload_resp = requests.post(
        f"{BASE_URL}/documents/upload",
        headers=lawyer_a_headers,
        data={"case_number": "CIV-2026-104", "uploaded_by": "Advocate Ananya Verma"},
        files={"file": ("affidavit_v1.txt", io.BytesIO(doc_v1_text), "text/plain")},
    )
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    doc_data = upload_resp.json()
    doc_id = doc_data["document_id"]
    doc_v1_hash = doc_data["file_hash"]
    print(f"    ✓ Document #{doc_id} created with initial version V1 (SHA-256: {doc_v1_hash[:16]}...).")

    # Check ungenerated timeline state
    get_v1_tl = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=lawyer_a_headers)
    assert get_v1_tl.status_code == 200
    assert get_v1_tl.json()["status"] == "NOT_GENERATED"
    assert get_v1_tl.json()["events"] == []
    print("    ✓ Initial timeline status is NOT_GENERATED.")

    # Generate V1 timeline
    gen_v1_tl = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=lawyer_a_headers)
    assert gen_v1_tl.status_code == 200, f"Timeline generation failed: {gen_v1_tl.text}"
    tl_v1_data = gen_v1_tl.json()
    assert tl_v1_data["status"] == "COMPLETED"
    assert tl_v1_data["cached"] is False
    assert len(tl_v1_data["events"]) == 3
    assert tl_v1_data["events"][0]["date"] == "2025-07-03"
    assert tl_v1_data["events"][1]["date"] == "2026-08-12"
    assert tl_v1_data["events"][2]["date"] == "2026-08-22"
    print("    ✓ V1 timeline generated successfully with 3 chronological events.")

    # Cache hit check (force=False)
    cache_v1_tl = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=lawyer_a_headers)
    assert cache_v1_tl.status_code == 200
    assert cache_v1_tl.json()["cached"] is True
    print("    ✓ Cache hit verified: returned existing timeline without re-processing (cached=true).")

    # Force re-generation (force=True)
    force_v1_tl = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline?force=true", headers=lawyer_a_headers)
    assert force_v1_tl.status_code == 200
    assert force_v1_tl.json()["cached"] is False
    print("    ✓ Force re-generation verified (cached=false).")

    # 8. Test Version Isolation (V1 vs V2)
    print("\n[8] Testing Version Isolation between V1 and V2 Timelines...")
    doc_v2_text = """
    IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD
    CIVIL SUIT NO. CIV-2026-104

    ANANYA VERMA (Petitioner)
    V/S
    RAMESH CHANDRA (Respondent)

    AMENDED PETITION

    1. The parties entered into an amended settlement agreement on 10 August 2026.
    2. A notice of compliance was issued on 15 August 2026.
    3. The final hearing is scheduled for 30 August 2026.
    """.encode("utf-8")

    upload_v2 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        headers=lawyer_a_headers,
        files={"file": ("amended_petition_v2.txt", io.BytesIO(doc_v2_text), "text/plain")},
    )
    assert upload_v2.status_code == 200, f"V2 upload failed: {upload_v2.text}"
    print("    ✓ Revision V2 uploaded.")

    # Generate V2 timeline
    gen_v2_tl = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/timeline", headers=lawyer_a_headers)
    assert gen_v2_tl.status_code == 200
    tl_v2_data = gen_v2_tl.json()
    assert tl_v2_data["version_number"] == 2
    assert len(tl_v2_data["events"]) == 3
    assert tl_v2_data["events"][0]["date"] == "2026-08-10"
    assert tl_v2_data["events"][1]["date"] == "2026-08-15"
    assert tl_v2_data["events"][2]["date"] == "2026-08-30"

    # Verify V1 timeline remains completely untouched
    check_v1_tl = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=lawyer_a_headers)
    assert check_v1_tl.status_code == 200
    v1_saved = check_v1_tl.json()
    assert v1_saved["version_number"] == 1
    assert v1_saved["events"][0]["date"] == "2025-07-03"
    assert v1_saved["events"][2]["date"] == "2026-08-22"
    print("    ✓ Strict version isolation confirmed: V1 timeline and V2 timeline exist independently.")

    # Master document endpoint resolution
    master_tl = requests.get(f"{BASE_URL}/documents/{doc_id}/timeline", headers=lawyer_a_headers)
    assert master_tl.status_code == 200
    assert master_tl.json()["version_number"] == 2
    print("    ✓ GET /documents/{id}/timeline correctly resolves to active version (V2).")

    # 9. Test Role-Based Access Control (RBAC)
    print("\n[9] Testing RBAC on Timeline Endpoints...")
    # Share document with Judge and Client
    share_judge = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_a_headers,
        json={"shared_with_user_id": judge_id},
    )
    assert share_judge.status_code == 200, f"Share with judge failed: {share_judge.text}"

    share_client = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_a_headers,
        json={"email": "client@legalvault.local"},
    )
    assert share_client.status_code == 200, f"Share with client failed: {share_client.text}"
    print("    ✓ Document shared with Judge and Client.")

    # Shared Judge GET -> Allowed (200)
    judge_get = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=judge_headers)
    assert judge_get.status_code == 200, f"Judge GET failed: {judge_get.text}"
    print("    ✓ Shared Judge can view timeline (GET 200).")

    # Shared Judge POST -> Denied (403 ACTION_DENIED)
    judge_post = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=judge_headers)
    assert judge_post.status_code == 403, f"Judge POST should be denied, got {judge_post.status_code}"
    print("    ✓ Shared Judge cannot trigger timeline generation (POST 403 ACTION_DENIED).")

    # Shared Client GET -> Allowed (200)
    client_get = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=client_headers)
    assert client_get.status_code == 200, f"Client GET failed: {client_get.text}"
    print("    ✓ Shared Client can view timeline (GET 200).")

    # Shared Client POST -> Denied (403 ACTION_DENIED)
    client_post = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=client_headers)
    assert client_post.status_code == 403, f"Client POST should be denied, got {client_post.status_code}"
    print("    ✓ Shared Client cannot trigger timeline generation (POST 403 ACTION_DENIED).")

    # Admin POST -> Allowed (200)
    admin_post = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline?force=true", headers=admin_headers)
    assert admin_post.status_code == 200
    print("    ✓ Administrator can generate timeline (POST 200).")

    # Unauthorized User (Lawyer B) GET & POST -> Denied (403 ACCESS_DENIED)
    unauth_get = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=lawyer_b_headers)
    assert unauth_get.status_code == 403
    unauth_post = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/timeline", headers=lawyer_b_headers)
    assert unauth_post.status_code == 403
    print("    ✓ Unauthorized users are strictly blocked (403 ACCESS_DENIED).")

    # 10. Test Forensic Audit Trail & Privacy Masking
    print("\n[10] Testing Forensic Audit Trail & Privacy Safeguards...")
    audit_resp = requests.get(f"{BASE_URL}/documents/{doc_id}/audit", headers=lawyer_a_headers)
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    actions = [ev["action"] for ev in audit_data["events"]]
    assert "AI_TIMELINE_GENERATED" in actions, "Expected AI_TIMELINE_GENERATED in audit trail"

    # Verify sensitive data masking
    for ev in audit_data["events"]:
        meta = ev.get("metadata") or {}
        assert "prompt" not in meta
        assert "timeline_prompt" not in meta
        assert "raw_text" not in meta
        assert "raw_events" not in meta
        assert "api_key" not in meta
    print("    ✓ AI_TIMELINE_GENERATED recorded with sanitized metadata (no raw text or secret leaks).")

    # 11. Test UTC ISO 8601 Timestamp Serialization
    print("\n[11] Testing UTC Timestamp Serialization...")
    assert tl_v1_data["created_at"].endswith("Z"), f"created_at timestamp must end with 'Z', got {tl_v1_data['created_at']}"
    assert tl_v1_data["updated_at"].endswith("Z"), f"updated_at timestamp must end with 'Z', got {tl_v1_data['updated_at']}"
    print("    ✓ UTC timestamps cleanly serialized ending with 'Z'.")

    # 12. Test Custody Layer Integrity Invariants
    print("\n[12] Testing Cryptographic Custody Invariants & Blockchain State...")
    verify_resp = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_a_headers)
    assert verify_resp.status_code == 200
    ver_json = verify_resp.json()
    assert ver_json["result"] == "VERIFIED", f"Expected VERIFIED, got {ver_json.get('result')}"
    assert ver_json["verified"] is True
    print("    ✓ Cryptographic custody invariants intact: Verification status remains 100% VERIFIED.")

    # 13. Test Vault Reset Cleanup
    print("\n[13] Testing Vault Reset Database Cascade Cleanup...")
    reset_again = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert reset_again.status_code == 200

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM document_version_timelines")
    t_count = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM document_version_timeline_events")
    e_count = cursor.fetchone()[0]
    conn.close()

    assert t_count == 0, f"Expected 0 timeline rows after reset, found {t_count}"
    assert e_count == 0, f"Expected 0 timeline event rows after reset, found {e_count}"
    print("    ✓ Vault reset cleanly removed all timeline and timeline event records.")

    print("\n=================================================================")
    print("ALL 13 MAJOR TIMELINE TEST SUITES & 29 INVARIANTS PASSED!")
    print("=================================================================\n")


if __name__ == "__main__":
    run_ai_timeline_tests()
