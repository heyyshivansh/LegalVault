import os
import requests
import json
import sqlite3
import time

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "legalvault.db")


def run_version_history_tests():
    print("=================================================================")
    print("RUNNING DOCUMENT VERSION HISTORY COMPREHENSIVE TEST SUITE")
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

    print("[1] Authentication confirmed across all user roles.")

    # 1b. Reset dev vault for clean state
    requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)

    salt = str(int(time.time()))

    # 2. Initial Upload Creates Version 1
    print("\n[2] Testing Initial Upload (creates Version 1)...")
    v1_content = f"%PDF-1.4 Agreement Draft Initial Version 1 {salt} %%EOF".encode()
    files_v1 = {"file": ("commercial_lease_v1.pdf", v1_content, "application/pdf")}
    data_v1 = {"case_number": f"CASE-VERSIONS-{salt}", "uploaded_by": "Advocate Rajesh Sharma"}
    res_v1 = requests.post(f"{BASE_URL}/documents/upload", files=files_v1, data=data_v1, headers=lawyer_a_headers)
    assert res_v1.status_code == 200, f"Upload v1 failed: {res_v1.text}"
    v1_json = res_v1.json()
    doc_id = v1_json["document_id"]
    v1_hash = v1_json["file_hash"]
    assert v1_json["version"] == 1, f"Expected version=1, got {v1_json['version']}"
    print(f"    [OK] Document #{doc_id} created with initial Version 1 (Hash: {v1_hash[:16]}...)")

    # Verify versions list for v1
    v_list = requests.get(f"{BASE_URL}/documents/{doc_id}/versions", headers=lawyer_a_headers).json()
    assert len(v_list) == 1, f"Expected 1 version, got {len(v_list)}"
    assert v_list[0]["version_number"] == 1
    assert v_list[0]["is_current"] is True
    assert v_list[0]["blockchain_status"] == "confirmed"
    print("    [OK] GET /documents/{id}/versions returns 1 version with is_current=True.")

    # Verify v1 cryptographic integrity
    verify_v1 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_a_headers).json()
    assert verify_v1["verified"] is True
    assert verify_v1["result"] == "VERIFIED"
    assert verify_v1["current_hash"] == v1_hash
    print("    [OK] POST /documents/{id}/versions/1/verify confirms VERIFIED on-chain.")

    # 3. Upload Revision Creates Version 2
    print("\n[3] Testing Upload Revision (creates Version 2)...")
    v2_content = f"%PDF-1.4 Agreement Draft Revised Version 2 (Clauses Added) {salt} %%EOF".encode()
    files_v2 = {"file": ("commercial_lease_v2_amended.pdf", v2_content, "application/pdf")}
    data_v2 = {"uploaded_by": "Advocate Rajesh Sharma"}
    res_v2 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files=files_v2,
        data=data_v2,
        headers=lawyer_a_headers,
    )
    assert res_v2.status_code == 200, f"Upload v2 failed: {res_v2.text}"
    v2_json = res_v2.json()
    assert v2_json["version_number"] == 2
    assert v2_json["document_id"] == doc_id
    v2_hash = v2_json["file_hash"]
    assert v2_hash != v1_hash, "v2 hash must differ from v1 hash"
    assert v2_json["blockchain_status"] == "confirmed"
    print(f"    [OK] Version 2 created and anchored on-chain (Hash: {v2_hash[:16]}...)")

    # Check document master reflects v2
    doc_detail = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=lawyer_a_headers).json()
    assert doc_detail["version"] == 2
    assert doc_detail["version_count"] == 2
    assert doc_detail["file_hash"] == v2_hash
    print("    [OK] Master Document updated to current Version 2.")

    # 4. Upload Another Revision Creates Version 3
    print("\n[4] Testing Upload Second Revision (creates Version 3)...")
    v3_content = f"%PDF-1.4 Agreement Draft Final Version 3 (Executed) {salt} %%EOF".encode()
    files_v3 = {"file": ("commercial_lease_v3_final.pdf", v3_content, "application/pdf")}
    data_v3 = {"uploaded_by": "Advocate Rajesh Sharma"}
    res_v3 = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files=files_v3,
        data=data_v3,
        headers=lawyer_a_headers,
    )
    assert res_v3.status_code == 200, f"Upload v3 failed: {res_v3.text}"
    v3_json = res_v3.json()
    assert v3_json["version_number"] == 3
    v3_hash = v3_json["file_hash"]
    print(f"    [OK] Version 3 created and anchored on-chain (Hash: {v3_hash[:16]}...)")

    # Check versions list has 3 items in descending order
    versions_3 = requests.get(f"{BASE_URL}/documents/{doc_id}/versions", headers=lawyer_a_headers).json()
    assert len(versions_3) == 3, f"Expected 3 versions, got {len(versions_3)}"
    assert versions_3[0]["version_number"] == 3 and versions_3[0]["is_current"] is True
    assert versions_3[1]["version_number"] == 2 and versions_3[1]["is_current"] is False
    assert versions_3[2]["version_number"] == 1 and versions_3[2]["is_current"] is False
    print("    [OK] Versions list shows v3 (Current), v2, v1 in proper order.")

    # 5. Immutability & Independent Downloads
    print("\n[5] Testing Immutability & Independent Historical Downloads...")
    dl_v1 = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/download", headers=lawyer_a_headers)
    assert dl_v1.status_code == 200
    assert dl_v1.content == v1_content, "Downloaded v1 content must exactly match original v1 bytes"

    dl_v2 = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/2/download", headers=lawyer_a_headers)
    assert dl_v2.status_code == 200
    assert dl_v2.content == v2_content, "Downloaded v2 content must exactly match original v2 bytes"

    dl_v3 = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/3/download", headers=lawyer_a_headers)
    assert dl_v3.status_code == 200
    assert dl_v3.content == v3_content, "Downloaded v3 content must exactly match original v3 bytes"
    print("    [OK] Historical files v1, v2, v3 remain distinct, untampered, and independently downloadable.")

    # 6. Independent Cryptographic Blockchain Verification
    print("\n[6] Testing Independent Blockchain Verification for each version...")
    v1_ver_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_a_headers).json()
    assert v1_ver_res["verified"] is True and v1_ver_res["result"] == "VERIFIED"
    assert v1_ver_res["current_hash"] == v1_hash

    v2_ver_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_a_headers).json()
    assert v2_ver_res["verified"] is True and v2_ver_res["result"] == "VERIFIED"
    assert v2_ver_res["current_hash"] == v2_hash

    v3_ver_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/3/verify", headers=lawyer_a_headers).json()
    assert v3_ver_res["verified"] is True and v3_ver_res["result"] == "VERIFIED"
    assert v3_ver_res["current_hash"] == v3_hash

    # Master verify verifies current active version (v3)
    master_ver_res = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_a_headers).json()
    assert master_ver_res["verified"] is True and master_ver_res["result"] == "VERIFIED"
    assert master_ver_res["current_hash"] == v3_hash
    print("    [OK] v1, v2, v3 and master verify all report VERIFIED against smart contract.")

    # 7. Tamper Detection on Specific Historical Version
    print("\n[7] Testing Tamper Detection on Historical Version 2...")
    v2_meta = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/2", headers=lawyer_a_headers).json()
    v2_filename = v2_meta.get("stored_filename") or v2_meta.get("filename")
    v2_disk_path = os.path.join(UPLOADS_DIR, v2_filename)
    assert os.path.exists(v2_disk_path), f"File {v2_disk_path} must exist"

    # Tamper with v2 file on disk
    with open(v2_disk_path, "wb") as f:
        f.write(b"%PDF-1.4 TAMPERED V2 CONTENT INJECTED BY ADVERSARY %%EOF")

    # Verify v2 -> Expect TAMPERED
    tamper_v2_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_a_headers).json()
    assert tamper_v2_res["verified"] is False
    assert tamper_v2_res["result"] == "TAMPERED"
    assert tamper_v2_res["current_hash"] != tamper_v2_res["blockchain_hash"]
    print("    [OK] Version 2 modification correctly detected as TAMPERED.")

    # Confirm v1 and v3 remain VERIFIED
    chk_v1 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_a_headers).json()
    assert chk_v1["verified"] is True and chk_v1["result"] == "VERIFIED"
    chk_v3 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/3/verify", headers=lawyer_a_headers).json()
    assert chk_v3["verified"] is True and chk_v3["result"] == "VERIFIED"
    print("    [OK] Versions 1 and 3 remain strictly VERIFIED (isolation maintained).")

    # Restore v2 file bytes
    with open(v2_disk_path, "wb") as f:
        f.write(v2_content)
    restore_v2 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=lawyer_a_headers).json()
    assert restore_v2["verified"] is True and restore_v2["result"] == "VERIFIED"
    print("    [OK] Restoring Version 2 bytes returns state to VERIFIED.")

    # 8. Security & RBAC Scoping
    print("\n[8] Testing Security & RBAC Scoping...")
    # 8a. Lawyer B cannot upload version to Lawyer A's document (Expect 403)
    unauth_v_upload = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("malicious_v4.pdf", b"fake", "application/pdf")},
        headers=lawyer_b_headers,
    )
    assert unauth_v_upload.status_code == 403, f"Expected 403, got {unauth_v_upload.status_code}"
    print("    [OK] Unauthorized Lawyer B rejected from uploading new revision (403 Forbidden).")

    # 8b. Judge and Client cannot upload new versions (Expect 403)
    judge_v_upload = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("judge_v4.pdf", b"fake", "application/pdf")},
        headers=judge_headers,
    )
    assert judge_v_upload.status_code == 403
    client_v_upload = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("client_v4.pdf", b"fake", "application/pdf")},
        headers=client_headers,
    )
    assert client_v_upload.status_code == 403
    print("    [OK] Non-depositor roles (Judge/Client) blocked from uploading revisions (403 Forbidden).")

    # 8c. Share document with Judge & Client
    share_res = requests.post(f"{BASE_URL}/documents/{doc_id}/share", json={"shared_with_user_id": judge_id}, headers=lawyer_a_headers)
    assert share_res.status_code == 200
    share_c_res = requests.post(f"{BASE_URL}/documents/{doc_id}/share", json={"shared_with_user_id": client_id}, headers=lawyer_a_headers)
    assert share_c_res.status_code == 200

    # Judge and Client can view all versions and verify
    j_versions = requests.get(f"{BASE_URL}/documents/{doc_id}/versions", headers=judge_headers)
    assert j_versions.status_code == 200 and len(j_versions.json()) == 3
    j_v2_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers=judge_headers)
    assert j_v2_verify.status_code == 200 and j_v2_verify.json()["verified"] is True
    print("    [OK] Shared Judge can view and independently verify all historical versions.")

    # 8d. Unauthorized Lawyer B cannot access versions (Expect 403)
    b_versions = requests.get(f"{BASE_URL}/documents/{doc_id}/versions", headers=lawyer_b_headers)
    assert b_versions.status_code == 403
    b_v1_dl = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/download", headers=lawyer_b_headers)
    assert b_v1_dl.status_code == 403
    print("    [OK] Unauthorized Lawyer B blocked from accessing version records or downloads (403 Forbidden).")

    # 9. Validation & Duplicate Detection on Versions
    print("\n[9] Testing Validation & Duplicate Detection on Version Uploads...")
    # 9a. Unsupported file extension (Expect 400)
    bad_ext = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("revision.exe", b"MZ\x90\x00", "application/x-msdownload")},
        headers=lawyer_a_headers,
    )
    assert bad_ext.status_code == 400
    print("    [OK] Unsupported file extension for revision rejected (400 Bad Request).")

    # 9b. Duplicate hash without allow_duplicate (Expect 409 Conflict)
    dup_v_res = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("exact_duplicate_v3.pdf", v3_content, "application/pdf")},
        headers=lawyer_a_headers,
    )
    assert dup_v_res.status_code == 409, f"Expected 409, got {dup_v_res.status_code}"
    dup_v_json = dup_v_res.json()["detail"]
    assert dup_v_json["code"] == "DUPLICATE_VERSION"
    assert dup_v_json["existing_version"]["version_number"] == 3
    print("    [OK] Re-uploading identical bytes without override rejected (409 DUPLICATE_VERSION).")

    # 9c. Duplicate hash with allow_duplicate=true (Expect Success creating Version 4)
    dup_override_res = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("duplicate_override_v4.pdf", v3_content, "application/pdf")},
        data={"allow_duplicate": "true"},
        headers=lawyer_a_headers,
    )
    assert dup_override_res.status_code == 200
    assert dup_override_res.json()["version_number"] == 4
    print("    [OK] Duplicate revision with allow_duplicate=true succeeded as Version 4.")

    # 10. Concurrency & Uniqueness Database Constraint
    print("\n[10] Testing Database Uniqueness Constraint (document_id, version_number)...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    raised_integrity = False
    try:
        cursor.execute("""
            INSERT INTO document_versions (document_id, version_number, filename, stored_filename, file_size, file_hash, uploaded_by)
            VALUES (?, 1, 'conflict.pdf', 'conflict.pdf', 100, 'somehash12345', 'Tester')
        """, (doc_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        raised_integrity = True
    finally:
        conn.close()

    assert raised_integrity is True, "Database UNIQUE constraint on (document_id, version_number) must prevent duplicate version numbers"
    print("    [OK] Database uniqueness constraint strictly prevents duplicate (document_id, version_number).")

    # 11. Development Vault Reset Cleanly Purges Versions
    print("\n[11] Testing Development Vault Reset on Document Versions...")
    reset_res = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert reset_res.status_code == 200
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM document_versions")
    v_count = c.fetchone()[0]
    c.execute("SELECT count(*) FROM documents")
    d_count = c.fetchone()[0]
    conn.close()
    assert v_count == 0, f"Expected 0 document_versions after reset, got {v_count}"
    assert d_count == 0, f"Expected 0 documents after reset, got {d_count}"
    assert len(os.listdir(UPLOADS_DIR)) == 0, "Uploads directory must be empty after reset"
    print("    [OK] Vault reset cleanly purged all documents, versions, shares, and disk files.")

    print("\n=================================================================")
    print("ALL 11 VERSION HISTORY TEST SUITES PASSED WITH 100% SUCCESS!")
    print("=================================================================")


if __name__ == "__main__":
    run_version_history_tests()
