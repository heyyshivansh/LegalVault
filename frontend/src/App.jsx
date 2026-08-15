import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import StatsStrip from './components/StatsStrip';
import DocumentList from './components/DocumentList';
import DocumentUploadModal from './components/DocumentUploadModal';
import VerificationModal from './components/VerificationModal';
import DocumentDetailDrawer from './components/DocumentDetailDrawer';
import ShareDocumentModal from './components/ShareDocumentModal';
import LoginView from './components/LoginView';
import { AuthProvider, useAuth } from './context/AuthContext';
import { checkApiHealth, fetchDocuments } from './services/api';

function VaultWorkspace() {
  const { isAuthenticated, isLoading: isAuthLoading, user, role, isLawyer, isJudge, isClient, isAdmin, canDeposit } = useAuth();
  const [isOnline, setIsOnline] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Modals state
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [verifyingDocId, setVerifyingDocId] = useState(null);
  const [inspectingDocId, setInspectingDocId] = useState(null);
  const [sharingDoc, setSharingDoc] = useState(null);

  const loadData = useCallback(async () => {
    if (!isAuthenticated) return;
    setIsLoading(true);
    setError(null);
    try {
      await checkApiHealth();
      setIsOnline(true);
      const docs = await fetchDocuments();
      setDocuments(docs);
    } catch (err) {
      setIsOnline(false);
      setError('Unable to load vault repository records. Please verify backend connectivity.');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      loadData();
    }
    const interval = setInterval(() => {
      checkApiHealth()
        .then(() => setIsOnline(true))
        .catch(() => setIsOnline(false));
    }, 15000);
    return () => clearInterval(interval);
  }, [isAuthenticated, loadData]);

  const handleUploadSuccess = () => {
    loadData();
  };

  const handleShareSuccess = () => {
    loadData();
  };

  if (isAuthLoading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-app)' }}>
        <div style={{ textAlign: 'center' }}>
          <div className="serif-heading" style={{ fontSize: '1.35rem', marginBottom: '0.5rem' }}>
            LegalVault Custody System
          </div>
          <div style={{ color: 'var(--ink-muted)', fontSize: '0.85rem' }}>
            Initializing cryptographic session...
          </div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginView />;
  }

  const getWorkspaceTitle = () => {
    if (isJudge) return 'Judicial Evidence Docket & Verification Chamber';
    if (isClient) return 'Client Evault Records & Verification Portal';
    if (isLawyer) return 'Legal Records Custody & Depositor Workspace';
    return 'Master Evault Ledger & System Administration';
  };

  const getWorkspaceDescription = () => {
    if (isJudge) {
      return 'Official judicial review station. Inspect blockchain-anchored evidence records and run independent cryptographic verification proofs.';
    }
    if (isClient) {
      return 'Client evidentiary records repository. Access authorized case files and verify document integrity directly against the smart contract.';
    }
    if (isLawyer) {
      return 'Secure off-chain evidence vault anchored to the Ethereum smart contract. Deposit legal records, manage judicial shares, and verify cryptographic SHA-256 custody chains.';
    }
    return 'Full vault registry access with master administrative oversight. Monitor on-chain transactions, manage storage custody, and verify forensic integrity.';
  };

  return (
    <div className="app-container">
      <Header
        isOnline={isOnline}
        onOpenUpload={() => setIsUploadOpen(true)}
        onRefresh={loadData}
      />

      <main className="main-content">
        {/* Workspace Intro Header */}
        <div className="workspace-intro">
          <div className="intro-meta">
            <span className="intro-pretitle">
              Role Session: {role} · {user?.email}
            </span>
            <h1 className="intro-title">{getWorkspaceTitle()}</h1>
            <p className="intro-description">{getWorkspaceDescription()}</p>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            {canDeposit && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setIsUploadOpen(true)}
              >
                + Deposit New Record
              </button>
            )}
          </div>
        </div>

        {/* Global Connection / System Warning */}
        {error && (
          <div className="verdict-banner tampered" style={{ marginBottom: '1.5rem' }}>
            <div>
              <div className="verdict-headline">REPOSITORY NOTICE</div>
              <div className="verdict-explanation">{error}</div>
            </div>
          </div>
        )}

        {/* Administration Status Strip for Admin */}
        {isAdmin && (
          <div style={{ backgroundColor: '#FEFCE8', border: '1px solid #FEF08A', padding: '0.75rem 1.25rem', borderRadius: 'var(--radius-sm)', marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontWeight: 700, fontSize: '0.78rem', color: '#854D0E', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                ADMINISTRATIVE OVERSIGHT ACTIVE
              </span>
              <div style={{ fontSize: '0.8rem', color: '#713F12', marginTop: '0.15rem' }}>
                You have unrestricted access to all vault dockets, cryptographic proofs, active shares, and blockchain transactions.
              </div>
            </div>
            <span className="badge" style={{ backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' }}>
              ALL RECORDS VISIBLE
            </span>
          </div>
        )}

        {/* Summary Metric Strip */}
        <StatsStrip documents={documents} />

        {/* Legal Docket Table */}
        <DocumentList
          documents={documents}
          isLoading={isLoading}
          onVerifyDocument={(id) => setVerifyingDocId(id)}
          onInspectDocument={(id) => setInspectingDocId(id)}
        />
      </main>

      {/* Upload Modal (Only accessible if canDeposit) */}
      {canDeposit && (
        <DocumentUploadModal
          isOpen={isUploadOpen}
          onClose={() => setIsUploadOpen(false)}
          onUploadSuccess={handleUploadSuccess}
        />
      )}

      {/* Hero Verification Modal */}
      <VerificationModal
        documentId={verifyingDocId}
        isOpen={Boolean(verifyingDocId)}
        onClose={() => setVerifyingDocId(null)}
      />

      {/* Record Inspection Drawer */}
      <DocumentDetailDrawer
        documentId={inspectingDocId}
        isOpen={Boolean(inspectingDocId)}
        onClose={() => setInspectingDocId(null)}
        onVerify={(id) => setVerifyingDocId(id)}
        onOpenShare={(doc) => setSharingDoc(doc)}
      />

      {/* Share Document Modal */}
      <ShareDocumentModal
        document={sharingDoc}
        isOpen={Boolean(sharingDoc)}
        onClose={() => setSharingDoc(null)}
        onShareSuccess={handleShareSuccess}
      />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <VaultWorkspace />
    </AuthProvider>
  );
}
