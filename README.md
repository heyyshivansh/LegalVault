# LegalVault

## AI-Assisted Blockchain eVault for Legal Records

SIH1284 Prototype

LegalVault is a prototype blockchain-based eVault designed to securely manage, verify, and share legal records.

It combines AI-assisted document analysis with blockchain-based integrity verification.

## Problem

Legal records need to be:
- Secure
- Accessible to authorized stakeholders
- Resistant to tampering
- Easy to verify
- Traceable through their lifecycle

## Proposed Solution

LegalVault provides:

- Secure document storage
- AI-assisted document analysis
- Blockchain-based document integrity verification
- Role-based access
- Controlled document sharing
- Version tracking
- AI-assisted version comparison

## Architecture

## 🏗️ System Architecture

```mermaid
flowchart TB
    U[Users<br/>Lawyer · Administrator · Judge · Client]

    FE[React Frontend<br/>Dashboard & UI]
    API[FastAPI Backend<br/>Authentication · RBAC · Document Lifecycle<br/>Version Control · Audit Trail]

    DB[(Database<br/>Users · Metadata · Versions<br/>AI Results · Audit Records)]
    FS[(File Storage<br/>Master Documents · Revisions)]

    AI[AI Service<br/>Metadata Extraction · Summarization<br/>Version Comparison · Evidence Timeline]
    GEM[Gemini Provider]
    MOCK[Offline Mock Provider]

    HASH[SHA-256<br/>Document Hash]
    SC[Smart Contract<br/>Master + Revision Anchors]
    BC[EVM Blockchain<br/>Hardhat]

    U --> FE
    FE -->|REST API| API

    API --> DB
    API --> FS
    API --> AI

    FS --> HASH
    HASH --> SC
    SC --> BC

    AI --> GEM
    AI --> MOCK
    AI --> DB

    FS -. Document Text .-> AI
```
