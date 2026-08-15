import requests
import json

BASE_URL = "http://127.0.0.1:8000"


def run_sharing_tests():
    print("=====================================================")
    print("RUNNING DOCUMENT SHARING & PERMISSIONS TEST SUITE")
    print("=====================================================")

    # 1. Login all users
    lawyer_a_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "lawyer123"}).json()
    lawyer_a_token = lawyer_a_resp["access_token"]
    lawyer_a_headers = {"Authorization": f"Bearer {lawyer_a_token}"}

    lawyer_b_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer2@legalvault.local", "password": "lawyer123"}).json()
    lawyer_b_token = lawyer_b_resp["access_token"]
    lawyer_b_headers = {"Authorization": f"Bearer {lawyer_b_token}"}

    judge_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "judge@legalvault.local", "password": "judge123"}).json()
    judge_token = judge_resp["access_token"]
    judge_headers = {"Authorization": f"Bearer {judge_token}"}
    judge_id = judge_resp["user"]["id"]

    client_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "client@legalvault.local", "password": "client123"}).json()
    client_token = client_resp["access_token"]
    client_headers = {"Authorization": f"Bearer {client_token}"}
    client_id = client_resp["user"]["id"]

    admin_resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@legalvault.local", "password": "admin123"}).json()
    admin_token = admin_resp["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Lawyer A deposits a test document
    print("\n[1] Lawyer A deposits a test document...")
    files = {"file": ("affidavit_evidence_share.pdf", b"%PDF-1.4 Evidentiary Affidavit for Sharing %%EOF", "application/pdf")}
    data = {"case_number": "CASE-SHARE-DEMO-001", "uploaded_by": "Advocate Rajesh Sharma"}
    upload_resp = requests.post(f"{BASE_URL}/documents/upload", files=files, data=data, headers=lawyer_a_headers)
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    doc_id = upload_resp.json()["document_id"]
    print(f">>> Lawyer A deposited Document ID #{doc_id}")

    # 3. Check Shareable Users endpoint
    print("\n[2] Testing GET /users/shareable...")
    users_resp = requests.get(f"{BASE_URL}/users/shareable", headers=lawyer_a_headers)
    assert users_resp.status_code == 200
    shareable = users_resp.json()
    roles = [u["role"] for u in shareable]
    assert "JUDGE" in roles and "CLIENT" in roles
    assert "LAWYER" not in roles and "ADMIN" not in roles
    print(f">>> Shareable recipients verified ({len(shareable)} candidates found: Judge, Client)")

    # 4. Lawyer A shares with Judge
    print(f"\n[3] Lawyer A shares Document #{doc_id} with Judge (ID: {judge_id})...")
    share_judge_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        json={"shared_with_user_id": judge_id},
        headers=lawyer_a_headers,
    )
    assert share_judge_resp.status_code == 200, f"Share with judge failed: {share_judge_resp.text}"
    judge_share_id = share_judge_resp.json()["id"]
    print(f">>> Document #{doc_id} successfully shared with Judge (Share ID #{judge_share_id})")

    # 5. Duplicate share prevention
    print("\n[4] Testing duplicate share rejection (Expect 409 Conflict)...")
    dup_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        json={"shared_with_user_id": judge_id},
        headers=lawyer_a_headers,
    )
    assert dup_resp.status_code == 409, f"Expected 409, got {dup_resp.status_code}"
    print(">>> Duplicate share attempt correctly rejected (409)!")

    # 6. Lawyer A shares with Client
    print(f"\n[5] Lawyer A shares Document #{doc_id} with Client by email (client@legalvault.local)...")
    share_client_resp = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        json={"email": "client@legalvault.local"},
        headers=lawyer_a_headers,
    )
    assert share_client_resp.status_code == 200, f"Share with client failed: {share_client_resp.text}"
    client_share_id = share_client_resp.json()["id"]
    print(f">>> Document #{doc_id} successfully shared with Client (Share ID #{client_share_id})")

    # 7. Lawyer B cannot share Lawyer A's document
    print(f"\n[6] Testing Lawyer B sharing Lawyer A's document (Expect 403 Forbidden)...")
    unauth_share = requests.post(
        f"{BASE_URL}/documents/{doc_id}/share",
        json={"shared_with_user_id": judge_id},
        headers=lawyer_b_headers,
    )
    assert unauth_share.status_code == 403, f"Expected 403, got {unauth_share.status_code}"
    print(">>> Unauthorized lawyer sharing correctly forbidden (403)!")

    # 8. Judge sees shared document in docket
    print(f"\n[7] Testing Judge GET /documents (Expect Document #{doc_id})...")
    judge_docs = requests.get(f"{BASE_URL}/documents", headers=judge_headers).json()
    judge_doc_ids = [d["id"] for d in judge_docs]
    assert doc_id in judge_doc_ids, f"Expected doc #{doc_id} in Judge's list: {judge_doc_ids}"
    print(f">>> Judge sees shared document in docket (is_shared: True, shared_by: {judge_docs[0]['shared_by_name']})")

    # 9. Client sees shared document in docket
    print(f"\n[8] Testing Client GET /documents (Expect Document #{doc_id})...")
    client_docs = requests.get(f"{BASE_URL}/documents", headers=client_headers).json()
    client_doc_ids = [d["id"] for d in client_docs]
    assert doc_id in client_doc_ids, f"Expected doc #{doc_id} in Client's list: {client_doc_ids}"
    print(">>> Client sees shared document in docket!")

    # 10. Judge operations on shared document
    print(f"\n[9] Testing Judge Inspect, Verify, Download on Document #{doc_id}...")
    j_inspect = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=judge_headers)
    assert j_inspect.status_code == 200, f"Inspect failed: {j_inspect.text}"
    j_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=judge_headers)
    assert j_verify.status_code == 200 and j_verify.json()["verified"] is True
    j_download = requests.get(f"{BASE_URL}/documents/{doc_id}/download", headers=judge_headers)
    assert j_download.status_code == 200 and len(j_download.content) > 0
    print(">>> Judge inspect, verify (VERIFIED), and download all succeeded!")

    # 11. Client operations on shared document
    print(f"\n[10] Testing Client Inspect, Verify, Download on Document #{doc_id}...")
    c_inspect = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=client_headers)
    assert c_inspect.status_code == 200, f"Inspect failed: {c_inspect.text}"
    c_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=client_headers)
    assert c_verify.status_code == 200 and c_verify.json()["verified"] is True
    c_download = requests.get(f"{BASE_URL}/documents/{doc_id}/download", headers=client_headers)
    assert c_download.status_code == 200 and len(c_download.content) > 0
    print(">>> Client inspect, verify (VERIFIED), and download all succeeded!")

    # 12. Judge and Client cannot share onward
    print(f"\n[11] Testing Judge & Client sharing onward (Expect 403 Forbidden)...")
    j_onward = requests.post(f"{BASE_URL}/documents/{doc_id}/share", json={"shared_with_user_id": client_id}, headers=judge_headers)
    assert j_onward.status_code == 403, f"Expected 403 for Judge onward share, got {j_onward.status_code}"
    c_onward = requests.post(f"{BASE_URL}/documents/{doc_id}/share", json={"shared_with_user_id": judge_id}, headers=client_headers)
    assert c_onward.status_code == 403, f"Expected 403 for Client onward share, got {c_onward.status_code}"
    print(">>> Onward sharing by recipients correctly forbidden (403)!")

    # 13. Lawyer B (unauthorized) cannot access Document
    print(f"\n[12] Testing unauthorized Lawyer B access on Document #{doc_id} (Expect 403)...")
    b_inspect = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=lawyer_b_headers)
    assert b_inspect.status_code == 403
    b_verify = requests.post(f"{BASE_URL}/documents/{doc_id}/verify", headers=lawyer_b_headers)
    assert b_verify.status_code == 403
    print(">>> Unauthorized lawyer access strictly blocked (403)!")

    # 14. Revoke share from Judge
    print(f"\n[13] Lawyer A revokes share #{judge_share_id} from Judge...")
    revoke_resp = requests.delete(f"{BASE_URL}/documents/{doc_id}/shares/{judge_share_id}", headers=lawyer_a_headers)
    assert revoke_resp.status_code == 200
    print(">>> Share revoked successfully!")

    # 15. Verify Judge access is immediately revoked
    print(f"\n[14] Testing Judge access after revocation (Expect 403 Forbidden and 0 docs in list)...")
    j_revoked_inspect = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=judge_headers)
    assert j_revoked_inspect.status_code == 403, f"Expected 403, got {j_revoked_inspect.status_code}"
    j_revoked_list = requests.get(f"{BASE_URL}/documents", headers=judge_headers).json()
    assert doc_id not in [d["id"] for d in j_revoked_list]
    print(">>> Judge access immediately terminated (403 + excluded from list)!")

    # 16. Client still has active access
    print(f"\n[15] Testing Client still retains active share...")
    c_still_inspect = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=client_headers)
    assert c_still_inspect.status_code == 200
    print(">>> Client access intact!")

    # 17. Admin can view active shares and manage document
    print(f"\n[16] Testing Admin access on shares and document...")
    admin_shares = requests.get(f"{BASE_URL}/documents/{doc_id}/shares", headers=admin_headers)
    assert admin_shares.status_code == 200
    assert len(admin_shares.json()) == 1  # only client share remains
    # Admin revokes remaining client share
    admin_revoke = requests.delete(f"{BASE_URL}/documents/{doc_id}/shares/{client_share_id}", headers=admin_headers)
    assert admin_revoke.status_code == 200
    print(">>> Admin full management and revocation verified!")

    print("\n=====================================================")
    print("ALL 16 SHARING & PERMISSIONS TESTS PASSED SUCCESSFULLY!")
    print("=====================================================")


if __name__ == "__main__":
    run_sharing_tests()
