import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import StatsStrip from './components/StatsStrip';
import DocumentList from './components/DocumentList';
import DocumentUploadModal from './components/DocumentUploadModal';
import VerificationModal from './components/VerificationModal';
import DocumentDetailDrawer from './components/DocumentDetailDrawer';
import { checkApiHealth, fetchDocuments } from './services/api';

export default function App() {
  const [isOnline, setIsOnline] = useState(false);
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Modals state
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [verifyingDocId, setVerifyingDocId] = useState(null);
  const [inspectingDocId, setInspectingDocId] = useState(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await checkApiHealth();
      setIsOnline(true);
      const docs = await fetchDocuments();
      setDocuments(docs);
    } catch (err) {
      setIsOnline(false);
      setError('Unable to connect to the LegalVault backend server. Please verify the service is running.');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(() => {
      checkApiHealth()
        .then(() => setIsOnline(true))
        .catch(() => setIsOnline(false));
    }, 15000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleUploadSuccess = () => {
    loadData();
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
            <span className="intro-pretitle">Judicial Evidence Ledger · Protocol v1.0</span>
            <h1 className="intro-title">Legal Records Repository &amp; Custody Docket</h1>
            <p className="intro-description">
              Secure off-chain evidence vault anchored to an Ethereum smart contract. Every deposited record possesses an immutable cryptographic SHA-256 fingerprint verified against the decentralized ledger.
            </p>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setIsUploadOpen(true)}
            >
              + Deposit New Record
            </button>
          </div>
        </div>

        {/* Global Connection Warning */}
        {error && (
          <div className="verdict-banner tampered" style={{ marginBottom: '1.5rem' }}>
            <div>
              <div className="verdict-headline">SYSTEM CONNECTIVITY NOTICE</div>
              <div className="verdict-explanation">{error}</div>
            </div>
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

      {/* Upload Modal */}
      <DocumentUploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadSuccess={handleUploadSuccess}
      />

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
      />
    </div>
  );
}
