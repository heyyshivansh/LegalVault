# LegalVault - Project Context

## Project
SIH1284 - Developing a Blockchain-Based eVault for Legal Records

## Hackathon Goal
Build a functional prototype for the internal SIH hackathon.

The prototype should demonstrate secure storage, management, verification, and controlled sharing of legal records using blockchain and smart contracts.

## Problem Statement

The objective is to develop a blockchain-based eVault system for legal records that ensures security, transparency, and accessibility for stakeholders.

The system should support:
- Secure storage of legal records
- Document management
- Document sharing
- Change tracking
- Access control
- Authentication
- Encryption/privacy
- Blockchain-based verification
- Smart-contract-based access and transaction management
- Future integration with legal databases and case-management systems
- Scalability and adaptability

## Target Users

- Lawyers
- Judges
- Clients
- Administrators
- Other authorized legal stakeholders

## Our Proposed Solution

LegalVault is an AI-assisted blockchain-based legal document vault.

The system will combine:

1. AI
   - Legal document analysis
   - Metadata extraction
   - Document summarization
   - Version comparison

2. Blockchain
   - Document integrity verification
   - Immutable record of document hashes
   - Timestamping
   - Access/transaction records

3. Secure Off-Chain Storage
   - Actual legal documents remain off-chain
   - Blockchain stores hashes and relevant metadata

4. Access Control
   - Role-based permissions
   - Controlled document sharing

## Core MVP Features

### Authentication
- Login
- Role-based access

### Document Management
- Upload document
- View document
- Retrieve document
- Document metadata
- Document versioning

### AI
- Extract important metadata
- Generate document summary
- Compare document versions
- Explain detected changes

### Blockchain
- Generate SHA-256 document hash
- Register document hash on blockchain
- Store document metadata on-chain where appropriate
- Verify document integrity
- Record timestamps/transactions

### Sharing
- Grant access to authorized users
- Revoke access
- Track important access events

### Verification
- Upload/select a document
- Calculate current hash
- Compare with blockchain hash
- Display:
  - VERIFIED
  - TAMPERED / HASH MISMATCH

## Proposed Document Flow

User
→ Authentication
→ Upload Legal Document
→ AI Analysis
→ Generate Metadata
→ Generate SHA-256 Hash
→ Secure Off-Chain Storage
→ Register Hash + Metadata on Blockchain
→ Smart Contract
→ Authorized Access / Sharing
→ Verification

## Important Architecture Decision

The actual legal document should NOT be stored directly on the blockchain.

The prototype should keep the document off-chain and use the blockchain primarily for:
- Hashes
- Integrity verification
- Timestamping
- Relevant metadata
- Access/transaction records

## Technology Stack

### Frontend
React + Vite

### Backend
Python + FastAPI

### Database
SQLite initially for the MVP.
PostgreSQL may be considered later.

### Blockchain
Ethereum-compatible blockchain
Solidity
Hardhat

### AI
LLM API for document analysis and comparison.

The exact model/API will be selected during implementation based on availability and limits.

### Storage
Local/off-chain storage initially.
IPFS may be considered later if time permits.

## MVP Priority

### Must Have
1. Authentication
2. Document upload
3. Document storage
4. SHA-256 hashing
5. Smart contract
6. Blockchain registration
7. Blockchain verification
8. Basic role-based access
9. AI metadata extraction/summary

### Should Have
10. Document sharing
11. Version history
12. AI version comparison

### Nice to Have
13. QR verification
14. IPFS
15. Advanced analytics
16. Real external legal database integration

## Current Status

- [x] GitHub repository created
- [x] Project structure
- [x] Backend
- [x] Frontend (Phase 1 React + Vite eVault UI)
- [x] Database
- [x] Authentication (Bcrypt + JWT + Role Management)
- [x] Document upload
- [x] Document storage
- [ ] AI analysis
- [x] SHA-256 hashing
- [x] Smart contract
- [x] Blockchain integration
- [x] Verification
- [x] Access control (RBAC: Lawyer, Judge, Client, Admin)
- [x] Sharing (Document sharing & permission management)
- [x] Version history (Immutable revisions, per-version on-chain anchors, isolated historical storage & verification)
- [ ] AI comparison
- [ ] Documentation
- [ ] Presentation

## Development Principle

Build the smallest working version first.

Do not add complex technologies or features unless they directly contribute to the SIH1284 requirements or improve the core demonstration.

## Team

Project Lead / Integration:
Shivansh

Other members:
- Frontend
- AI/document processing
- Documentation/presentation

Names and exact responsibilities will be updated later.

## Important

This is a prototype for the internal SIH selection round.

Priority:
Working core > fancy features.

The system must be understandable by the team and explainable to judges.

---

## Document Version History Architecture

LegalVault implements immutable revision tracking for legal records:

### 1. Data Model (`DocumentVersion`)
- `(document_id, version_number)` is uniquely constrained (`uq_document_version`).
- Indexed on `document_id` and `file_hash`.
- Foreign key cascading on `document_id` and references `users.id` for depositor provenance.
- Legacy records backfilled as `v1` during schema migrations without initiating blockchain transactions.

### 2. Off-Chain File Isolation
- Revision files are saved under `uploads/doc_{document_id}_v{version_number}_{sanitized_filename}` to ensure historical revisions are never overwritten or corrupted.

### 3. Dual On-Chain Anchoring
- **Version Anchor**: Each revision is anchored with key `"{document_id}_v{version_number}"` on `LegalVault.sol`.
- **Master Anchor**: The latest master state is anchored under key `"{document_id}"`.
- Supports per-version cryptographic verification (`POST /documents/{id}/versions/{version}/verify`).

### 4. API Endpoints
- `GET /documents/{id}/versions`: Lists all historical revisions with `is_current` indicators.
- `GET /documents/{id}/versions/{version}`: Details of a specific revision.
- `GET /documents/{id}/versions/{version}/download`: Downloads exact historical file.
- `POST /documents/{id}/versions`: Uploads new immutable revision with validation, duplicate detection, and EVM anchoring.
- `POST /documents/{id}/versions/{version}/verify`: Live verification of specific revision against on-chain hash.

### 5. Automated Verification Suite
Run the test suite:
```bash
python test_version_history.py
```

---

## Indian Standard Time (IST) & Timezone Architecture

LegalVault standardizes all timestamps across the system using a canonical UTC storage and IANA `Asia/Kolkata` presentation strategy:

### 1. Canonical UTC Backend Storage
- All internal datetime objects are generated using timezone-aware UTC: `datetime.now(timezone.utc)`.
- SQLite database persists timestamps in canonical UTC.
- Historical naive timestamps are strictly interpreted as UTC without modifying or shifting numerical clock values.

### 2. Timezone-Aware API Serialization
- All API datetime endpoints return unambiguous ISO 8601 UTC strings ending with `'Z'` via `format_utc_iso()`:
  `"2026-08-16T08:45:00.123456Z"`
- Blockchain block timestamps are returned as raw Unix epoch seconds (`block.timestamp`).

### 3. Centralized Frontend IST Conversion (`frontend/src/utils/timezone.js`)
- Standardized conversion to **Indian Standard Time (IST, UTC+05:30)** using IANA identifier `Asia/Kolkata` via `Intl.DateTimeFormat`.
- `formatISTDateTime()` renders user-facing timestamps (e.g. `16 Aug 2026, 2:15 PM IST`).
- `formatBlockTimestampIST()` renders blockchain EVM block timestamps in IST.
- Client/host browser timezone configuration does not alter the displayed IST representation.

### 4. Automated Timezone Verification Suite
Run the timezone test suites:
```bash
# Backend test
python test_timezone_ist.py

# Frontend cross-timezone matrix test
node test_timezone.js
```
