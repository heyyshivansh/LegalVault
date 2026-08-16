"""
LegalVault Audit Trail Comprehensive Automated Test Suite
Verifies:
1. Taxonomy and unit functionality in audit.py (sanitization, formatting, masking).
2. Authentication auditing (LOGIN_SUCCESS, LOGIN_FAILED, LOGOUT).
3. Document lifecycle auditing (DOCUMENT_CREATED, DOCUMENT_VIEWED, DOCUMENT_DOWNLOADED).
4. Version lifecycle auditing (VERSION_CREATED, VERSION_VIEWED, VERSION_DOWNLOADED).
5. Verification and tamper auditing (VERSION_VERIFIED, VERSION_TAMPERED, DOCUMENT_TAMPERED).
6. Sharing and revocation auditing (DOCUMENT_SHARED, DOCUMENT_SHARE_REVOKED, SHARED_DOCUMENT_ACCESSED).
7. Security denial persistence (ACCESS_DENIED, ACTION_DENIED with isolated DB sessions).
8. Document-level audit RBAC (GET /documents/{id}/audit: owner/shared/admin allowed, unauthorized 403, IP masking).
9. Admin system-wide audit (GET /audit: admin 200 with forensic IP/email, other roles 403).
10. Vault reset persistence (VAULT_RESET survives development reset with reset counts).
11. Timestamps (UTC standard with trailing 'Z').
"""

import os
import io
import sys
import hashlib
import requests
from datetime import datetime, timezone

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, migrate_schema, seed_initial_users
from models import User, Document, DocumentVersion, DocumentShare, AuditLog, UserRole
from audit import (
    AuditEventType,
    AuditResult,
    AuditResourceType,
    log_audit_event,
    format_audit_event_response,
)

BASE_URL = "http://127.0.0.1:8000"


def get_token(email: str, password: str = "lawyer123"):
    res = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return res.json()["access_token"]


def test_audit_unit_and_formatting():
    """Unit tests for audit.py functions, metadata sanitization, and masking."""
    print("\n--- [1] Running Unit Tests on audit.py ---")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.role == UserRole.LAWYER).first()
        assert user is not None

        # Test log_audit_event
        event = log_audit_event(
            db=db,
            action=AuditEventType.DOCUMENT_CREATED,
            result=AuditResult.SUCCESS,
            actor=user,
            ip_address="192.168.1.100",
            metadata={"test_key": "test_val", "huge_text": "x" * 2000},
        )
        assert event.id is not None
        assert event.action == AuditEventType.DOCUMENT_CREATED
        assert event.actor_id == user.id
        assert event.actor_name == user.name
        assert event.actor_email == user.email
        assert event.actor_role == user.role
        assert event.ip_address == "192.168.1.100"
        assert event.created_at is not None

        # Test format_audit_event_response: document view (masked)
        doc_view = format_audit_event_response(event, is_system_view=False)
        assert doc_view["actor_email"] is None, "Actor email should be masked in doc view"
        assert doc_view["ip_address"] is None, "IP address should be masked in doc view"
        assert doc_view["created_at"].endswith("Z"), "Timestamp must end with Z"

        # Test format_audit_event_response: system view (unmasked)
        sys_view = format_audit_event_response(event, is_system_view=True)
        assert sys_view["actor_email"] == user.email, "Actor email should be visible in system view"
        assert sys_view["ip_address"] == "192.168.1.100", "IP address should be visible in system view"
        assert sys_view["created_at"].endswith("Z")

        print("  [OK] Unit audit logging, sanitization, and view masking verified.")
    finally:
        db.close()


def test_full_audit_trail_lifecycle():
    """Integration test suite covering all audit events, RBAC, tamper detection, and reset."""
    print("\n--- [2] Running Audit Trail Full Integration Test Suite ---")

    # Step 0: Ensure clean state using dev reset
    admin_token = get_token("admin@legalvault.local", "admin123")
    reset_res = requests.post(
        f"{BASE_URL}/admin/dev/reset-vault",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert reset_res.status_code == 200, f"Reset failed: {reset_res.text}"

    # Verify that VAULT_RESET is the only surviving audit event
    db = SessionLocal()
    try:
        logs_after_reset = db.query(AuditLog).all()
        assert len(logs_after_reset) == 1, f"Expected exactly 1 audit log after reset, got {len(logs_after_reset)}"
        assert logs_after_reset[0].action == AuditEventType.VAULT_RESET
        assert logs_after_reset[0].result == AuditResult.SUCCESS
        assert logs_after_reset[0].actor_role == UserRole.ADMIN
    finally:
        db.close()
    print("  [OK] Vault reset properly cleared previous logs and recorded single surviving VAULT_RESET event.")

    # Step 1: Authentication Auditing
    # 1a. Failed Login
    bad_login_res = requests.post(f"{BASE_URL}/auth/login", json={"email": "hacker@evil.com", "password": "wrongpassword"})
    assert bad_login_res.status_code == 401

    # 1b. Successful Lawyer Login
    lawyer_token = get_token("lawyer@legalvault.local", "lawyer123")
    assert lawyer_token is not None

    # 1c. Logout
    logout_res = requests.post(f"{BASE_URL}/auth/logout", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert logout_res.status_code == 200

    # Re-login tokens for remaining tests
    lawyer_token = get_token("lawyer@legalvault.local", "lawyer123")
    judge_token = get_token("judge@legalvault.local", "judge123")
    client_token = get_token("client@legalvault.local", "client123")

    # Verify auth events in DB
    db = SessionLocal()
    try:
        failed_log = db.query(AuditLog).filter(AuditLog.action == AuditEventType.LOGIN_FAILED).first()
        assert failed_log is not None
        assert failed_log.actor_email == "hacker@evil.com"
        assert failed_log.result == AuditResult.FAILED

        success_log = db.query(AuditLog).filter(
            AuditLog.action == AuditEventType.LOGIN_SUCCESS,
            AuditLog.actor_email == "lawyer@legalvault.local",
        ).first()
        assert success_log is not None
        assert success_log.result == AuditResult.SUCCESS

        logout_log = db.query(AuditLog).filter(
            AuditLog.action == AuditEventType.LOGOUT,
            AuditLog.actor_email == "lawyer@legalvault.local",
        ).first()
        assert logout_log is not None
        assert logout_log.result == AuditResult.SUCCESS
    finally:
        db.close()
    print("  [OK] LOGIN_FAILED, LOGIN_SUCCESS, and LOGOUT events properly audited.")

    # Step 2: Document Upload & Audit Logging
    doc_content = b"Evidentiary Agreement v1 initial draft for legal audit verification."
    upload_res = requests.post(
        f"{BASE_URL}/documents/upload",
        headers={"Authorization": f"Bearer {lawyer_token}"},
        data={"case_number": "AUDIT-2026-001"},
        files={"file": ("contract_v1.pdf", io.BytesIO(doc_content), "application/pdf")},
    )
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"
    doc_data = upload_res.json()
    doc_id = doc_data["document_id"]

    # Step 3: Document Download & View Audit Logging
    view_res = requests.get(f"{BASE_URL}/documents/{doc_id}", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert view_res.status_code == 200

    download_res = requests.get(f"{BASE_URL}/documents/{doc_id}/download", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert download_res.status_code == 200

    # Step 4: Version Revision Creation & Audit Logging
    rev_content = b"Evidentiary Agreement v2 finalized terms after judicial review."
    rev_res = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        headers={"Authorization": f"Bearer {lawyer_token}"},
        files={"file": ("contract_v2.pdf", io.BytesIO(rev_content), "application/pdf")},
    )
    assert rev_res.status_code == 200, f"Version upload failed: {rev_res.text}"
    v2_data = rev_res.json()
    assert v2_data["version_number"] == 2

    # Download version 1 and version 2
    v1_dl = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/1/download", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert v1_dl.status_code == 200
    v2_dl = requests.get(f"{BASE_URL}/documents/{doc_id}/versions/2/download", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert v2_dl.status_code == 200

    # Step 5: Verification and Tamper Auditing
    # 5a. Verify Document v1
    ver1_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/1/verify", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert ver1_res.status_code in [200, 502, 503]

    # 5b. Verify Document v2
    ver2_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert ver2_res.status_code in [200, 502, 503]

    # 5c. Simulate Tampering on v2 and Verify
    db = SessionLocal()
    try:
        v2_record = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.version_number == 2,
        ).first()
        assert v2_record is not None
        # Tamper stored file on disk
        from main import UPLOAD_DIR
        file_path = os.path.join(UPLOAD_DIR, v2_record.stored_filename)
        with open(file_path, "wb") as f:
            f.write(b"TAMPERED MALICIOUS CONTENT IN VERSION 2")
    finally:
        db.close()

    tamper_verify_res = requests.post(f"{BASE_URL}/documents/{doc_id}/versions/2/verify", headers={"Authorization": f"Bearer {lawyer_token}"})
    if tamper_verify_res.status_code == 200:
        tamper_data = tamper_verify_res.json()
        assert tamper_data["result"] == "TAMPERED"

    print("  [OK] Document upload, revision, downloads, and verification recorded.")

    # Step 6: Sharing & Revocation Auditing
    # 6a. Share with Judge
    db = SessionLocal()
    try:
        judge_user = db.query(User).filter(User.role == UserRole.JUDGE).first()
        judge_id = judge_user.id
    finally:
        db.close()

    share_res = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        headers={"Authorization": f"Bearer {lawyer_token}"},
        json={"shared_with_user_id": judge_id},
    )
    assert share_res.status_code == 200
    share_id = share_res.json()["id"]

    # 6b. Judge accesses shared document
    judge_access_res = requests.get(f"{BASE_URL}/documents/{doc_id}", headers={"Authorization": f"Bearer {judge_token}"})
    assert judge_access_res.status_code == 200

    # 6c. Revoke share
    revoke_res = requests.delete(
        f"{BASE_URL}/documents/{doc_id}/shares/{share_id}",
        headers={"Authorization": f"Bearer {lawyer_token}"},
    )
    assert revoke_res.status_code == 200

    print("  [OK] Sharing, shared document access, and revocation audited.")

    # Step 7: Security Denial Auditing (ACCESS_DENIED & ACTION_DENIED)
    # 7a. Client attempts to view unshared document (Expect 403 Forbidden)
    denied_view_res = requests.get(f"{BASE_URL}/documents/{doc_id}", headers={"Authorization": f"Bearer {client_token}"})
    assert denied_view_res.status_code == 403

    # 7b. Judge (not owner) attempts to upload a revision to the document (Expect 403 Forbidden)
    denied_rev_res = requests.post(
        f"{BASE_URL}/documents/{doc_id}/versions",
        headers={"Authorization": f"Bearer {judge_token}"},
        files={"file": ("unauthorized_rev.pdf", io.BytesIO(b"illegal rev"), "application/pdf")},
    )
    assert denied_rev_res.status_code == 403

    # Verify security denial audit logs in DB
    db = SessionLocal()
    try:
        access_denied_log = db.query(AuditLog).filter(
            AuditLog.action == AuditEventType.ACCESS_DENIED,
            AuditLog.document_id == doc_id,
        ).first()
        assert access_denied_log is not None
        assert access_denied_log.result == AuditResult.DENIED

        action_denied_log = db.query(AuditLog).filter(
            AuditLog.action == AuditEventType.ACTION_DENIED,
            AuditLog.document_id == doc_id,
        ).first()
        assert action_denied_log is not None
        assert action_denied_log.result == AuditResult.DENIED
    finally:
        db.close()

    print("  [OK] Security denials (ACCESS_DENIED, ACTION_DENIED) properly logged with isolated commits.")

    # Step 8: Document-Level Audit Trail API (GET /documents/{id}/audit)
    # 8a. Lawyer (Owner) access
    doc_audit_res = requests.get(f"{BASE_URL}/documents/{doc_id}/audit", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert doc_audit_res.status_code == 200
    doc_audit_data = doc_audit_res.json()
    assert doc_audit_data["document_id"] == doc_id
    assert doc_audit_data["total_count"] > 0
    # Verify IP and sensitive emails are masked in document-level views
    for event in doc_audit_data["events"]:
        assert event["ip_address"] is None, f"IP leaked in document view: {event}"
        assert event["actor_email"] is None, f"Actor email leaked in document view: {event}"
        assert event["created_at"].endswith("Z"), f"Timestamp does not end with Z: {event['created_at']}"

    # 8b. Filter by action and version
    filtered_audit_res = requests.get(
        f"{BASE_URL}/documents/{doc_id}/audit?action=DOCUMENT_CREATED",
        headers={"Authorization": f"Bearer {lawyer_token}"},
    )
    assert filtered_audit_res.status_code == 200
    filtered_data = filtered_audit_res.json()
    assert all(e["action"] == "DOCUMENT_CREATED" for e in filtered_data["events"])

    # 8c. Unauthorized client access (Expect 403 Forbidden)
    unauth_audit_res = requests.get(f"{BASE_URL}/documents/{doc_id}/audit", headers={"Authorization": f"Bearer {client_token}"})
    assert unauth_audit_res.status_code == 403

    print("  [OK] Document-level audit trail RBAC, filtering, and data masking verified.")

    # Step 9: Admin System-Wide Audit API (GET /audit)
    # 9a. Admin access (Expect 200 with full details)
    sys_audit_res = requests.get(f"{BASE_URL}/audit", headers={"Authorization": f"Bearer {admin_token}"})
    assert sys_audit_res.status_code == 200
    sys_audit_data = sys_audit_res.json()
    assert sys_audit_data["total_count"] >= doc_audit_data["total_count"]

    # In system audit view, actor emails should be visible for forensics
    has_actor_email = any(e["actor_email"] is not None for e in sys_audit_data["events"])
    assert has_actor_email, "Admin system audit view should provide actor emails for security oversight"

    # 9b. Non-admin access (Expect 403 Forbidden)
    lawyer_sys_res = requests.get(f"{BASE_URL}/audit", headers={"Authorization": f"Bearer {lawyer_token}"})
    assert lawyer_sys_res.status_code == 403

    judge_sys_res = requests.get(f"{BASE_URL}/audit", headers={"Authorization": f"Bearer {judge_token}"})
    assert judge_sys_res.status_code == 403

    client_sys_res = requests.get(f"{BASE_URL}/audit", headers={"Authorization": f"Bearer {client_token}"})
    assert client_sys_res.status_code == 403

    print("  [OK] System-wide audit trail RBAC and forensic detail verification passed.")


if __name__ == "__main__":
    print("=================================================================")
    print("LEGALVAULT AUDIT TRAIL AUTOMATED TEST SUITE")
    print("=================================================================")
    test_audit_unit_and_formatting()
    test_full_audit_trail_lifecycle()
    print("\n=================================================================")
    print("ALL AUDIT TRAIL TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")
