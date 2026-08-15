import React, { useState, useEffect } from 'react';
import { verifyDocument, getDocumentDownloadUrl } from '../services/api';

export default function VerificationModal({ documentId, isOpen, onClose }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);

  useEffect(() => {
    if (!isOpen || !documentId) {
      setData(null);
      setError(null);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    verifyDocument(documentId)
      .then((res) => {
        if (isMounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || 'Failed to execute verification.');
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

  const formatTimestamp = (ts) => {
    if (!ts) return 'Not available';
    try {
      // In Solidity, timestamp is unix timestamp in seconds
      const date = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
      return date.toUTCString();
    } catch {
      return String(ts);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">Cryptographic Evidence Verification</span>
            <h3 className="modal-title">Document Integrity Inspection</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body" style={{ padding: '1.75rem' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '3.5rem 1rem' }}>
              <div className="serif-heading" style={{ fontSize: '1.25rem', marginBottom: '0.5rem' }}>
                Executing Cryptographic Verification...
              </div>
              <div style={{ color: 'var(--ink-muted)', fontSize: '0.85rem' }}>
                Reading physical document bytes from storage, computing current SHA-256 fingerprint, and querying Ethereum smart contract state.
              </div>
            </div>
          ) : error ? (
            <div className="verdict-banner tampered">
              <div>
                <div className="verdict-headline">VERIFICATION SERVICE ERROR</div>
                <div className="verdict-explanation">{error}</div>
              </div>
            </div>
          ) : data ? (
            <div className="forensic-certificate">
              {/* Forensic Document Header */}
              <div className="forensic-header">
                <div className="forensic-title-block">
                  <h2>DOCUMENT INTEGRITY REPORT</h2>
                  <div className="forensic-id">
                    RECORD ID: #{data.document_id} · CASE REF: {data.case_number || 'N/A'}
                  </div>
                </div>
                <div className="forensic-seal">
                  FORENSIC PROOF SEAL
                </div>
              </div>

              {/* Document Reference Info */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem', background: 'var(--bg-subtle)', padding: '0.85rem 1rem', borderRadius: 'var(--radius-xs)', border: '1px solid var(--border-color)' }}>
                <div>
                  <div className="stat-label">Document Title</div>
                  <div style={{ fontWeight: 600, color: 'var(--ink-primary)', fontSize: '0.9rem' }}>
                    {data.filename}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Case Identifier</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--ink-primary)', fontSize: '0.9rem' }}>
                    {data.case_number || 'UNSPECIFIED'}
                  </div>
                </div>
              </div>

              {/* Hero Verdict Banner */}
              {data.verified ? (
                <div className="verdict-banner verified">
                  <div>
                    <div className="verdict-headline">CRYPTOGRAPHICALLY VERIFIED</div>
                    <div className="verdict-subheadline">INTEGRITY INTACT · ZERO MODIFICATIONS DETECTED</div>
                    <div className="verdict-explanation">
                      The mathematical SHA-256 digest of the stored document file exactly matches the immutable hash registered on the Ethereum smart contract. The record is mathematically guaranteed to be pristine and untampered since initial deposit.
                    </div>
                  </div>
                </div>
              ) : (
                <div className="verdict-banner tampered">
                  <div>
                    <div className="verdict-headline">TAMPER DETECTED</div>
                    <div className="verdict-subheadline">CRITICAL WARNING · CRYPTOGRAPHIC HASH MISMATCH</div>
                    <div className="verdict-explanation">
                      The SHA-256 fingerprint generated from the current physical file on disk does NOT match the immutable hash registered on the blockchain. The contents of this document have been altered, corrupted, or replaced post-registration.
                    </div>
                  </div>
                </div>
              )}

              {/* Side-by-side Hash Inspection Deck */}
              <div className="hash-comparison-grid">
                {/* Current File Hash */}
                <div className="hash-panel">
                  <div className="hash-panel-header">
                    <span className="hash-panel-title">Current File Hash (Physical Storage)</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
                      onClick={() => copyToClipboard(data.current_hash, 'current')}
                    >
                      {copiedField === 'current' ? 'Copied ✓' : 'Copy Hash'}
                    </button>
                  </div>
                  <div className={`hash-display ${data.verified ? 'match' : 'mismatch'}`}>
                    {data.current_hash}
                  </div>
                </div>

                {/* On-Chain Registered Hash */}
                <div className="hash-panel">
                  <div className="hash-panel-header">
                    <span className="hash-panel-title">On-Chain Registered Hash (Ethereum Smart Contract)</span>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ fontSize: '0.7rem', padding: '0.15rem 0.4rem' }}
                      onClick={() => copyToClipboard(data.blockchain_hash, 'onchain')}
                    >
                      {copiedField === 'onchain' ? 'Copied ✓' : 'Copy Hash'}
                    </button>
                  </div>
                  <div className={`hash-display ${data.verified ? 'match' : 'mismatch'}`}>
                    {data.blockchain_hash}
                  </div>
                </div>
              </div>

              {/* Blockchain Provenance Ledger Breakdown */}
              <div style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border-color)' }}>
                <div className="serif-heading" style={{ fontSize: '1.05rem', marginBottom: '0.75rem' }}>
                  Blockchain Provenance &amp; Custody Trail
                </div>

                <table className="provenance-table">
                  <tbody>
                    <tr>
                      <td className="field-name">Transaction Hash</td>
                      <td className="field-val">
                        <span>{data.blockchain_tx_hash || '0x (Registered during intake)'}</span>
                        {data.blockchain_tx_hash && (
                          <button
                            type="button"
                            className="copy-btn"
                            onClick={() => copyToClipboard(data.blockchain_tx_hash, 'tx')}
                            title="Copy Transaction Hash"
                          >
                            {copiedField === 'tx' ? '✓' : '⧉'}
                          </button>
                        )}
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">Smart Contract</td>
                      <td className="field-val">
                        <span>{data.contract_address || '0x5FbDB2315678afecb367f032d93F642f64180aa3'}</span>
                        <button
                          type="button"
                          className="copy-btn"
                          onClick={() => copyToClipboard(data.contract_address || '0x5FbDB2315678afecb367f032d93F642f64180aa3', 'contract')}
                          title="Copy Contract Address"
                        >
                          {copiedField === 'contract' ? '✓' : '⧉'}
                        </button>
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">Registrar / Owner Wallet</td>
                      <td className="field-val">
                        <span>{data.owner || 'Authorized Depositor Node (EVM Account)'}</span>
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">On-Chain Timestamp</td>
                      <td className="field-val">
                        {formatTimestamp(data.timestamp)}
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">Document Version</td>
                      <td className="field-val">
                        v{data.version || 1} (Canonical Master)
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Action Toolbar */}
              <div style={{ marginTop: '1.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <a
                  href={getDocumentDownloadUrl(data.document_id)}
                  download={data.filename}
                  className="btn btn-secondary btn-sm"
                >
                  Download Inspected File
                </a>

                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
                    Close Certificate
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
