import os
import time
import requests
import json

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def simulate_full_document_verification(doc_id, auth_headers):
    """
    Simulates the exact full verification workflow executed by the frontend:
    1. Fetch document version list
    2. Sequentially call POST /documents/{id}/versions/{v}/verify for each version
    3. Aggregate results and compute overall document integrity
    """
    versions_res = requests.get(f"{BASE_URL}/documents/{doc_id}/versions", headers=auth_headers)
    assert versions_res.status_code == 200
    versions = versions_res.json()

    sorted_versions = sorted(versions, key=lambda v: v["version_number"])
    per_version_results = {}
    tampered_versions = []
    verified_versions = []
    unavailable_versions = []

    for v in sorted_versions:
        v_num = v["version_number"]
        v_ver = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/{v_num}/verify", headers=auth_headers).json()
        per_version_results[v_num] = v_ver
        if v_ver.get("result") == "TAMPERED" or (v_ver.get("verified") is False and v_ver.get("result") != "BLOCKCHAIN_PROOF_UNAVAILABLE"):
            tampered_versions.append(v_num)
        elif v_ver.get("result") == "BLOCKCHAIN_PROOF_UNAVAILABLE":
            unavailable_versions.append(v_num)
        elif v_ver.get("result") == "VERIFIED" or v_ver.get("verified") is True:
            verified_versions.append(v_num)

    if tampered_versions:
        overall_status = "TAMPERED"
        affected_label = ", ".join(f"v{v}" for v in tampered_versions)
    elif unavailable_versions:
        overall_status = "BLOCKCHAIN_PROOF_UNAVAILABLE"
        affected_label = ", ".join(f"v{v}" for v in unavailable_versions)
    elif verified_versions:
        overall_status = "VERIFIED"
        affected_label = ", ".join(f"v{v}" for v in verified_versions)
    else:
        overall_status = "UNVERIFIED"
        affected_label = ""

    return {
        "versions_checked": len(sorted_versions),
        "per_version_results": per_version_results,
        "overall_status": overall_status,
        "affected_label": affected_label,
        "tampered_versions": tampered_versions,
        "verified_versions": verified_versions,
    }


def test_full_document_verification_workflow():
    print("=================================================================")
    print("TESTING FULL DOCUMENT INTEGRITY VERIFICATION SUITE (TESTS 1–6)")
    print("=================================================================")

    # 0. Authenticate
    admin_login = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@legalvault.local", "password": "admin123"}).json()
    admin_headers = {"Authorization": f"Bearer {admin_login['access_token']}"}
    requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)

    lawyer_login = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "lawyer123"}).json()
    lawyer_headers = {"Authorization": f"Bearer {lawyer_login['access_token']}"}

    salt = str(int(time.time()))

    # Setup: Create Document with v1, v2, v3
    v1_raw = f"%PDF-1.4 Agreement Contract v1 {salt} %%EOF".encode()
    v2_raw = f"%PDF-1.4 Agreement Contract v2 {salt} %%EOF".encode()
    v3_raw = f"%PDF-1.4 Agreement Contract v3 {salt} %%EOF".encode()

    up_v1 = requests.post(
        f"{BASE_URL}/documents/upload",
        files={"file": ("Affidavit of Evidence 2.txt", v1_raw, "text/plain")},
        data={"case_number": f"CASE-FULL-AUDIT-{salt}", "uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    ).json()
    doc_id = up_v1["document_id"]

    requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("Affidavit of Evidence 2.txt", v2_raw, "text/plain")},
        headers=lawyer_headers,
    )

    requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("Affidavit of Evidence 2.txt", v3_raw, "text/plain")},
        headers=lawyer_headers,
    )

    v1_meta = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1", headers=lawyer_headers).json()
    v2_meta = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/2", headers=lawyer_headers).json()
    v3_meta = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/3", headers=lawyer_headers).json()

    v1_path = os.path.join(UPLOADS_DIR, v1_meta["stored_filename"])
    v2_path = os.path.join(UPLOADS_DIR, v2_meta["stored_filename"])
    v3_path = os.path.join(UPLOADS_DIR, v3_meta["stored_filename"])

    # -------------------------------------------------------------
    # TEST 1 — All healthy
    # -------------------------------------------------------------
    print("\n[TEST 1] All healthy (v1=VERIFIED, v2=VERIFIED, v3=VERIFIED)...")
    res1 = simulate_full_document_verification(doc_id, lawyer_headers)
    print(f"  Versions checked: {res1['versions_checked']}")
    print(f"  v1: {res1['per_version_results'][1]['result']}")
    print(f"  v2: {res1['per_version_results'][2]['result']}")
    print(f"  v3: {res1['per_version_results'][3]['result']}")
    print(f"  Overall Status: {res1['overall_status']}")
    assert res1["versions_checked"] == 3
    assert res1["per_version_results"][1]["result"] == "VERIFIED"
    assert res1["per_version_results"][2]["result"] == "VERIFIED"
    assert res1["per_version_results"][3]["result"] == "VERIFIED"
    assert res1["overall_status"] == "VERIFIED"
    print(">>> TEST 1 PASSED: All 3 versions verified -> Overall VERIFIED.")

    # -------------------------------------------------------------
    # TEST 2 — Historical v1 tampered
    # -------------------------------------------------------------
    print("\n[TEST 2] Historical v1 tampered on disk...")
    with open(v1_path, "wb") as f:
        f.write(b"TAMPERED V1 OFF-CHAIN CONTENT")

    res2 = simulate_full_document_verification(doc_id, lawyer_headers)
    print(f"  v1: {res2['per_version_results'][1]['result']}")
    print(f"  v2: {res2['per_version_results'][2]['result']}")
    print(f"  v3: {res2['per_version_results'][3]['result']}")
    print(f"  Overall Status: {res2['overall_status']}, Affected: {res2['affected_label']}")
    assert res2["per_version_results"][1]["result"] == "TAMPERED"
    assert res2["per_version_results"][2]["result"] == "VERIFIED"
    assert res2["per_version_results"][3]["result"] == "VERIFIED"
    assert res2["overall_status"] == "TAMPERED"
    assert res2["affected_label"] == "v1"
    print(">>> TEST 2 PASSED: Overall status is TAMPERED with Affected: v1.")

    # -------------------------------------------------------------
    # TEST 3 — Current version healthy while historical version is tampered
    # -------------------------------------------------------------
    print("\n[TEST 3] Current version healthy (v3) while historical v1 is tampered...")
    # v3 is current master and healthy, v1 is tampered.
    res3 = simulate_full_document_verification(doc_id, lawyer_headers)
    print(f"  Current v3 result: {res3['per_version_results'][3]['result']}")
    print(f"  Historical v1 result: {res3['per_version_results'][1]['result']}")
    print(f"  Overall Status: {res3['overall_status']}")
    assert res3["per_version_results"][3]["result"] == "VERIFIED"
    assert res3["overall_status"] == "TAMPERED"
    assert "v1" in res3["affected_label"]
    print(">>> TEST 3 PASSED: Healthy current version does NOT cause overall to appear VERIFIED.")

    # -------------------------------------------------------------
    # TEST 4 — Restore historical version
    # -------------------------------------------------------------
    print("\n[TEST 4] Restore v1 to original authentic bytes...")
    with open(v1_path, "wb") as f:
        f.write(v1_raw)

    res4 = simulate_full_document_verification(doc_id, lawyer_headers)
    print(f"  v1: {res4['per_version_results'][1]['result']}")
    print(f"  v2: {res4['per_version_results'][2]['result']}")
    print(f"  v3: {res4['per_version_results'][3]['result']}")
    print(f"  Overall Status: {res4['overall_status']}")
    assert res4["per_version_results"][1]["result"] == "VERIFIED"
    assert res4["overall_status"] == "VERIFIED"
    print(">>> TEST 4 PASSED: Restoring v1 restores overall status to VERIFIED.")

    # -------------------------------------------------------------
    # TEST 5 — Multiple tampered versions (v1 and v2)
    # -------------------------------------------------------------
    print("\n[TEST 5] Multiple tampered versions (v1 and v2)...")
    with open(v1_path, "wb") as f:
        f.write(b"TAMPERED V1 CORRUPT")
    with open(v2_path, "wb") as f:
        f.write(b"TAMPERED V2 CORRUPT")

    res5 = simulate_full_document_verification(doc_id, lawyer_headers)
    print(f"  v1: {res5['per_version_results'][1]['result']}")
    print(f"  v2: {res5['per_version_results'][2]['result']}")
    print(f"  v3: {res5['per_version_results'][3]['result']}")
    print(f"  Overall Status: {res5['overall_status']}, Affected: {res5['affected_label']}")
    assert res5["per_version_results"][1]["result"] == "TAMPERED"
    assert res5["per_version_results"][2]["result"] == "TAMPERED"
    assert res5["per_version_results"][3]["result"] == "VERIFIED"
    assert res5["overall_status"] == "TAMPERED"
    assert "v1" in res5["affected_label"] and "v2" in res5["affected_label"]
    print(">>> TEST 5 PASSED: Overall status is TAMPERED with Affected: v1, v2.")

    # -------------------------------------------------------------
    # TEST 6 — Individual verification still works independently
    # -------------------------------------------------------------
    print("\n[TEST 6] Individual version verification (Verify only v3)...")
    single_v3_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/3/verify", headers=lawyer_headers).json()
    print(f"  Single Verify v3 result: {single_v3_res['result']}")
    assert single_v3_res["version_number"] == 3
    assert single_v3_res["result"] == "VERIFIED"

    single_v2_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_headers).json()
    print(f"  Single Verify v2 result: {single_v2_res['result']}")
    assert single_v2_res["version_number"] == 2
    assert single_v2_res["result"] == "TAMPERED"
    print(">>> TEST 6 PASSED: Individual version verification works independently.")

    # Clean up files
    with open(v1_path, "wb") as f:
        f.write(v1_raw)
    with open(v2_path, "wb") as f:
        f.write(v2_raw)

    print("\n=================================================================")
    print("ALL 6 FULL DOCUMENT INTEGRITY VERIFICATION TESTS PASSED (100%)!")
    print("=================================================================")


if __name__ == "__main__":
    test_full_document_verification_workflow()
