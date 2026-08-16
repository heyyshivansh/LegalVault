import os
import requests
import json
import sqlite3

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "legalvault.db")

def run_tests():
    print("=================================================================")
    print("RUNNING STABILITY & DATA INTEGRITY AUTOMATED TEST SUITE")
    print("=================================================================")

    # 1. Authenticate users
    lawyer_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "lawyer123"}).json()
    lawyer_token = lawyer_resp["access_token"]
    lawyer_headers = {"Authorization": f"Bearer {lawyer_token}"}

    admin_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@legalvault.local", "password": "admin123"}).json()
    admin_token = admin_resp["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    judge_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "judge@legalvault.local", "password": "judge123"}).json()
    judge_headers = {"Authorization": f"Bearer {judge_resp['access_token']}"}

    client_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "client@legalvault.local", "password": "client123"}).json()
    client_headers = {"Authorization": f"Bearer {client_resp['access_token']}"}

    print("[1] Authentication verified across all system roles.")

    # 1b. Clean reset at start to ensure idempotent state
    requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)

    import time
    salt = str(int(time.time()))

    # 2. Upload File-Type Validation
    print("\n[2] Testing Upload File-Type Validation...")
    
    # 2a. Supported Types: .pdf, .txt, .docx, .png, .jpg
    types_to_test = [
        ("contract.pdf", f"%PDF-1.4 Valid PDF Evidence Record {salt} %%EOF".encode(), "application/pdf"),
        ("statement.txt", f"Official witness deposition statement transcript {salt}.".encode(), "text/plain"),
        ("brief.docx", f"PK\x03\x04\x14\x00\x00\x00\x08\x00Sample Mock DOCX Document Stream {salt}".encode(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("exhibit.png", f"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRSample Mock PNG Stream {salt}".encode(), "image/png"),
        ("photo.jpg", f"\xff\xd8\xff\xe0\x00\x10JFIF\x00Sample Mock JPG Stream {salt}".encode(), "image/jpeg"),
    ]

    for fname, content, mime in types_to_test:
        files = {"file": (fname, content, mime)}
        data = {"case_number": f"CASE-TYPE-TEST-{fname}", "uploaded_by": "Advocate Rajesh Sharma"}
        res = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
        assert res.status_code == 200, f"Expected 200 for supported extension {fname}, got {res.status_code}: {res.text}"
        print(f"    [OK] Accepted supported format: {fname} (ID #{res.json()['document_id']})")

    # 2b. Unsupported Types: .exe, .py, .sh, .bin -> Expect 400 Bad Request
    unsupported_types = [
        ("malicious.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/x-msdownload"),
        ("exploit.py", b"import os; os.system('echo hacked')", "text/x-python"),
        ("script.sh", b"#!/bin/bash\nrm -rf /", "application/x-sh"),
    ]

    for fname, content, mime in unsupported_types:
        files = {"file": (fname, content, mime)}
        data = {"case_number": f"CASE-REJECT-{fname}", "uploaded_by": "Advocate Rajesh Sharma"}
        res = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
        assert res.status_code == 400, f"Expected 400 for unsupported extension {fname}, got {res.status_code}: {res.text}"
        assert "Unsupported file format" in res.json()["detail"]
        print(f"    [OK] Correctly rejected unsupported format: {fname} (400 Bad Request)")

    # 3. Upload File-Size Validation
    print("\n[3] Testing Upload File-Size Validation (Max 10 MB)...")
    
    # 3a. Valid file under 10MB
    valid_size_bytes = b"%PDF-1.4 " + (b"A" * 50000) + b" %%EOF"
    files = {"file": ("normal_size_doc.pdf", valid_size_bytes, "application/pdf")}
    data = {"case_number": "CASE-SIZE-VALID", "uploaded_by": "Advocate Rajesh Sharma"}
    res = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
    assert res.status_code == 200, f"Expected 200 for valid sized file, got {res.status_code}: {res.text}"
    print(f"    [OK] Valid 50 KB file accepted (Doc #{res.json()['document_id']})")

    # 3b. Oversized file > 10MB (e.g. 10.5 MB) -> Expect 413 Payload Too Large
    oversized_bytes = b"%PDF-1.4 " + (b"X" * (11 * 1024 * 1024)) + b" %%EOF"
    files = {"file": ("oversized_doc.pdf", oversized_bytes, "application/pdf")}
    data = {"case_number": "CASE-SIZE-OVERSIZE", "uploaded_by": "Advocate Rajesh Sharma"}
    res = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
    assert res.status_code == 413, f"Expected 413 for oversized file, got {res.status_code}: {res.text}"
    assert "exceeds maximum allowed size" in res.json()["detail"]
    print("    [OK] Oversized 11 MB file correctly rejected with HTTP 413 Payload Too Large")

    # 4. Duplicate SHA-256 Detection
    print("\n[4] Testing Duplicate SHA-256 Detection...")
    dup_bytes = b"%PDF-1.4 Unique Canonical Evidence Content for Duplicate Test %%EOF"
    
    # 4a. Initial Upload -> Success
    files = {"file": ("canonical_orig.pdf", dup_bytes, "application/pdf")}
    data = {"case_number": "CASE-DUP-001", "uploaded_by": "Advocate Rajesh Sharma"}
    res_orig = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
    assert res_orig.status_code == 200
    orig_doc_id = res_orig.json()["document_id"]
    orig_hash = res_orig.json()["file_hash"]
    print(f"    [OK] Initial canonical document uploaded (ID #{orig_doc_id}, Hash: {orig_hash[:16]}...)")

    # 4b. Duplicate Upload without override -> Expect 409 Conflict
    files = {"file": ("duplicate_attempt.pdf", dup_bytes, "application/pdf")}
    data = {"case_number": "CASE-DUP-002", "uploaded_by": "Advocate Rajesh Sharma", "allow_duplicate": "false"}
    res_dup = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
    assert res_dup.status_code == 409, f"Expected 409 Conflict for duplicate file, got {res_dup.status_code}: {res_dup.text}"
    dup_detail = res_dup.json()["detail"]
    assert dup_detail["code"] == "DUPLICATE_DOCUMENT"
    assert dup_detail["existing_document"]["id"] == orig_doc_id
    assert dup_detail["existing_document"]["file_hash"] == orig_hash
    print(f"    [OK] Duplicate upload correctly detected & rejected with HTTP 409 Conflict (Existing Match: #{orig_doc_id})")

    # 4c. Duplicate Upload with override (allow_duplicate=true) -> Success
    files = {"file": ("duplicate_override.pdf", dup_bytes, "application/pdf")}
    data = {"case_number": "CASE-DUP-LEGIT-REENTRY", "uploaded_by": "Advocate Rajesh Sharma", "allow_duplicate": "true"}
    res_override = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
    assert res_override.status_code == 200, f"Expected 200 for duplicate with allow_duplicate=true, got {res_override.status_code}: {res_override.text}"
    override_doc_id = res_override.json()["document_id"]
    print(f"    [OK] Duplicate successfully deposited with explicit override flag (New Distinct Record ID #{override_doc_id})")

    # 5. Blockchain Verification & State Distinctions
    print("\n[5] Testing Blockchain States (VERIFIED, TAMPERED, BLOCKCHAIN_PROOF_UNAVAILABLE)...")
    
    # 5a. VERIFIED state
    verify_res = requests.post(f"{BASE_URL}/documents/{orig_doc_id}/verify", headers=lawyer_headers).json()
    assert verify_res["verified"] is True
    assert verify_res["result"] == "VERIFIED"
    assert verify_res["current_hash"] == verify_res["blockchain_hash"]
    print("    [OK] State 'VERIFIED': Canonical on-disk hash matches blockchain ledger.")

    # 5b. TAMPERED state
    orig_path = os.path.join(UPLOADS_DIR, "canonical_orig.pdf")
    with open(orig_path, "wb") as f:
        f.write(b"%PDF-1.4 TAMPERED BY CORRUPTOR %%EOF")
    
    tamper_res = requests.post(f"{BASE_URL}/documents/{orig_doc_id}/verify", headers=lawyer_headers).json()
    assert tamper_res["verified"] is False
    assert tamper_res["result"] == "TAMPERED"
    assert tamper_res["blockchain_status"] == "confirmed" # Anchor intact!
    assert tamper_res["current_hash"] != tamper_res["blockchain_hash"]
    print("    [OK] State 'TAMPERED': File modification detected while anchor remains confirmed.")

    # Restore file
    with open(orig_path, "wb") as f:
        f.write(dup_bytes)
    restore_res = requests.post(f"{BASE_URL}/documents/{orig_doc_id}/verify", headers=lawyer_headers).json()
    assert restore_res["verified"] is True
    assert restore_res["result"] == "VERIFIED"
    print("    [OK] State Restored: Re-verified as VERIFIED after restoring original bytes.")

    # 5c. BLOCKCHAIN_PROOF_UNAVAILABLE state (Insert simulated SQLite record whose ID was never registered on Hardhat)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Create fake un-anchored document record #88888
    fake_file_name = "unregistered_chain_doc.pdf"
    fake_file_path = os.path.join(UPLOADS_DIR, fake_file_name)
    with open(fake_file_path, "wb") as f:
        f.write(b"%PDF-1.4 Fake Document for Unregistered Proof Test %%EOF")
    fake_hash = "1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"
    cursor.execute("""
        INSERT INTO documents (id, filename, case_number, uploaded_by, owner_id, file_hash, blockchain_status)
        VALUES (88888, ?, 'CASE-UNREGISTERED-88888', 'Advocate Rajesh Sharma', 1, ?, 'confirmed')
    """, (fake_file_name, fake_hash))
    conn.commit()
    conn.close()

    unregistered_res = requests.post(f"{BASE_URL}/documents/88888/verify", headers=lawyer_headers).json()
    assert unregistered_res["verified"] is False
    assert unregistered_res["result"] == "BLOCKCHAIN_PROOF_UNAVAILABLE"
    assert "proof is unavailable" in unregistered_res["message"]
    assert unregistered_res["blockchain_hash"] is None
    print("    [OK] State 'BLOCKCHAIN_PROOF_UNAVAILABLE': Missing blockchain proof correctly distinguished from TAMPERED.")

    # Clean up mock document 88888
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM documents WHERE id = 88888")
    conn.commit()
    conn.close()
    if os.path.exists(fake_file_path):
        os.remove(fake_file_path)

    # 6. Development Vault Reset Access Control & Execution
    print("\n[6] Testing Development Vault Reset Access Control & Execution...")
    
    # 6a. Access control checks
    unauth_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault")
    assert unauth_reset.status_code == 401
    lawyer_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=lawyer_headers)
    assert lawyer_reset.status_code == 403
    judge_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=judge_headers)
    assert judge_reset.status_code == 403
    client_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=client_headers)
    assert client_reset.status_code == 403
    print("    [OK] Access control strictly blocks unauthenticated, Lawyer, Judge, and Client requests (401/403)")

    # 6b. Admin execution
    admin_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert admin_reset.status_code == 200, f"Reset failed: {admin_reset.text}"
    reset_data = admin_reset.json()
    print(f"    [OK] Admin reset succeeded: {reset_data['documents_deleted']} documents, {reset_data['shares_deleted']} shares, {reset_data['files_deleted']} files deleted.")
    assert reset_data["documents_deleted"] >= 1

    # 6c. Verify clean database state & user preservation
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM documents")
    doc_count = c.fetchone()[0]
    c.execute("SELECT count(*) FROM document_shares")
    share_count = c.fetchone()[0]
    c.execute("SELECT count(*) FROM users")
    user_count = c.fetchone()[0]
    conn.close()

    assert doc_count == 0, f"Expected 0 docs, got {doc_count}"
    assert share_count == 0, f"Expected 0 shares, got {share_count}"
    assert user_count == 5, f"Expected 5 preserved users, got {user_count}"
    assert len(os.listdir(UPLOADS_DIR)) == 0, "Expected empty uploads folder"
    print("    [OK] Post-reset state verified: 0 documents, 0 shares, 0 files in uploads, all 5 users preserved.")

    print("\n=================================================================")
    print("ALL STABILITY & DATA INTEGRITY TESTS PASSED WITH 100% SUCCESS!")
    print("=================================================================")

if __name__ == "__main__":
    run_tests()
