import React, { useState, useEffect } from 'react';
import { verifyDocument, downloadDocumentFile } from '../services/api';

export default function VerificationModal({ documentId, isOpen, onClose }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [isDownloading, setIsDownloading] = useState(false);

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
          setError(err.message || 'Integrity verification failed.');
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

  const handleDownload = async () => {
    if (!data) return;
    setIsDownloading(true);
    try {
      await downloadDocumentFile(data.document_id, data.filename);
    } catch (err) {
      alert(err.message || 'Download failed');
    } finally {
      setIsDownloading(false);
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
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">Evault Verification Protocol</span>
            <h3 className="modal-title">Cryptographic Integrity Certificate</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          {loading ? (
            <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--ink-muted)' }}>
              Executing live SHA-256 computation &amp; querying EVM smart contract state...
            </div>
          ) : error ? (
            <div>
              <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem' }}>
                <div className="verdict-headline font-mono">VERIFICATION FAILED</div>
                <div className="verdict-explanation">{error}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  Close
                </button>
              </div>
            </div>
          ) : data ? (
            <div>
              {/* Verdict Banner */}
              <div className={`verdict-banner ${data.verified ? 'verified' : 'tampered'}`}>
                <div>
                  <div className="verdict-headline">
                    {data.verified ? '✓ INTEGRITY VERIFIED (UNALTERED)' : '⚠ INTEGRITY MISMATCH DETECTED'}
                  </div>
                  <div className="verdict-explanation">
                    {data.verified
                      ? 'The on-disk document SHA-256 hash perfectly matches the immutable hash registered on the Ethereum smart contract.'
                      : 'WARNING: The computed on-disk document hash differs from the canonical hash stored on-chain. This record may have been altered or corrupted.'}
                  </div>
                </div>
              </div>

              {/* Side by Side Hash Comparison */}
              <div className="hash-comparison-grid">
                <div className="hash-box">
                  <div className="hash-box-label">
                    Live On-Disk SHA-256 Hash
                  </div>
                  <div className="hash-value">
                    {data.current_hash}
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() => copyToClipboard(data.current_hash, 'current')}
                    >
                      {copiedField === 'current' ? '✓' : '⧉'}
                    </button>
                  </div>
                </div>

                <div className="hash-box">
                  <div className="hash-box-label">
                    Canonical On-Chain Hash
                  </div>
                  <div className="hash-value">
                    {data.blockchain_hash}
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() => copyToClipboard(data.blockchain_hash, 'chain')}
                    >
                      {copiedField === 'chain' ? '✓' : '⧉'}
                    </button>
                  </div>
                </div>
              </div>

              {/* Forensic Details */}
              <div style={{ marginTop: '1.5rem' }}>
                <div className="serif-heading" style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>
                  Forensic Chain-of-Custody Record
                </div>
                <table className="provenance-table">
                  <tbody>
                    <tr>
                      <td className="field-name">Document Title</td>
                      <td className="field-val">{data.filename}</td>
                    </tr>
                    <tr>
                      <td className="field-name">Case Reference</td>
                      <td className="field-val">{data.case_number || 'UNASSIGNED'}</td>
                    </tr>
                    <tr>
                      <td className="field-name">Original Depositor</td>
                      <td className="field-val">{data.uploaded_by}</td>
                    </tr>
                    <tr>
                      <td className="field-name">Smart Contract Address</td>
                      <td className="field-val font-mono">{data.contract_address}</td>
                    </tr>
                    <tr>
                      <td className="field-name">EVM Transaction Hash</td>
                      <td className="field-val font-mono">
                        {data.blockchain_tx_hash || 'N/A'}
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">On-Chain Custody Wallet</td>
                      <td className="field-val font-mono">{data.owner || 'N/A'}</td>
                    </tr>
                    <tr>
                      <td className="field-name">On-Chain Block Timestamp</td>
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
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleDownload}
                  disabled={isDownloading}
                >
                  {isDownloading ? 'Downloading...' : 'Download Inspected File'}
                </button>

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
