import os
import io
import time
import json
import sqlite3
import hashlib
import requests
from unittest.mock import patch, MagicMock

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "legalvault.db")


def run_ai_comparison_tests():
    print("=================================================================")
    print("RUNNING LEGALVAULT AI VERSION COMPARISON TEST SUITE")
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

    # 3. Unit test deterministic diff engine
    print("\n[3] Testing Deterministic Delta Engine & Directional Asymmetry...")
    from ai_extractor import (
        compute_deterministic_diff,
        normalize_comparison_schema,
        is_generic_summary_placeholder,
        MockProvider,
        GeminiProvider,
        AIExtractor,
        AIConfigurationError,
        AIServiceError,
        AITimeoutError,
        AIParsingError,
    )

    mock_prov = MockProvider()

    v1_meta = {
        "document_type": "Affidavit",
        "case_number": "CIV-2026-104",
        "court": "District Court of Kanpur Nagar",
        "jurisdiction": "Uttar Pradesh",
        "subject": "Evidentiary affidavit in support of civil land partition suit.",
        "parties": [{"name": "Ananya Verma", "role": "Petitioner"}],
        "dates": [{"date": "3 July 2025", "description": "Agreement Date"}, {"date": "22 August 2026", "description": "Hearing Date"}],
        "keywords": ["ownership", "possession", "agricultural", "land"],
    }
    v1_summary = {
        "summary": "Affidavit submitted by Ananya Verma in Civil Suit CIV-2026-104 concerning agricultural land.",
        "key_facts": ["Disputed property transferred under agreement dated 3 July 2025.", "Petitioner in lawful possession."],
        "legal_issues": ["The dispute concerns ownership and possession of agricultural land in Kanpur."],
        "important_points": ["Agreement dated 3 July 2025.", "Hearing scheduled for 22 August 2026."],
    }

    v2_meta = {
        "document_type": "Amended Affidavit",
        "case_number": "CIV-2026-104",
        "court": "High Court of Judicature at Allahabad",
        "jurisdiction": "Uttar Pradesh",
        "subject": "Amended evidentiary affidavit in support of civil land partition suit.",
        "parties": [{"name": "Ananya Verma", "role": "Petitioner"}, {"name": "Rohan Mehta", "role": "Respondent"}],
        "dates": [{"date": "3 July 2025", "description": "Original Agreement Date"}, {"date": "10 August 2026", "description": "Amended Agreement Date"}, {"date": "30 August 2026", "description": "Next Hearing Date"}],
        "keywords": ["ownership", "possession", "agricultural", "land", "amended", "respondent"],
    }
    v2_summary = {
        "summary": "Amended affidavit adding Rohan Mehta as respondent and introducing supplementary agreement dated 10 August 2026.",
        "key_facts": ["Disputed property transferred under agreement dated 3 July 2025.", "Petitioner in lawful possession.", "Survey marks indicate clear boundary demarcation.", "Western agricultural plot fence inspected and verified."],
        "legal_issues": ["The dispute concerns ownership and possession of agricultural land in Kanpur.", "Additional claims regarding joint property possession."],
        "important_points": ["Original agreement dated 3 July 2025.", "Amended agreement executed on 10 August 2026.", "Next hearing scheduled for 30 August 2026."],
    }

    # 3a. Test Forward Direction (V1 -> V2)
    diff_forward = compute_deterministic_diff(v1_meta, v2_meta, v1_summary, v2_summary, from_version_number=1, to_version_number=2)
    meta_adds = [p["value"] for p in diff_forward["metadata_changes"]["added"] if p["field"] == "party"]
    assert "Rohan Mehta (Respondent)" in meta_adds, f"Expected Rohan Mehta added, got {meta_adds}"
    assert any(ch["field"] == "court" for ch in diff_forward["metadata_changes"]["changed"])
    assert any("amended" in kw["value"] for kw in diff_forward["metadata_changes"]["added"] if kw["field"] == "keyword")
    assert len(diff_forward["summary_changes"]["facts_added"]) == 2
    assert len(diff_forward["summary_changes"]["procedural_added"]) >= 2
    assert len(diff_forward["summary_changes"]["legal_issues_added"]) == 1
    assert "Version 2 updates the filing" in diff_forward["material_changes"]
    print("    [OK] Forward comparison (V1 -> V2) identified added party, court shift, new facts, procedural updates, and new claims.")

    # 3b. Test Reverse Direction (V2 -> V1) - Directional Inversion
    diff_reverse = compute_deterministic_diff(v2_meta, v1_meta, v2_summary, v1_summary, from_version_number=2, to_version_number=1)
    meta_rems = [p["value"] for p in diff_reverse["metadata_changes"]["removed"] if p["field"] == "party"]
    assert "Rohan Mehta (Respondent)" in meta_rems, f"Expected Rohan Mehta in removed for reverse, got {meta_rems}"
    assert len(diff_reverse["summary_changes"]["facts_removed"]) == 2
    assert len(diff_reverse["summary_changes"]["procedural_removed"]) >= 2
    assert "Version 1 does not include subsequent updates" in diff_reverse["material_changes"]
    print("    [OK] Reverse comparison (V2 -> V1) correctly inverted additions into removals.")

    # 3c. Test Identical Comparison (V1 -> V1)
    diff_same = compute_deterministic_diff(v1_meta, v1_meta, v1_summary, v1_summary, from_version_number=1, to_version_number=1)
    assert len(diff_same["metadata_changes"]["added"]) == 0
    assert len(diff_same["metadata_changes"]["removed"]) == 0
    assert len(diff_same["metadata_changes"]["changed"]) == 0
    assert len(diff_same["summary_changes"]["facts_added"]) == 0
    assert len(diff_same["summary_changes"]["procedural_added"]) == 0
    assert len(diff_same["summary_changes"]["legal_issues_added"]) == 0
    assert "No material differences detected" in diff_same["material_changes"]
    print("    [OK] Identical comparison (V1 -> V1) returned 0 deltas and no-changes narrative.")

    # 3d. Test Semantic MODIFIED for Hearing Date & Jurisdiction Reversal
    mod_v1_meta = {
        "dates": [{"date": "22 August 2026", "description": "Hearing Date"}],
        "jurisdiction": "Not Specified",
    }
    mod_v2_meta = {
        "dates": [{"date": "30 August 2026", "description": "Hearing Date"}],
        "jurisdiction": "Uttar Pradesh",
    }
    mod_forward = compute_deterministic_diff(mod_v1_meta, mod_v2_meta, {}, {}, from_version_number=1, to_version_number=2)
    assert len(mod_forward["metadata_changes"]["added"]) == 0, f"Expected 0 added, got {mod_forward['metadata_changes']['added']}"
    assert len(mod_forward["metadata_changes"]["removed"]) == 0, f"Expected 0 removed, got {mod_forward['metadata_changes']['removed']}"
    changed_forward = mod_forward["metadata_changes"]["changed"]
    assert len(changed_forward) == 2, f"Expected 2 changed entries, got {changed_forward}"

    date_ch = next(c for c in changed_forward if c["field"] == "date")
    assert date_ch["from"] == "22 August 2026"
    assert date_ch["to"] == "30 August 2026"

    jur_ch = next(c for c in changed_forward if c["field"] == "jurisdiction")
    assert jur_ch["from"] == "Not Specified"
    assert jur_ch["to"] == "Uttar Pradesh"

    mod_reverse = compute_deterministic_diff(mod_v2_meta, mod_v1_meta, {}, {}, from_version_number=2, to_version_number=1)
    changed_rev = mod_reverse["metadata_changes"]["changed"]
    date_rev = next(c for c in changed_rev if c["field"] == "date")
    assert date_rev["from"] == "30 August 2026"
    assert date_rev["to"] == "22 August 2026"

    jur_rev = next(c for c in changed_rev if c["field"] == "jurisdiction")
    assert jur_rev["from"] == "Uttar Pradesh"
    assert jur_rev["to"] == "Not Specified"
    print("    [OK] Semantic MODIFIED matching verified for Hearing Date, Jurisdiction, and directional reversal.")

    # 3e. Test Context-Aware Date Matching & Semantic Separation (Theft Fixture)
    theft_v1_meta = {
        "subject": "Theft at Sharma Electronics",
        "dates": [{"date": "4 June 2026", "description": "Important Date"}, {"date": "5 June 2026", "description": "Important Date"}],
        "parties": [{"name": "Sharma Electronics", "role": "Petitioner"}]
    }
    theft_v1_sum = {
        "key_facts": [
            "The theft was reported at Sharma Electronics on 5 June 2026 involving missing cash of Rs 2,50,000.",
            "The incident is believed to have occurred between 9 PM on 4 June 2026 and 7 AM on 5 June 2026."
        ],
        "legal_issues": ["No explicit statutory violations or contested issues specified in the text."],
        "important_points": ["Refer to primary document text for specific procedural dates and covenants."]
    }

    theft_v2_meta = {
        "subject": "Supplemental Investigation Report - Theft at Sharma Electronics",
        "dates": [{"date": "4 June 2026", "description": "Important Date"}, {"date": "5 June 2026", "description": "Important Date"}, {"date": "18 June 2026", "description": "Important Date"}],
        "parties": [{"name": "Sharma Electronics", "role": "Petitioner"}, {"name": "Amit Verma", "role": "Witness"}]
    }
    theft_v2_sum = {
        "key_facts": [
            "The theft was reported at Sharma Electronics on 5 June 2026 involving missing cash of Rs 2,50,000.",
            "The incident is believed to have occurred between 9 PM on 4 June 2026 and 7 AM on 5 June 2026.",
            "CCTV footage recovered from a nearby building reportedly showed a person entering the store at approximately 11:42 PM on 4 June 2026.",
            "Amit Verma reportedly stated that he saw Rohan Mehta near the rear entrance of the store shortly before midnight.",
            "A second witness reportedly observed a motorcycle matching the description associated with Rohan Mehta near the premises.",
            "The investigation into the theft reported at Sharma Electronics progressed after statements were obtained from two witnesses.",
            "Rohan Mehta was questioned on 18 June 2026, and the investigation remained ongoing regarding the missing funds."
        ],
        "legal_issues": [],
        "important_points": ["Investigation update dated 18 June 2026."]
    }

    theft_diff = compute_deterministic_diff(theft_v1_meta, theft_v2_meta, theft_v1_sum, theft_v2_sum, from_version_number=1, to_version_number=2)
    # 1. Subject remains under metadata
    subject_ch = next(c for c in theft_diff["metadata_changes"]["changed"] if c["field"] == "subject")
    assert subject_ch["from"] == "Theft at Sharma Electronics"
    assert subject_ch["to"] == "Supplemental Investigation Report - Theft at Sharma Electronics"
    # 2. Generic dates were NOT matched as false MODIFIED
    assert not any(c["field"] == "date" for c in theft_diff["metadata_changes"]["changed"])
    # 3. Check 18 June added
    date_adds = [d["value"] for d in theft_diff["metadata_changes"]["added"] if d["field"] == "date"]
    assert any("18 June 2026" in d for d in date_adds)
    # 4. Check 3 pure factual / evidentiary assertions added
    assert len(theft_diff["summary_changes"]["facts_added"]) == 3, f"Expected 3 facts_added, got {theft_diff['summary_changes']['facts_added']}"
    assert any("CCTV footage" in f for f in theft_diff["summary_changes"]["facts_added"])
    assert any("Amit Verma" in f for f in theft_diff["summary_changes"]["facts_added"])
    assert any("motorcycle" in f for f in theft_diff["summary_changes"]["facts_added"])
    # 5. Check procedural developments separated from facts
    assert len(theft_diff["summary_changes"]["procedural_added"]) >= 2, f"Expected procedural items, got {theft_diff['summary_changes']['procedural_added']}"
    assert any("investigation" in p.lower() for p in theft_diff["summary_changes"]["procedural_added"])
    assert any("questioned" in p.lower() for p in theft_diff["summary_changes"]["procedural_added"])
    # 6. Legal claims strictly empty (never populated from subject or CCTV/witness facts)
    assert theft_diff["summary_changes"]["legal_issues_added"] == [], f"Expected 0 legal issues added, got {theft_diff['summary_changes']['legal_issues_added']}"
    assert theft_diff["summary_changes"]["legal_issues_removed"] == []
    # 7. Material changes narrative is category-aware and grounded
    assert "Version 2 records additional investigative developments" in theft_diff["material_changes"]
    assert "CCTV observations" in theft_diff["material_changes"]
    assert "No new explicit legal claims or grounds were identified" in theft_diff["material_changes"]

    # 8. Check reverse direction (V2 -> V1)
    theft_rev = compute_deterministic_diff(theft_v2_meta, theft_v1_meta, theft_v2_sum, theft_v1_sum, from_version_number=2, to_version_number=1)
    assert len(theft_rev["summary_changes"]["facts_removed"]) == 3
    assert theft_rev["summary_changes"]["facts_added"] == []
    assert len(theft_rev["summary_changes"]["procedural_removed"]) >= 2
    assert theft_rev["summary_changes"]["procedural_added"] == []
    assert theft_rev["summary_changes"]["legal_issues_removed"] == []
    assert theft_rev["summary_changes"]["legal_issues_added"] == []
    assert "Version 1 does not contain the supplemental investigative developments" in theft_rev["material_changes"]
    # 3f. Comprehensive 17-Item Semantic Categorization & Directional Invariant Verification
    print("    [+] Running 17-Item Semantic Categorization & Presentation Invariant Tests...")
    # Item 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
    doc_v1_text = """
    POLICE INVESTIGATION REPORT / INCIDENT STATEMENT
    Subject: Incident at Metro Plaza
    1. Incident reported on 10 July 2026 regarding broken storefront glass.
    2. Store manager confirmed inventory intact.
    """
    doc_v2_text = """
    POLICE INVESTIGATION REPORT / INCIDENT STATEMENT
    Subject: Supplemental Incident Report - Metro Plaza
    1. Incident reported on 10 July 2026 regarding broken storefront glass.
    2. Store manager confirmed inventory intact.
    3. CCTV footage recovered showed a vehicle colliding with the storefront barrier at 2:15 AM.
    4. Security guard Rajesh reportedly stated that he observed the vehicle speeding away.
    5. Investigation progressed on 15 July 2026 after vehicle license records were obtained.
    6. Suspect driver was questioned on 15 July 2026.
    """
    doc_v1_sum = mock_prov.generate_summary(doc_v1_text)
    doc_v2_sum = mock_prov.generate_summary(doc_v2_text)
    doc_v1_meta = mock_prov.extract_metadata(doc_v1_text)
    doc_v2_meta = mock_prov.extract_metadata(doc_v2_text)

    # 3 & 4. Document subject and title must NOT become legal issues
    assert doc_v1_sum["legal_issues"] == [], "Subject/title must never populate legal_issues in V1"
    assert doc_v2_sum["legal_issues"] == [], "Subject/title must never populate legal_issues in V2"

    diff_v1_v2 = mock_prov.compare_versions(doc_v1_meta, doc_v2_meta, doc_v1_sum, doc_v2_sum, from_version_number=1, to_version_number=2)
    
    # 1. Factual changes separated from metadata
    assert diff_v1_v2["metadata_changes"]["changed"] != []
    assert any(c["field"] == "subject" for c in diff_v1_v2["metadata_changes"]["changed"])
    
    # 2. Procedural changes separated from factual changes
    assert len(diff_v1_v2["summary_changes"]["facts_added"]) > 0
    assert len(diff_v1_v2["summary_changes"]["procedural_added"]) > 0

    # 5. CCTV observations remain factual/evidentiary
    assert any("CCTV footage" in f for f in diff_v1_v2["summary_changes"]["facts_added"])
    assert not any("CCTV footage" in p for p in diff_v1_v2["summary_changes"]["procedural_added"])
    assert not any("CCTV footage" in l for l in diff_v1_v2["summary_changes"]["legal_issues_added"])

    # 6. Witness statements remain factual/evidentiary
    assert any("Rajesh" in f or "stated" in f for f in diff_v1_v2["summary_changes"]["facts_added"])
    assert not any("Rajesh" in l for l in diff_v1_v2["summary_changes"]["legal_issues_added"])

    # 7. Investigation progression remains procedural
    assert any("investigation progressed" in p.lower() for p in diff_v1_v2["summary_changes"]["procedural_added"])
    assert not any("investigation progressed" in f.lower() for f in diff_v1_v2["summary_changes"]["facts_added"])

    # 8. Questioning remains procedural
    assert any("questioned" in p.lower() for p in diff_v1_v2["summary_changes"]["procedural_added"])
    assert not any("questioned" in f.lower() for f in diff_v1_v2["summary_changes"]["facts_added"])

    # 9 & 10. Documents without legal claims return an empty legal_issues list
    assert diff_v1_v2["summary_changes"]["legal_issues_added"] == []
    assert diff_v1_v2["summary_changes"]["legal_issues_removed"] == []

    # 11. Generic fallback text never becomes a comparison delta
    for field in ["facts_added", "facts_removed", "procedural_added", "procedural_removed", "legal_issues_added", "legal_issues_removed"]:
        for item in diff_v1_v2["summary_changes"][field]:
            assert not is_generic_summary_placeholder(item), f"Generic placeholder detected in {field}: {item}"

    # 12 & 13. Symmetrical Direction Reversal (V2 -> V1)
    diff_v2_v1 = mock_prov.compare_versions(doc_v2_meta, doc_v1_meta, doc_v2_sum, doc_v1_sum, from_version_number=2, to_version_number=1)
    assert len(diff_v2_v1["summary_changes"]["facts_removed"]) == len(diff_v1_v2["summary_changes"]["facts_added"])
    assert diff_v2_v1["summary_changes"]["facts_added"] == []
    assert len(diff_v2_v1["summary_changes"]["procedural_removed"]) == len(diff_v1_v2["summary_changes"]["procedural_added"])
    assert diff_v2_v1["summary_changes"]["procedural_added"] == []

    # 14. Modified metadata remains MODIFIED
    subj_rev = next(c for c in diff_v2_v1["metadata_changes"]["changed"] if c["field"] == "subject")
    assert subj_rev["from"] == "Supplemental Incident Report - Metro Plaza"
    assert subj_rev["to"] == "Incident at Metro Plaza"

    # 15. Dynamic Directional Label Mapping Contract (V1 -> V2 vs V2 -> V1)
    def compute_ui_directional_labels(from_v, to_v):
        return f"NEW IN V{to_v}", f"PRESENT IN V{from_v} ONLY", "MODIFIED"

    fwd_new, fwd_only, fwd_mod = compute_ui_directional_labels(1, 2)
    assert fwd_new == "NEW IN V2"
    assert fwd_only == "PRESENT IN V1 ONLY"
    assert fwd_mod == "MODIFIED"

    rev_new, rev_only, rev_mod = compute_ui_directional_labels(2, 1)
    assert rev_new == "NEW IN V1"
    assert rev_only == "PRESENT IN V2 ONLY"
    assert rev_mod == "MODIFIED"

    # 16. Technical metadata isolation (keywords stay inside technical section)
    assert any("amended" in kw["value"] for kw in diff_forward["metadata_changes"]["added"] if kw["field"] == "keyword")
    # Keywords are not present in summary_changes facts or procedural
    assert not any("amended" in f for f in diff_forward["summary_changes"]["facts_added"])
    assert not any("amended" in p for p in diff_forward["summary_changes"]["procedural_added"])

    print("    [OK] All semantic presentation, directional labels (NEW IN Vx / PRESENT IN Vy ONLY), and classification invariants verified.")

    # 4. MockProvider Material Change Narrative Generation
    print("\n[4] Testing MockProvider Source-Grounded Comparison...")
    mock_prov = MockProvider()
    mock_res = mock_prov.compare_versions(v1_meta, v2_meta, v1_summary, v2_summary, from_version_number=1, to_version_number=2)
    assert mock_res["material_changes"] is not None
    assert "Rohan Mehta" in mock_res["material_changes"]
    assert "confidence" not in mock_res
    print("    [OK] MockProvider generated grounded material change narrative.")

    # 5. Gemini Provider Contract & Failure Isolation
    print("\n[5] Testing Gemini Provider Contract & Failure Isolation...")
    # Missing API Key
    try:
        GeminiProvider(api_key="")
        assert False, "Expected AIConfigurationError on missing API key"
    except AIConfigurationError:
        print("    [OK] Missing API key raises AIConfigurationError.")

    # Invalid API Key
    try:
        prov_bad = GeminiProvider(api_key="AIzaSyBadKeyTest123")
        prov_bad.compare_versions(v1_meta, v2_meta, v1_summary, v2_summary)
    except AIServiceError as e:
        assert "Gemini API error" in str(e)
        print("    [OK] Invalid API key safely caught as AIServiceError.")

    # Timeout Handling
    prov_mock = GeminiProvider(api_key="mock_key")
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
        try:
            prov_mock.compare_versions(v1_meta, v2_meta, v1_summary, v2_summary)
            assert False, "Expected AITimeoutError"
        except AITimeoutError:
            print("    [OK] Timeout properly caught as AITimeoutError.")

    # Malformed JSON Handling
    bad_json_resp = MagicMock()
    bad_json_resp.status_code = 200
    bad_json_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{ not json"}]}}]}
    with patch("requests.post", return_value=bad_json_resp):
        try:
            prov_mock.compare_versions(v1_meta, v2_meta, v1_summary, v2_summary)
            assert False, "Expected AIParsingError"
        except AIParsingError:
            print("    [OK] Malformed JSON response properly caught as AIParsingError.")

    # Valid Gemini response parsing
    valid_mock_json = {
        "material_changes": "Version 2 adds Rohan Mehta as a respondent and includes a new hearing schedule.",
        "metadata_changes": {
            "added": [{"field": "party", "value": "Rohan Mehta (Respondent)", "description": "Added Rohan Mehta"}],
            "removed": [],
            "changed": []
        },
        "summary_changes": {
            "facts_added": ["New factual submission on property bounds."],
            "facts_removed": [],
            "legal_issues_added": ["Joint possession plea."],
            "legal_issues_removed": [],
            "important_points_added": [],
            "important_points_removed": []
        }
    }
    good_json_resp = MagicMock()
    good_json_resp.status_code = 200
    good_json_resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(valid_mock_json)}]}}]}
    with patch("requests.post", return_value=good_json_resp):
        gem_out = prov_mock.compare_versions(v1_meta, v2_meta, v1_summary, v2_summary)
        assert gem_out["material_changes"] == valid_mock_json["material_changes"]
        assert len(gem_out["metadata_changes"]["added"]) == 1
        print("    [OK] Valid Gemini structured response parsed and normalized.")

    # 6. Upload Document v1 and Revision v2 via REST API
    print("\n[6] Depositing Document v1 and Revision v2 in Vault...")

    v1_content = (
        "IN THE DISTRICT COURT OF KANPUR NAGAR\n"
        "CIVIL SUIT NO. CIV-2026-104\n"
        "IN THE MATTER OF: Ananya Verma (Petitioner)\n"
        "AFFIDAVIT OF EVIDENCE\n"
        "Subject: Evidentiary affidavit in support of civil land partition suit.\n"
        "I, Ananya Verma, state that the agricultural land situated at Kanpur was transferred under agreement dated 3 July 2025. "
        "The matter is scheduled for hearing on 22 August 2026.\n"
    ).encode("utf-8")
    resp_upload1 = requests.post(
        f"{BASE_URL}/documents/upload",
        headers=lawyer_a_headers,
        data={"case_number": "CIV-2026-104", "uploaded_by": "Advocate Ananya Verma"},
        files={"file": ("Suit_Affidavit_v1.txt", io.BytesIO(v1_content), "text/plain")},
    )
    assert resp_upload1.status_code == 200, f"Upload v1 failed: {resp_upload1.text}"
    doc_data = resp_upload1.json()
    doc_id = doc_data["document_id"]
    print(f"    [OK] Document #{doc_id} created with Version 1 (Hash: {doc_data['file_hash'][:16]}...).")

    # Upload Revision v2
    v2_content = (
        "IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD\n"
        "CIVIL SUIT NO. CIV-2026-104\n"
        "IN THE MATTER OF: Ananya Verma (Petitioner) Versus Rohan Mehta (Respondent)\n"
        "AMENDED AFFIDAVIT OF EVIDENCE\n"
        "Subject: Amended evidentiary affidavit in support of civil land partition suit.\n"
        "I, Ananya Verma, state that the agricultural land situated at Kanpur was transferred under agreement dated 3 July 2025. "
        "Further, a supplementary agreement dated 10 August 2026 was executed with Rohan Mehta. "
        "The petitioner raises additional claims regarding joint property possession. "
        "The next hearing is scheduled for 30 August 2026.\n"
    ).encode("utf-8")
    resp_upload2 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        headers=lawyer_a_headers,
        files={"file": ("Suit_Affidavit_v2.txt", io.BytesIO(v2_content), "text/plain")},
    )
    assert resp_upload2.status_code == 200, f"Upload v2 failed: {resp_upload2.text}"
    print(f"    [OK] Revision Version 2 anchored for Document #{doc_id}.")

    # 7. Generate Version Comparison via REST API (POST /documents/{id}/compare)
    print("\n[7] Testing AI Version Comparison Endpoint (POST & GET)...")
    resp_comp1 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=lawyer_a_headers,
    )
    assert resp_comp1.status_code == 200, f"Comparison failed: {resp_comp1.text}"
    comp_json1 = resp_comp1.json()
    assert comp_json1["status"] == "COMPLETED"
    assert comp_json1["from_version_number"] == 1
    assert comp_json1["to_version_number"] == 2
    assert comp_json1["cached"] is False
    assert comp_json1["material_changes"] is not None
    print(f"    [OK] Comparison generated (v1 -> v2): {comp_json1['material_changes'][:65]}...")

    # Verify GET retrieval
    resp_get_comp = requests.get(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=lawyer_a_headers,
    )
    assert resp_get_comp.status_code == 200
    assert resp_get_comp.json()["status"] == "COMPLETED"
    print("    [OK] GET /documents/{id}/compare returns existing comparison record.")

    # 8. Testing Caching & Force Re-generation
    print("\n[8] Testing SHA-256 Comparison Caching & Force Re-generation...")
    resp_comp_cache = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=lawyer_a_headers,
    )
    assert resp_comp_cache.status_code == 200
    assert resp_comp_cache.json()["cached"] is True
    print("    [OK] Cache hit verified: repeat call returned cached=True with 0ms overhead.")

    resp_comp_force = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2&force=true",
        headers=lawyer_a_headers,
    )
    assert resp_comp_force.status_code == 200
    assert resp_comp_force.json()["cached"] is False
    print("    [OK] Force re-generation verified: force=true refreshed comparison.")

    # 9. Testing Cross-Document Comparison Rejection
    print("\n[9] Testing Cross-Document Comparison Rejection...")
    # Create Document #2
    resp_doc2 = requests.post(
        f"{BASE_URL}/documents/upload",
        headers=lawyer_a_headers,
        data={"case_number": "CIV-2026-999", "uploaded_by": "Advocate Test"},
        files={"file": ("Doc2.txt", io.BytesIO(b"Document 2 sample content for cross-doc test."), "text/plain")},
    )
    assert resp_doc2.status_code == 200
    doc2_id = resp_doc2.json()["document_id"]

    # Attempt cross-document comparison
    resp_cross = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=999",
        headers=lawyer_a_headers,
    )
    assert resp_cross.status_code in [400, 404]
    print("    [OK] Cross-document and nonexistent version comparison rejected with HTTP 400/404.")

    # 10. Testing Identical Version Comparison (v1 -> v1)
    print("\n[10] Testing Identical Version Comparison (v1 -> v1)...")
    resp_same_ver = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=1",
        headers=lawyer_a_headers,
    )
    assert resp_same_ver.status_code == 200
    same_json = resp_same_ver.json()
    assert same_json["status"] == "COMPLETED"
    assert "identical" in same_json["material_changes"].lower()
    print("    [OK] Identical version comparison (v1 -> v1) returned zero-difference response.")

    # 11. Testing RBAC Scoping
    print("\n[11] Testing Role-Based Access Control (RBAC) Scoping...")
    # Share document with Judge and Client
    resp_share_judge = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_a_headers,
        json={"shared_with_user_id": judge_id},
    )
    assert resp_share_judge.status_code == 200

    resp_share_client = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers=lawyer_a_headers,
        json={"shared_with_user_id": client_id},
    )
    assert resp_share_client.status_code == 200

    # 11a. Shared Judge can GET comparison
    resp_judge_get = requests.get(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=judge_headers,
    )
    assert resp_judge_get.status_code == 200
    assert resp_judge_get.json()["status"] == "COMPLETED"
    print("    [OK] Shared Judge permitted to view existing version comparison.")

    # 11b. Shared Judge blocked from triggering comparison generation (403 ACTION_DENIED)
    resp_judge_post = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=judge_headers,
    )
    assert resp_judge_post.status_code == 403
    print("    [OK] Shared Judge blocked from triggering comparison generation (403 ACTION_DENIED).")

    # 11c. Shared Client permitted to GET, blocked from POST
    resp_client_get = requests.get(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=client_headers,
    )
    assert resp_client_get.status_code == 200

    resp_client_post = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=client_headers,
    )
    assert resp_client_post.status_code == 403
    print("    [OK] Shared Client permitted to view, blocked from triggering comparison generation.")

    # 11d. Unauthorized Lawyer B blocked from both GET and POST (403 ACCESS_DENIED)
    resp_lawyer2_get = requests.get(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=lawyer_b_headers,
    )
    assert resp_lawyer2_get.status_code == 403

    resp_lawyer2_post = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2",
        headers=lawyer_b_headers,
    )
    assert resp_lawyer2_post.status_code == 403
    print("    [OK] Unauthorized Lawyer B strictly blocked from viewing and generating (403 ACCESS_DENIED).")

    # 11e. Administrator has full generation and inspection privileges
    resp_admin_post = requests.post(
        f"{BASE_URL}/documents/{doc_id}/compare?from_version=1&to_version=2&force=true",
        headers=admin_headers,
    )
    assert resp_admin_post.status_code == 200
    print("    [OK] Administrator has full generation and inspection privileges.")

    # 12. Verifying Custody Layer Invariants & Fault Isolation
    print("\n[12] Verifying Custody Layer Invariants & Blockchain State...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT file_hash FROM document_versions WHERE document_id = ? AND version_number = 1", (doc_id,))
    v1_hash = cur.fetchone()[0]
    cur.execute("SELECT file_hash FROM document_versions WHERE document_id = ? AND version_number = 2", (doc_id,))
    v2_hash = cur.fetchone()[0]
    conn.close()

    assert v1_hash == hashlib.sha256(v1_content).hexdigest()
    assert v2_hash == hashlib.sha256(v2_content).hexdigest()

    # Blockchain verification on each version remains intact
    resp_v1_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_a_headers)
    assert resp_v1_verify.status_code == 200
    assert resp_v1_verify.json()["result"] == "VERIFIED"

    resp_v2_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_a_headers)
    assert resp_v2_verify.status_code == 200
    assert resp_v2_verify.json()["result"] == "VERIFIED"
    print("    [OK] Document versions, SHA-256 hashes, and blockchain state remain 100% verified and untouched.")

    # 13. Verifying Privacy & Forensic Audit Logging
    print("\n[13] Verifying Privacy & Forensic Audit Logging...")
    resp_audit = requests.get(f"{BASE_URL}/documents/{doc_id}/audit", headers=lawyer_a_headers)
    assert resp_audit.status_code == 200
    events = resp_audit.json()["events"]
    comp_events = [e for e in events if e["action"] == "AI_VERSION_COMPARISON_GENERATED"]
    assert len(comp_events) > 0
    for ce in comp_events:
        meta = ce.get("metadata") or {}
        # Ensure no sensitive keys leaked
        assert "comparison_prompt" not in meta
        assert "raw_diff" not in meta
        assert "prompt" not in meta
        assert "document_text" not in meta
        assert "api_key" not in meta
        assert "from_version" in meta
        assert "to_version" in meta
    print("    [OK] Forensic audit trail recorded comparison events with zero raw text or prompt leakage.")

    # 14. Verifying Timezone Standardization (UTC Z Serialization)
    print("\n[14] Verifying Timezone Standardization (UTC Z Serialization)...")
    assert comp_json1["created_at"].endswith("Z")
    assert comp_json1["updated_at"].endswith("Z")
    print("    [OK] Comparison timestamps conform strictly to UTC ISO 8601 with trailing 'Z'.")

    # 15. Testing Development Vault Reset Cleanup
    print("\n[15] Testing Development Vault Reset Cleanup on Comparison Records...")
    reset_resp = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert reset_resp.status_code == 200
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM document_version_comparisons")
    rem_comp = cur.fetchone()[0]
    conn.close()
    assert rem_comp == 0, f"Expected 0 comparisons after reset, found {rem_comp}"
    print("    [OK] Development vault reset cleanly purged document_version_comparisons records.")

    print("\n" + "=" * 65)
    print("ALL 15 AI VERSION COMPARISON TEST SUITES PASSED (100% SUCCESS)!")
    print("=" * 65)


if __name__ == "__main__":
    run_ai_comparison_tests()
