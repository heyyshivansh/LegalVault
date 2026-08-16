import React, { useState } from 'react';
import { resetDevelopmentVault } from '../services/api';

export default function AdminResetModal({ isOpen, onClose, onResetSuccess }) {
  const [isResetting, setIsResetting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successResult, setSuccessResult] = useState(null);

  if (!isOpen) return null;

  const handleReset = async () => {
    setIsResetting(true);
    setErrorMessage('');
    setSuccessResult(null);

    try {
      const res = await resetDevelopmentVault();
      setSuccessResult(res);
      if (onResetSuccess) {
        onResetSuccess(res);
      }
      setTimeout(() => {
        onClose();
      }, 2000);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to reset development vault.');
    } finally {
      setIsResetting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle" style={{ color: '#B91C1C' }}>
              System Administration Protocol
            </span>
            <h3 className="modal-title">Reset Development Vault</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          {errorMessage && (
            <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem', padding: '0.75rem 1rem' }}>
              <div className="verdict-explanation" style={{ margin: 0, fontWeight: 500 }}>
                {errorMessage}
              </div>
            </div>
          )}

          {successResult && (
            <div className="verdict-banner verified" style={{ marginBottom: '1.25rem', padding: '0.75rem 1rem' }}>
              <div className="verdict-explanation" style={{ margin: 0, fontWeight: 500 }}>
                {successResult.message} ({successResult.documents_deleted} documents, {successResult.shares_deleted} shares, {successResult.files_deleted} files cleared).
              </div>
            </div>
          )}

          <div style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '1rem', borderRadius: 'var(--radius-xs)', marginBottom: '1.25rem' }}>
            <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#991B1B', marginBottom: '0.35rem' }}>
              ⚠ WARNING: IRREVERSIBLE DEVELOPMENT ACTION
            </div>
            <div style={{ fontSize: '0.82rem', color: '#7F1D1D', lineHeight: 1.45 }}>
              This will permanently delete all legal document metadata, evidentiary shares, and physical files from the local off-chain vault storage.
            </div>
          </div>

          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '0.85rem', marginBottom: '1rem' }}>
            <div className="stat-label" style={{ marginBottom: '0.4rem' }}>Targeted Operations</div>
            <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.8rem', color: 'var(--ink-secondary)', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <li><strong>Documents Table:</strong> All document records will be purged.</li>
              <li><strong>Document Shares Table:</strong> All judicial &amp; client shares will be revoked.</li>
              <li><strong>Uploads Directory:</strong> All stored PDF files on disk will be deleted.</li>
              <li><strong>Users &amp; RBAC:</strong> <span style={{ color: '#047857', fontWeight: 600 }}>All user accounts and authentication credentials remain preserved.</span></li>
            </ul>
          </div>

          <div style={{ fontSize: '0.78rem', color: 'var(--ink-muted)', backgroundColor: 'var(--bg-subtle)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-xs)', border: '1px solid var(--border-color)' }}>
            <strong>Note on Blockchain State:</strong> The local Hardhat Ethereum node is append-only and will retain previous registrations. To start from Block #0, restart the Hardhat node and redeploy the smart contract.
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isResetting}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={handleReset}
            disabled={isResetting || Boolean(successResult)}
          >
            {isResetting ? 'Resetting Vault...' : 'Confirm & Reset Vault'}
          </button>
        </div>
      </div>
    </div>
  );
}
