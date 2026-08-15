import React, { useState, useEffect, useCallback } from 'react';
import { fetchDocumentDetail, downloadDocumentFile, fetchDocumentShares, revokeDocumentShare } from '../services/api';
import { useAuth } from '../context/AuthContext';

export default function DocumentDetailDrawer({ documentId, isOpen, onClose, onVerify, onOpenShare }) {
  const { user, isAdmin } = useAuth();
  const [doc, setDoc] = useState(null);
  const [shares, setShares] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [revokingShareId, setRevokingShareId] = useState(null);
  const [isDownloading, setIsDownloading] = useState(false);

  const loadDetail = useCallback(async () => {
    if (!documentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDocumentDetail(documentId);
      setDoc(data);

      // If owner or admin, load active shares
      if (data.is_owner || isAdmin) {
        try {
          const activeShares = await fetchDocumentShares(documentId);
          setShares(activeShares);
        } catch {
          setShares([]);
        }
      } else {
        setShares([]);
      }
    } catch (err) {
      setError(err.message || 'Failed to load document details.');
    } finally {
      setLoading(false);
    }
  }, [documentId, isAdmin]);

  useEffect(() => {
    if (isOpen && documentId) {
      loadDetail();
    } else {
      setDoc(null);
      setShares([]);
      setError(null);
    }
  }, [isOpen, documentId, loadDetail]);

  if (!isOpen) return null;

  const copyToClipboard = (text, fieldName) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handleRevoke = async (shareId) => {
    if (!documentId) return;
    setRevokingShareId(shareId);
    try {
      await revokeDocumentShare(documentId, shareId);
      setShares((prev) => prev.filter((s) => s.id !== shareId));
    } catch (err) {
      alert(err.message || 'Failed to revoke share');
    } finally {
      setRevokingShareId(null);
    }
  };

  const handleDownload = async () => {
    if (!doc) return;
    setIsDownloading(true);
    try {
      await downloadDocumentFile(doc.id, doc.filename);
    } catch (err) {
      alert(err.message || 'Download failed');
    } finally {
      setIsDownloading(false);
    }
  };

  const formatDate = (isoString) => {
    if (!isoString) return '—';
    try {
      return new Date(isoString).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'medium',
      });
    } catch {
      return isoString;
    }
  };

  const formatTimestamp = (ts) => {
    if (!ts) return 'Not recorded';
    try {
      const date = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
      return date.toUTCString();
    } catch {
      return String(ts);
    }
  };

  const canManageSharing = doc?.is_owner || isAdmin;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">Evault Docket Inspection</span>
            <h3 className="modal-title">Record #{documentId} Details</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          {loading ? (
            <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--ink-muted)' }}>
              Retrieving off-chain metadata and on-chain state...
            </div>
          ) : error ? (
            <div className="verdict-banner tampered">
              <div className="verdict-explanation">{error}</div>
            </div>
          ) : doc ? (
            <div>
              <div style={{ marginBottom: '1.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <h3 className="serif-heading" style={{ fontSize: '1.25rem', marginBottom: '0.25rem' }}>
                    {doc.filename}
                  </h3>
                  <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                    <span className="case-id-cell">Case: {doc.case_number || 'UNASSIGNED'}</span>
                    <span style={{ color: 'var(--border-strong)' }}>|</span>
                    <span style={{ fontSize: '0.8rem', color: 'var(--ink-muted)' }}>
                      Deposited: {formatDate(doc.created_at)}
                    </span>
                  </div>
                </div>

                {canManageSharing && onOpenShare && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => onOpenShare(doc)}
                  >
                    + Share Legal Record
                  </button>
                )}
              </div>

              <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem', marginBottom: '1.25rem' }}>
                <div className="stat-label">Cryptographic Fingerprint (SHA-256)</div>
                <div className="hash-tag" style={{ width: '100%', wordBreak: 'break-all', marginTop: '0.35rem' }}>
                  {doc.file_hash}
                  <button
                    type="button"
                    className="copy-btn"
                    onClick={() => copyToClipboard(doc.file_hash, 'hash')}
                    title="Copy SHA-256 Hash"
                  >
                    {copiedField === 'hash' ? '✓' : '⧉'}
                  </button>
                </div>
              </div>

              <div className="serif-heading" style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>
                Custody &amp; Blockchain Provenance
              </div>

              <table className="provenance-table">
                <tbody>
                  <tr>
                    <td className="field-name">Deposited By</td>
                    <td className="field-val">{doc.uploaded_by || 'Unknown'}</td>
                  </tr>
                  <tr>
                    <td className="field-name">Blockchain Status</td>
                    <td className="field-val">
                      <span className={`badge ${doc.blockchain_status === 'confirmed' ? 'badge-confirmed' : 'badge-failed'}`}>
                        ● {doc.blockchain_status || 'Pending'}
                      </span>
                    </td>
                  </tr>
                  <tr>
                    <td className="field-name">EVM Transaction Hash</td>
                    <td className="field-val">
                      <span>{doc.blockchain_tx_hash || 'None'}</span>
                      {doc.blockchain_tx_hash && (
                        <button
                          type="button"
                          className="copy-btn"
                          onClick={() => copyToClipboard(doc.blockchain_tx_hash, 'tx')}
                        >
                          {copiedField === 'tx' ? '✓' : '⧉'}
                        </button>
                      )}
                    </td>
                  </tr>
                  <tr>
                    <td className="field-name">Smart Contract Address</td>
                    <td className="field-val">
                      <span>{doc.contract_address}</span>
                      {doc.contract_address && (
                        <button
                          type="button"
                          className="copy-btn"
                          onClick={() => copyToClipboard(doc.contract_address, 'contract')}
                        >
                          {copiedField === 'contract' ? '✓' : '⧉'}
                        </button>
                      )}
                    </td>
                  </tr>
                  {doc.onchain && (
                    <>
                      <tr>
                        <td className="field-name">On-Chain Owner</td>
                        <td className="field-val">{doc.onchain.owner}</td>
                      </tr>
                      <tr>
                        <td className="field-name">On-Chain Timestamp</td>
                        <td className="field-val">{formatTimestamp(doc.onchain.timestamp)}</td>
                      </tr>
                      <tr>
                        <td className="field-name">On-Chain Version</td>
                        <td className="field-val">v{doc.onchain.version}</td>
                      </tr>
                    </>
                  )}
                </tbody>
              </table>

              {/* Active Judicial & Client Shares Section (Owner / Admin only) */}
              {canManageSharing && (
                <div style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border-color)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.65rem' }}>
                    <div className="serif-heading" style={{ fontSize: '0.98rem' }}>
                      Active Judicial &amp; Client Access ({shares.length})
                    </div>
                  </div>

                  {shares.length === 0 ? (
                    <div style={{ fontSize: '0.8rem', color: 'var(--ink-muted)', padding: '0.75rem', backgroundColor: 'var(--bg-subtle)', borderRadius: 'var(--radius-xs)' }}>
                      This document is currently confidential and has not been shared with any Judge or Client accounts.
                    </div>
                  ) : (
                    <table className="docket-table" style={{ fontSize: '0.8rem' }}>
                      <thead>
                        <tr>
                          <th>Recipient</th>
                          <th>Role</th>
                          <th>Shared On</th>
                          <th style={{ textAlign: 'right' }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shares.map((s) => (
                          <tr key={s.id}>
                            <td>
                              <div style={{ fontWeight: 600, color: 'var(--ink-primary)' }}>{s.shared_with_name}</div>
                              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>{s.shared_with_email}</div>
                            </td>
                            <td>
                              <span className="badge" style={{ fontSize: '0.68rem', padding: '0.1rem 0.4rem', backgroundColor: 'var(--bg-subtle)' }}>
                                {s.shared_with_role}
                              </span>
                            </td>
                            <td style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                              {formatDate(s.created_at)}
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              <button
                                type="button"
                                className="btn btn-danger btn-sm"
                                style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
                                onClick={() => handleRevoke(s.id)}
                                disabled={revokingShareId === s.id}
                              >
                                {revokingShareId === s.id ? 'Revoking...' : 'Revoke'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              <div style={{ marginTop: '1.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleDownload}
                  disabled={isDownloading}
                >
                  {isDownloading ? 'Downloading...' : 'Download Original File'}
                </button>

                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      onClose();
                      onVerify(doc.id);
                    }}
                  >
                    Run Integrity Verification
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
