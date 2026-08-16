import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchDocumentDetail,
  downloadDocumentFile,
  fetchDocumentShares,
  revokeDocumentShare,
  fetchDocumentVersions,
  uploadDocumentVersion,
  downloadVersionFile,
} from '../services/api';
import { useAuth } from '../context/AuthContext';
import { getVersionIntegrity } from '../utils/integrity';

const ALLOWED_EXTENSIONS = ['.pdf', '.txt', '.docx', '.jpg', '.jpeg', '.png'];
const MAX_FILE_SIZE_MB = 10;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

export default function DocumentDetailDrawer({ documentId, isOpen, onClose, onVerify, onOpenShare, integrityResults = {} }) {
  const { user, isAdmin } = useAuth();
  const [doc, setDoc] = useState(null);
  const [versions, setVersions] = useState([]);
  const [shares, setShares] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);
  const [revokingShareId, setRevokingShareId] = useState(null);
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadingVersionNum, setDownloadingVersionNum] = useState(null);

  // New Revision Upload Modal State
  const [isUploadRevisionOpen, setIsUploadRevisionOpen] = useState(false);
  const [revisionFile, setRevisionFile] = useState(null);
  const [revisionHash, setRevisionHash] = useState('');
  const [isHashingRevision, setIsHashingRevision] = useState(false);
  const [revisionSubmitting, setRevisionSubmitting] = useState(false);
  const [revisionError, setRevisionError] = useState('');
  const [revisionDuplicate, setRevisionDuplicate] = useState(null);
  const fileInputRef = useRef(null);

  const resetRevisionForm = useCallback(() => {
    setRevisionFile(null);
    setRevisionHash('');
    setRevisionError('');
    setRevisionDuplicate(null);
    setRevisionSubmitting(false);
    setIsHashingRevision(false);
  }, []);

  const loadDetail = useCallback(async () => {
    if (!documentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDocumentDetail(documentId);
      setDoc(data);

      // Load Version History
      try {
        const vList = await fetchDocumentVersions(documentId);
        setVersions(vList);
      } catch (err) {
        console.warn('Failed to load version history:', err);
        setVersions([]);
      }

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
      setVersions([]);
      setShares([]);
      setError(null);
      setIsUploadRevisionOpen(false);
      resetRevisionForm();
    }
  }, [isOpen, documentId, loadDetail, resetRevisionForm]);

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

  const handleDownloadMaster = async () => {
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

  const handleDownloadVersion = async (versionNumber, filename) => {
    if (!doc) return;
    setDownloadingVersionNum(versionNumber);
    try {
      await downloadVersionFile(doc.id, versionNumber, filename);
    } catch (err) {
      alert(err.message || 'Download failed');
    } finally {
      setDownloadingVersionNum(null);
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

  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  // --- Revision Upload Logic ---

  const validateRevisionFile = (selectedFile) => {
    const filename = selectedFile.name.toLowerCase();
    const ext = filename.lastIndexOf('.') !== -1 ? filename.substring(filename.lastIndexOf('.')) : '';

    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Unsupported file format '${ext}'. Allowed formats: ${ALLOWED_EXTENSIONS.join(', ')}`;
    }

    if (selectedFile.size > MAX_FILE_SIZE_BYTES) {
      return `File exceeds maximum allowed size of ${MAX_FILE_SIZE_MB} MB (${(selectedFile.size / (1024 * 1024)).toFixed(2)} MB).`;
    }

    return null;
  };

  const calculateRevisionSha256 = async (selectedFile) => {
    setIsHashingRevision(true);
    setRevisionHash('');
    try {
      const arrayBuffer = await selectedFile.arrayBuffer();
      const hashBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
      setRevisionHash(hashHex);
    } catch (err) {
      console.warn('Could not compute client-side SHA-256:', err);
    } finally {
      setIsHashingRevision(false);
    }
  };

  const handleRevisionFileChange = (e) => {
    const selected = e.target.files?.[0];
    if (selected) {
      const valError = validateRevisionFile(selected);
      if (valError) {
        setRevisionError(valError);
        setRevisionFile(null);
        setRevisionHash('');
        setRevisionDuplicate(null);
        return;
      }
      setRevisionFile(selected);
      setRevisionError('');
      setRevisionDuplicate(null);
      calculateRevisionSha256(selected);
    }
  };

  const handleRevisionDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      const valError = validateRevisionFile(dropped);
      if (valError) {
        setRevisionError(valError);
        setRevisionFile(null);
        setRevisionHash('');
        setRevisionDuplicate(null);
        return;
      }
      setRevisionFile(dropped);
      setRevisionError('');
      setRevisionDuplicate(null);
      calculateRevisionSha256(dropped);
    }
  };

  const performRevisionUpload = async (allowDuplicate = false) => {
    if (!revisionFile) {
      setRevisionError('Please select a revised file to upload.');
      return;
    }

    setRevisionSubmitting(true);
    setRevisionError('');
    setRevisionDuplicate(null);

    try {
      await uploadDocumentVersion(doc.id, {
        file: revisionFile,
        uploadedBy: user?.name,
        allowDuplicate,
      });

      // Reset form and reload
      setIsUploadRevisionOpen(false);
      resetRevisionForm();
      await loadDetail();
    } catch (err) {
      if (err.status === 409 || err.data?.code === 'DUPLICATE_VERSION') {
        const existingVer = err.data?.existing_version;
        setRevisionDuplicate(existingVer || { file_hash: revisionHash });
      } else {
        setRevisionError(err.message || 'Revision upload failed. Please verify system connectivity.');
      }
    } finally {
      setRevisionSubmitting(false);
    }
  };

  const canManageDoc = doc?.is_owner || isAdmin;
  const nextVersionNumber = (doc?.version || 1) + 1;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">Evault Docket Inspection &amp; Provenance</span>
            <h3 className="modal-title">Record #{documentId} Details</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          {loading ? (
            <div style={{ textAlign: 'center', padding: '2.5rem 1rem', color: 'var(--ink-muted)' }}>
              Retrieving off-chain metadata, version tree, and on-chain state...
            </div>
          ) : error ? (
            <div className="verdict-banner tampered">
              <div className="verdict-explanation">{error}</div>
            </div>
          ) : doc ? (
            <div>
              {/* Document Master Header */}
              <div style={{ marginBottom: '1.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                    <h3 className="serif-heading" style={{ fontSize: '1.25rem', margin: 0 }}>
                      {doc.filename}
                    </h3>
                    <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#3730A3', border: '1px solid #C7D2FE', fontWeight: 600, fontSize: '0.72rem' }}>
                      v{doc.version || 1} (Current)
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <span className="case-id-cell">Case: {doc.case_number || 'UNASSIGNED'}</span>
                    <span style={{ color: 'var(--border-strong)' }}>|</span>
                    <span style={{ fontSize: '0.8rem', color: 'var(--ink-muted)' }}>
                      Initial Deposit: {formatDate(doc.created_at)}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  {canManageDoc && (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => setIsUploadRevisionOpen(true)}
                      title="Upload a new immutable version for this legal document"
                    >
                      + Upload New Revision
                    </button>
                  )}

                  {canManageDoc && onOpenShare && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => onOpenShare(doc)}
                    >
                      Share Record
                    </button>
                  )}
                </div>
              </div>

              {/* Master Active Fingerprint */}
              <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem', marginBottom: '1.25rem' }}>
                <div className="stat-label">Current Master Fingerprint (SHA-256)</div>
                <div className="hash-tag" style={{ width: '100%', wordBreak: 'break-all', marginTop: '0.35rem' }}>
                  {doc.file_hash}
                  <button
                    type="button"
                    className="copy-btn"
                    onClick={() => copyToClipboard(doc.file_hash, 'master_hash')}
                    title="Copy SHA-256 Hash"
                  >
                    {copiedField === 'master_hash' ? '✓' : '⧉'}
                  </button>
                </div>
              </div>

              {/* Revision Upload Form Modal Overlay */}
              {isUploadRevisionOpen && (
                <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1', borderRadius: 'var(--radius-sm)', padding: '1.25rem', marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="serif-heading" style={{ fontSize: '1.05rem', color: 'var(--accent-navy)' }}>
                        Deposit New Document Revision
                      </span>
                      <span className="badge" style={{ backgroundColor: '#ECFDF5', color: '#047857', border: '1px solid #A7F3D0', fontWeight: 700, fontSize: '0.72rem' }}>
                        WILL BECOME VERSION {nextVersionNumber}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => {
                        setIsUploadRevisionOpen(false);
                        resetRevisionForm();
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  <p style={{ fontSize: '0.8rem', color: 'var(--ink-secondary)', marginBottom: '1rem', lineHeight: 1.45 }}>
                    Uploading a revised file creates a new immutable version (<strong>v{nextVersionNumber}</strong>). All historical revisions (v1 .. v{doc.version || 1}) will remain permanently preserved, downloadable, and cryptographically verifiable.
                  </p>

                  {revisionError && (
                    <div className="verdict-banner tampered" style={{ marginBottom: '1rem', padding: '0.65rem 0.85rem' }}>
                      <div className="verdict-explanation" style={{ margin: 0, fontSize: '0.8rem' }}>
                        {revisionError}
                      </div>
                    </div>
                  )}

                  {/* Duplicate Revision Warning */}
                  {revisionDuplicate && (
                    <div style={{ backgroundColor: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 'var(--radius-xs)', padding: '0.85rem', marginBottom: '1rem' }}>
                      <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#92400E', marginBottom: '0.25rem' }}>
                        ⚠ IDENTICAL CONTENT DETECTED IN VERSION HISTORY
                      </div>
                      <div style={{ fontSize: '0.78rem', color: '#78350F', marginBottom: '0.65rem' }}>
                        This file has an identical SHA-256 cryptographic hash to <strong>Version {revisionDuplicate.version_number || 'previous'}</strong> of this document.
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => setRevisionDuplicate(null)}
                          disabled={revisionSubmitting}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          style={{ backgroundColor: '#B45309', borderColor: '#B45309' }}
                          onClick={() => performRevisionUpload(true)}
                          disabled={revisionSubmitting}
                        >
                          {revisionSubmitting ? 'Creating Revision...' : `Deposit Anyway as v${nextVersionNumber}`}
                        </button>
                      </div>
                    </div>
                  )}

                  <div className="form-group" style={{ marginBottom: '1rem' }}>
                    <div
                      className="dropzone"
                      style={{ padding: '1.25rem 1rem' }}
                      onDrop={handleRevisionDrop}
                      onDragOver={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                      }}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        style={{ display: 'none' }}
                        accept={ALLOWED_EXTENSIONS.join(',')}
                        onChange={handleRevisionFileChange}
                      />
                      {revisionFile ? (
                        <div>
                          <div className="dropzone-title" style={{ color: 'var(--accent-navy)', fontSize: '0.92rem' }}>
                            {revisionFile.name}
                          </div>
                          <div className="dropzone-subtitle" style={{ fontSize: '0.78rem' }}>
                            {formatFileSize(revisionFile.size)} · Click to choose different file
                          </div>
                        </div>
                      ) : (
                        <div>
                          <div className="dropzone-title" style={{ fontSize: '0.92rem' }}>
                            Click to select or drag revised legal document
                          </div>
                          <div className="dropzone-subtitle" style={{ fontSize: '0.78rem' }}>
                            Supported formats: PDF, DOCX, TXT, JPG, PNG (Max {MAX_FILE_SIZE_MB} MB)
                          </div>
                        </div>
                      )}
                    </div>

                    {isHashingRevision && (
                      <div className="form-helper mono-text" style={{ color: 'var(--ink-muted)', marginTop: '0.35rem' }}>
                        Computing cryptographic SHA-256 fingerprint...
                      </div>
                    )}
                    {revisionHash && !isHashingRevision && (
                      <div style={{ marginTop: '0.4rem' }}>
                        <span className="form-label" style={{ fontSize: '0.68rem', marginBottom: '0.15rem' }}>
                          Calculated Revision SHA-256:
                        </span>
                        <div className="hash-tag" style={{ width: '100%', wordBreak: 'break-all', fontSize: '0.72rem' }}>
                          {revisionHash}
                        </div>
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.6rem' }}>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => {
                        setIsUploadRevisionOpen(false);
                        resetRevisionForm();
                      }}
                      disabled={revisionSubmitting}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => performRevisionUpload(false)}
                      disabled={revisionSubmitting || !revisionFile || isHashingRevision || Boolean(revisionDuplicate)}
                    >
                      {revisionSubmitting ? 'Registering on Blockchain...' : `Anchor Version ${nextVersionNumber} on Blockchain`}
                    </button>
                  </div>
                </div>
              )}

              {/* Version History Section */}
              <div style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.65rem' }}>
                  <div className="serif-heading" style={{ fontSize: '1.05rem', color: 'var(--ink-primary)' }}>
                    Version History &amp; Revision Provenance ({versions.length})
                  </div>
                </div>

                {versions.length === 0 ? (
                  <div style={{ fontSize: '0.8rem', color: 'var(--ink-muted)', padding: '0.75rem', backgroundColor: 'var(--bg-subtle)', borderRadius: 'var(--radius-xs)' }}>
                    Initial Version 1 active.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                    {versions.map((v) => {
                      const isCurrent = v.is_current || (v.version_number === doc.version);
                      const verIntegrity = getVersionIntegrity(doc.id, v.version_number, integrityResults);
                      return (
                        <div
                          key={v.id || v.version_number}
                          style={{
                            border: isCurrent ? '1.5px solid #6366F1' : '1px solid var(--border-color)',
                            backgroundColor: isCurrent ? '#F5F3FF' : 'var(--bg-card)',
                            borderRadius: 'var(--radius-xs)',
                            padding: '0.85rem 1rem',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.4rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                              <span
                                className="badge"
                                style={{
                                  backgroundColor: isCurrent ? '#4338CA' : '#E2E8F0',
                                  color: isCurrent ? '#FFFFFF' : '#334155',
                                  fontWeight: 700,
                                  fontSize: '0.75rem',
                                  padding: '0.15rem 0.55rem',
                                }}
                              >
                                v{v.version_number}
                              </span>
                              {isCurrent && (
                                <span className="badge" style={{ backgroundColor: '#ECFDF5', color: '#047857', border: '1px solid #A7F3D0', fontWeight: 600, fontSize: '0.68rem' }}>
                                  CURRENT ACTIVE
                                </span>
                              )}
                              <span style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--ink-primary)' }}>
                                {v.filename}
                              </span>
                              {v.file_size > 0 && (
                                <span style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                                  ({formatFileSize(v.file_size)})
                                </span>
                              )}
                            </div>

                            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
                                onClick={() => handleDownloadVersion(v.version_number, v.filename)}
                                disabled={downloadingVersionNum === v.version_number}
                                title="Download exact file for this revision"
                              >
                                {downloadingVersionNum === v.version_number ? 'Downloading...' : 'Download File'}
                              </button>

                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                style={{ fontSize: '0.72rem', padding: '0.2rem 0.6rem' }}
                                onClick={() => {
                                  onClose();
                                  onVerify(doc.id, v.version_number);
                                }}
                                title="Run live cryptographic verification for this specific revision"
                              >
                                Verify v{v.version_number}
                              </button>
                            </div>
                          </div>

                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.5rem', fontSize: '0.78rem', color: 'var(--ink-secondary)', marginTop: '0.35rem' }}>
                            <div>
                              <span style={{ color: 'var(--ink-muted)' }}>Deposited by: </span>
                              <strong>{v.uploaded_by || 'Unknown'}</strong>
                            </div>
                            <div>
                              <span style={{ color: 'var(--ink-muted)' }}>Date: </span>
                              <span style={{ fontFamily: 'var(--font-mono)' }}>{formatDate(v.created_at)}</span>
                            </div>
                            <div>
                              <span style={{ color: 'var(--ink-muted)' }}>Anchor: </span>
                              <span className={`badge ${v.blockchain_status === 'confirmed' ? 'badge-confirmed' : 'badge-failed'}`} style={{ fontSize: '0.68rem', padding: '0.05rem 0.4rem' }}>
                                ● {v.blockchain_status === 'confirmed' ? 'CONFIRMED' : (v.blockchain_status || 'Pending').toUpperCase()}
                              </span>
                            </div>
                            <div>
                              <span style={{ color: 'var(--ink-muted)' }}>Integrity: </span>
                              {verIntegrity ? (
                                verIntegrity.result === 'VERIFIED' ? (
                                  <span className="badge" style={{ backgroundColor: '#ECFDF5', color: '#047857', border: '1px solid #A7F3D0', fontWeight: 700, fontSize: '0.68rem', padding: '0.05rem 0.4rem' }}>
                                    ✓ VERIFIED
                                  </span>
                                ) : verIntegrity.result === 'BLOCKCHAIN_PROOF_UNAVAILABLE' ? (
                                  <span className="badge" style={{ backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FCD34D', fontWeight: 700, fontSize: '0.68rem', padding: '0.05rem 0.4rem' }}>
                                    ⚠ PROOF UNAVAILABLE
                                  </span>
                                ) : (
                                  <span className="badge" style={{ backgroundColor: '#FEF2F2', color: '#B91C1C', border: '1px solid #FECACA', fontWeight: 700, fontSize: '0.68rem', padding: '0.05rem 0.4rem' }}>
                                    ⚠ TAMPERED
                                  </span>
                                )
                              ) : (
                                <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontStyle: 'italic' }}>
                                  Unverified
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Version SHA256 */}
                          <div style={{ marginTop: '0.45rem', fontSize: '0.72rem' }}>
                            <span style={{ color: 'var(--ink-muted)' }}>SHA-256 Fingerprint: </span>
                            <div className="hash-tag" style={{ width: '100%', wordBreak: 'break-all', marginTop: '0.15rem', fontSize: '0.7rem' }}>
                              {v.file_hash}
                              <button
                                type="button"
                                className="copy-btn"
                                onClick={() => copyToClipboard(v.file_hash, `v_${v.version_number}_hash`)}
                                title="Copy Version Hash"
                              >
                                {copiedField === `v_${v.version_number}_hash` ? '✓' : '⧉'}
                              </button>
                            </div>
                          </div>

                          {/* EVM TX Hash if present */}
                          {v.blockchain_tx_hash && (
                            <div style={{ marginTop: '0.3rem', fontSize: '0.72rem' }}>
                              <span style={{ color: 'var(--ink-muted)' }}>EVM TX: </span>
                              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-primary)' }}>
                                {v.blockchain_tx_hash.substring(0, 20)}...
                              </span>
                              <button
                                type="button"
                                className="copy-btn"
                                onClick={() => copyToClipboard(v.blockchain_tx_hash, `v_${v.version_number}_tx`)}
                                title="Copy TX Hash"
                              >
                                {copiedField === `v_${v.version_number}_tx` ? '✓' : '⧉'}
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Master Blockchain Provenance Table */}
              <div className="serif-heading" style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>
                Master Blockchain Provenance
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
                        <td className="field-name">On-Chain Current Version</td>
                        <td className="field-val">v{doc.onchain.version}</td>
                      </tr>
                    </>
                  )}
                </tbody>
              </table>

              {/* Active Judicial & Client Shares Section (Owner / Admin only) */}
              {canManageDoc && (
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

              {/* Master Actions Toolbar */}
              <div style={{ marginTop: '1.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleDownloadMaster}
                  disabled={isDownloading}
                >
                  {isDownloading ? 'Downloading...' : 'Download Current Master File'}
                </button>

                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      onClose();
                      onVerify(doc.id);
                    }}
                    title="Run comprehensive cryptographic audit across all historical versions"
                  >
                    Run Full Document Integrity Verification
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
