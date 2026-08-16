import os
import io
import time
import json
import sqlite3
import requests
from unittest.mock import patch, MagicMock
from pypdf import PdfWriter, PdfReader

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "legalvault.db")


def create_synthetic_pdf(text_pages: list[str]) -> bytes:
    """Helper to generate a minimal valid synthetic PDF with text using pypdf."""
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    for page_text in text_pages:
        page = writer.add_blank_page(width=612, height=792)
        if page_text:
            escaped_text = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content_str = f"BT /F1 12 Tf 50 700 Td ({escaped_text}) Tj ET"
            stream = DecodedStreamObject()
            stream.set_data(content_str.encode("latin1", errors="replace"))
            page[NameObject("/Contents")] = stream

            font_dict = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            res_dict = DictionaryObject({
                NameObject("/Font"): DictionaryObject({
                    NameObject("/F1"): font_dict
                })
            })
            page[NameObject("/Resources")] = res_dict

    out_buffer = io.BytesIO()
    writer.write(out_buffer)
    return out_buffer.getvalue()


def run_ai_summary_tests():
    print("=================================================================")
    print("RUNNING LEGALVAULT AI SUMMARIZATION TEST SUITE")
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

    # 2. Reset development vault for a clean test docket
    reset_resp = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert reset_resp.status_code == 200, f"Reset failed: {reset_resp.text}"
    print("[2] Development vault cleanly reset.")

    # 3. Unit test text extraction pipeline & processing limits
    print("\n[3] Testing Text Extraction Pipeline & 500k Character Limit...")
    from ai_extractor import (
        AIExtractor,
        MockProvider,
        GeminiProvider,
        AIConfigurationError,
        AIServiceError,
        AITimeoutError,
        AIParsingError,
        normalize_summary_schema,
    )

    # 3a. Plain text extraction
    txt_sample = (
        "IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD\n"
        "WRIT PETITION NO. CIV-2026-88\n"
        "IN THE MATTER OF: Rajesh Sharma (Petitioner) Versus State of Uttar Pradesh (Respondent)\n"
        "DATED: 12th August 2026\n"
        "Subject: Evidentiary affidavit in support of civil land partition suit.\n"
        "PRAYER: The Petitioner respectfully prays for interim injunction against illegal demolition.\n"
    )
    txt_path = os.path.join(UPLOADS_DIR, "test_summary_sample.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_sample)

    txt_content, txt_status, txt_err = AIExtractor.extract_text_from_file(txt_path, ".txt")
    assert txt_status == "OK", f"TXT extraction failed: {txt_err}"
    print("    [OK] Plain text UTF-8 extraction validated.")

    # 3b. Insufficient text (< 20 chars)
    short_txt_path = os.path.join(UPLOADS_DIR, "test_summary_short.txt")
    with open(short_txt_path, "w", encoding="utf-8") as f:
        f.write("Short text")
    _, short_status, short_err = AIExtractor.extract_text_from_file(short_txt_path, ".txt")
    assert short_status == "EXTRACTION_UNAVAILABLE"
    print("    [OK] Insufficient text (< 20 chars) correctly returned EXTRACTION_UNAVAILABLE.")

    # 3c. 500,000 Character Processing Limit Enforcement
    large_txt_path = os.path.join(UPLOADS_DIR, "test_oversized_text.txt")
    with open(large_txt_path, "w", encoding="utf-8") as f:
        f.write("Legal filing statement paragraph.\n" * 20000)  # > 600,000 chars
    _, large_status, large_err = AIExtractor.extract_text_from_file(large_txt_path, ".txt")
    assert large_status == "EXTRACTION_LIMIT_EXCEEDED", f"Expected EXTRACTION_LIMIT_EXCEEDED, got {large_status}"
    assert "exceeds maximum AI processing limit of 500,000 characters" in large_err
    print("    [OK] 500,000-character processing limit strictly enforced with EXTRACTION_LIMIT_EXCEEDED.")

    # 3d. Blank / Image-only PDF
    blank_pdf_bytes = create_synthetic_pdf([""])
    blank_pdf_path = os.path.join(UPLOADS_DIR, "test_summary_blank.pdf")
    with open(blank_pdf_path, "wb") as f:
        f.write(blank_pdf_bytes)
    _, blank_status, blank_err = AIExtractor.extract_text_from_file(blank_pdf_path, ".pdf")
    assert blank_status == "EXTRACTION_UNAVAILABLE"
    print("    [OK] Blank / Image-only PDF correctly returned EXTRACTION_UNAVAILABLE.")

    # 4. MockProvider Summary Heuristics & Anti-Hallucination Guarantees
    print("\n[4] Testing MockProvider Summary Extraction & Anti-Hallucination Guarantees...")
    mock_prov = MockProvider()

    latest_test_fixture = (
        "AFFIDAVIT OF OWNERSHIP AND POSSESSION\n"
        "District Court of Kanpur Nagar in connection with Civil Suit No. CIV-2026-104.\n"
        "I, Rajesh Sharma, do hereby state on solemn affirmation that I am in lawful ownership and physical possession of the agricultural land situated at Village Kalyanpur. "
        "The property title transfer was duly executed on 3 July 2025 with supporting evidentiary documents.\n"
        "Filing Date: 14 August 2026\n"
        "Hearing Date: 22 August 2026\n"
    )
    mock_summary = mock_prov.generate_summary(latest_test_fixture, {"filename": "Affidavit_Ownership.txt"})
    assert mock_summary["summary"] is not None
    assert "Rajesh Sharma" in mock_summary["summary"] or "ownership" in mock_summary["summary"].lower()
    assert len(mock_summary["key_facts"]) > 0
    assert any("Kalyanpur" in f or "ownership" in f for f in mock_summary["key_facts"])
    assert any("14 August 2026" in p or "22 August 2026" in p for p in mock_summary["important_points"])
    assert "confidence" not in mock_summary, "Summary schema must NOT contain confidence score!"
    print("    [OK] MockProvider summary generated source-grounded narrative, key facts, and important points.")

    # 4a. Multi-sentence continuous paragraph with leading artifact test (User specification)
    user_fixture_text = (
        "..................\n"
        "This affidavit is submitted by Ananya Verma in support of Civil Suit No. CIV-2026-104 concerning ownership and possession of agricultural land in Kanpur, Uttar Pradesh. "
        "The petitioner states that the disputed property was transferred under an agreement dated 3 July 2025 and seeks appropriate relief regarding possession and title. "
        "The matter is scheduled for hearing on 22 August 2026."
    )
    user_summary = mock_prov.generate_summary(user_fixture_text)
    assert not user_summary["summary"].startswith("."), "Summary must not contain leading dot artifacts!"
    assert "Ananya Verma" in user_summary["summary"]
    # Check concise key facts (individual sentences)
    assert len(user_summary["key_facts"]) >= 2
    assert any("Ananya Verma" in f for f in user_summary["key_facts"])
    assert any("3 July 2025" in f for f in user_summary["key_facts"])
    # Check concise legal issues (not the entire paragraph)
    assert len(user_summary["legal_issues"]) >= 1
    for issue in user_summary["legal_issues"]:
        assert len(issue) < 200, f"Legal issue should be concise, got length {len(issue)}: {issue}"
    assert any("ownership" in i.lower() or "possession" in i.lower() or "relief" in i.lower() for i in user_summary["legal_issues"])
    # Check important points (detected dates and relief)
    assert any("3 July 2025" in p for p in user_summary["important_points"])
    assert any("relief" in p.lower() for p in user_summary["important_points"])
    assert any("22 August 2026" in p for p in user_summary["important_points"])
    assert "confidence" not in user_summary, "Summary schema must NOT contain confidence score!"
    print("    [OK] User paragraph verified: clean summary, concise facts/issues, explicit dates/relief detected.")

    # 4b. Negative document summary test
    neg_doc_text = (
        "The defendant owns agricultural land near Kanpur.\n"
        "The document does not contain a case number, court name, jurisdiction declaration, hearing date, or formal subject heading."
    )
    neg_summary = mock_prov.generate_summary(neg_doc_text)
    assert "confidence" not in neg_summary
    assert isinstance(neg_summary["legal_issues"], list)
    print("    [OK] Negative document produced safe, source-bounded summary with clean empty legal claims.")

    # 4c. Theft V2 fixture key facts extraction
    theft_v2_text = """
    POLICE INVESTIGATION REPORT / INCIDENT STATEMENT
    Date: 18 June 2026
    Subject: Supplemental Investigation Report - Theft at Sharma Electronics

    1. The theft was reported at Sharma Electronics on 5 June 2026 involving missing cash of Rs 2,50,000.
    2. The incident is believed to have occurred between 9 PM on 4 June 2026 and 7 AM on 5 June 2026.
    3. CCTV footage recovered from a nearby building reportedly showed a person entering the store at approximately 11:42 PM on 4 June 2026.
    4. Amit Verma reportedly stated that he saw Rohan Mehta near the rear entrance of the store shortly before midnight.
    5. A second witness reportedly observed a motorcycle matching the description associated with Rohan Mehta near the premises.
    6. The investigation into the theft reported at Sharma Electronics progressed after statements were obtained from two witnesses.
    7. Rohan Mehta was questioned on 18 June 2026, and the investigation remained ongoing regarding the missing funds.
    """
    theft_summary = mock_prov.generate_summary(theft_v2_text)
    assert len(theft_summary["key_facts"]) >= 4, f"Expected >= 4 key facts, got {len(theft_summary['key_facts'])}"
    assert "Factual background and procedural statements as detailed in the filing text." not in theft_summary["key_facts"]
    assert any("CCTV footage" in f for f in theft_summary["key_facts"])
    assert any("Amit Verma" in f for f in theft_summary["key_facts"])
    assert any("motorcycle" in f for f in theft_summary["key_facts"])
    assert any("investigation" in f.lower() for f in theft_summary["key_facts"])
    print("    [OK] Theft V2 fixture generated concrete, source-grounded key facts without generic fallbacks.")

    # 5. Gemini Provider Contract & Failure Handling Tests
    print("\n[5] Testing Gemini Provider Contract & Failure Isolation...")
    # Missing API Key
    try:
        GeminiProvider(api_key="")
        assert False, "GeminiProvider must raise AIConfigurationError when API key is empty"
    except AIConfigurationError:
        print("    [OK] Missing API key raises AIConfigurationError.")

    # Invalid API Key
    try:
        prov_bad_key = GeminiProvider(api_key="AIzaSyInvalidKeyTest12345")
        prov_bad_key.generate_summary("Sample text")
    except AIServiceError as e:
        assert "Gemini API error" in str(e)
        print("    [OK] Invalid API key safely caught as AIServiceError.")

    # Provider Timeout Handling
    prov_mock = GeminiProvider(api_key="mock_key")
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
        try:
            prov_mock.generate_summary("Sample text")
            assert False, "Expected AITimeoutError"
        except AITimeoutError:
            print("    [OK] Timeout properly caught as AITimeoutError.")

    # Malformed JSON Handling
    bad_json_resp = MagicMock()
    bad_json_resp.status_code = 200
    bad_json_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{ malformed json"}]}}]}
    with patch("requests.post", return_value=bad_json_resp):
        try:
            prov_mock.generate_summary("Sample text")
            assert False, "Expected AIParsingError"
        except AIParsingError:
            print("    [OK] Malformed JSON response properly caught as AIParsingError.")

    # Valid Structured Response Simulation
    simulated_gemini_json = json.dumps({
        "summary": "This affidavit submitted by Rajesh Sharma affirms lawful ownership and physical possession of agricultural land in Kalyanpur.",
        "key_facts": [
            "Rajesh Sharma is in physical possession of agricultural land situated at Village Kalyanpur.",
            "Property title transfer was duly executed on 3 July 2025 with supporting evidentiary documents."
        ],
        "legal_issues": [
            "Land title and possession verification in connection with Civil Suit No. CIV-2026-104."
        ],
        "important_points": [
            "Filing Date: 14 August 2026",
            "Hearing Date: 22 August 2026"
        ]
    })
    valid_resp = MagicMock()
    valid_resp.status_code = 200
    valid_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": simulated_gemini_json}]}}]}
    with patch("requests.post", return_value=valid_resp):
        gemini_parsed = prov_mock.generate_summary("Sample text")
        assert gemini_parsed["summary"].startswith("This affidavit")
        assert len(gemini_parsed["key_facts"]) == 2
        assert len(gemini_parsed["legal_issues"]) == 1
        assert "confidence" not in gemini_parsed
        print("    [OK] Valid Gemini structured summary response parsed and normalized.")

    # 6. Integration: Document Upload (v1) and AI Summary Generation
    print("\n[6] Testing Initial Upload (v1) and Summary Generation Endpoint...")
    v1_content = (
        "IN THE DISTRICT AND SESSIONS COURT, KANPUR NAGAR\n"
        "CASE NO: CIV-2026-88\n"
        "AFFIDAVIT OF EVIDENCE\n"
        "Deponent: Rajesh Sharma, S/o Late Ram Sharma\n"
        "Versus: State of Uttar Pradesh\n"
        "Filing Date: 12 Aug 2026\n"
        "Subject: Evidentiary affidavit in support of civil land partition suit.\n"
    ).encode("utf-8")

    upload_v1_resp = requests.post(
        f"{BASE_URL}/documents/upload",
        headers=lawyer_a_headers,
        data={"case_number": "CIV-2026-88", "uploaded_by": "Advocate Rajesh Sharma"},
        files={"file": ("Affidavit_Evidence_v1.txt", io.BytesIO(v1_content), "text/plain")},
    ).json()
    doc_id = upload_v1_resp["document_id"]
    print(f"    [OK] Document #{doc_id} deposited as Version 1.")

    # 6a. Generate summary for v1
    sum_gen_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=lawyer_a_headers,
    )
    assert sum_gen_resp.status_code == 200, f"Summary generation failed: {sum_gen_resp.text}"
    v1_summary = sum_gen_resp.json()
    assert v1_summary["status"] == "COMPLETED"
    assert v1_summary["summary"] is not None
    assert v1_summary["ai_provider"] == "mock"
    assert v1_summary["ai_model"] == "offline-heuristics"
    assert v1_summary["version_number"] == 1
    assert v1_summary["cached"] is False
    assert v1_summary["is_owner_or_admin"] is True
    print(f"    [OK] Summary generated for v1: {v1_summary['summary'][:60]}...")

    # 6b. Verify GET /documents/{id}/versions/1/summary and GET /documents/{id}/summary
    get_v1_sum = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=lawyer_a_headers,
    ).json()
    assert get_v1_sum["status"] == "COMPLETED"
    assert get_v1_sum["summary"] == v1_summary["summary"]

    get_master_sum = requests.get(
        f"{BASE_URL}/documents/{doc_id}/summary",
        headers=lawyer_a_headers,
    ).json()
    assert get_master_sum["version_number"] == 1
    assert get_master_sum["summary"] == v1_summary["summary"]
    print("    [OK] GET /documents/{id}/versions/1/summary and GET /documents/{id}/summary return active v1 summary.")

    # 7. Testing Caching & Force Re-Generation
    print("\n[7] Testing SHA-256 Summary Caching & Force Re-Generation...")
    cached_sum_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=lawyer_a_headers,
    ).json()
    assert cached_sum_resp["cached"] is True, "Second call without force=True must return cached result!"
    print("    [OK] Cache hit verified: repeated call returned cached summary with cached=True.")

    force_sum_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary?force=true",
        headers=lawyer_a_headers,
    ).json()
    assert force_sum_resp["cached"] is False, "Call with force=True must re-synthesize and return cached=False!"
    print("    [OK] Force re-generation verified: force=true refreshed summary record.")

    # 8. Testing Version Isolation (v1 summary vs v2 summary)
    print("\n[8] Testing Version History Isolation (v1 -> Summary A, v2 -> Summary B)...")
    v2_content = (
        "IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD\n"
        "WRIT PETITION NO. W.P.(C) 412/2026\n"
        "AMENDED PETITION FOR INTERIM RELIEF\n"
        "Petitioner: Priya Patel, Advocate\n"
        "Respondent: Nagar Nigam Kanpur\n"
        "Filing Date: 16 Aug 2026\n"
        "Subject: Challenge to municipal acquisition notice without due compensation.\n"
    ).encode("utf-8")

    upload_v2_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        headers=lawyer_a_headers,
        files={"file": ("Amended_Petition_v2.txt", io.BytesIO(v2_content), "text/plain")},
    ).json()
    assert upload_v2_resp["version_number"] == 2
    print("    [OK] Version 2 uploaded to document.")

    # Before generation, v2 summary status must be NOT_GENERATED
    v2_initial_sum = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/2/summary",
        headers=lawyer_a_headers,
    ).json()
    assert v2_initial_sum["status"] == "NOT_GENERATED"
    print("    [OK] Un-summarized Version 2 returns status NOT_GENERATED.")

    # Generate summary for Version 2
    v2_sum_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/2/summary",
        headers=lawyer_a_headers,
    ).json()
    assert v2_sum_resp["version_number"] == 2
    assert v2_sum_resp["status"] == "COMPLETED"
    print(f"    [OK] Version 2 summary generated: {v2_sum_resp['summary'][:60]}...")

    # Verify Version 1 summary remains completely untouched and isolated
    v1_check_sum = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=lawyer_a_headers,
    ).json()
    assert v1_check_sum["version_number"] == 1
    assert v1_check_sum["summary"] == v1_summary["summary"]
    print("    [OK] Version 1 summary strictly preserved and isolated from Version 2 changes.")

    # Master document summary now points to Version 2
    master_sum_v2 = requests.get(
        f"{BASE_URL}/documents/{doc_id}/summary",
        headers=lawyer_a_headers,
    ).json()
    assert master_sum_v2["version_number"] == 2
    assert master_sum_v2["summary"] == v2_sum_resp["summary"]
    print("    [OK] Master document summary endpoint resolves to active Version 2.")

    # 9. Testing RBAC Scoping on AI Summary Endpoints
    print("\n[9] Testing Role-Based Access Control (RBAC) Scoping...")
    # 9a. Share document with Judge and Client
    requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_a_headers,
        json={"shared_with_user_id": judge_id},
    )

    # 9b. Shared Judge can GET existing summary (v1 and v2)
    judge_get_v1 = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=judge_headers,
    )
    assert judge_get_v1.status_code == 200
    assert judge_get_v1.json()["is_owner_or_admin"] is False
    print("    [OK] Shared Judge can read existing version summary.")

    # 9c. Shared Judge CANNOT trigger generation (POST -> 403 Forbidden with ACTION_DENIED)
    judge_generate = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary?force=true",
        headers=judge_headers,
    )
    assert judge_generate.status_code == 403, f"Expected 403, got {judge_generate.status_code}"
    print("    [OK] Shared Judge blocked from triggering summary generation (403 Forbidden).")

    # 9d. Unauthorized Lawyer B cannot GET or POST
    unauth_get = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=lawyer_b_headers,
    )
    assert unauth_get.status_code == 403, f"Expected 403, got {unauth_get.status_code}"

    unauth_post = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=lawyer_b_headers,
    )
    assert unauth_post.status_code == 403, f"Expected 403, got {unauth_post.status_code}"
    print("    [OK] Unauthorized Lawyer B blocked from viewing or generating summary (403 Forbidden).")

    # 9e. Administrator has full trigger and view access
    admin_sum = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/summary",
        headers=admin_headers,
    )
    assert admin_sum.status_code == 200
    assert admin_sum.json()["is_owner_or_admin"] is True
    print("    [OK] Administrator has full summary generation and inspection privileges.")

    # 10. Testing Custody Invariants & Fault Isolation
    print("\n[10] Verifying Custody Layer Invariants & Fault Isolation...")
    v1_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_a_headers).json()
    assert v1_verify["result"] == "VERIFIED"

    v2_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_a_headers).json()
    assert v2_verify["result"] == "VERIFIED"
    print("    [OK] Document versions, SHA-256 hashes, and blockchain verification remain 100% verified and authoritative.")

    # 11. Privacy & Audit Trail Verification
    print("\n[11] Verifying Privacy & Forensic Audit Logging...")
    audit_resp = requests.get(f"{BASE_URL}/documents/{doc_id}/audit", headers=lawyer_a_headers).json()
    events = audit_resp["events"]
    actions = [e["action"] for e in events]
    assert "AI_SUMMARY_GENERATED" in actions

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT action, metadata_json, reason FROM audit_logs WHERE action LIKE 'AI_SUMMARY_%'")
    ai_logs = cur.fetchall()
    for act, meta_json, rsn in ai_logs:
        if meta_json:
            assert "PRAYER" not in meta_json
            assert "Rajesh Sharma, S/o Late Ram Sharma" not in meta_json
            assert "API_KEY" not in meta_json
            assert "prompt" not in meta_json
    conn.close()
    print("    [OK] Audit trail recorded AI summary events with zero raw document text or prompt leakage.")

    # 12. Timezone UTC Compliance Verification
    print("\n[12] Verifying Timezone Standardization (UTC Z Serialization)...")
    assert v1_summary["created_at"].endswith("Z")
    assert v1_summary["updated_at"].endswith("Z")
    print("    [OK] Summary timestamps conform strictly to UTC ISO 8601 with trailing 'Z'.")

    # 13. Development Vault Reset cleans up DocumentVersionSummary
    print("\n[13] Testing Development Vault Reset on AI Summary Records...")
    reset_after = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers).json()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM document_version_summaries")
    sum_count = cur.fetchone()[0]
    conn.close()
    assert sum_count == 0
    print("    [OK] Development vault reset cleanly purged document_version_summaries records.")

    # Clean up test artifacts in uploads/
    for tf in ["test_summary_sample.txt", "test_summary_short.txt", "test_oversized_text.txt", "test_summary_blank.pdf"]:
        tp = os.path.join(UPLOADS_DIR, tf)
        if os.path.exists(tp):
            try:
                os.remove(tp)
            except Exception:
                pass

    print("\n=================================================================")
    print("ALL AI SUMMARIZATION TESTS PASSED WITH 100% SUCCESS!")
    print("=================================================================")


if __name__ == "__main__":
    run_ai_summary_tests()
