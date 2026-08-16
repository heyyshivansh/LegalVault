import requests
import json
import os
import sqlite3

BASE_URL = "http://127.0.0.1:8000"


def run_tests():
    print("=====================================================")
    print("RUNNING VERIFICATION / TAMPER DETECTION TEST SUITE")
    print("=====================================================")

    # Authenticate as Admin to verify full lifecycle
    auth_resp = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "admin@legalvault.local", "password": "admin123"},
    )
    assert auth_resp.status_code == 200, f"Auth failed: {auth_resp.text}"
    token = auth_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    import time
    salt = str(int(time.time()))

    # --- TEST CASE A: ORIGINAL UNTAMPERED DOCUMENT ---
    print("\n[TEST CASE A] Original Document Verification...")
    pdf_orig_bytes = f"%PDF-1.4 1 0 obj << /Type /Catalog >> endobj trailer << /Size {salt} >> %%EOF".encode()
    files_a = {"file": ("original_verification_doc.pdf", pdf_orig_bytes, "application/pdf")}
    data_a = {"case_number": f"CASE-VERIFY-TEST-{salt}", "uploaded_by": "Advocate Rajesh Sharma"}
    upload_a = requests.post(f"{BASE_URL}/documents/upload", files=files_a, data=data_a, headers=headers)
    assert upload_a.status_code == 200, f"Upload failed: {upload_a.text}"
    doc_a_id = upload_a.json()["document_id"]

    resp_a = requests.post(f"{BASE_URL}/documents/{doc_a_id}/verify", headers=headers)
    print("HTTP Status:", resp_a.status_code)
    data_a = resp_a.json()
    print("Payload:", json.dumps(data_a, indent=2))

    assert resp_a.status_code == 200, f"Expected 200, got {resp_a.status_code}"
    assert data_a["verified"] is True, f"Expected verified=True, got {data_a['verified']}"
    assert data_a["result"] == "VERIFIED", f"Expected result=VERIFIED, got {data_a['result']}"
    assert data_a["current_hash"] == data_a["blockchain_hash"], "Current hash must match blockchain hash"
    print(">>> TEST CASE A PASSED (VERIFIED)!")

    # --- TEST CASE B: TAMPER DETECTION ON SEPARATE TEST DOCUMENT ---
    print("\n[TEST CASE B] Tamper Detection Test...")
    # 1. Upload a separate test document
    pdf_tamper_orig = f"%PDF-1.4 2 0 obj << /Type /TamperFixture >> endobj trailer << /Size {salt}B >> %%EOF".encode()
    files_b = {"file": ("tamper_fixture_doc.pdf", pdf_tamper_orig, "application/pdf")}
    data_b = {"case_number": f"CASE-TAMPER-TEST-{salt}", "uploaded_by": "Tester"}

    upload_resp = requests.post(f"{BASE_URL}/documents/upload", files=files_b, data=data_b, headers=headers)
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    upload_json = upload_resp.json()
    tamper_doc_id = upload_json["document_id"]
    original_reg_hash = upload_json["file_hash"]
    print(f"Uploaded separate fixture doc ID {tamper_doc_id}, registered on-chain hash: {original_reg_hash}")

    # 2. Verify it is initially VERIFIED
    pre_verify = requests.post(f"{BASE_URL}/documents/{tamper_doc_id}/verify", headers=headers).json()
    assert pre_verify["verified"] is True
    print("Fixture initially verified before tampering: OK")

    # 3. Safely tamper with the disk file bytes
    fixture_path = os.path.join(os.path.dirname(__file__), "uploads", "tamper_fixture_doc.pdf")
    with open(fixture_path, "wb") as f:
        f.write(b"%PDF-1.4 TAMPERED CONTENT INJECTED BY ATTACKER %%EOF")

    # 4. Run verification on tampered file
    resp_b = requests.post(f"{BASE_URL}/documents/{tamper_doc_id}/verify", headers=headers)
    print("HTTP Status:", resp_b.status_code)
    data_b = resp_b.json()
    print("Payload:", json.dumps(data_b, indent=2))

    assert resp_b.status_code == 200, f"Expected 200, got {resp_b.status_code}"
    assert data_b["verified"] is False, f"Expected verified=False, got {data_b['verified']}"
    assert data_b["result"] == "TAMPERED", f"Expected result=TAMPERED, got {data_b['result']}"
    assert data_b["current_hash"] != data_b["blockchain_hash"], "Current hash must NOT match blockchain hash"
    print(">>> TEST CASE B PASSED (TAMPERED)!")

    # Clean up fixture file on disk after test
    if os.path.exists(fixture_path):
        os.remove(fixture_path)

    # --- TEST CASE C: NONEXISTENT DOCUMENT ID ---
    print("\n[TEST CASE C] Nonexistent Document ID (999999)...")
    resp_c = requests.post(f"{BASE_URL}/documents/999999/verify", headers=headers)
    print("HTTP Status:", resp_c.status_code)
    print("Payload:", resp_c.json())
    assert resp_c.status_code == 404, f"Expected 404, got {resp_c.status_code}"
    print(">>> TEST CASE C PASSED (404 Document not found)!")

    # --- TEST CASE D: MISSING FILE ON DISK ---
    print(f"\n[TEST CASE D] Missing File on Disk Test (using doc ID {tamper_doc_id} where disk file was removed)...")
    resp_d = requests.post(f"{BASE_URL}/documents/{tamper_doc_id}/verify", headers=headers)
    print("HTTP Status:", resp_d.status_code)
    print("Payload:", resp_d.json())
    assert resp_d.status_code == 404, f"Expected 404, got {resp_d.status_code}"
    assert "not found on disk" in resp_d.json()["detail"]
    print(">>> TEST CASE D PASSED (404 Missing file on disk)!")

    # Clean up temporary test rows from SQLite and disk so test is idempotent
    try:
        db_path = os.path.join(os.path.dirname(__file__), "legalvault.db")
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM document_version_metadata WHERE document_id IN (?, ?)", (doc_a_id, tamper_doc_id))
        conn.execute("DELETE FROM document_versions WHERE document_id IN (?, ?)", (doc_a_id, tamper_doc_id))
        conn.execute("DELETE FROM documents WHERE id IN (?, ?)", (doc_a_id, tamper_doc_id))
        conn.commit()
        conn.close()
        orig_file = os.path.join(os.path.dirname(__file__), "uploads", "original_verification_doc.pdf")
        if os.path.exists(orig_file):
            os.remove(orig_file)
    except Exception as e:
        print("Note: cleanup exception:", e)

    print("\n=====================================================")
    print("ALL TEST CASES PASSED SUCCESSFULLY!")
    print("=====================================================")


if __name__ == "__main__":
    run_tests()
