import requests
import json

BASE_URL = "http://127.0.0.1:8000"


def run_auth_rbac_tests():
    print("=====================================================")
    print("RUNNING STRICT AUTHENTICATION & RBAC SCOPING TESTS")
    print("=====================================================")

    # 1. Login with Lawyer A (Rajesh Sharma)
    print("\n[1] Testing Lawyer A Login...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "lawyer123"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    lawyer_a_token = resp.json()["access_token"]
    lawyer_a_id = resp.json()["user"]["id"]
    print(f">>> Lawyer A login OK! (User ID: {lawyer_a_id})")

    # 2. Login with Lawyer B (Priya Patel)
    print("\n[2] Testing Lawyer B Login...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer2@legalvault.local", "password": "lawyer123"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    lawyer_b_token = resp.json()["access_token"]
    lawyer_b_id = resp.json()["user"]["id"]
    print(f">>> Lawyer B login OK! (User ID: {lawyer_b_id})")

    # 3. Login with Judge
    print("\n[3] Testing Judge Login...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "judge@legalvault.local", "password": "judge123"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    judge_token = resp.json()["access_token"]
    print(">>> Judge login OK!")

    # 4. Login with Client
    print("\n[4] Testing Client Login...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "client@legalvault.local", "password": "client123"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    client_token = resp.json()["access_token"]
    print(">>> Client login OK!")

    # 5. Login with Admin
    print("\n[5] Testing Admin Login...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "admin@legalvault.local", "password": "admin123"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    admin_token = resp.json()["access_token"]
    print(">>> Admin login OK!")

    # 6. Invalid Password Rejection
    print("\n[6] Testing Invalid Password Rejection (Expect 401)...")
    resp = requests.post(f"{BASE_URL}/auth/login", json={"email": "lawyer@legalvault.local", "password": "wrong_password"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    print(">>> Invalid password correctly rejected (401)!")

    # 7. Unauthenticated Protected Endpoint Rejection
    print("\n[7] Testing Unauthenticated /documents Endpoint (Expect 401)...")
    resp = requests.get(f"{BASE_URL}/documents")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    print(">>> Unauthenticated access correctly rejected (401)!")

    # 8. Lawyer B Deposits a Confidential Document
    print("\n[8] Lawyer B Deposits a Confidential Legal Document...")
    files = {"file": ("lawyer_b_contract.pdf", b"%PDF-1.4 Confidential Contract for Lawyer B %%EOF", "application/pdf")}
    data = {"case_number": "CASE-LAWYER-B-CONFIDENTIAL", "uploaded_by": "Advocate Priya Patel"}
    resp = requests.post(
        f"{BASE_URL}/documents/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {lawyer_b_token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    lawyer_b_doc_id = resp.json()["document_id"]
    print(f">>> Lawyer B deposited Document ID #{lawyer_b_doc_id} successfully.")

    # 9. Scoping Check: Lawyer A must NOT see Lawyer B's Document
    print("\n[9] Testing Lawyer A Document List Scoping...")
    resp = requests.get(f"{BASE_URL}/documents", headers={"Authorization": f"Bearer {lawyer_a_token}"})
    assert resp.status_code == 200
    lawyer_a_docs = resp.json()
    lawyer_a_doc_ids = [d["id"] for d in lawyer_a_docs]
    assert lawyer_b_doc_id not in lawyer_a_doc_ids, f"Lawyer A must NOT see Lawyer B's doc #{lawyer_b_doc_id}"
    print(">>> Lawyer A list correctly excludes Lawyer B's document!")

    # 10. Direct Access Check: Lawyer A accessing Lawyer B's Document (Expect 403)
    print(f"\n[10] Testing Lawyer A GET /documents/{lawyer_b_doc_id} (Expect 403 Forbidden)...")
    resp = requests.get(f"{BASE_URL}/documents/{lawyer_b_doc_id}", headers={"Authorization": f"Bearer {lawyer_a_token}"})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print(">>> Lawyer A inspection correctly forbidden (403)!")

    # 11. Download Check: Lawyer A downloading Lawyer B's Document (Expect 403)
    print(f"\n[11] Testing Lawyer A GET /documents/{lawyer_b_doc_id}/download (Expect 403 Forbidden)...")
    resp = requests.get(f"{BASE_URL}/documents/{lawyer_b_doc_id}/download", headers={"Authorization": f"Bearer {lawyer_a_token}"})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print(">>> Lawyer A download correctly forbidden (403)!")

    # 12. Verification Check: Lawyer A verifying Lawyer B's Document (Expect 403)
    print(f"\n[12] Testing Lawyer A POST /documents/{lawyer_b_doc_id}/verify (Expect 403 Forbidden)...")
    resp = requests.post(f"{BASE_URL}/documents/{lawyer_b_doc_id}/verify", headers={"Authorization": f"Bearer {lawyer_a_token}"})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print(">>> Lawyer A verification correctly forbidden (403)!")

    # 13. Admin Master Access Check
    print(f"\n[13] Testing Admin Full Access on Lawyer B's Document #{lawyer_b_doc_id}...")
    resp = requests.get(f"{BASE_URL}/documents/{lawyer_b_doc_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    resp_v = requests.post(f"{BASE_URL}/documents/{lawyer_b_doc_id}/verify", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp_v.status_code == 200, f"Expected 200, got {resp_v.status_code}"
    print(">>> Admin master inspection and verification succeeded!")

    # 14. Judge Zero Unshared Documents Check
    print("\n[14] Testing Judge Scoping (0 unshared documents)...")
    resp = requests.get(f"{BASE_URL}/documents", headers={"Authorization": f"Bearer {judge_token}"})
    assert resp.status_code == 200
    judge_doc_ids = [d["id"] for d in resp.json()]
    assert lawyer_b_doc_id not in judge_doc_ids, f"Unshared document #{lawyer_b_doc_id} should not appear in Judge docket"
    # Direct access forbidden
    resp = requests.get(f"{BASE_URL}/documents/{lawyer_b_doc_id}", headers={"Authorization": f"Bearer {judge_token}"})
    assert resp.status_code == 403, f"Expected 403 for Judge, got {resp.status_code}"
    print(">>> Judge zero-access scoping verified!")

    # 15. Client Zero Unshared Documents Check
    print("\n[15] Testing Client Scoping (0 unshared documents)...")
    resp = requests.get(f"{BASE_URL}/documents", headers={"Authorization": f"Bearer {client_token}"})
    assert resp.status_code == 200
    client_doc_ids = [d["id"] for d in resp.json()]
    assert lawyer_b_doc_id not in client_doc_ids, f"Unshared document #{lawyer_b_doc_id} should not appear in Client docket"
    # Direct access forbidden
    resp = requests.get(f"{BASE_URL}/documents/{lawyer_b_doc_id}", headers={"Authorization": f"Bearer {client_token}"})
    assert resp.status_code == 403, f"Expected 403 for Client, got {resp.status_code}"
    print(">>> Client zero-access scoping verified!")

    print("\n=====================================================")
    print("ALL 15 AUTHENTICATION & RBAC SCOPING TESTS PASSED!")
    print("=====================================================")


if __name__ == "__main__":
    run_auth_rbac_tests()
