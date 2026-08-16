import os
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def compute_integrity_status(doc_id, integrity_results):
    """Python reference mirroring the frontend getDocumentIntegrity calculation."""
    doc_data = integrity_results.get(doc_id)
    if not doc_data:
        return {"status": "UNVERIFIED", "affectedLabel": "", "summaryText": "Unverified"}
    
    version_map = doc_data.get("versions", {})
    if not version_map and "result" in doc_data:
        v_num = doc_data.get("version_number") or doc_data.get("version") or 1
        version_map = {v_num: doc_data}
    
    tampered = []
    unavailable = []
    verified = []
    
    for v_num_str, res in version_map.items():
        v_num = int(v_num_str)
        if res.get("result") == "TAMPERED" or (res.get("verified") is False and res.get("result") != "BLOCKCHAIN_PROOF_UNAVAILABLE"):
            tampered.push(v_num) if hasattr(tampered, 'push') else tampered.append(v_num)
        elif res.get("result") == "BLOCKCHAIN_PROOF_UNAVAILABLE":
            unavailable.append(v_num)
        elif res.get("result") == "VERIFIED" or res.get("verified") is True:
            verified.append(v_num)
            
    tampered.sort()
    unavailable.sort()
    verified.sort()
    
    if tampered:
        affected = ", ".join(f"v{v}" for v in tampered)
        return {
            "status": "TAMPERED",
            "tamperedVersions": tampered,
            "verifiedVersions": verified,
            "affectedLabel": affected,
            "summaryText": f"TAMPERED · {affected}"
        }
    if unavailable:
        affected = ", ".join(f"v{v}" for v in unavailable)
        return {
            "status": "BLOCKCHAIN_PROOF_UNAVAILABLE",
            "affectedLabel": affected,
            "summaryText": f"PROOF UNAVAILABLE · {affected}"
        }
    if verified:
        affected = ", ".join(f"v{v}" for v in verified)
        return {
            "status": "VERIFIED",
            "tamperedVersions": [],
            "verifiedVersions": verified,
            "affectedLabel": affected,
            "summaryText": f"VERIFIED · {affected}"
        }
    return {"status": "UNVERIFIED", "affectedLabel": "", "summaryText": "Unverified"}


def test_five_exact_scenarios():
    print("=================================================================")
    print("TESTING 5 EXACT INTEGRITY STATUS & VERSION HISTORY SCENARIOS")
    print("=================================================================")

    # Authenticate admin and lawyer
    admin_login = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@legalvault.local", "password": "admin123"}).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}
    requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)

    lawyer_login = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "lawyer123"}).json()
    lawyer_headers = {"Authorization": f"Bearer {lawyer_login['access_token']}"}

    salt = str(int(time.time()))

    # 1. Upload v1, v2, v3
    v1_raw = f"%PDF-1.4 Agreement Draft v1 {salt} %%EOF".encode()
    v2_raw = f"%PDF-1.4 Agreement Draft v2 {salt} %%EOF".encode()
    v3_raw = f"%PDF-1.4 Agreement Draft v3 {salt} %%EOF".encode()

    up_v1 = requests.post(
        f"{BASE_URL}/documents/upload",
        files={"file": ("affidavit_v1.pdf", v1_raw, "application/pdf")},
        data={"case_number": f"CASE-INTEGRITY-{salt}", "uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    ).json()
    doc_id = up_v1["document_id"]

    up_v2 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("affidavit_v2.pdf", v2_raw, "application/pdf")},
        headers=lawyer_headers,
    ).json()

    up_v3 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("affidavit_v3.pdf", v3_raw, "application/pdf")},
        headers=lawyer_headers,
    ).json()

    # Track UI simulated state
    ui_integrity = {doc_id: {"versions": {}}}

    # SCENARIO A: Verify v1, v2, v3 (All valid)
    print("\n--- [SCENARIO A] All versions valid ---")
    res_v1 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_headers).json()
    res_v2 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_headers).json()
    res_v3 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/3/verify", headers=lawyer_headers).json()

    ui_integrity[doc_id]["versions"][1] = res_v1
    ui_integrity[doc_id]["versions"][2] = res_v2
    ui_integrity[doc_id]["versions"][3] = res_v3

    status_a = compute_integrity_status(doc_id, ui_integrity)
    print(f"v1 status: {res_v1['result']}")
    print(f"v2 status: {res_v2['result']}")
    print(f"v3 status: {res_v3['result']}")
    print(f"Overall status: {status_a['status']} ({status_a['summaryText']})")

    assert res_v1["result"] == "VERIFIED"
    assert res_v2["result"] == "VERIFIED"
    assert res_v3["result"] == "VERIFIED"
    assert status_a["status"] == "VERIFIED"
    print(">>> Scenario A PASSED: Overall status is VERIFIED.")

    # SCENARIO B: Tamper v1 file on disk and verify v1
    print("\n--- [SCENARIO B] v1 tampered ---")
    v1_meta = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1", headers=lawyer_headers).json()
    v1_path = os.path.join(UPLOADS_DIR, v1_meta["stored_filename"])
    with open(v1_path, "wb") as f:
        f.write(b"%PDF-1.4 TAMPERED CONTENT IN V1 %%EOF")

    res_v1_tampered = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_headers).json()
    ui_integrity[doc_id]["versions"][1] = res_v1_tampered

    status_b = compute_integrity_status(doc_id, ui_integrity)
    print(f"v1 status: {res_v1_tampered['result']}")
    print(f"v2 status: {ui_integrity[doc_id]['versions'][2]['result']}")
    print(f"v3 status: {ui_integrity[doc_id]['versions'][3]['result']}")
    print(f"Overall status: {status_b['status']}, Affected: {status_b['affectedLabel']}")

    assert res_v1_tampered["result"] == "TAMPERED"
    assert status_b["status"] == "TAMPERED"
    assert status_b["affectedLabel"] == "v1"
    print(">>> Scenario B PASSED: Overall is TAMPERED and identifies affected version v1.")

    # SCENARIO C: Restore v1 and re-verify v1
    print("\n--- [SCENARIO C] Restore v1 ---")
    with open(v1_path, "wb") as f:
        f.write(v1_raw)

    res_v1_restored = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_headers).json()
    ui_integrity[doc_id]["versions"][1] = res_v1_restored

    status_c = compute_integrity_status(doc_id, ui_integrity)
    print(f"v1 status: {res_v1_restored['result']}")
    print(f"v2 status: {ui_integrity[doc_id]['versions'][2]['result']}")
    print(f"v3 status: {ui_integrity[doc_id]['versions'][3]['result']}")
    print(f"Overall status: {status_c['status']} ({status_c['summaryText']})")

    assert res_v1_restored["result"] == "VERIFIED"
    assert status_c["status"] == "VERIFIED"
    print(">>> Scenario C PASSED: Overall status restored to VERIFIED.")

    # SCENARIO D: Tamper v2 and verify v2
    print("\n--- [SCENARIO D] v2 tampered ---")
    v2_meta = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/2", headers=lawyer_headers).json()
    v2_path = os.path.join(UPLOADS_DIR, v2_meta["stored_filename"])
    with open(v2_path, "wb") as f:
        f.write(b"%PDF-1.4 TAMPERED CONTENT IN V2 %%EOF")

    res_v2_tampered = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_headers).json()
    ui_integrity[doc_id]["versions"][2] = res_v2_tampered

    status_d = compute_integrity_status(doc_id, ui_integrity)
    print(f"v1 status: {ui_integrity[doc_id]['versions'][1]['result']}")
    print(f"v2 status: {res_v2_tampered['result']}")
    print(f"v3 status: {ui_integrity[doc_id]['versions'][3]['result']}")
    print(f"Overall status: {status_d['status']}, Affected: {status_d['affectedLabel']}")

    assert res_v2_tampered["result"] == "TAMPERED"
    assert status_d["status"] == "TAMPERED"
    assert status_d["affectedLabel"] == "v2"
    print(">>> Scenario D PASSED: Overall is TAMPERED and identifies affected version v2.")

    # SCENARIO E: Verify a healthy version (v3) while another version (v2) is tampered
    print("\n--- [SCENARIO E] Verify healthy version (v3) while v2 remains tampered ---")
    res_v3_reverify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/3/verify", headers=lawyer_headers).json()
    ui_integrity[doc_id]["versions"][3] = res_v3_reverify

    status_e = compute_integrity_status(doc_id, ui_integrity)
    print(f"v2 status: {ui_integrity[doc_id]['versions'][2]['result']}")
    print(f"v3 status (just re-verified): {res_v3_reverify['result']}")
    print(f"Overall status: {status_e['status']}, Affected: {status_e['affectedLabel']}")

    assert res_v3_reverify["result"] == "VERIFIED"
    assert ui_integrity[doc_id]["versions"][2]["result"] == "TAMPERED"
    assert status_e["status"] == "TAMPERED"
    assert status_e["affectedLabel"] == "v2"
    print(">>> Scenario E PASSED: Overall status strictly preserves TAMPERED · v2 and does NOT become VERIFIED.")

    # Clean up restored files
    with open(v2_path, "wb") as f:
        f.write(v2_raw)

    print("\n=================================================================")
    print("ALL 5 EXACT INTEGRITY VALIDATION SCENARIOS PASSED WITH 100% SUCCESS!")
    print("=================================================================")


if __name__ == "__main__":
    test_five_exact_scenarios()
