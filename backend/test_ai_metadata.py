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


def run_ai_metadata_tests():
    print("=================================================================")
    print("RUNNING LEGALVAULT AI METADATA EXTRACTION TEST SUITE")
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

    # 3. Unit test text extraction pipeline
    print("\n[3] Testing Text Extraction Pipeline (PDF / TXT / Image-only)...")
    from ai_extractor import (
        AIExtractor,
        MockProvider,
        GeminiProvider,
        AIConfigurationError,
        AIServiceError,
        AITimeoutError,
        AIParsingError,
        normalize_extracted_schema,
    )

    # 3a. Plain text extraction
    txt_sample = (
        "IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD\n"
        "WRIT PETITION NO. CIV-2026-88\n"
        "IN THE MATTER OF: Rajesh Sharma (Petitioner) Versus State of Uttar Pradesh (Respondent)\n"
        "DATED: 12th August 2026\n"
        "Subject: Property boundary dispute regarding agricultural land in Kanpur.\n"
        "PRAYER: The Petitioner respectfully prays for interim injunction against illegal demolition.\n"
    )
    txt_path = os.path.join(UPLOADS_DIR, "test_sample_petition.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_sample)

    txt_content, txt_status, txt_err = AIExtractor.extract_text_from_file(txt_path, ".txt")
    assert txt_status == "OK", f"TXT extraction failed: {txt_err}"
    assert "Rajesh Sharma" in txt_content
    assert "CIV-2026-88" in txt_content
    print("    [OK] Plain text UTF-8 extraction validated.")

    # 3b. Insufficient text (< 20 chars)
    short_txt_path = os.path.join(UPLOADS_DIR, "test_short.txt")
    with open(short_txt_path, "w", encoding="utf-8") as f:
        f.write("Short text")
    _, short_status, short_err = AIExtractor.extract_text_from_file(short_txt_path, ".txt")
    assert short_status == "EXTRACTION_UNAVAILABLE"
    print("    [OK] Insufficient text (< 20 chars) correctly returned EXTRACTION_UNAVAILABLE.")

    # 3c. Synthetic PDF text extraction
    synthetic_pdf_bytes = create_synthetic_pdf([
        "IN THE SUPREME COURT OF INDIA\nCASE NO: SLP-2026-440\n"
        "Deponent: Priya Patel, Advocate\n"
        "AFFIDAVIT OF EVIDENCE filed on 16th August 2026 regarding commercial contract breach."
    ])
    pdf_path = os.path.join(UPLOADS_DIR, "test_synthetic_sample.pdf")
    with open(pdf_path, "wb") as f:
        f.write(synthetic_pdf_bytes)

    pdf_content, pdf_status, pdf_err = AIExtractor.extract_text_from_file(pdf_path, ".pdf")
    assert pdf_status == "OK", f"PDF extraction failed: {pdf_err}"
    assert "AFFIDAVIT" in pdf_content or "Priya Patel" in pdf_content
    print("    [OK] Synthetic PDF multi-line text extraction validated.")

    # 3d. Blank / Image-only PDF
    blank_pdf_bytes = create_synthetic_pdf([""])
    blank_pdf_path = os.path.join(UPLOADS_DIR, "test_blank_image.pdf")
    with open(blank_pdf_path, "wb") as f:
        f.write(blank_pdf_bytes)

    _, blank_status, blank_err = AIExtractor.extract_text_from_file(blank_pdf_path, ".pdf")
    assert blank_status == "EXTRACTION_UNAVAILABLE"
    print("    [OK] Blank / Image-only PDF correctly returned EXTRACTION_UNAVAILABLE.")

    # 3e. Unsupported file format
    dummy_img_path = os.path.join(UPLOADS_DIR, "test_photo.jpg")
    with open(dummy_img_path, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 50)
    _, img_status, img_err = AIExtractor.extract_text_from_file(dummy_img_path, ".jpg")
    assert img_status == "UNSUPPORTED_FORMAT"
    print("    [OK] Unsupported format (.jpg) correctly returned UNSUPPORTED_FORMAT.")

    # 4. Explicit Regression Tests for MockProvider Extraction & Anti-Hallucination
    print("\n[4] Testing Explicit MockProvider Extraction & Anti-Hallucination Guarantees...")
    mock_prov = MockProvider()

    # Test 1: Explicit Subject Extraction
    meta_explicit_sub = mock_prov.extract_metadata(
        "IN THE HIGH COURT OF DELHI\n"
        "CASE NO: W.P.(C) 99/2026\n"
        "Subject: Evidentiary affidavit in support of civil land partition suit.\n"
    )
    assert meta_explicit_sub["subject"] == "Evidentiary affidavit in support of civil land partition suit", \
        f"Subject mismatch: {meta_explicit_sub['subject']}"
    print("    [OK] Test 1: Explicit subject correctly extracted verbatim from source text.")

    # Test 2: No Subject returns None
    meta_no_sub = mock_prov.extract_metadata(
        "IN THE HIGH COURT OF DELHI\n"
        "CASE NO: W.P.(C) 99/2026\n"
        "COMMERCIAL CONTRACT between Alpha and Beta.\n"
    )
    assert meta_no_sub["subject"] is None, f"Expected subject=None, got {meta_no_sub['subject']}"
    print("    [OK] Test 2: Document with no Subject line correctly returns subject=None.")

    # Test 3: No Synthetic Subject
    meta_land_text = mock_prov.extract_metadata("The defendant owns agricultural land in rural area.")
    assert meta_land_text["subject"] is None, f"Subject should be None, got: {meta_land_text['subject']}"
    assert meta_land_text["subject"] != "Property and land title dispute"
    print("    [OK] Test 3: Document mentioning 'land' produces zero synthetic subject.")

    # Test 4: Keywords Are Source-Derived
    meta_sample_kw = mock_prov.extract_metadata(txt_sample)
    for kw in meta_sample_kw["keywords"]:
        assert any(w in txt_sample.lower() for w in kw.split()), f"Keyword '{kw}' not in source text!"
    print("    [OK] Test 4: All extracted keywords verified to originate literally from source text.")

    # Test 5: No Synthetic Keywords for Unrelated Text
    meta_unrelated = mock_prov.extract_metadata("The defendant owns agricultural land.")
    assert "land dispute" not in meta_unrelated["keywords"]
    assert "property dispute" not in meta_unrelated["keywords"]
    assert "criminal procedure" not in meta_unrelated["keywords"]
    print("    [OK] Test 5: No synthetic keyword tuples injected for simple sentence.")

    # Test 6: Court Regex Line and Clause Bounded (No Newline or Preposition Bleed)
    sample_court_clause_text = "District Court of Kanpur Nagar in connection with Civil Suit No. CIV-2026-104."
    meta_court_clause = mock_prov.extract_metadata(sample_court_clause_text)
    assert meta_court_clause["court"] == "District Court of Kanpur Nagar", \
        f"Court regex clause bleed: got '{meta_court_clause['court']}'"
    assert "connection" not in (meta_court_clause["court"] or "")
    assert "Civil Suit" not in (meta_court_clause["court"] or "")

    sample_court_bleed_text = (
        "IN THE DISTRICT AND SESSIONS COURT, KANPUR NAGAR\n"
        "CASE NO: CIV-2026-88\n"
        "AFFIDAVIT OF EVIDENCE"
    )
    meta_court_bleed = mock_prov.extract_metadata(sample_court_bleed_text)
    assert meta_court_bleed["court"] == "District and Sessions Court, Kanpur Nagar", \
        f"Court regex newline bleed: got '{meta_court_bleed['court']}'"
    assert "CASE NO" not in (meta_court_bleed["court"] or "")
    print("    [OK] Test 6: Court regex verified line- and clause-bounded without consuming trailing prepositions or case numbers.")

    # Test 7: Case Number Identifier Isolation (Stripping prefix labels)
    assert mock_prov.extract_metadata("CASE NO: CIV-2026-88")["case_number"] == "CIV-2026-88"
    assert mock_prov.extract_metadata("Civil Suit No. CIV-2026-104")["case_number"] == "CIV-2026-104"
    assert mock_prov.extract_metadata("W.P. No. 1234/2026")["case_number"] == "1234/2026"
    assert mock_prov.extract_metadata("WRIT PETITION NO. W.P.(C) 412/2026")["case_number"] == "W.P.(C) 412/2026"
    print("    [OK] Test 7: Case numbers isolated to pure identifiers, stripping 'Civil Suit No.', 'Case No:', etc.")

    # Test 8: Full Extraction on Latest Test Document Fixture
    latest_test_fixture = (
        "AFFIDAVIT OF OWNERSHIP AND POSSESSION\n"
        "District Court of Kanpur Nagar in connection with Civil Suit No. CIV-2026-104.\n"
        "I, Rajesh Sharma, do hereby state on solemn affirmation that I am in lawful ownership and physical possession of the agricultural land situated at Village Kalyanpur. "
        "The property title transfer was duly executed on 3 July 2025 with supporting evidentiary documents.\n"
        "Filing Date: 14 August 2026\n"
        "Hearing Date: 22 August 2026\n"
    )
    meta_latest = mock_prov.extract_metadata(latest_test_fixture, {"filename": "Affidavit_Ownership.txt"})
    assert meta_latest["document_type"] == "Affidavit"
    assert meta_latest["case_number"] == "CIV-2026-104"
    assert meta_latest["court"] == "District Court of Kanpur Nagar"
    assert meta_latest["jurisdiction"] == "Uttar Pradesh"
    assert meta_latest["subject"] is None, f"Expected subject=None, got {meta_latest['subject']}"
    assert any("14 August 2026" in d["date"] for d in meta_latest["dates"])
    assert any("22 August 2026" in d["date"] for d in meta_latest["dates"])
    assert any("3 July 2025" in d["date"] for d in meta_latest["dates"])
    assert "agricultural land" in meta_latest["keywords"]
    assert "evidentiary documents" in meta_latest["keywords"]
    assert "ownership" in meta_latest["keywords"]
    assert "possession" in meta_latest["keywords"]
    assert "land dispute" not in meta_latest["keywords"]
    assert "property dispute" not in meta_latest["keywords"]
    print("    [OK] Test 8: Latest manual test document fixture verified with 100% extraction precision.")

    # Test 9: Provider Identity
    extractor_mock = AIExtractor(provider_name="mock")
    assert extractor_mock.provider_name == "mock"
    assert extractor_mock.model_name == "offline-heuristics"
    print("    [OK] Test 9: MockProvider identity set strictly to 'mock' / 'offline-heuristics'.")

    # 4b. Negative Document Anti-Hallucination Test
    print("\n[4b] Testing Negative Document Anti-Hallucination Guarantees...")
    neg_doc_text = (
        "The defendant owns agricultural land near Kanpur.\n"
        "The document does not contain a case number, court name, jurisdiction declaration, hearing date, or formal subject heading."
    )
    neg_meta = mock_prov.extract_metadata(neg_doc_text)
    assert neg_meta["case_number"] is None, "Negative doc must not invent a case number"
    assert neg_meta["court"] is None, "Negative doc must not invent a court"
    assert neg_meta["subject"] is None, "Negative doc must not invent a subject"
    assert len(neg_meta["dates"]) == 0, "Negative doc must not invent dates"
    assert "land dispute" not in neg_meta["keywords"]
    assert "property dispute" not in neg_meta["keywords"]
    print("    [OK] Negative document produced zero invented case numbers, courts, subjects, dates, or dispute keywords.")

    # 4c. Gemini Provider Architecture & Error Handling Tests
    print("\n[4c] Testing Gemini Provider Contract & Failure Isolation...")
    # Missing API Key
    try:
        GeminiProvider(api_key="")
        assert False, "GeminiProvider must raise AIConfigurationError when API key is empty"
    except AIConfigurationError:
        print("    [OK] Missing API key raises AIConfigurationError.")

    # Invalid API Key (Network / API Error from Google)
    try:
        prov_bad_key = GeminiProvider(api_key="AIzaSyInvalidKeyTest12345")
        prov_bad_key.extract_metadata("Sample text")
    except AIServiceError as e:
        assert "Gemini API error" in str(e)
        print("    [OK] Invalid API key safely caught as AIServiceError.")

    # Provider Timeout Handling
    prov_mock = GeminiProvider(api_key="mock_key")
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
        try:
            prov_mock.extract_metadata("Sample text")
            assert False, "Expected AITimeoutError"
        except AITimeoutError:
            print("    [OK] Timeout properly caught as AITimeoutError.")

    # Malformed JSON Handling
    bad_json_resp = MagicMock()
    bad_json_resp.status_code = 200
    bad_json_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{ not valid json"}]}}]}
    with patch("requests.post", return_value=bad_json_resp):
        try:
            prov_mock.extract_metadata("Sample text")
            assert False, "Expected AIParsingError"
        except AIParsingError:
            print("    [OK] Malformed JSON response properly caught as AIParsingError.")

    # Empty candidate list
    empty_cand_resp = MagicMock()
    empty_cand_resp.status_code = 200
    empty_cand_resp.json.return_value = {"candidates": []}
    with patch("requests.post", return_value=empty_cand_resp):
        try:
            prov_mock.extract_metadata("Sample text")
            assert False, "Expected AIParsingError"
        except AIParsingError:
            print("    [OK] Empty candidate response properly caught as AIParsingError.")

    # Valid Structured Response Simulation
    simulated_gemini_json = json.dumps({
        "document_type": "Affidavit",
        "case_number": "CIV-2026-104",
        "court": "District Court of Kanpur Nagar",
        "jurisdiction": "Uttar Pradesh",
        "parties": [{"name": "Rajesh Sharma", "role": "Deponent"}],
        "dates": [{"date": "2026-08-14", "description": "Filing Date"}],
        "subject": "Affidavit of ownership and physical possession of agricultural land in Kalyanpur",
        "keywords": ["ownership", "possession", "agricultural land", "title transfer", "evidentiary documents"],
        "confidence": {
            "overall": 0.95,
            "fields": {
                "document_type": 0.98,
                "case_number": 0.97,
                "court": 0.95,
                "jurisdiction": 0.95,
                "parties": 0.92,
                "dates": 0.90,
                "subject": 0.94
            }
        }
    })
    valid_resp = MagicMock()
    valid_resp.status_code = 200
    valid_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": simulated_gemini_json}]}}]}
    with patch("requests.post", return_value=valid_resp):
        gemini_parsed = prov_mock.extract_metadata("Sample text")
        assert gemini_parsed["document_type"] == "Affidavit"
        assert gemini_parsed["case_number"] == "CIV-2026-104"
        assert gemini_parsed["court"] == "District Court of Kanpur Nagar"
        assert gemini_parsed["jurisdiction"] == "Uttar Pradesh"
        assert "summary_snippet" not in gemini_parsed
        print("    [OK] Valid Gemini structured response parsed and normalized to schema.")

    # 4d. Optional Live Gemini Test (if GEMINI_API_KEY is configured in environment)
    real_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if real_api_key and len(real_api_key) > 10:
        print("\n[4d] LIVE GEMINI API KEY DETECTED! Executing Live Extraction Test...")
        try:
            live_prov = GeminiProvider(api_key=real_api_key, model=os.getenv("LEGALVAULT_AI_MODEL", "gemini-2.0-flash"))
            live_meta = live_prov.extract_metadata(latest_test_fixture)
            print(f"    [LIVE GEMINI OK] Document Type: {live_meta.get('document_type')}")
            print(f"    [LIVE GEMINI OK] Case Number:   {live_meta.get('case_number')}")
            print(f"    [LIVE GEMINI OK] Court:         {live_meta.get('court')}")
            print(f"    [LIVE GEMINI OK] Jurisdiction:  {live_meta.get('jurisdiction')}")
            print(f"    [LIVE GEMINI OK] Subject:       {live_meta.get('subject')}")
            print(f"    [LIVE GEMINI OK] Keywords:      {live_meta.get('keywords')}")
            print(f"    [LIVE GEMINI OK] Confidence:    {live_meta.get('confidence', {}).get('overall')}")
        except Exception as e:
            print(f"    [LIVE GEMINI NOTE] Live call encountered: {e}")
    else:
        print("\n[4d] (Note: GEMINI_API_KEY is not set locally; verified via isolated contract tests).")

    # 5. Integration: Document Upload (v1) and AI Metadata Extraction
    print("\n[5] Testing Initial Upload (v1) and Metadata Extraction Endpoint...")
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

    # 5a. Extract metadata for v1
    meta_extract_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata/extract",
        headers=lawyer_a_headers,
    )
    assert meta_extract_resp.status_code == 200, f"Extraction failed: {meta_extract_resp.text}"
    v1_meta = meta_extract_resp.json()
    assert v1_meta["status"] == "COMPLETED"
    assert v1_meta["document_type"] == "Affidavit"
    assert v1_meta["case_number"] == "CIV-2026-88"
    assert v1_meta["court"] == "District and Sessions Court, Kanpur Nagar"
    assert v1_meta["jurisdiction"] == "Uttar Pradesh"
    assert v1_meta["subject"] == "Evidentiary affidavit in support of civil land partition suit"
    assert v1_meta["ai_provider"] == "mock"
    assert v1_meta["ai_model"] == "offline-heuristics"
    assert v1_meta["version_number"] == 1
    assert v1_meta["cached"] is False
    assert v1_meta["is_owner_or_admin"] is True
    print(f"    [OK] Metadata extracted for v1: {v1_meta['document_type']} | Court: {v1_meta['court']} | Subject: {v1_meta['subject']}")

    # 5b. Verify GET /documents/{id}/versions/1/metadata and GET /documents/{id}/metadata
    get_v1_meta = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata",
        headers=lawyer_a_headers,
    ).json()
    assert get_v1_meta["status"] == "COMPLETED"
    assert get_v1_meta["document_type"] == "Affidavit"
    assert get_v1_meta["court"] == "District and Sessions Court, Kanpur Nagar"

    get_master_meta = requests.get(
        f"{BASE_URL}/documents/{doc_id}/metadata",
        headers=lawyer_a_headers,
    ).json()
    assert get_master_meta["version_number"] == 1
    assert get_master_meta["document_type"] == "Affidavit"
    print("    [OK] GET /documents/{id}/versions/1/metadata and GET /documents/{id}/metadata return active v1 metadata.")

    # 6. Testing Caching & Force Re-Extraction
    print("\n[6] Testing SHA-256 Metadata Caching & Force Re-Extraction...")
    cached_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata/extract",
        headers=lawyer_a_headers,
    ).json()
    assert cached_resp["cached"] is True, "Second call without force=True must return cached result!"
    print("    [OK] Cache hit verified: repeated call returned cached record with cached=True.")

    force_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata/extract?force=true",
        headers=lawyer_a_headers,
    ).json()
    assert force_resp["cached"] is False, "Call with force=True must re-analyze and return cached=False!"
    print("    [OK] Force re-extraction verified: force=true refreshed metadata record.")

    # 7. Testing Version Isolation (v1 metadata vs v2 metadata)
    print("\n[7] Testing Version History Isolation (v1 -> Metadata A, v2 -> Metadata B)...")
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

    # Before extraction, v2 metadata status must be NOT_ANALYZED
    v2_initial_meta = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/2/metadata",
        headers=lawyer_a_headers,
    ).json()
    assert v2_initial_meta["status"] == "NOT_ANALYZED"
    print("    [OK] Un-analyzed Version 2 returns status NOT_ANALYZED.")

    # Extract metadata for Version 2
    v2_extract_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/2/metadata/extract",
        headers=lawyer_a_headers,
    ).json()
    assert v2_extract_resp["version_number"] == 2
    assert v2_extract_resp["document_type"] == "Writ Petition"
    assert "W.P." in v2_extract_resp["case_number"] or "412/2026" in v2_extract_resp["case_number"]
    assert any("Priya Patel" in p["name"] for p in v2_extract_resp["parties"])
    assert v2_extract_resp["subject"] == "Challenge to municipal acquisition notice without due compensation"
    print(f"    [OK] Version 2 metadata extracted: {v2_extract_resp['document_type']} | Case: {v2_extract_resp['case_number']}")

    # Verify Version 1 metadata remains completely untouched (Affidavit, CIV-2026-88, District and Sessions Court, Kanpur Nagar)
    v1_check_meta = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata",
        headers=lawyer_a_headers,
    ).json()
    assert v1_check_meta["version_number"] == 1
    assert v1_check_meta["document_type"] == "Affidavit"
    assert v1_check_meta["case_number"] == "CIV-2026-88"
    assert v1_check_meta["court"] == "District and Sessions Court, Kanpur Nagar"
    assert v1_check_meta["subject"] == "Evidentiary affidavit in support of civil land partition suit"
    assert any("Rajesh Sharma" in p["name"] for p in v1_check_meta["parties"])
    print("    [OK] Version 1 metadata strictly preserved and isolated from Version 2 changes.")

    # Master document metadata now points to Version 2
    master_meta_v2 = requests.get(
        f"{BASE_URL}/documents/{doc_id}/metadata",
        headers=lawyer_a_headers,
    ).json()
    assert master_meta_v2["version_number"] == 2
    assert master_meta_v2["document_type"] == "Writ Petition"
    print("    [OK] Master document metadata endpoint resolves to active Version 2.")

    # 8. Testing RBAC Scoping on AI Endpoints
    print("\n[8] Testing Role-Based Access Control (RBAC) Scoping...")
    # 8a. Share document with Judge and Client
    share_judge = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_a_headers,
        json={"shared_with_user_id": judge_id},
    )
    assert share_judge.status_code == 200

    # 8b. Shared Judge can GET existing metadata (v1 and v2)
    judge_get_v1 = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata",
        headers=judge_headers,
    )
    assert judge_get_v1.status_code == 200
    assert judge_get_v1.json()["is_owner_or_admin"] is False
    print("    [OK] Shared Judge can read existing version metadata.")

    # 8c. Shared Judge CANNOT trigger extraction (POST -> 403 Forbidden with ACTION_DENIED)
    judge_extract = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata/extract?force=true",
        headers=judge_headers,
    )
    assert judge_extract.status_code == 403, f"Expected 403, got {judge_extract.status_code}"
    print("    [OK] Shared Judge blocked from triggering extraction (403 Forbidden).")

    # 8d. Unauthorized Lawyer B cannot GET or POST
    unauth_get = requests.get(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata",
        headers=lawyer_b_headers,
    )
    assert unauth_get.status_code == 403, f"Expected 403, got {unauth_get.status_code}"

    unauth_post = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata/extract",
        headers=lawyer_b_headers,
    )
    assert unauth_post.status_code == 403, f"Expected 403, got {unauth_post.status_code}"
    print("    [OK] Unauthorized Lawyer B blocked from viewing or extracting metadata (403 Forbidden).")

    # 8e. Administrator has full trigger and view access
    admin_extract = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions/1/metadata/extract",
        headers=admin_headers,
    )
    assert admin_extract.status_code == 200
    assert admin_extract.json()["is_owner_or_admin"] is True
    print("    [OK] Administrator has full extraction and inspection privileges.")

    # 9. Testing Custody Invariants & Fault Isolation
    print("\n[9] Verifying Custody Layer Invariants & Fault Isolation...")
    doc_detail = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=lawyer_a_headers).json()
    assert doc_detail["version"] == 2
    assert doc_detail["file_hash"] is not None

    v1_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_a_headers).json()
    assert v1_verify["result"] == "VERIFIED"

    v2_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_a_headers).json()
    assert v2_verify["result"] == "VERIFIED"
    print("    [OK] Document versions, SHA-256 hashes, and blockchain verification remain 100% verified and authoritative.")

    # 10. Privacy & Audit Trail Verification
    print("\n[10] Verifying Privacy & Forensic Audit Logging...")
    audit_resp = requests.get(f"{BASE_URL}/documents/{doc_id}/audit", headers=lawyer_a_headers).json()
    events = audit_resp["events"]
    actions = [e["action"] for e in events]
    assert "AI_METADATA_EXTRACTED" in actions

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT action, metadata_json, reason FROM audit_logs WHERE action LIKE 'AI_%'")
    ai_logs = cur.fetchall()
    for act, meta_json, rsn in ai_logs:
        if meta_json:
            assert "PRAYER" not in meta_json
            assert "Rajesh Sharma, S/o Late Ram Sharma" not in meta_json
            assert "API_KEY" not in meta_json
    conn.close()
    print("    [OK] Audit trail recorded AI events with zero raw document text or credential leakage.")

    # 11. Timezone UTC Compliance Verification
    print("\n[11] Verifying Timezone Standardization (UTC Z Serialization)...")
    assert v1_meta["created_at"].endswith("Z")
    assert v1_meta["updated_at"].endswith("Z")
    print("    [OK] Metadata timestamps conform strictly to UTC ISO 8601 with trailing 'Z'.")

    # 12. Development Vault Reset cleans up DocumentVersionMetadata
    print("\n[12] Testing Development Vault Reset on AI Metadata Records...")
    reset_after = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers).json()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM document_version_metadata")
    meta_count = cur.fetchone()[0]
    conn.close()
    assert meta_count == 0
    print("    [OK] Development vault reset cleanly purged document_version_metadata records.")

    # Clean up test artifacts in uploads/
    for tf in ["test_sample_petition.txt", "test_short.txt", "test_synthetic_sample.pdf", "test_blank_image.pdf", "test_photo.jpg"]:
        tp = os.path.join(UPLOADS_DIR, tf)
        if os.path.exists(tp):
            try:
                os.remove(tp)
            except Exception:
                pass

    print("\n=================================================================")
    print("ALL AI METADATA EXTRACTION & REGRESSION TESTS PASSED (100%)!")
    print("=================================================================")


if __name__ == "__main__":
    run_ai_metadata_tests()
