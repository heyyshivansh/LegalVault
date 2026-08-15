import React, { useState, useEffect } from 'react';
import { fetchDocumentDetail, getDocumentDownloadUrl } from '../services/api';

export default function DocumentDetailDrawer({ documentId, isOpen, onClose, onVerify }) {
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);

  useEffect(() => {
    if (!isOpen || !documentId) {
      setDoc(null);
      setError(null);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchDocumentDetail(documentId)
      .then((data) => {
        if (isMounted) {
          setDoc(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || 'Failed to load document details.');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, documentId]);

  if (!isOpen) return null;

  const copyToClipboard = (text, fieldName) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
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

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
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
              <div style={{ marginBottom: '1.25rem' }}>
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

              <div style={{ marginTop: '1.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <a
                  href={getDocumentDownloadUrl(doc.id)}
                  download={doc.filename}
                  className="btn btn-secondary btn-sm"
                >
                  Download Original File
                </a>

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
