"""
LegalVault Admin Dashboard Comprehensive Automated Test Suite
Verifies:
1. RBAC enforcement on GET /admin/dashboard (401 unauthenticated, 403 Lawyer/Judge/Client, 200 Admin).
2. System overview metrics accuracy (documents, versions, storage bytes, user roles, shares).
3. Security telemetry (24h sliding window vs all-time counts for failed logins, access denials, action denials).
4. Authoritative latest verification state vs historical tamper events (verifying that restoring and re-verifying returns state to VERIFIED and removes from attention list).
5. Blockchain overview information & sanitization (no secrets or raw RPC URLs exposed).
6. UTC ISO timestamp formatting ending in 'Z'.
"""

import os
import io
import sys
import hashlib
import requests
from datetime import datetime, timezone, timedelta

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, migrate_schema, seed_initial_users
from models import User, Document, DocumentVersion, DocumentShare, AuditLog, UserRole
from audit import AuditEventType, AuditResult, log_audit_event

BASE_URL = "http://127.0.0.1:8000"
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def get_token(email: str, password: str) -> str:
    res = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def get_auth_headers(email: str, password: str) -> dict:
    token = get_token(email, password)
    return {"Authorization": f"Bearer {token}"}


def reset_dev_vault():
    admin_headers = get_auth_headers("admin@legalvault.local", "admin123")
    res = requests.post(f"{BASE_URL}/admin/dev/reset-vault", headers=admin_headers)
    assert res.status_code == 200, f"Vault reset failed: {res.text}"


def test_admin_dashboard_rbac():
    print("\n--- [1] Testing Admin Dashboard RBAC & Role Enforcement ---")
    reset_dev_vault()

    # 1. Unauthenticated request
    res = requests.get(f"{BASE_URL}/admin/dashboard")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print("  [OK] Unauthenticated request rejected with 401 Unauthorized.")

    # 2. Non-Admin roles
    lawyer_headers = get_auth_headers("lawyer@legalvault.local", "lawyer123")
    judge_headers = get_auth_headers("judge@legalvault.local", "judge123")
    client_headers = get_auth_headers("client@legalvault.local", "client123")

    res_lawyer = requests.get(f"{BASE_URL}/admin/dashboard", headers=lawyer_headers)
    assert res_lawyer.status_code == 403, f"Expected 403 for Lawyer, got {res_lawyer.status_code}"

    res_judge = requests.get(f"{BASE_URL}/admin/dashboard", headers=judge_headers)
    assert res_judge.status_code == 403, f"Expected 403 for Judge, got {res_judge.status_code}"

    res_client = requests.get(f"{BASE_URL}/admin/dashboard", headers=client_headers)
    assert res_client.status_code == 403, f"Expected 403 for Client, got {res_client.status_code}"
    print("  [OK] Lawyer, Judge, and Client roles strictly rejected with 403 Forbidden.")

    # 3. Admin role
    admin_headers = get_auth_headers("admin@legalvault.local", "admin123")
    res_admin = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers)
    assert res_admin.status_code == 200, f"Expected 200 for Admin, got {res_admin.status_code}: {res_admin.text}"
    data = res_admin.json()
    assert "system_overview" in data
    assert "integrity_overview" in data
    assert "security_overview" in data
    assert "blockchain_overview" in data
    assert "attention_documents" in data
    assert "recent_activity" in data
    assert "generated_at" in data
    assert data["generated_at"].endswith("Z")
    print("  [OK] Admin granted full access to dashboard (200 OK) with complete schema.")


def test_system_overview_metrics_accuracy():
    print("\n--- [2] Testing System Overview Metrics Aggregation Accuracy ---")
    reset_dev_vault()

    admin_headers = get_auth_headers("admin@legalvault.local", "admin123")
    lawyer_headers = get_auth_headers("lawyer@legalvault.local", "lawyer123")

    # 1. Upload Document 1
    doc_content = b"Initial contract clause for commercial agreement."
    file_payload = {"file": ("contract_v1.pdf", io.BytesIO(doc_content), "application/pdf")}
    res_upload1 = requests.post(
        f"{BASE_URL}/documents/upload",
        files=file_payload,
        data={"case_number": "CASE-2026-001", "uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    )
    assert res_upload1.status_code == 200, f"Upload 1 failed: {res_upload1.text}"
    doc1_id = res_upload1.json()["document_id"]

    # 2. Upload Revision (Version 2) to Document 1
    doc_v2_content = b"Revised contract clause with revised termination penalty."
    file_payload_v2 = {"file": ("contract_v2.pdf", io.BytesIO(doc_v2_content), "application/pdf")}
    res_rev = requests.post(
        f"{BASE_URL}/documents/{doc1_id}/versions",
        files=file_payload_v2,
        data={"uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    )
    assert res_rev.status_code == 200, f"Revision failed: {res_rev.text}"

    # 3. Upload Document 2
    doc2_content = b"Evidentiary affidavit testimony."
    file_payload2 = {"file": ("affidavit.pdf", io.BytesIO(doc2_content), "application/pdf")}
    res_upload2 = requests.post(
        f"{BASE_URL}/documents/upload",
        files=file_payload2,
        data={"case_number": "CASE-2026-002", "uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    )
    assert res_upload2.status_code == 200, f"Upload 2 failed: {res_upload2.text}"
    doc2_id = res_upload2.json()["document_id"]

    # 4. Share Document 1 with Judge
    db = SessionLocal()
    judge_user = db.query(User).filter(User.email == "judge@legalvault.local").first()
    db.close()
    res_share = requests.post(
        f"{BASE_URL}/documents/{doc1_id}/share",
        json={"shared_with_user_id": judge_user.id},
        headers=lawyer_headers,
    )
    assert res_share.status_code == 200, f"Share failed: {res_share.text}"

    # Fetch Dashboard
    res_dash = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers)
    assert res_dash.status_code == 200
    dash = res_dash.json()
    sys_metrics = dash["system_overview"]

    assert sys_metrics["total_documents"] == 2
    assert sys_metrics["total_versions"] == 3  # Doc 1 has v1+v2, Doc 2 has v1
    assert sys_metrics["total_active_shares"] == 1
    assert sys_metrics["shared_documents_count"] == 1
    assert sys_metrics["total_users"] >= 4
    assert sys_metrics["users_by_role"]["LAWYER"] >= 1
    assert sys_metrics["users_by_role"]["JUDGE"] >= 1
    assert sys_metrics["users_by_role"]["CLIENT"] >= 1
    assert sys_metrics["users_by_role"]["ADMIN"] >= 1
    assert sys_metrics["total_file_size_bytes"] == len(doc_content) + len(doc_v2_content) + len(doc2_content)
    print(f"  [OK] Metrics verified: {sys_metrics['total_documents']} docs, {sys_metrics['total_versions']} versions, {sys_metrics['total_active_shares']} shares, {sys_metrics['total_file_size_bytes']} bytes.")


def test_security_telemetry_24h_vs_all_time():
    print("\n--- [3] Testing Security Threat Telemetry (24h Window vs All-Time) ---")
    reset_dev_vault()

    admin_headers = get_auth_headers("admin@legalvault.local", "admin123")
    lawyer_headers = get_auth_headers("lawyer@legalvault.local", "lawyer123")

    # 1. Trigger failed login
    requests.post(f"{BASE_URL}/auth/login", json={"email": "hacker@malicious.local", "password": "wrongpassword"})
    requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "wrongpassword"})

    # 2. Upload a private document as Lawyer
    doc_payload = {"file": ("private_notes.pdf", io.BytesIO(b"Private notes"), "application/pdf")}
    res_upload = requests.post(
        f"{BASE_URL}/documents/upload",
        files=doc_payload,
        data={"case_number": "CASE-SEC-01", "uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    )
    doc_id = res_upload.json()["document_id"]

    # 3. Client attempts unauthorized access to private document (Triggers ACCESS_DENIED)
    client_headers = get_auth_headers("client@legalvault.local", "client123")
    requests.get(f"{BASE_URL}/documents/{doc_id}", headers=client_headers)

    # 4. Judge attempts unauthorized revision upload to lawyer document (Triggers ACTION_DENIED)
    judge_headers = get_auth_headers("judge@legalvault.local", "judge123")
    requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        files={"file": ("unauthorized.pdf", io.BytesIO(b"Unauthorized"), "application/pdf")},
        data={"uploaded_by": "Judge Rao"},
        headers=judge_headers,
    )

    # 5. Simulate an older security event from 30 hours ago in database
    db = SessionLocal()
    old_time = datetime.now(timezone.utc) - timedelta(hours=30)
    old_log = AuditLog(
        action=AuditEventType.LOGIN_FAILED,
        result=AuditResult.FAILED,
        actor_email="old_hacker@test.local",
        ip_address="127.0.0.1",
        reason="Historical failed login",
        created_at=old_time,
    )
    db.add(old_log)
    db.commit()
    db.close()

    # Fetch Dashboard
    res_dash = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers)
    assert res_dash.status_code == 200
    sec = res_dash.json()["security_overview"]

    assert sec["window_hours"] == 24
    assert sec["failed_logins_24h"] == 2
    assert sec["failed_logins_all_time"] == 3  # 2 recent + 1 historical from 30h ago
    assert sec["access_denied_24h"] == 1
    assert sec["access_denied_all_time"] == 1
    assert sec["action_denied_24h"] == 1
    assert sec["action_denied_all_time"] == 1
    print(f"  [OK] Security Telemetry accurate: 24h Failed Logins={sec['failed_logins_24h']} (All-Time={sec['failed_logins_all_time']}), Access Denied={sec['access_denied_24h']} (All-Time={sec['access_denied_all_time']}), Action Denied={sec['action_denied_24h']} (All-Time={sec['action_denied_all_time']}).")


def test_authoritative_integrity_vs_historical_tamper():
    print("\n--- [4] Testing Authoritative Current Integrity vs Historical Tamper Events ---")
    reset_dev_vault()

    admin_headers = get_auth_headers("admin@legalvault.local", "admin123")
    lawyer_headers = get_auth_headers("lawyer@legalvault.local", "lawyer123")

    # 1. Upload Document
    original_bytes = b"Official binding contract agreement for testing integrity."
    file_payload = {"file": ("contract.pdf", io.BytesIO(original_bytes), "application/pdf")}
    res_upload = requests.post(
        f"{BASE_URL}/documents/upload",
        files=file_payload,
        data={"case_number": "CASE-TAMPER-01", "uploaded_by": "Advocate Rajesh Sharma"},
        headers=lawyer_headers,
    )
    assert res_upload.status_code == 200, f"Upload failed: {res_upload.text}"
    doc_id = res_upload.json()["document_id"]

    # 2. Initial Verification -> VERIFIED
    res_v1 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_headers)
    assert res_v1.status_code == 200
    assert res_v1.json()["result"] == "VERIFIED"

    # Dashboard check: Should show 1 verified, 0 tampered, 0 attention
    dash1 = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers).json()
    assert dash1["integrity_overview"]["verified_documents"] == 1
    assert dash1["integrity_overview"]["tampered_documents"] == 0
    assert dash1["integrity_overview"]["attention_required_count"] == 0
    assert len(dash1["attention_documents"]) == 0
    print("  [OK] Step 1: Initial state verified as VERIFIED (0 attention required).")

    # 3. Simulate Physical File Tampering on disk
    db = SessionLocal()
    ver = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc_id, DocumentVersion.version_number == 1).first()
    file_path = os.path.join(UPLOAD_DIR, ver.stored_filename)
    with open(file_path, "wb") as f:
        f.write(b"MALICIOUS TAMPERED CONTRACT BYTES!")
    db.close()

    # 4. Verify tampered version -> TAMPERED
    res_v2 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_headers)
    assert res_v2.status_code == 200
    assert res_v2.json()["result"] == "TAMPERED"

    # Dashboard check: Should now show 1 tampered, 1 attention required
    dash2 = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers).json()
    assert dash2["integrity_overview"]["tampered_documents"] == 1
    assert dash2["integrity_overview"]["attention_required_count"] == 1
    assert len(dash2["attention_documents"]) == 1
    assert dash2["attention_documents"][0]["issue_type"] == "TAMPERED"
    assert dash2["attention_documents"][0]["document_id"] == doc_id
    print("  [OK] Step 2: Tamper incident correctly reported in integrity overview and attention queue.")

    # 5. Restore original bytes on disk (Simulating restoration / recovery)
    with open(file_path, "wb") as f:
        f.write(original_bytes)

    # 6. Re-Verify restored version -> VERIFIED
    res_v3 = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers=lawyer_headers)
    assert res_v3.status_code == 200
    assert res_v3.json()["result"] == "VERIFIED"

    # Dashboard check: MUST reflect current VERIFIED status, NOT stale historical tamper event!
    dash3 = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers).json()
    assert dash3["integrity_overview"]["verified_documents"] == 1
    assert dash3["integrity_overview"]["tampered_documents"] == 0
    assert dash3["integrity_overview"]["attention_required_count"] == 0
    assert len(dash3["attention_documents"]) == 0
    print("  [OK] Step 3: CRITICAL REQUIREMENT MET: Dashboard accurately reflects restored VERIFIED state while audit trail preserves historical tamper record!")


def test_blockchain_overview_sanitization():
    print("\n--- [5] Testing Blockchain Overview Information & Sanitization ---")
    admin_headers = get_auth_headers("admin@legalvault.local", "admin123")
    res = requests.get(f"{BASE_URL}/admin/dashboard", headers=admin_headers)
    assert res.status_code == 200
    chain = res.json()["blockchain_overview"]

    assert "is_connected" in chain
    assert "network_name" in chain
    assert "contract_address" in chain
    assert "anchored_versions_count" in chain
    assert "pending_versions_count" in chain

    # Ensure no raw RPC URLs or sensitive keys exposed
    chain_str = str(chain).lower()
    assert "http://" not in chain_str or "rpc" not in chain_str
    assert "private" not in chain_str
    assert "secret" not in chain_str
    print(f"  [OK] Blockchain info sanitized: Network={chain['network_name']}, Connected={chain['is_connected']}, Contract={chain['contract_address'][:10]}...")


if __name__ == "__main__":
    print("=================================================================")
    print("LEGALVAULT ADMIN DASHBOARD AUTOMATED TEST SUITE")
    print("=================================================================")
    test_admin_dashboard_rbac()
    test_system_overview_metrics_accuracy()
    test_security_telemetry_24h_vs_all_time()
    test_authoritative_integrity_vs_historical_tamper()
    test_blockchain_overview_sanitization()
    print("\n=================================================================")
    print("ALL ADMIN DASHBOARD TESTS COMPLETED SUCCESSFULLY WITH 100% PASS!")
    print("=================================================================")
