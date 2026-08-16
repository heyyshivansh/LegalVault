import React, { useState, useEffect, useRef } from 'react';
import {
  verifyDocument,
  verifyDocumentVersion,
  fetchDocumentVersions,
  downloadDocumentFile,
  downloadVersionFile,
} from '../services/api';
import { getDocumentIntegrity } from '../utils/integrity';
import { getLiveAuditTimestampIST, formatBlockTimestampIST } from '../utils/timezone';

export default function VerificationModal({
  documentId,
  versionIdentifier,
  isOpen,
  onClose,
  onVerificationComplete,
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [isDownloading, setIsDownloading] = useState(false);

  // Single Version Mode State
  const [singleData, setSingleData] = useState(null);

  // Full Document Verification Mode State
  const isFullVerification = !versionIdentifier;
  const [fullProgressList, setFullProgressList] = useState([]);
  const [overallSummary, setOverallSummary] = useState(null);
  const [auditTimestamp, setAuditTimestamp] = useState(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!isOpen || !documentId) {
      setSingleData(null);
      setFullProgressList([]);
      setOverallSummary(null);
      setError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    setSingleData(null);
    setFullProgressList([]);
    setOverallSummary(null);
    setAuditTimestamp(getLiveAuditTimestampIST());

    if (versionIdentifier) {
      // --- MODE 1: SINGLE VERSION VERIFICATION ---
      verifyDocumentVersion(documentId, versionIdentifier)
        .then((res) => {
          if (!isMountedRef.current) return;
          setSingleData(res);
          setLoading(false);
          if (onVerificationComplete) {
            onVerificationComplete(documentId, res);
          }
        })
        .catch((err) => {
          if (!isMountedRef.current) return;
          setError(err.message || `Integrity verification failed for version ${versionIdentifier}.`);
          setLoading(false);
        });
    } else {
      // --- MODE 2: FULL DOCUMENT INTEGRITY VERIFICATION (ALL VERSIONS) ---
      (async () => {
        try {
          // 1. Fetch version history list
          let versions = [];
          try {
            versions = await fetchDocumentVersions(documentId);
          } catch (e) {
            console.warn('Could not fetch version history for full verification:', e);
          }

          if (!versions || versions.length === 0) {
            // Fallback for standalone single document
            const singleRes = await verifyDocument(documentId);
            if (!isMountedRef.current) return;
            setSingleData(singleRes);
            setLoading(false);
            if (onVerificationComplete) {
              onVerificationComplete(documentId, singleRes);
            }
            return;
          }

          // Sort ascending (v1, v2, v3 ...) for chronological auditing
          const sorted = [...versions].sort((a, b) => a.version_number - b.version_number);

          // Initialize progress items
          const initialItems = sorted.map((v, idx) => ({
            version_number: v.version_number,
            filename: v.filename,
            file_size: v.file_size,
            is_current: v.is_current,
            status: idx === 0 ? 'verifying' : 'waiting',
            result: null,
            error: null,
          }));

          if (!isMountedRef.current) return;
          setFullProgressList(initialItems);

          const accumulatedResults = {};
          const currentProgress = [...initialItems];

          // 2. Sequentially verify each version
          for (let i = 0; i < sorted.length; i++) {
            if (!isMountedRef.current) return;
            const targetV = sorted[i];

            // Mark as verifying
            currentProgress[i] = {
              ...currentProgress[i],
              status: 'verifying',
            };
            setFullProgressList([...currentProgress]);

            try {
              const res = await verifyDocumentVersion(documentId, targetV.version_number);
              if (!isMountedRef.current) return;

              currentProgress[i] = {
                ...currentProgress[i],
                status: 'completed',
                result: res,
              };
              accumulatedResults[targetV.version_number] = res;

              // Notify parent state immediately so UI remains responsive
              if (onVerificationComplete) {
                onVerificationComplete(documentId, res);
              }
            } catch (verErr) {
              if (!isMountedRef.current) return;
              currentProgress[i] = {
                ...currentProgress[i],
                status: 'failed',
                error: verErr.message || 'Verification failed',
              };
            }

            setFullProgressList([...currentProgress]);
          }

          // 3. Compute overall document integrity
          const docIntegrityObj = getDocumentIntegrity(documentId, {
            [documentId]: { versions: accumulatedResults },
          });

          if (!isMountedRef.current) return;
          setOverallSummary(docIntegrityObj);
          setLoading(false);
        } catch (fullErr) {
          if (!isMountedRef.current) return;
          setError(fullErr.message || 'Full document integrity verification failed.');
          setLoading(false);
        }
      })();
    }
  }, [isOpen, documentId, versionIdentifier]);

  if (!isOpen) return null;

  const copyToClipboard = (text, fieldName) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handleDownloadFile = async (docId, verNum, filename) => {
    setIsDownloading(true);
    try {
      if (verNum) {
        await downloadVersionFile(docId, verNum, filename);
      } else {
        await downloadDocumentFile(docId, filename);
      }
    } catch (err) {
      alert(err.message || 'Download failed');
    } finally {
      setIsDownloading(false);
    }
  };

  const formatTimestamp = (ts) => formatBlockTimestampIST(ts);

  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  // --- RENDER HELPERS: SINGLE VERSION MODE ---

  const renderSingleVerdictBanner = (data) => {
    const verNum = data.version_number || data.version || versionIdentifier || 1;
    if (data.result === 'VERIFIED') {
      return (
        <div className="verdict-banner verified" style={{ marginBottom: '1.25rem' }}>
          <div>
            <div className="verdict-headline">✓ VERSION v{verNum} INTEGRITY VERIFIED (UNALTERED)</div>
            <div className="verdict-explanation">
              The on-disk document SHA-256 hash for <strong>{data.filename} (v{verNum})</strong> perfectly matches the immutable cryptographic hash registered on the Ethereum smart contract.
            </div>
          </div>
        </div>
      );
    }

    if (data.result === 'TAMPERED') {
      return (
        <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem' }}>
          <div>
            <div className="verdict-headline">⚠ VERSION v{verNum} INTEGRITY MISMATCH DETECTED (TAMPERED)</div>
            <div className="verdict-explanation">
              WARNING: The computed on-disk document SHA-256 hash for <strong>{data.filename} (v{verNum})</strong> differs from the canonical hash stored on-chain. This evidentiary revision has been altered or corrupted.
            </div>
          </div>
        </div>
      );
    }

    if (data.result === 'BLOCKCHAIN_PROOF_UNAVAILABLE') {
      return (
        <div style={{ backgroundColor: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 'var(--radius-xs)', padding: '1rem', marginBottom: '1.25rem' }}>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#92400E', marginBottom: '0.35rem' }}>
            ⚠ VERSION v{verNum} BLOCKCHAIN PROOF UNAVAILABLE (CHAIN MISMATCH)
          </div>
          <div style={{ fontSize: '0.82rem', color: '#78350F', lineHeight: 1.45 }}>
            {data.message || `Version v${verNum} exists in the local repository, but its blockchain proof is unavailable on the currently connected chain.`}
          </div>
        </div>
      );
    }

    return null;
  };

  // --- RENDER HELPERS: FULL DOCUMENT AUDIT MODE ---

  const renderFullAuditBanner = () => {
    if (!overallSummary) return null;

    if (overallSummary.status === 'VERIFIED') {
      return (
        <div className="verdict-banner verified" style={{ marginBottom: '1.25rem' }}>
          <div>
            <div className="verdict-headline">✓ OVERALL DOCUMENT INTEGRITY VERIFIED (ALL VERSIONS)</div>
            <div className="verdict-explanation">
              All {fullProgressList.length} historical versions ({fullProgressList.map((v) => `v${v.version_number}`).join(', ')}) passed cryptographic SHA-256 and Ethereum smart contract verification. The entire chain of custody is authentic and unaltered.
            </div>
          </div>
        </div>
      );
    }

    if (overallSummary.status === 'TAMPERED') {
      return (
        <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem' }}>
          <div>
            <div className="verdict-headline">⚠ OVERALL DOCUMENT INTEGRITY: TAMPERED</div>
            <div className="verdict-explanation">
              WARNING: Integrity mismatch detected in <strong>{overallSummary.affectedLabel}</strong>. One or more historical revisions do not match their immutable on-chain cryptographic registrations.
            </div>
          </div>
        </div>
      );
    }

    if (overallSummary.status === 'BLOCKCHAIN_PROOF_UNAVAILABLE') {
      return (
        <div style={{ backgroundColor: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 'var(--radius-xs)', padding: '1rem', marginBottom: '1.25rem' }}>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#92400E', marginBottom: '0.35rem' }}>
            ⚠ OVERALL DOCUMENT STATUS: BLOCKCHAIN PROOF UNAVAILABLE
          </div>
          <div style={{ fontSize: '0.82rem', color: '#78350F', lineHeight: 1.45 }}>
            Blockchain registration proofs are unavailable on the currently connected chain for {overallSummary.affectedLabel}.
          </div>
        </div>
      );
    }

    return null;
  };

  const masterDoc = fullProgressList.find((v) => v.is_current) || fullProgressList[fullProgressList.length - 1] || singleData;
  const masterFilename = masterDoc?.filename || singleData?.filename || `Document #${documentId}`;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">
              {isFullVerification ? 'Comprehensive Forensic Audit' : 'Evault Verification Protocol'}
            </span>
            <h3 className="modal-title">
              {isFullVerification
                ? `Full Document Integrity Verification · Record #${documentId}`
                : `Cryptographic Integrity Certificate · v${versionIdentifier || singleData?.version || 1}`}
            </h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          {error ? (
            <div>
              <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem' }}>
                <div className="verdict-headline font-mono">BLOCKCHAIN VERIFICATION ERROR</div>
                <div className="verdict-explanation">{error}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  Close
                </button>
              </div>
            </div>
          ) : isFullVerification ? (
            /* --- FULL DOCUMENT VERIFICATION UI --- */
            <div>
              {/* Document Master Audit Strip */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem', backgroundColor: 'var(--bg-subtle)', padding: '0.75rem 1rem', borderRadius: 'var(--radius-xs)' }}>
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--ink-primary)', fontSize: '0.96rem' }}>
                    {masterFilename}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--ink-muted)' }}>
                    Audited: {auditTimestamp}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#3730A3', border: '1px solid #C7D2FE', fontWeight: 700, fontSize: '0.75rem' }}>
                    {fullProgressList.length} Historical Revisions Checked
                  </span>
                </div>
              </div>

              {/* Progress / Overall Banner */}
              {loading ? (
                <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1', borderRadius: 'var(--radius-xs)', padding: '1rem', marginBottom: '1.25rem', textAlign: 'center' }}>
                  <div style={{ fontWeight: 600, color: 'var(--accent-navy)', fontSize: '0.9rem', marginBottom: '0.25rem' }}>
                    Checking cryptographic fingerprints and blockchain anchors across version history...
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--ink-muted)' }}>
                    Sequentially evaluating on-disk byte hashes against Ethereum smart contract registry.
                  </div>
                </div>
              ) : (
                renderFullAuditBanner()
              )}

              {/* Version by Version Audit List */}
              <div style={{ marginBottom: '1.5rem' }}>
                <div className="serif-heading" style={{ fontSize: '0.98rem', marginBottom: '0.65rem' }}>
                  Version-by-Version Cryptographic Audit
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                  {fullProgressList.map((item) => {
                    const isVerifying = item.status === 'verifying';
                    const isWaiting = item.status === 'waiting';
                    const isCompleted = item.status === 'completed';
                    const res = item.result;

                    let statusBadge = null;
                    if (isWaiting) {
                      statusBadge = (
                        <span className="badge" style={{ backgroundColor: '#F1F5F9', color: '#64748B', border: '1px solid #CBD5E1', fontSize: '0.72rem' }}>
                          ○ WAITING
                        </span>
                      );
                    } else if (isVerifying) {
                      statusBadge = (
                        <span className="badge" style={{ backgroundColor: '#EFF6FF', color: '#1D4ED8', border: '1px solid #BFDBFE', fontWeight: 700, fontSize: '0.72rem' }}>
                          ⟳ VERIFYING...
                        </span>
                      );
                    } else if (isCompleted && res) {
                      if (res.result === 'VERIFIED') {
                        statusBadge = (
                          <span className="badge" style={{ backgroundColor: '#ECFDF5', color: '#047857', border: '1px solid #A7F3D0', fontWeight: 700, fontSize: '0.75rem' }}>
                            ✓ VERIFIED
                          </span>
                        );
                      } else if (res.result === 'TAMPERED') {
                        statusBadge = (
                          <span className="badge" style={{ backgroundColor: '#FEF2F2', color: '#B91C1C', border: '1px solid #FECACA', fontWeight: 700, fontSize: '0.75rem' }}>
                            ✕ TAMPERED
                          </span>
                        );
                      } else {
                        statusBadge = (
                          <span className="badge" style={{ backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FCD34D', fontWeight: 700, fontSize: '0.75rem' }}>
                            ⚠ PROOF UNAVAILABLE
                          </span>
                        );
                      }
                    }

                    return (
                      <div
                        key={item.version_number}
                        style={{
                          border: res?.result === 'TAMPERED' ? '1.5px solid #EF4444' : isCompleted && res?.result === 'VERIFIED' ? '1px solid #A7F3D0' : '1px solid var(--border-color)',
                          backgroundColor: res?.result === 'TAMPERED' ? '#FEF2F2' : isCompleted && res?.result === 'VERIFIED' ? '#F0FDF4' : '#FFFFFF',
                          borderRadius: 'var(--radius-xs)',
                          padding: '0.85rem 1rem',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.35rem' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span
                              className="badge"
                              style={{
                                backgroundColor: item.is_current ? '#4338CA' : '#E2E8F0',
                                color: item.is_current ? '#FFFFFF' : '#334155',
                                fontWeight: 700,
                                fontSize: '0.75rem',
                              }}
                            >
                              v{item.version_number}
                            </span>
                            {item.is_current && (
                              <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#3730A3', fontSize: '0.68rem' }}>
                                CURRENT
                              </span>
                            )}
                            <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--ink-primary)' }}>
                              {item.filename}
                            </span>
                            {item.file_size > 0 && (
                              <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)' }}>
                                ({formatFileSize(item.file_size)})
                              </span>
                            )}
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            {statusBadge}
                          </div>
                        </div>

                        {/* Hash details if completed */}
                        {res && (
                          <div style={{ fontSize: '0.72rem', color: 'var(--ink-secondary)', marginTop: '0.4rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.4rem' }}>
                            <div>
                              <span style={{ color: 'var(--ink-muted)' }}>On-Disk SHA-256: </span>
                              <span style={{ fontFamily: 'var(--font-mono)' }}>{res.current_hash?.substring(0, 24)}...</span>
                              <button
                                type="button"
                                className="copy-btn"
                                onClick={() => copyToClipboard(res.current_hash, `full_v${item.version_number}_hash`)}
                                title="Copy on-disk hash"
                              >
                                {copiedField === `full_v${item.version_number}_hash` ? '✓' : '⧉'}
                              </button>
                            </div>
                            <div>
                              <span style={{ color: 'var(--ink-muted)' }}>On-Chain Hash: </span>
                              <span style={{ fontFamily: 'var(--font-mono)' }}>{res.blockchain_hash ? `${res.blockchain_hash.substring(0, 24)}...` : 'Unavailable'}</span>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Master Forensic Chain-of-Custody Record */}
              {!loading && overallSummary && (
                <div style={{ marginTop: '1.5rem' }}>
                  <div className="serif-heading" style={{ fontSize: '0.98rem', marginBottom: '0.5rem' }}>
                    Forensic Chain-of-Custody Summary
                  </div>
                  <table className="provenance-table">
                    <tbody>
                      <tr>
                        <td className="field-name">Document Title</td>
                        <td className="field-val">{masterFilename}</td>
                      </tr>
                      <tr>
                        <td className="field-name">Total Versions Checked</td>
                        <td className="field-val">{fullProgressList.length} Revisions</td>
                      </tr>
                      <tr>
                        <td className="field-name">Overall Integrity Verdict</td>
                        <td className="field-val">
                          <span
                            className="badge"
                            style={{
                              backgroundColor: overallSummary.status === 'VERIFIED' ? '#ECFDF5' : '#FEF2F2',
                              color: overallSummary.status === 'VERIFIED' ? '#047857' : '#B91C1C',
                              fontWeight: 700,
                              fontSize: '0.75rem',
                            }}
                          >
                            {overallSummary.status === 'VERIFIED' ? '✓ VERIFIED' : '⚠ TAMPERED'}
                          </span>
                        </td>
                      </tr>
                      {overallSummary.status === 'TAMPERED' && (
                        <tr>
                          <td className="field-name">Affected Revision(s)</td>
                          <td className="field-val" style={{ color: '#B91C1C', fontWeight: 700 }}>
                            {overallSummary.affectedLabel}
                          </td>
                        </tr>
                      )}
                      <tr>
                        <td className="field-name">Audit Execution Time</td>
                        <td className="field-val">{auditTimestamp}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {/* Actions Toolbar */}
              <div style={{ marginTop: '1.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleDownloadFile(documentId, null, masterFilename)}
                  disabled={isDownloading || loading}
                >
                  {isDownloading ? 'Downloading...' : 'Download Current Master File'}
                </button>

                <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
                  Close Certificate
                </button>
              </div>
            </div>
          ) : singleData ? (
            /* --- SINGLE VERSION VERIFICATION UI --- */
            <div>
              {/* Inspected Target Summary Strip */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem', backgroundColor: 'var(--bg-subtle)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-xs)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontWeight: 600, color: 'var(--ink-primary)', fontSize: '0.92rem' }}>
                    {singleData.filename}
                  </span>
                  <span
                    className="badge"
                    style={{
                      backgroundColor: '#EEF2FF',
                      color: '#3730A3',
                      border: '1px solid #C7D2FE',
                      fontWeight: 700,
                      fontSize: '0.72rem',
                    }}
                  >
                    v{versionIdentifier || singleData.version_number || singleData.version || 1} {singleData.is_current !== false ? '(Current Master)' : '(Historical Revision)'}
                  </span>
                </div>
                {singleData.case_number && (
                  <span className="case-id-cell">Case: {singleData.case_number}</span>
                )}
              </div>

              {/* Verdict Banner */}
              {renderSingleVerdictBanner(singleData)}

              {/* Side by Side Hash Comparison */}
              <div className="hash-comparison-grid">
                <div className="hash-box">
                  <div className="hash-box-label">Live On-Disk SHA-256 Hash</div>
                  <div className="hash-value">
                    {singleData.current_hash}
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() => copyToClipboard(singleData.current_hash, 'single_current')}
                      title="Copy Current Hash"
                    >
                      {copiedField === 'single_current' ? '✓' : '⧉'}
                    </button>
                  </div>
                </div>

                <div className="hash-box">
                  <div className="hash-box-label">Canonical On-Chain Hash</div>
                  <div className="hash-value">
                    {singleData.blockchain_hash || <span style={{ color: 'var(--ink-subdued)' }}>Proof Missing on Connected Chain</span>}
                    {singleData.blockchain_hash && (
                      <button
                        type="button"
                        className="copy-btn"
                        onClick={() => copyToClipboard(singleData.blockchain_hash, 'single_chain')}
                        title="Copy Blockchain Hash"
                      >
                        {copiedField === 'single_chain' ? '✓' : '⧉'}
                      </button>
                    )}
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
                      <td className="field-val">{singleData.filename}</td>
                    </tr>
                    <tr>
                      <td className="field-name">Case Reference</td>
                      <td className="field-val">{singleData.case_number || 'UNASSIGNED'}</td>
                    </tr>
                    <tr>
                      <td className="field-name">Original Depositor</td>
                      <td className="field-val">{singleData.uploaded_by}</td>
                    </tr>
                    <tr>
                      <td className="field-name">Smart Contract Address</td>
                      <td className="field-val font-mono">{singleData.contract_address}</td>
                    </tr>
                    <tr>
                      <td className="field-name">EVM Transaction Hash</td>
                      <td className="field-val font-mono">
                        {singleData.blockchain_tx_hash || 'N/A'}
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">On-Chain Custody Wallet</td>
                      <td className="field-val font-mono">{singleData.owner || 'N/A'}</td>
                    </tr>
                    <tr>
                      <td className="field-name">On-Chain Block Timestamp</td>
                      <td className="field-val">
                        {formatTimestamp(singleData.timestamp)}
                      </td>
                    </tr>
                    <tr>
                      <td className="field-name">Inspected Version</td>
                      <td className="field-val">
                        v{singleData.version_number || singleData.version || 1}{' '}
                        <span style={{ fontSize: '0.78rem', color: 'var(--ink-muted)' }}>
                          {singleData.is_current ? '(Current Active Version)' : '(Historical Revision Proof)'}
                        </span>
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
                  onClick={() => handleDownloadFile(singleData.document_id, singleData.version_number || singleData.version, singleData.filename)}
                  disabled={isDownloading}
                >
                  {isDownloading ? 'Downloading...' : 'Download Inspected File'}
                </button>

                <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
                  Close Certificate
                </button>
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--ink-muted)' }}>
              Executing live SHA-256 computation &amp; querying EVM smart contract state...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
