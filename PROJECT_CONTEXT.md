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
- [ ] Project structure
- [ ] Backend
- [ ] Frontend
- [ ] Database
- [ ] Authentication
- [ ] Document upload
- [ ] Document storage
- [ ] AI analysis
- [ ] SHA-256 hashing
- [ ] Smart contract
- [ ] Blockchain integration
- [ ] Verification
- [ ] Access control
- [ ] Sharing
- [ ] Version history
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