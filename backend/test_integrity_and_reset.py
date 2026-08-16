import os
import requests
import json
import sqlite3

BASE_URL = "http://127.0.0.1:8000"
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DB_PATH = os.path.join(os.path.dirname(__file__), "legalvault.db")

def run_tests():
    print("=================================================================")
    print("RUNNING INTEGRITY CYCLE & DEVELOPMENT RESET AUTOMATED TEST SUITE")
    print("=================================================================")

    # 1. Login all users
    lawyer_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "lawyer123"}).json()
    lawyer_token = lawyer_resp["access_token"]
    lawyer_headers = {"Authorization": f"Bearer {lawyer_token}"}

    judge_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "judge@legalvault.local", "password": "judge123"}).json()
    judge_token = judge_resp["access_token"]
    judge_headers = {"Authorization": f"Bearer {judge_token}"}
    judge_id = judge_resp["user"]["id"]

    client_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "client@legalvault.local", "password": "client123"}).json()
    client_token = client_resp["access_token"]
    client_headers = {"Authorization": f"Bearer {client_token}"}

    admin_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@legalvault.local", "password": "admin123"}).json()
    admin_token = admin_resp["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    print("\n[1] Authentication verified for Lawyer, Judge, Client, and Admin.")

    # 2. Deposit test document
    print("\n[2] Lawyer deposits test document (integrity_lifecycle_doc.pdf)...")
    original_pdf_bytes = b"%PDF-1.4 Canonical Unaltered Evidentiary Record 2026 %%EOF"
    files = {"file": ("integrity_lifecycle_doc.pdf", original_pdf_bytes, "application/pdf")}
    data = {"case_number": "CASE-INTEGRITY-CYCLE-2026", "uploaded_by": "Advocate Rajesh Sharma"}
    upload_resp = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_headers)
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    doc_id = upload_resp.json()["document_id"]
    filename = upload_resp.json()["filename"]
    print(f">>> Deposited Document ID #{doc_id} ({filename})")

    # 3. Share with Judge
    print(f"\n[3] Lawyer shares Document #{doc_id} with Judge...")
    share_resp = requests.post(f"{BASE_URL}/documents/{doc_id}/share", json={"shared_with_user_id": judge_id}, headers=lawyer_headers)
    assert share_resp.status_code == 200, f"Share failed: {share_resp.text}"
    print(f">>> Document #{doc_id} shared with Judge (Share ID #{share_resp.json()['id']})")

    # 4. Phase A: Initial Verification -> Expect VERIFIED
    print(f"\n[4] Phase A: Verify Initial Document #{doc_id} against Blockchain...")
    verify_a = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_headers).json()
    print(f">>> Result: {verify_a['result']} (verified={verify_a['verified']})")
    assert verify_a["verified"] is True
    assert verify_a["result"] == "VERIFIED"
    assert verify_a["current_hash"] == verify_a["blockchain_hash"]
    print(">>> Phase A Verified: Document is authentic and matches blockchain ledger.")

    # 5. Phase B: Simulate Tampering on disk -> Expect TAMPERED
    print(f"\n[5] Phase B: Simulating off-chain file alteration on disk...")
    target_file_path = os.path.join(UPLOADS_DIR, filename)
    with open(target_file_path, "wb") as f:
        f.write(b"%PDF-1.4 TAMPERED_CONTENT_MALICIOUS_INJECTION %%EOF")
    print(f">>> File '{filename}' modified on disk.")

    verify_b = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_headers).json()
    print(f">>> Result: {verify_b['result']} (verified={verify_b['verified']})")
    print(f"    Current On-Disk Hash:   {verify_b['current_hash']}")
    print(f"    Immutable On-Chain Hash:{verify_b['blockchain_hash']}")
    assert verify_b["verified"] is False
    assert verify_b["result"] == "TAMPERED"
    assert verify_b["current_hash"] != verify_b["blockchain_hash"]
    assert verify_b["blockchain_status"] == "confirmed"  # Anchor remains confirmed
    print(">>> Phase B Verified: Tamper detected! Blockchain anchor remains intact while integrity is TAMPERED.")

    # 6. Phase C: Restore original file on disk -> Expect VERIFIED again
    print(f"\n[6] Phase C: Restoring original file bytes to disk...")
    with open(target_file_path, "wb") as f:
        f.write(original_pdf_bytes)
    print(f">>> File '{filename}' restored to authentic state.")

    verify_c = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_headers).json()
    print(f">>> Result: {verify_c['result']} (verified={verify_c['verified']})")
    assert verify_c["verified"] is True
    assert verify_c["result"] == "VERIFIED"
    assert verify_c["current_hash"] == verify_c["blockchain_hash"]
    print(">>> Phase C Verified: Restored document successfully re-verified as VERIFIED.")

    # 7. Access Control on Development Reset Endpoint
    print("\n[7] Testing Access Control on POST /admin/dev/reset-vault...")
    
    # 7a. Unauthenticated
    unauth_resp = requests.post(f"{BASE_URL}/admin/dev/reset-vault")
    assert unauth_resp.status_code == 401, f"Expected 401, got {unauth_resp.status_code}"
    print(">>> Unauthenticated access rejected (401 Unauthorized)")

    # 7b. Lawyer (Non-Admin)
    lawyer_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=lawyer_headers)
    assert lawyer_reset.status_code == 403, f"Expected 403 for Lawyer, got {lawyer_reset.status_code}"
    print(">>> Lawyer access rejected (403 Forbidden)")

    # 7c. Judge (Non-Admin)
    judge_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=judge_headers)
    assert judge_reset.status_code == 403, f"Expected 403 for Judge, got {judge_reset.status_code}"
    print(">>> Judge access rejected (403 Forbidden)")

    # 7d. Client (Non-Admin)
    client_reset = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=client_headers)
    assert client_reset.status_code == 403, f"Expected 403 for Client, got {client_reset.status_code}"
    print(">>> Client access rejected (403 Forbidden)")

    # 8. Execute Reset as Admin
    print("\n[8] Executing POST /admin/dev/reset-vault as ADMIN...")
    reset_resp = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert reset_resp.status_code == 200, f"Reset failed: {reset_resp.text}"
    reset_data = reset_resp.json()
    print(f">>> Reset Response: {json.dumps(reset_data, indent=2)}")
    assert reset_data["documents_deleted"] >= 1
    assert reset_data["shares_deleted"] >= 1
    assert reset_data["files_deleted"] >= 1

    # 9. Verify Post-Reset State
    print("\n[9] Verifying Clean Database & File State...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM documents")
    post_doc_count = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM document_shares")
    post_share_count = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM users")
    post_user_count = cursor.fetchone()[0]
    cursor.execute("SELECT id, name, email, role FROM users ORDER BY id ASC")
    users = cursor.fetchall()
    conn.close()

    assert post_doc_count == 0, f"Expected 0 documents, got {post_doc_count}"
    assert post_share_count == 0, f"Expected 0 shares, got {post_share_count}"
    assert post_user_count == 5, f"Expected 5 preserved users, got {post_user_count}"
    print(f">>> Documents count: {post_doc_count}")
    print(f">>> Shares count: {post_share_count}")
    print(f">>> Preserved users count: {post_user_count}")
    for u in users:
        print(f"      User #{u[0]}: {u[1]} ({u[2]}) [{u[3]}]")

    remaining_files = os.listdir(UPLOADS_DIR) if os.path.exists(UPLOADS_DIR) else []
    assert len(remaining_files) == 0, f"Expected 0 files, got {remaining_files}"
    print(f">>> Uploads folder files count: {len(remaining_files)}")

    print("\n=================================================================")
    print("ALL INTEGRITY LIFECYCLE & DEV RESET TESTS PASSED WITH 100% SUCCESS!")
    print("=================================================================")

if __name__ == "__main__":
    run_tests()
