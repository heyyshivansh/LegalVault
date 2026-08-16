import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchDocumentDetail,
  downloadDocumentFile,
  fetchDocumentShares,
  revokeDocumentShare,
  fetchDocumentVersions,
  uploadDocumentVersion,
  downloadVersionFile,
  fetchDocumentAuditTrail,
  extractVersionMetadata,
  fetchVersionMetadata,
  generateVersionSummary,
  fetchVersionSummary,
  compareDocumentVersions,
  fetchDocumentVersionComparison,
  generateVersionTimeline,
  fetchVersionTimeline,
  fetchDocumentTimeline,
} from '../services/api';
import { useAuth } from '../context/AuthContext';
import { getVersionIntegrity } from '../utils/integrity';
import { formatISTDateTime, formatBlockTimestampIST } from '../utils/timezone';

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

  // AI Metadata State
  const [selectedMetaVersion, setSelectedMetaVersion] = useState(1);
  const [metadataMap, setMetadataMap] = useState({});
  const [loadingMetaVer, setLoadingMetaVer] = useState(null);
  const [extractingMetaVer, setExtractingMetaVer] = useState(null);
  const [metaError, setMetaError] = useState(null);

  // AI Summary State
  const [selectedSummaryVersion, setSelectedSummaryVersion] = useState(1);
  const [summaryMap, setSummaryMap] = useState({});
  const [loadingSummaryVer, setLoadingSummaryVer] = useState(null);
  const [generatingSummaryVer, setGeneratingSummaryVer] = useState(null);
  const [summaryError, setSummaryError] = useState(null);

  // AI Evidence Timeline State
  const [selectedTimelineVersion, setSelectedTimelineVersion] = useState(1);
  const [timelineMap, setTimelineMap] = useState({});
  const [loadingTimelineVer, setLoadingTimelineVer] = useState(null);
  const [generatingTimelineVer, setGeneratingTimelineVer] = useState(null);
  const [timelineError, setTimelineError] = useState(null);

  // AI Version Comparison State
  const [fromCompareVer, setFromCompareVer] = useState(1);
  const [toCompareVer, setToCompareVer] = useState(2);
  const [comparisonMap, setComparisonMap] = useState({});
  const [loadingComparisonKey, setLoadingComparisonKey] = useState(null);
  const [runningComparisonKey, setRunningComparisonKey] = useState(null);
  const [comparisonError, setComparisonError] = useState(null);

  // Audit Trail State
  const [auditEvents, setAuditEvents] = useState([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState(null);
  const [auditActionFilter, setAuditActionFilter] = useState('');
  const [auditVersionFilter, setAuditVersionFilter] = useState('');

  // New Revision Upload Modal State
  const [isUploadRevisionOpen, setIsUploadRevisionOpen] = useState(false);
  const [revisionFile, setRevisionFile] = useState(null);
  const [revisionHash, setRevisionHash] = useState('');
  const [isHashingRevision, setIsHashingRevision] = useState(false);
  const [revisionSubmitting, setRevisionSubmitting] = useState(false);
  const [revisionError, setRevisionError] = useState('');
  const [revisionDuplicate, setRevisionDuplicate] = useState(null);
  const fileInputRef = useRef(null);
  const revisionSectionRef = useRef(null);

  const handleOpenRevisionUpload = useCallback(() => {
    setIsUploadRevisionOpen(true);
    requestAnimationFrame(() => {
      if (revisionSectionRef.current) {
        revisionSectionRef.current.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      }
    });
  }, []);

  const resetRevisionForm = useCallback(() => {
    setRevisionFile(null);
    setRevisionHash('');
    setRevisionError('');
    setRevisionDuplicate(null);
    setRevisionSubmitting(false);
    setIsHashingRevision(false);
  }, []);

  const loadVersionMetadata = useCallback(async (versionNum) => {
    if (!documentId || !versionNum) return;
    setLoadingMetaVer(versionNum);
    setMetaError(null);
    try {
      const data = await fetchVersionMetadata(documentId, versionNum);
      setMetadataMap((prev) => ({ ...prev, [versionNum]: data }));
    } catch (err) {
      console.warn(`Failed to load AI metadata for v${versionNum}:`, err);
    } finally {
      setLoadingMetaVer(null);
    }
  }, [documentId]);

  const handleExtractMetadata = async (versionNum, force = false) => {
    if (!documentId || !versionNum) return;
    setExtractingMetaVer(versionNum);
    setMetaError(null);
    try {
      const data = await extractVersionMetadata(documentId, versionNum, force);
      setMetadataMap((prev) => ({ ...prev, [versionNum]: data }));
      // Refresh audit trail
      loadAuditTrail();
    } catch (err) {
      setMetaError(err.message || 'AI metadata extraction failed.');
    } finally {
      setExtractingMetaVer(null);
    }
  };

  const loadVersionSummary = useCallback(async (versionNum) => {
    if (!documentId || !versionNum) return;
    setLoadingSummaryVer(versionNum);
    setSummaryError(null);
    try {
      const data = await fetchVersionSummary(documentId, versionNum);
      setSummaryMap((prev) => ({ ...prev, [versionNum]: data }));
    } catch (err) {
      console.warn(`Failed to load AI summary for v${versionNum}:`, err);
    } finally {
      setLoadingSummaryVer(null);
    }
  }, [documentId]);

  const handleGenerateSummary = async (versionNum, force = false) => {
    if (!documentId || !versionNum) return;
    setGeneratingSummaryVer(versionNum);
    setSummaryError(null);
    try {
      const data = await generateVersionSummary(documentId, versionNum, force);
      setSummaryMap((prev) => ({ ...prev, [versionNum]: data }));
      // Refresh audit trail
      loadAuditTrail();
    } catch (err) {
      setSummaryError(err.message || 'AI summary generation failed.');
    } finally {
      setGeneratingSummaryVer(null);
    }
  };

  const loadVersionTimeline = useCallback(async (versionNum) => {
    if (!documentId || !versionNum) return;
    setLoadingTimelineVer(versionNum);
    setTimelineError(null);
    try {
      const data = await fetchVersionTimeline(documentId, versionNum);
      setTimelineMap((prev) => ({ ...prev, [versionNum]: data }));
    } catch (err) {
      console.warn(`Failed to load AI timeline for v${versionNum}:`, err);
    } finally {
      setLoadingTimelineVer(null);
    }
  }, [documentId]);

  const handleGenerateTimeline = async (versionNum, force = false) => {
    if (!documentId || !versionNum) return;
    setGeneratingTimelineVer(versionNum);
    setTimelineError(null);
    try {
      const data = await generateVersionTimeline(documentId, versionNum, force);
      setTimelineMap((prev) => ({ ...prev, [versionNum]: data }));
      // Refresh audit trail
      loadAuditTrail();
    } catch (err) {
      setTimelineError(err.message || 'AI timeline extraction failed.');
    } finally {
      setGeneratingTimelineVer(null);
    }
  };

  const loadVersionComparison = useCallback(async (fromV, toV) => {
    if (!documentId || !fromV || !toV) return;
    const key = `${fromV}->${toV}`;
    setLoadingComparisonKey(key);
    setComparisonError(null);
    try {
      const data = await fetchDocumentVersionComparison(documentId, fromV, toV);
      setComparisonMap((prev) => ({ ...prev, [key]: data }));
    } catch (err) {
      console.warn(`Failed to load comparison for ${key}:`, err);
    } finally {
      setLoadingComparisonKey(null);
    }
  }, [documentId]);

  const handleRunComparison = async (fromV, toV, force = false) => {
    if (!documentId || !fromV || !toV) return;
    const key = `${fromV}->${toV}`;
    setRunningComparisonKey(key);
    setComparisonError(null);
    try {
      const data = await compareDocumentVersions(documentId, fromV, toV, force);
      setComparisonMap((prev) => ({ ...prev, [key]: data }));
      loadAuditTrail();
    } catch (err) {
      setComparisonError(err.message || `AI comparison between Version ${fromV} and Version ${toV} failed.`);
    } finally {
      setRunningComparisonKey(null);
    }
  };

  const loadAuditTrail = useCallback(async (actionFilter = auditActionFilter, versionFilter = auditVersionFilter) => {
    if (!documentId) return;
    setAuditLoading(true);
    setAuditError(null);
    try {
      const params = { limit: 100 };
      if (actionFilter) params.action = actionFilter;
      if (versionFilter !== '' && versionFilter !== null && versionFilter !== undefined) {
        params.version_number = parseInt(versionFilter, 10);
      }
      const data = await fetchDocumentAuditTrail(documentId, params);
      setAuditEvents(data.events || []);
      setAuditTotal(data.total_count || 0);
    } catch (err) {
      console.warn('Failed to load audit trail:', err);
      setAuditError(err.message || 'Failed to load audit trail.');
    } finally {
      setAuditLoading(false);
    }
  }, [documentId, auditActionFilter, auditVersionFilter]);

  const loadDetail = useCallback(async () => {
    if (!documentId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDocumentDetail(documentId);
      setDoc(data);

      const activeVer = data.version || 1;
      setSelectedMetaVersion(activeVer);
      setSelectedSummaryVersion(activeVer);
      setSelectedTimelineVersion(activeVer);

      // Load Version History
      try {
        const vList = await fetchDocumentVersions(documentId);
        setVersions(vList);
        if (vList && vList.length >= 2) {
          const vFrom = vList[0].version_number;
          const vTo = vList[vList.length - 1].version_number;
          setFromCompareVer(vFrom);
          setToCompareVer(vTo);
          try {
            const compData = await fetchDocumentVersionComparison(documentId, vFrom, vTo);
            const compKey = `${vFrom}->${vTo}`;
            setComparisonMap((prev) => ({ ...prev, [compKey]: compData }));
          } catch {
            // Not generated yet
          }
        }
      } catch (err) {
        console.warn('Failed to load version history:', err);
        setVersions([]);
      }

      // Load AI Metadata for the active version
      try {
        const metaData = await fetchVersionMetadata(documentId, activeVer);
        setMetadataMap((prev) => ({ ...prev, [activeVer]: metaData }));
      } catch (err) {
        console.warn('Failed to load active version AI metadata:', err);
      }

      // Load AI Summary for the active version
      try {
        const summaryData = await fetchVersionSummary(documentId, activeVer);
        setSummaryMap((prev) => ({ ...prev, [activeVer]: summaryData }));
      } catch (err) {
        console.warn('Failed to load active version AI summary:', err);
      }

      // Load AI Evidence Timeline for the active version
      try {
        const timelineData = await fetchVersionTimeline(documentId, activeVer);
        setTimelineMap((prev) => ({ ...prev, [activeVer]: timelineData }));
      } catch (err) {
        console.warn('Failed to load active version AI timeline:', err);
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

      // Load Audit Trail
      try {
        const auditData = await fetchDocumentAuditTrail(documentId, { limit: 100 });
        setAuditEvents(auditData.events || []);
        setAuditTotal(auditData.total_count || 0);
      } catch (err) {
        console.warn('Failed to load audit trail:', err);
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
      setAuditEvents([]);
      setAuditTotal(0);
      setAuditError(null);
      setAuditActionFilter('');
      setAuditVersionFilter('');
      setError(null);
      setIsUploadRevisionOpen(false);
      resetRevisionForm();
      setMetadataMap({});
      setMetaError(null);
      setExtractingMetaVer(null);
      setLoadingMetaVer(null);
      setSummaryMap({});
      setSummaryError(null);
      setGeneratingSummaryVer(null);
      setLoadingSummaryVer(null);
      setTimelineMap({});
      setTimelineError(null);
      setGeneratingTimelineVer(null);
      setLoadingTimelineVer(null);
      setComparisonMap({});
      setComparisonError(null);
      setRunningComparisonKey(null);
      setLoadingComparisonKey(null);
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

  const getActionBadgeStyle = (action) => {
    switch (action) {
      case 'DOCUMENT_CREATED':
      case 'VERSION_CREATED':
        return { backgroundColor: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE' };
      case 'DOCUMENT_VERIFIED':
      case 'VERSION_VERIFIED':
        return { backgroundColor: '#ECFDF5', color: '#047857', border: '1px solid #A7F3D0' };
      case 'DOCUMENT_TAMPERED':
      case 'VERSION_TAMPERED':
        return { backgroundColor: '#FEF2F2', color: '#B91C1C', border: '1px solid #FECACA' };
      case 'DOCUMENT_SHARED':
        return { backgroundColor: '#FAF5FF', color: '#7E22CE', border: '1px solid #E9D5FF' };
      case 'DOCUMENT_SHARE_REVOKED':
        return { backgroundColor: '#FFFBEB', color: '#B45309', border: '1px solid #FDE68A' };
      case 'DOCUMENT_DOWNLOADED':
      case 'VERSION_DOWNLOADED':
        return { backgroundColor: '#F0FDFA', color: '#0F766E', border: '1px solid #99F6E4' };
      case 'DOCUMENT_VIEWED':
      case 'VERSION_VIEWED':
      case 'SHARED_DOCUMENT_ACCESSED':
        return { backgroundColor: '#F8FAFC', color: '#475569', border: '1px solid #E2E8F0' };
      case 'ACCESS_DENIED':
      case 'ACTION_DENIED':
        return { backgroundColor: '#FFF1F2', color: '#BE123C', border: '1px solid #FECDD3' };
      case 'AI_METADATA_EXTRACTED':
        return { backgroundColor: '#F5F3FF', color: '#6D28D9', border: '1px solid #DDD6FE' };
      case 'AI_METADATA_EXTRACTION_FAILED':
        return { backgroundColor: '#FEF2F2', color: '#B91C1C', border: '1px solid #FECACA' };
      default:
        return { backgroundColor: '#F1F5F9', color: '#334155', border: '1px solid #CBD5E1' };
    }
  };

  const getResultBadgeStyle = (res) => {
    switch (res) {
      case 'SUCCESS':
      case 'VERIFIED':
        return { backgroundColor: '#ECFDF5', color: '#065F46', fontWeight: 600 };
      case 'TAMPERED':
      case 'FAILED':
      case 'DENIED':
        return { backgroundColor: '#FEF2F2', color: '#991B1B', fontWeight: 700 };
      case 'UNAVAILABLE':
        return { backgroundColor: '#FFFBEB', color: '#92400E', fontWeight: 600 };
      default:
        return { backgroundColor: '#F1F5F9', color: '#475569', fontWeight: 500 };
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

  const formatDate = (isoString) => formatISTDateTime(isoString);

  const formatTimestamp = (ts) => formatBlockTimestampIST(ts);

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
                      onClick={handleOpenRevisionUpload}
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

              {/* AI-Extracted Legal Metadata Section */}
              <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 'var(--radius-sm)', padding: '1.15rem 1.25rem', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.65rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
                    <span className="serif-heading" style={{ fontSize: '1rem', color: 'var(--accent-navy)', margin: 0 }}>
                      AI-Extracted Legal Metadata
                    </span>
                    <span className="badge" style={{ backgroundColor: '#EFF6FF', color: '#1D4ED8', border: '1px solid #BFDBFE', fontSize: '0.7rem', fontWeight: 600 }}>
                      v{selectedMetaVersion} {selectedMetaVersion === (doc.version || 1) ? '(Current)' : ''}
                    </span>
                    <span className="badge" style={{ backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A', fontSize: '0.65rem', fontWeight: 600 }}>
                      Informational · Non-Authoritative
                    </span>
                  </div>

                  {/* Version switcher pills if multiple versions exist */}
                  {versions.length > 1 && (
                    <div style={{ display: 'flex', gap: '0.3rem', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)' }}>Version:</span>
                      {versions.map((v) => (
                        <button
                          key={v.version_number}
                          type="button"
                          className={`btn btn-sm ${selectedMetaVersion === v.version_number ? 'btn-primary' : 'btn-ghost'}`}
                          style={{
                            fontSize: '0.68rem',
                            padding: '0.15rem 0.45rem',
                            minWidth: '2rem',
                          }}
                          onClick={() => {
                            setSelectedMetaVersion(v.version_number);
                            if (!metadataMap[v.version_number]) {
                              loadVersionMetadata(v.version_number);
                            }
                          }}
                        >
                          v{v.version_number}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Explicit Disclaimer Notice */}
                <div style={{ fontSize: '0.74rem', color: 'var(--ink-secondary)', backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', padding: '0.45rem 0.65rem', borderRadius: 'var(--radius-xs)', marginBottom: '0.85rem' }}>
                  ℹ <strong>Evidentiary Notice:</strong> AI metadata is an analytical extraction for categorization. It does <em>not</em> constitute legal verification or replace cryptographic blockchain provenance.
                </div>

                {metaError && (
                  <div className="verdict-banner tampered" style={{ marginBottom: '0.85rem', padding: '0.55rem 0.75rem' }}>
                    <div className="verdict-explanation" style={{ margin: 0, fontSize: '0.78rem' }}>
                      {metaError}
                    </div>
                  </div>
                )}

                {/* Loading / Extracting State */}
                {extractingMetaVer === selectedMetaVersion || loadingMetaVer === selectedMetaVersion ? (
                  <div style={{ textAlign: 'center', padding: '1.75rem 1rem', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-xs)', border: '1px solid #E2E8F0' }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-navy)', marginBottom: '0.25rem' }}>
                      {extractingMetaVer === selectedMetaVersion ? 'Analyzing Document Text with AI Model...' : 'Retrieving Metadata for Version...'}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                      Extracting legal entities, case citations, court details, parties, and dates.
                    </div>
                  </div>
                ) : (() => {
                  const currentMeta = metadataMap[selectedMetaVersion];
                  const status = currentMeta?.status || 'NOT_ANALYZED';

                  if (status === 'NOT_ANALYZED') {
                    return (
                      <div style={{ textAlign: 'center', padding: '1.25rem 1rem', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-xs)', border: '1px dashed #CBD5E1' }}>
                        <div style={{ fontSize: '0.82rem', color: 'var(--ink-secondary)', marginBottom: '0.75rem' }}>
                          No AI metadata has been extracted for <strong>Version {selectedMetaVersion}</strong> yet.
                        </div>
                        {canManageDoc ? (
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            style={{ fontSize: '0.78rem' }}
                            onClick={() => handleExtractMetadata(selectedMetaVersion, false)}
                          >
                            ✨ Extract Legal Metadata
                          </button>
                        ) : (
                          <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)', fontStyle: 'italic' }}>
                            AI metadata extraction must be initiated by the document depositor or vault administrator.
                          </div>
                        )}
                      </div>
                    );
                  }

                  if (status === 'EXTRACTION_UNAVAILABLE') {
                    return (
                      <div style={{ backgroundColor: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                        <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#92400E', marginBottom: '0.25rem' }}>
                          ⚠ TEXT EXTRACTION UNAVAILABLE
                        </div>
                        <div style={{ fontSize: '0.78rem', color: '#78350F', marginBottom: '0.65rem' }}>
                          {currentMeta?.error_message || 'Document contains insufficient extractable text or appears to be a scanned image-only PDF. OCR is not enabled for this vault instance.'}
                        </div>
                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', backgroundColor: '#FFFFFF' }}
                            onClick={() => handleExtractMetadata(selectedMetaVersion, true)}
                          >
                            ↻ Retry Analysis
                          </button>
                        )}
                      </div>
                    );
                  }

                  if (status === 'FAILED') {
                    return (
                      <div style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                        <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#B91C1C', marginBottom: '0.25rem' }}>
                          ⚠ METADATA EXTRACTION FAILED
                        </div>
                        <div style={{ fontSize: '0.78rem', color: '#991B1B', marginBottom: '0.65rem' }}>
                          {currentMeta?.error_message || 'An error occurred while communicating with the AI service.'}
                        </div>
                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', backgroundColor: '#FFFFFF' }}
                            onClick={() => handleExtractMetadata(selectedMetaVersion, true)}
                          >
                            ↻ Retry Extraction
                          </button>
                        )}
                      </div>
                    );
                  }

                  // Status is COMPLETED
                  const conf = currentMeta?.confidence || { overall: 0.0, fields: {} };
                  const confPct = Math.round((conf.overall || 0) * 100);
                  const getConfBadge = (val) => {
                    const pct = Math.round((val || 0) * 100);
                    if (pct >= 85) return { bg: '#ECFDF5', text: '#047857', border: '#A7F3D0', label: `High (${pct}%)` };
                    if (pct >= 60) return { bg: '#FEF3C7', text: '#92400E', border: '#FCD34D', label: `Medium (${pct}%)` };
                    return { bg: '#FEF2F2', text: '#B91C1C', border: '#FECACA', label: `Low (${pct}%)` };
                  };
                  const overallBadge = getConfBadge(conf.overall);

                  return (
                    <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '1rem' }}>
                      {/* Top Grid: Type, Confidence, Case Number, Court */}
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem', marginBottom: '0.85rem' }}>
                        <div>
                          <div className="stat-label">Document Type</div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.15rem' }}>
                            <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--accent-navy)' }}>
                              {currentMeta.document_type || 'Unspecified Legal Document'}
                            </span>
                          </div>
                        </div>

                        <div>
                          <div className="stat-label">AI Extraction Confidence</div>
                          <div style={{ marginTop: '0.15rem' }}>
                            <span className="badge" style={{ backgroundColor: overallBadge.bg, color: overallBadge.text, border: `1px solid ${overallBadge.border}`, fontWeight: 700, fontSize: '0.72rem' }}>
                              ● {overallBadge.label}
                            </span>
                          </div>
                        </div>

                        <div>
                          <div className="stat-label">Identified Case Number</div>
                          <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--ink-primary)', marginTop: '0.15rem', fontFamily: 'var(--font-mono)' }}>
                            {currentMeta.case_number || 'Not Detected in Text'}
                          </div>
                        </div>

                        <div>
                          <div className="stat-label">Court / Forum</div>
                          <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--ink-primary)', marginTop: '0.15rem' }}>
                            {currentMeta.court || 'Not Specified'}
                          </div>
                        </div>

                        <div>
                          <div className="stat-label">Jurisdiction</div>
                          <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--ink-primary)', marginTop: '0.15rem' }}>
                            {currentMeta.jurisdiction || 'Not Specified'}
                          </div>
                        </div>

                        <div>
                          <div className="stat-label">Legal Subject Matter</div>
                          <div style={{ fontSize: '0.82rem', color: 'var(--ink-primary)', marginTop: '0.15rem', lineHeight: 1.35 }}>
                            {currentMeta.subject || 'Not Specified'}
                          </div>
                        </div>
                      </div>

                      {/* Parties Section */}
                      {currentMeta.parties && currentMeta.parties.length > 0 && (
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', marginBottom: '0.75rem' }}>
                          <div className="stat-label" style={{ marginBottom: '0.35rem' }}>
                            Identified Parties ({currentMeta.parties.length})
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                            {currentMeta.parties.map((p, pIdx) => (
                              <div key={pIdx} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem' }}>
                                <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE', fontSize: '0.68rem', fontWeight: 600, padding: '0.1rem 0.4rem' }}>
                                  {p.role || 'Party'}
                                </span>
                                <strong style={{ color: 'var(--ink-primary)' }}>{p.name}</strong>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Important Dates Section */}
                      {currentMeta.dates && currentMeta.dates.length > 0 && (
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', marginBottom: '0.75rem' }}>
                          <div className="stat-label" style={{ marginBottom: '0.35rem' }}>
                            Key Dates Extracted ({currentMeta.dates.length})
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                            {currentMeta.dates.map((d, dIdx) => (
                              <div key={dIdx} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', backgroundColor: '#F8FAFC', border: '1px solid #E2E8F0', padding: '0.2rem 0.55rem', borderRadius: 'var(--radius-xs)', fontSize: '0.75rem' }}>
                                <span style={{ color: 'var(--ink-muted)' }}>{d.description}:</span>
                                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--accent-navy)' }}>{d.date}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Keywords Tags */}
                      {currentMeta.keywords && currentMeta.keywords.length > 0 && (
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', marginBottom: '0.75rem' }}>
                          <div className="stat-label" style={{ marginBottom: '0.35rem' }}>Relevant Keywords</div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                            {currentMeta.keywords.map((kw, kwIdx) => (
                              <span key={kwIdx} className="badge" style={{ backgroundColor: '#F1F5F9', color: '#334155', border: '1px solid #CBD5E1', fontSize: '0.68rem', padding: '0.1rem 0.45rem' }}>
                                #{kw}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Metadata Footer: Provider, Duration, IST Timestamp, Re-analyze Action */}
                      <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)' }}>
                          {currentMeta.ai_provider === 'mock' ? (
                            <span>Provider: <strong>Mock (offline heuristics)</strong></span>
                          ) : (
                            <span>Provider: <strong>Google Gemini</strong> · {currentMeta.ai_model || 'gemini-2.0-flash'}</span>
                          )}
                          {currentMeta.extraction_duration_ms && (
                            <span> · {currentMeta.extraction_duration_ms} ms</span>
                          )}
                          {currentMeta.updated_at && (
                            <span> · {formatDate(currentMeta.updated_at)}</span>
                          )}
                        </div>

                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', padding: '0.2rem 0.55rem' }}
                            onClick={() => handleExtractMetadata(selectedMetaVersion, true)}
                            disabled={extractingMetaVer === selectedMetaVersion}
                            title="Force re-extraction of AI metadata for this revision"
                          >
                            ↻ Re-analyze Version
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })()}
              </div>

              {/* AI-Generated Document Summary Section */}
              <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1', borderRadius: 'var(--radius-sm)', padding: '1.25rem', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className="serif-heading" style={{ fontSize: '1.05rem', color: 'var(--accent-navy)' }}>
                      AI Document Summary
                    </span>
                    <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE', fontWeight: 700, fontSize: '0.72rem' }}>
                      REVISION v{selectedSummaryVersion}
                    </span>
                  </div>

                  {/* Version Picker for Summary */}
                  {versions.length > 1 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontWeight: 600 }}>Inspect Summary:</span>
                      {versions.map((v) => (
                        <button
                          key={v.version_number}
                          type="button"
                          className={`btn btn-sm ${selectedSummaryVersion === v.version_number ? 'btn-primary' : 'btn-secondary'}`}
                          style={{
                            fontSize: '0.68rem',
                            padding: '0.15rem 0.45rem',
                            minWidth: '2rem',
                          }}
                          onClick={() => {
                            setSelectedSummaryVersion(v.version_number);
                            if (!summaryMap[v.version_number]) {
                              loadVersionSummary(v.version_number);
                            }
                          }}
                        >
                          v{v.version_number}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Explicit Disclaimer Notice */}
                <div style={{ fontSize: '0.74rem', color: 'var(--ink-secondary)', backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', padding: '0.45rem 0.65rem', borderRadius: 'var(--radius-xs)', marginBottom: '0.85rem' }}>
                  ℹ <strong>Evidentiary Notice:</strong> AI-generated summary is an analytical overview for rapid docket review. It does <em>not</em> constitute verified legal evidence or official court findings.
                </div>

                {summaryError && (
                  <div className="verdict-banner tampered" style={{ marginBottom: '0.85rem', padding: '0.55rem 0.75rem' }}>
                    <div className="verdict-explanation" style={{ margin: 0, fontSize: '0.78rem' }}>
                      {summaryError}
                    </div>
                  </div>
                )}

                {/* Loading / Generating State */}
                {generatingSummaryVer === selectedSummaryVersion || loadingSummaryVer === selectedSummaryVersion ? (
                  <div style={{ textAlign: 'center', padding: '1.75rem 1rem', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-xs)', border: '1px solid #E2E8F0' }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-navy)', marginBottom: '0.25rem' }}>
                      {generatingSummaryVer === selectedSummaryVersion ? 'Synthesizing Legal Summary with AI Model...' : 'Retrieving Summary for Version...'}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                      Analyzing narrative, key facts, legal issues, and procedural points.
                    </div>
                  </div>
                ) : (() => {
                  const currentSummary = summaryMap[selectedSummaryVersion];
                  const status = currentSummary?.status || 'NOT_GENERATED';

                  if (status === 'NOT_GENERATED') {
                    return (
                      <div style={{ textAlign: 'center', padding: '1.25rem 1rem', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-xs)', border: '1px dashed #CBD5E1' }}>
                        <div style={{ fontSize: '0.82rem', color: 'var(--ink-secondary)', marginBottom: '0.75rem' }}>
                          No AI summary has been generated for <strong>Version {selectedSummaryVersion}</strong> yet.
                        </div>
                        {canManageDoc ? (
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            style={{ fontSize: '0.78rem', padding: '0.35rem 0.85rem' }}
                            onClick={() => handleGenerateSummary(selectedSummaryVersion, false)}
                          >
                            ⚡ Generate AI Summary
                          </button>
                        ) : (
                          <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                            Summary generation can be triggered by the document owner or administrator.
                          </div>
                        )}
                      </div>
                    );
                  }

                  if (status === 'EXTRACTION_UNAVAILABLE') {
                    return (
                      <div style={{ backgroundColor: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                        <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#92400E', marginBottom: '0.25rem' }}>
                          ⚠ TEXT EXTRACTION UNAVAILABLE
                        </div>
                        <div style={{ fontSize: '0.78rem', color: '#78350F', marginBottom: '0.65rem' }}>
                          {currentSummary?.error_message || 'Document contains insufficient extractable text or appears to be a scanned image-only PDF. OCR is not enabled for this vault instance.'}
                        </div>
                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', backgroundColor: '#FFFFFF' }}
                            onClick={() => handleGenerateSummary(selectedSummaryVersion, true)}
                          >
                            ↻ Retry Summarization
                          </button>
                        )}
                      </div>
                    );
                  }

                  if (status === 'EXTRACTION_LIMIT_EXCEEDED') {
                    return (
                      <div style={{ backgroundColor: '#FEF3C7', border: '1px solid #FCD34D', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                        <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#92400E', marginBottom: '0.25rem' }}>
                          ⚠ PROCESSING SIZE LIMIT EXCEEDED
                        </div>
                        <div style={{ fontSize: '0.78rem', color: '#78350F', marginBottom: '0.65rem' }}>
                          {currentSummary?.error_message || 'Document text exceeds maximum AI processing limit of 500,000 characters.'}
                        </div>
                      </div>
                    );
                  }

                  if (status === 'FAILED') {
                    return (
                      <div style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                        <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#B91C1C', marginBottom: '0.25rem' }}>
                          ⚠ SUMMARY GENERATION FAILED
                        </div>
                        <div style={{ fontSize: '0.78rem', color: '#991B1B', marginBottom: '0.65rem' }}>
                          {currentSummary?.error_message || 'An error occurred while communicating with the AI summarization service.'}
                        </div>
                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', backgroundColor: '#FFFFFF' }}
                            onClick={() => handleGenerateSummary(selectedSummaryVersion, true)}
                          >
                            ↻ Retry Summarization
                          </button>
                        )}
                      </div>
                    );
                  }

                  // Status is COMPLETED
                  return (
                    <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '1rem' }}>
                      {/* Narrative Overview */}
                      <div style={{ marginBottom: '0.85rem' }}>
                        <div className="stat-label" style={{ marginBottom: '0.25rem' }}>Overview & Synthesis</div>
                        <p style={{ fontSize: '0.85rem', lineHeight: 1.5, color: 'var(--ink-primary)', margin: 0, fontWeight: 500 }}>
                          {currentSummary.summary || 'Summary narrative not available.'}
                        </p>
                      </div>

                      {/* Key Facts Section */}
                      {currentSummary.key_facts && currentSummary.key_facts.length > 0 && (
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', marginBottom: '0.75rem' }}>
                          <div className="stat-label" style={{ marginBottom: '0.35rem' }}>
                            Key Factual Assertions ({currentSummary.key_facts.length})
                          </div>
                          <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.78rem', color: 'var(--ink-primary)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            {currentSummary.key_facts.map((fact, fIdx) => (
                              <li key={fIdx} style={{ lineHeight: 1.4 }}>{fact}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Legal Issues Section */}
                      {currentSummary.legal_issues && currentSummary.legal_issues.length > 0 && (
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', marginBottom: '0.75rem' }}>
                          <div className="stat-label" style={{ marginBottom: '0.35rem' }}>
                            Legal Claims & Grounds ({currentSummary.legal_issues.length})
                          </div>
                          <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.78rem', color: 'var(--ink-primary)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            {currentSummary.legal_issues.map((issue, iIdx) => (
                              <li key={iIdx} style={{ lineHeight: 1.4 }}>{issue}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Important Points / Relief / Deadlines */}
                      {currentSummary.important_points && currentSummary.important_points.length > 0 && (
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', marginBottom: '0.75rem' }}>
                          <div className="stat-label" style={{ marginBottom: '0.35rem' }}>
                            Important Points, Relief & Deadlines ({currentSummary.important_points.length})
                          </div>
                          <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.78rem', color: 'var(--ink-primary)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                            {currentSummary.important_points.map((pt, pIdx) => (
                              <li key={pIdx} style={{ lineHeight: 1.4 }}>{pt}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Summary Footer: Provider, Duration, IST Timestamp, Re-generate Action */}
                      <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)' }}>
                          {currentSummary.ai_provider === 'mock' ? (
                            <span>Provider: <strong>Mock (offline heuristics)</strong></span>
                          ) : (
                            <span>Provider: <strong>Google Gemini</strong> · {currentSummary.ai_model || 'gemini-2.0-flash'}</span>
                          )}
                          {currentSummary.generation_duration_ms && (
                            <span> · {currentSummary.generation_duration_ms} ms</span>
                          )}
                          {currentSummary.updated_at && (
                            <span> · {formatDate(currentSummary.updated_at)}</span>
                          )}
                        </div>

                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', padding: '0.2rem 0.55rem' }}
                            onClick={() => handleGenerateSummary(selectedSummaryVersion, true)}
                            disabled={generatingSummaryVer === selectedSummaryVersion}
                            title="Force re-generation of AI summary for this revision"
                          >
                            ↻ Re-generate Summary
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })()}
              </div>

              {/* AI Evidence Timeline Section */}
              <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 'var(--radius-sm)', padding: '1.25rem', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                    <span style={{ fontSize: '1rem', color: 'var(--accent-gold)' }}>⏳</span>
                    <span className="serif-heading" style={{ fontSize: '1.05rem', color: 'var(--accent-navy)' }}>
                      AI Evidence Timeline
                    </span>
                    <span className="badge" style={{ backgroundColor: '#F8FAFC', color: 'var(--ink-secondary)', border: '1px solid #CBD5E1', fontSize: '0.7rem' }}>
                      REVISION V{selectedTimelineVersion}
                    </span>
                  </div>

                  {/* Version Selector (if multiple versions exist) */}
                  {versions.length > 1 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)' }}>Timeline Version:</span>
                      {versions.map((v) => (
                        <button
                          key={`tl-v-${v.version_number}`}
                          type="button"
                          onClick={() => {
                            setSelectedTimelineVersion(v.version_number);
                            if (!timelineMap[v.version_number]) {
                              loadVersionTimeline(v.version_number);
                            }
                          }}
                          className={`btn btn-sm ${selectedTimelineVersion === v.version_number ? 'btn-primary' : 'btn-secondary'}`}
                          style={{ fontSize: '0.72rem', padding: '0.15rem 0.5rem' }}
                        >
                          v{v.version_number}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Evidentiary Notice Disclaimer */}
                <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '0.5rem 0.75rem', fontSize: '0.73rem', color: 'var(--ink-secondary)', marginBottom: '1rem' }}>
                  ℹ <strong>Evidentiary Notice:</strong> AI-generated timeline is an informational chronology derived from document text. It does not constitute verified legal evidence or legal advice.
                </div>

                {/* Timeline Error */}
                {timelineError && (
                  <div style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 'var(--radius-xs)', padding: '0.65rem 0.85rem', color: '#991B1B', fontSize: '0.8rem', marginBottom: '1rem' }}>
                    ✕ {timelineError}
                  </div>
                )}

                {/* State Rendering */}
                {(() => {
                  const currentTimeline = timelineMap[selectedTimelineVersion];
                  const isGeneratingThis = generatingTimelineVer === selectedTimelineVersion;
                  const isLoadingThis = loadingTimelineVer === selectedTimelineVersion;

                  if (isGeneratingThis || isLoadingThis) {
                    return (
                      <div style={{ padding: '2rem 1rem', textAlign: 'center' }}>
                        <div className="spinner" style={{ margin: '0 auto 0.75rem' }} />
                        <div style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', fontWeight: 600 }}>
                          {isGeneratingThis ? 'Extracting chronological events...' : `Loading Timeline for Revision v${selectedTimelineVersion}...`}
                        </div>
                      </div>
                    );
                  }

                  if (!currentTimeline || currentTimeline.status === 'NOT_GENERATED') {
                    return (
                      <div style={{ textAlign: 'center', padding: '1.5rem 1rem', backgroundColor: '#F8FAFC', borderRadius: 'var(--radius-xs)', border: '1px dashed #CBD5E1' }}>
                        <p style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)', marginBottom: '1rem' }}>
                          Timeline has not been generated for Revision v{selectedTimelineVersion}.
                        </p>
                        {canManageDoc ? (
                          <button
                            type="button"
                            className="btn btn-primary"
                            style={{ fontSize: '0.82rem' }}
                            onClick={() => handleGenerateTimeline(selectedTimelineVersion, false)}
                          >
                            ⚡ Generate Evidence Timeline
                          </button>
                        ) : (
                          <span style={{ fontSize: '0.78rem', color: 'var(--ink-muted)' }}>
                            Only the document owner or an administrator can generate the AI timeline.
                          </span>
                        )}
                      </div>
                    );
                  }

                  if (currentTimeline.status === 'EXTRACTION_UNAVAILABLE') {
                    return (
                      <div style={{ textAlign: 'center', padding: '1.25rem', backgroundColor: '#FFFBEB', borderRadius: 'var(--radius-xs)', border: '1px solid #FDE68A' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#92400E', marginBottom: '0.35rem' }}>
                          Text Extraction Unavailable
                        </div>
                        <p style={{ fontSize: '0.78rem', color: '#B45309', margin: 0 }}>
                          {currentTimeline.error_message || 'Could not extract text from this revision file.'}
                        </p>
                      </div>
                    );
                  }

                  if (currentTimeline.status === 'EXTRACTION_LIMIT_EXCEEDED') {
                    return (
                      <div style={{ textAlign: 'center', padding: '1.25rem', backgroundColor: '#FEF2F2', borderRadius: 'var(--radius-xs)', border: '1px solid #FECACA' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#991B1B', marginBottom: '0.35rem' }}>
                          AI Processing Limit Exceeded
                        </div>
                        <p style={{ fontSize: '0.78rem', color: '#B91C1C', margin: 0 }}>
                          {currentTimeline.error_message || 'Document text exceeds maximum AI processing limits.'}
                        </p>
                      </div>
                    );
                  }

                  if (currentTimeline.status === 'FAILED') {
                    return (
                      <div style={{ textAlign: 'center', padding: '1.25rem', backgroundColor: '#FEF2F2', borderRadius: 'var(--radius-xs)', border: '1px solid #FECACA' }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#991B1B', marginBottom: '0.35rem' }}>
                          Timeline Generation Failed
                        </div>
                        <p style={{ fontSize: '0.78rem', color: '#B91C1C', marginBottom: '0.85rem' }}>
                          {currentTimeline.error_message || 'Unexpected failure during timeline extraction.'}
                        </p>
                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleGenerateTimeline(selectedTimelineVersion, true)}
                          >
                            ↻ Retry Timeline Generation
                          </button>
                        )}
                      </div>
                    );
                  }

                  // COMPLETED
                  const events = currentTimeline.events || [];
                  if (events.length === 0) {
                    return (
                      <div>
                        <div style={{ textAlign: 'center', padding: '1.5rem 1rem', backgroundColor: '#F8FAFC', borderRadius: 'var(--radius-xs)', border: '1px solid #E2E8F0', marginBottom: '0.75rem' }}>
                          <span style={{ fontSize: '0.85rem', color: 'var(--ink-secondary)' }}>
                            No dated events were explicitly identified in this revision.
                          </span>
                        </div>
                        {/* Footer */}
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                          <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)' }}>
                            {currentTimeline.ai_provider === 'mock' ? (
                              <span>Provider: <strong>Mock (offline heuristics)</strong></span>
                            ) : (
                              <span>Provider: <strong>Google Gemini</strong> · {currentTimeline.ai_model || 'gemini-2.0-flash'}</span>
                            )}
                            {currentTimeline.extraction_duration_ms !== null && currentTimeline.extraction_duration_ms !== undefined && (
                              <span> · {currentTimeline.extraction_duration_ms} ms</span>
                            )}
                            {currentTimeline.updated_at && (
                              <span> · {formatDate(currentTimeline.updated_at)}</span>
                            )}
                          </div>
                          {canManageDoc && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ fontSize: '0.72rem', padding: '0.2rem 0.55rem' }}
                              onClick={() => handleGenerateTimeline(selectedTimelineVersion, true)}
                            >
                              ↻ Re-generate Timeline
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  }

                  // Vertical timeline
                  const getEventTypeBadgeStyle = (type) => {
                    switch (type) {
                      case 'HEARING':
                        return { backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' };
                      case 'FILING':
                        return { backgroundColor: '#EFF6FF', color: '#1D4ED8', border: '1px solid #BFDBFE' };
                      case 'AGREEMENT':
                      case 'EXECUTION':
                        return { backgroundColor: '#ECFDF5', color: '#047857', border: '1px solid #A7F3D0' };
                      case 'ORDER':
                        return { backgroundColor: '#F3E8FF', color: '#7E22CE', border: '1px solid #E9D5FF' };
                      case 'NOTICE':
                        return { backgroundColor: '#FFF7ED', color: '#C2410C', border: '1px solid #FED7AA' };
                      case 'AMENDMENT':
                        return { backgroundColor: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE' };
                      case 'DEADLINE':
                        return { backgroundColor: '#FEE2E2', color: '#B91C1C', border: '1px solid #FECACA' };
                      case 'PAYMENT':
                        return { backgroundColor: '#D1FAE5', color: '#065F46', border: '1px solid #A7F3D0' };
                      case 'TRANSFER':
                        return { backgroundColor: '#CCFBF1', color: '#115E59', border: '1px solid #99F6E4' };
                      default:
                        return { backgroundColor: '#F1F5F9', color: '#475569', border: '1px solid #CBD5E1' };
                    }
                  };

                  return (
                    <div>
                      <div style={{ position: 'relative', paddingLeft: '1.5rem', marginBottom: '1.25rem' }}>
                        {/* Continuous vertical line */}
                        <div
                          style={{
                            position: 'absolute',
                            left: '0.45rem',
                            top: '0.75rem',
                            bottom: '0.75rem',
                            width: '2px',
                            backgroundColor: '#CBD5E1',
                          }}
                        />

                        {events.map((ev, idx) => (
                          <div
                            key={`event-${idx}`}
                            style={{
                              position: 'relative',
                              marginBottom: idx === events.length - 1 ? '0' : '1.25rem',
                            }}
                          >
                            {/* Timeline node marker */}
                            <div
                              style={{
                                position: 'absolute',
                                left: '-1.35rem',
                                top: '0.25rem',
                                width: '10px',
                                height: '10px',
                                borderRadius: '50%',
                                backgroundColor: 'var(--accent-navy)',
                                border: '2px solid #FFFFFF',
                                boxShadow: '0 0 0 1px #CBD5E1',
                              }}
                            />

                            <div
                              style={{
                                backgroundColor: '#F8FAFC',
                                border: '1px solid #E2E8F0',
                                borderRadius: 'var(--radius-xs)',
                                padding: '0.65rem 0.85rem',
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem', flexWrap: 'wrap', gap: '0.35rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                                  <span style={{ fontWeight: 700, fontSize: '0.82rem', color: 'var(--accent-navy)', letterSpacing: '0.02em' }}>
                                    {ev.date_raw || ev.date}
                                  </span>
                                  {ev.date && ev.date !== ev.date_raw && (
                                    <span style={{ fontSize: '0.68rem', color: 'var(--ink-muted)' }}>
                                      ({ev.date})
                                    </span>
                                  )}
                                </div>
                                <span
                                  className="badge"
                                  style={{
                                    ...getEventTypeBadgeStyle(ev.event_type),
                                    fontWeight: 700,
                                    fontSize: '0.68rem',
                                    padding: '0.15rem 0.45rem',
                                  }}
                                >
                                  {ev.event_type}
                                </span>
                              </div>

                              <p style={{ fontSize: '0.78rem', color: 'var(--ink-primary)', margin: '0 0 0.35rem 0', lineHeight: 1.45 }}>
                                {ev.description}
                              </p>

                              {ev.source_reference && (
                                <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)', fontStyle: 'italic', borderTop: '1px dashed #E2E8F0', paddingTop: '0.3rem', marginTop: '0.3rem' }}>
                                  Source: &ldquo;{ev.source_reference}&rdquo;
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>

                      {/* Timeline Footer */}
                      <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                        <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)' }}>
                          {currentTimeline.ai_provider === 'mock' ? (
                            <span>Provider: <strong>Mock (offline heuristics)</strong></span>
                          ) : (
                            <span>Provider: <strong>Google Gemini</strong> · {currentTimeline.ai_model || 'gemini-2.0-flash'}</span>
                          )}
                          {currentTimeline.extraction_duration_ms !== null && currentTimeline.extraction_duration_ms !== undefined && (
                            <span> · {currentTimeline.extraction_duration_ms} ms</span>
                          )}
                          {currentTimeline.updated_at && (
                            <span> · {formatDate(currentTimeline.updated_at)}</span>
                          )}
                        </div>

                        {canManageDoc && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ fontSize: '0.72rem', padding: '0.2rem 0.55rem' }}
                            onClick={() => handleGenerateTimeline(selectedTimelineVersion, true)}
                            disabled={generatingTimelineVer === selectedTimelineVersion}
                            title="Force re-generation of AI timeline"
                          >
                            ↻ Re-generate Timeline
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })()}
              </div>

              {/* AI Version Comparison Section (Displayed when at least 2 versions exist) */}
              {versions.length >= 2 && (
                <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1', borderRadius: 'var(--radius-sm)', padding: '1.25rem', marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="serif-heading" style={{ fontSize: '1.05rem', color: 'var(--accent-navy)' }}>
                        AI Version Comparison
                      </span>
                      <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE', fontWeight: 700, fontSize: '0.72rem' }}>
                        v{fromCompareVer} → v{toCompareVer}
                      </span>
                    </div>

                    {/* From/To Selectors & Swap Control */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontWeight: 600 }}>From:</span>
                      <select
                        value={fromCompareVer}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          setFromCompareVer(val);
                          const k = `${val}->${toCompareVer}`;
                          if (!comparisonMap[k]) {
                            loadVersionComparison(val, toCompareVer);
                          }
                        }}
                        style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', borderRadius: 'var(--radius-xs)', border: '1px solid var(--border-color)', backgroundColor: '#FFFFFF' }}
                      >
                        {versions.map((v) => (
                          <option key={v.version_number} value={v.version_number}>
                            v{v.version_number}
                          </option>
                        ))}
                      </select>

                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: '0.8rem', padding: '0.15rem 0.4rem' }}
                        title="Swap comparison direction"
                        onClick={() => {
                          const prevFrom = fromCompareVer;
                          const prevTo = toCompareVer;
                          setFromCompareVer(prevTo);
                          setToCompareVer(prevFrom);
                          const k = `${prevTo}->${prevFrom}`;
                          if (!comparisonMap[k]) {
                            loadVersionComparison(prevTo, prevFrom);
                          }
                        }}
                      >
                        ⇄
                      </button>

                      <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontWeight: 600 }}>To:</span>
                      <select
                        value={toCompareVer}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10);
                          setToCompareVer(val);
                          const k = `${fromCompareVer}->${val}`;
                          if (!comparisonMap[k]) {
                            loadVersionComparison(fromCompareVer, val);
                          }
                        }}
                        style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', borderRadius: 'var(--radius-xs)', border: '1px solid var(--border-color)', backgroundColor: '#FFFFFF' }}
                      >
                        {versions.map((v) => (
                          <option key={v.version_number} value={v.version_number}>
                            v{v.version_number}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Explicit Disclaimer Notice */}
                  <div style={{ fontSize: '0.74rem', color: 'var(--ink-secondary)', backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', padding: '0.45rem 0.65rem', borderRadius: 'var(--radius-xs)', marginBottom: '0.85rem' }}>
                    ℹ <strong>Evidentiary Notice:</strong> AI version comparison is an analytical tool identifying textual and structural shifts. It does <em>not</em> evaluate legal validity or determine party merits.
                  </div>

                  {comparisonError && (
                    <div className="verdict-banner tampered" style={{ marginBottom: '0.85rem', padding: '0.55rem 0.75rem' }}>
                      <div className="verdict-explanation" style={{ margin: 0, fontSize: '0.78rem' }}>
                        {comparisonError}
                      </div>
                    </div>
                  )}

                  {/* Loading / Comparing State */}
                  {runningComparisonKey === `${fromCompareVer}->${toCompareVer}` || loadingComparisonKey === `${fromCompareVer}->${toCompareVer}` ? (
                    <div style={{ textAlign: 'center', padding: '1.75rem 1rem', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-xs)', border: '1px solid #E2E8F0' }}>
                      <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-navy)', marginBottom: '0.25rem' }}>
                        {runningComparisonKey === `${fromCompareVer}->${toCompareVer}` ? 'Comparing Revisions with AI Engine...' : 'Retrieving Comparison for Versions...'}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
                        Evaluating metadata deltas, added/removed parties, modified dates, and factual/legal shifts.
                      </div>
                    </div>
                  ) : (() => {
                    const currentCompKey = `${fromCompareVer}->${toCompareVer}`;
                    const currentComp = comparisonMap[currentCompKey];
                    const compStatus = currentComp?.status || 'NOT_GENERATED';

                    if (compStatus === 'NOT_GENERATED') {
                      return (
                        <div style={{ textAlign: 'center', padding: '1.5rem 1rem', backgroundColor: '#FFFFFF', borderRadius: 'var(--radius-xs)', border: '1px dashed #CBD5E1' }}>
                          <div style={{ fontSize: '0.82rem', color: 'var(--ink-secondary)', marginBottom: '0.75rem' }}>
                            Comparison between <strong>Version {fromCompareVer}</strong> and <strong>Version {toCompareVer}</strong> has not been generated yet.
                          </div>
                          {canManageDoc ? (
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              style={{ fontSize: '0.8rem' }}
                              onClick={() => handleRunComparison(fromCompareVer, toCompareVer, false)}
                            >
                              ⚡ Compare Version {fromCompareVer} → Version {toCompareVer}
                            </button>
                          ) : (
                            <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)', fontStyle: 'italic' }}>
                              Version comparison must be initiated by the document depositor or vault administrator.
                            </div>
                          )}
                        </div>
                      );
                    }

                    if (compStatus === 'FAILED') {
                      return (
                        <div style={{ backgroundColor: '#FEF2F2', border: '1px solid #F87171', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                          <div style={{ fontWeight: 700, fontSize: '0.82rem', color: '#991B1B', marginBottom: '0.25rem' }}>
                            Comparison Generation Failed
                          </div>
                          <div style={{ fontSize: '0.75rem', color: '#7F1D1D', marginBottom: '0.65rem' }}>
                            {currentComp.error_message || 'An unexpected error occurred while analyzing differences.'}
                          </div>
                          {canManageDoc && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ fontSize: '0.75rem' }}
                              onClick={() => handleRunComparison(fromCompareVer, toCompareVer, true)}
                            >
                              ↻ Retry Comparison
                            </button>
                          )}
                        </div>
                      );
                    }

                    const metaChanges = currentComp.metadata_changes || { added: [], removed: [], changed: [] };
                    const sumChanges = currentComp.summary_changes || {};

                    const factsAdded = sumChanges.facts_added || [];
                    const factsRemoved = sumChanges.facts_removed || [];
                    const procAdded = (sumChanges.procedural_added?.length > 0 ? sumChanges.procedural_added : (sumChanges.important_points_added || []));
                    const procRemoved = (sumChanges.procedural_removed?.length > 0 ? sumChanges.procedural_removed : (sumChanges.important_points_removed || []));
                    const legalAdded = sumChanges.legal_issues_added || [];
                    const legalRemoved = sumChanges.legal_issues_removed || [];

                    // Party changes
                    const partyAdded = (metaChanges.added || []).filter(item => item.field === 'party');
                    const partyRemoved = (metaChanges.removed || []).filter(item => item.field === 'party');
                    const partyChanged = (metaChanges.changed || []).filter(item => item.field === 'party_role');

                    // Date / Event changes
                    const dateAdded = (metaChanges.added || []).filter(item => item.field === 'date');
                    const dateRemoved = (metaChanges.removed || []).filter(item => item.field === 'date');
                    const dateChanged = (metaChanges.changed || []).filter(item => item.field === 'date' || item.field === 'date_role');

                    // Technical / Scalar Metadata & Keywords (Optional / Collapsed)
                    const keywordAdded = (metaChanges.added || []).filter(item => item.field === 'keyword');
                    const keywordRemoved = (metaChanges.removed || []).filter(item => item.field === 'keyword');
                    const scalarChanged = (metaChanges.changed || []).filter(item => item.field !== 'date' && item.field !== 'date_role' && item.field !== 'party_role');
                    const scalarAdded = (metaChanges.added || []).filter(item => item.field !== 'party' && item.field !== 'date' && item.field !== 'keyword');
                    const scalarRemoved = (metaChanges.removed || []).filter(item => item.field !== 'party' && item.field !== 'date' && item.field !== 'keyword');
                    const totalTechDeltas = keywordAdded.length + keywordRemoved.length + scalarChanged.length + scalarAdded.length + scalarRemoved.length;
                    const newInLabel = `NEW IN V${toCompareVer}`;
                    const presentOnlyLabel = `PRESENT IN V${fromCompareVer} ONLY`;

                    return (
                      <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {/* Explicit Direction Header & Explanatory Banner */}
                        <div style={{ backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1', borderRadius: 'var(--radius-xs)', padding: '0.75rem 1rem' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.35rem' }}>
                            <div style={{ fontSize: '0.84rem', fontWeight: 800, color: 'var(--ink-primary)' }}>
                              Comparing Version {fromCompareVer} → Version {toCompareVer}
                            </div>
                            <span style={{ fontSize: '0.68rem', fontWeight: 700, color: '#475569', backgroundColor: '#E2E8F0', padding: '0.15rem 0.5rem', borderRadius: '10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                              Directional Revision Analysis
                            </span>
                          </div>
                          <div style={{ fontSize: '0.73rem', color: 'var(--ink-secondary)', lineHeight: 1.5 }}>
                            Comparison is directional. <strong>'New in V{toCompareVer}'</strong> means the information appears in V{toCompareVer} but not V{fromCompareVer}. <strong>'Present in V{fromCompareVer} only'</strong> means it appears in V{fromCompareVer} but not V{toCompareVer}. Modified values show how the same field or event changed between revisions.
                          </div>
                        </div>

                        {/* 1. SUMMARY OF MATERIAL CHANGES */}
                        <div style={{ backgroundColor: '#F8FAFC', borderLeft: '4px solid #4338CA', padding: '0.85rem 1rem', borderRadius: '0 var(--radius-xs) var(--radius-xs) 0' }}>
                          <div style={{ fontSize: '0.74rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#4338CA', marginBottom: '0.35rem' }}>
                            1. Summary of Material Changes (v{fromCompareVer} → v{toCompareVer})
                          </div>
                          <div style={{ fontSize: '0.82rem', color: 'var(--ink-primary)', lineHeight: 1.6 }}>
                            {currentComp.material_changes || 'No material differences detected between the selected versions.'}
                          </div>
                        </div>

                        {/* 2. FACTUAL / EVIDENTIARY DEVELOPMENTS (High Emphasis) */}
                        {(factsAdded.length > 0 || factsRemoved.length > 0) && (
                          <div style={{ border: '1px solid #CBD5E1', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                            <div style={{ fontSize: '0.76rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--ink-primary)', marginBottom: '0.2rem' }}>
                              2. Factual / Evidentiary Developments
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', marginBottom: '0.65rem' }}>
                              Concrete factual assertions, observations, and evidence-related statements
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                              {factsAdded.map((f, idx) => (
                                <div key={`fa-${idx}`} style={{ backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.78rem', color: '#047857', display: 'flex', flexDirection: 'column', gap: '0.2rem', lineHeight: 1.5 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem', color: '#047857' }}>🟢 {newInLabel}</span>
                                  </div>
                                  <div style={{ color: '#065F46', fontSize: '0.78rem' }}>{f}</div>
                                </div>
                              ))}
                              {factsRemoved.map((f, idx) => (
                                <div key={`fr-${idx}`} style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.78rem', color: '#B91C1C', display: 'flex', flexDirection: 'column', gap: '0.2rem', lineHeight: 1.5 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem', color: '#B91C1C' }}>🔴 {presentOnlyLabel}</span>
                                  </div>
                                  <div style={{ color: '#991B1B', fontSize: '0.78rem' }}>{f}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 3. PROCEDURAL DEVELOPMENTS (High Emphasis) */}
                        {(procAdded.length > 0 || procRemoved.length > 0) && (
                          <div style={{ border: '1px solid #CBD5E1', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                            <div style={{ fontSize: '0.76rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--ink-primary)', marginBottom: '0.2rem' }}>
                              3. Procedural Developments
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', marginBottom: '0.65rem' }}>
                              Investigative progress, witness questioning, court hearings, filings, and procedural actions
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                              {procAdded.map((p, idx) => (
                                <div key={`pa-${idx}`} style={{ backgroundColor: '#F0FDF4', border: '1px solid #BBF7D0', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.78rem', color: '#15803D', display: 'flex', flexDirection: 'column', gap: '0.2rem', lineHeight: 1.5 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem', color: '#15803D' }}>🟢 {newInLabel}</span>
                                  </div>
                                  <div style={{ color: '#166534', fontSize: '0.78rem' }}>{p}</div>
                                </div>
                              ))}
                              {procRemoved.map((p, idx) => (
                                <div key={`pr-${idx}`} style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.78rem', color: '#B91C1C', display: 'flex', flexDirection: 'column', gap: '0.2rem', lineHeight: 1.5 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem', color: '#B91C1C' }}>🔴 {presentOnlyLabel}</span>
                                  </div>
                                  <div style={{ color: '#991B1B', fontSize: '0.78rem' }}>{p}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 4. PARTY / ENTITY CHANGES */}
                        {(partyAdded.length > 0 || partyRemoved.length > 0 || partyChanged.length > 0) && (
                          <div style={{ border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                            <div style={{ fontSize: '0.74rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--ink-secondary)', marginBottom: '0.2rem' }}>
                              4. Party / Entity Changes
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', marginBottom: '0.65rem' }}>
                              Litigants, witnesses, authorities, and role designations
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                              {partyChanged.map((item, idx) => (
                                <div key={`pc-${idx}`} style={{ backgroundColor: '#EFF6FF', border: '1px solid #BFDBFE', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.25rem' }}>
                                    <span style={{ fontWeight: 700, color: '#1D4ED8', fontSize: '0.72rem' }}>↔ MODIFIED PARTY ROLE:</span>
                                    <span style={{ fontWeight: 700, color: '#1E40AF', fontSize: '0.8rem' }}>{item.field_name || 'Party'}</span>
                                  </div>
                                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.2rem 0.6rem', fontSize: '0.76rem', paddingLeft: '0.5rem', borderLeft: '2.5px solid #93C5FD' }}>
                                    <span style={{ color: 'var(--ink-muted)', fontWeight: 600 }}>v{fromCompareVer}:</span>
                                    <span style={{ color: 'var(--ink-primary)' }}>{item.from || 'Not Specified'}</span>
                                    <span style={{ color: 'var(--ink-muted)', fontWeight: 600 }}>v{toCompareVer}:</span>
                                    <span style={{ color: '#1E40AF', fontWeight: 700 }}>{item.to || 'Not Specified'}</span>
                                  </div>
                                </div>
                              ))}
                              {partyAdded.map((item, idx) => (
                                <div key={`pa-${idx}`} style={{ backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', padding: '0.45rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.76rem', color: '#047857' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem' }}>🟢 {newInLabel}:</span>
                                    <span style={{ fontWeight: 700, color: '#065F46' }}>{item.value || item.description}</span>
                                  </div>
                                </div>
                              ))}
                              {partyRemoved.map((item, idx) => (
                                <div key={`pr-${idx}`} style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '0.45rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.76rem', color: '#B91C1C' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem' }}>🔴 {presentOnlyLabel}:</span>
                                    <span style={{ fontWeight: 700, color: '#991B1B' }}>{item.value || item.description}</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 5. DATE / EVENT CHANGES */}
                        {(dateAdded.length > 0 || dateRemoved.length > 0 || dateChanged.length > 0) && (
                          <div style={{ border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                            <div style={{ fontSize: '0.74rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--ink-secondary)', marginBottom: '0.2rem' }}>
                              5. Date / Event Changes
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', marginBottom: '0.65rem' }}>
                              Hearing dates, filing deadlines, agreements, and chronological milestones
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                              {dateChanged.map((item, idx) => {
                                const dateLabel = item.field_name || 'Event Date';
                                return (
                                  <div key={`dc-${idx}`} style={{ backgroundColor: '#EFF6FF', border: '1px solid #BFDBFE', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.25rem' }}>
                                      <span style={{ fontWeight: 700, color: '#1D4ED8', fontSize: '0.72rem' }}>↔ MODIFIED EVENT DATE:</span>
                                      <span style={{ fontWeight: 700, color: '#1E40AF', fontSize: '0.8rem' }}>{dateLabel}</span>
                                    </div>
                                    <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.2rem 0.6rem', fontSize: '0.76rem', paddingLeft: '0.5rem', borderLeft: '2.5px solid #93C5FD' }}>
                                      <span style={{ color: 'var(--ink-muted)', fontWeight: 600 }}>v{fromCompareVer}:</span>
                                      <span style={{ color: 'var(--ink-primary)' }}>{item.from || 'Not Specified'}</span>
                                      <span style={{ color: 'var(--ink-muted)', fontWeight: 600 }}>v{toCompareVer}:</span>
                                      <span style={{ color: '#1E40AF', fontWeight: 700 }}>{item.to || 'Not Specified'}</span>
                                    </div>
                                  </div>
                                );
                              })}
                              {dateAdded.map((item, idx) => (
                                <div key={`da-${idx}`} style={{ backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', padding: '0.45rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.76rem', color: '#047857' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem' }}>🟢 {newInLabel}:</span>
                                    <span style={{ fontWeight: 700, color: '#065F46' }}>{item.value || item.description}</span>
                                  </div>
                                </div>
                              ))}
                              {dateRemoved.map((item, idx) => (
                                <div key={`dr-${idx}`} style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '0.45rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.76rem', color: '#B91C1C' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem' }}>🔴 {presentOnlyLabel}:</span>
                                    <span style={{ fontWeight: 700, color: '#991B1B' }}>{item.value || item.description}</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* 6. LEGAL CLAIMS & GROUNDS */}
                        <div style={{ border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem' }}>
                          <div style={{ fontSize: '0.74rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--ink-secondary)', marginBottom: '0.2rem' }}>
                            6. Legal Claims & Grounds
                          </div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', marginBottom: '0.65rem' }}>
                            Explicit statutory claims, disputed legal issues, and requested remedies
                          </div>
                          {legalAdded.length > 0 || legalRemoved.length > 0 ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                              {legalAdded.map((l, idx) => (
                                <div key={`la-${idx}`} style={{ backgroundColor: '#FAF5FF', border: '1px solid #E9D5FF', padding: '0.45rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.76rem', color: '#7E22CE', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem', color: '#7E22CE' }}>🟢 {newInLabel}</span>
                                  </div>
                                  <div style={{ color: '#6B21A8', fontSize: '0.76rem' }}>{l}</div>
                                </div>
                              ))}
                              {legalRemoved.map((l, idx) => (
                                <div key={`lr-${idx}`} style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '0.45rem 0.75rem', borderRadius: 'var(--radius-xs)', fontSize: '0.76rem', color: '#B91C1C', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <span style={{ fontWeight: 800, fontSize: '0.7rem', color: '#B91C1C' }}>🔴 {presentOnlyLabel}</span>
                                  </div>
                                  <div style={{ color: '#991B1B', fontSize: '0.76rem' }}>{l}</div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)', fontStyle: 'italic', backgroundColor: '#F8FAFC', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)' }}>
                              No explicit legal claims or grounds were identified in either revision.
                            </div>
                          )}
                        </div>

                        {/* 7. TECHNICAL METADATA (Optional / Collapsed) */}
                        <details style={{ border: '1px solid #E2E8F0', borderRadius: 'var(--radius-xs)', padding: '0.65rem 0.85rem', backgroundColor: '#F8FAFC' }}>
                          <summary style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--ink-secondary)', cursor: 'pointer', userSelect: 'none' }}>
                            7. Technical Metadata & Indexing Changes {totalTechDeltas > 0 ? `(${totalTechDeltas} items)` : '(None)'}
                          </summary>
                          <div style={{ marginTop: '0.65rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                            {scalarChanged.map((item, idx) => {
                              const fieldLabel = item.field_name || (item.field ? item.field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Field');
                              return (
                                <div key={`sc-${idx}`} style={{ backgroundColor: '#EFF6FF', border: '1px solid #BFDBFE', padding: '0.45rem 0.7rem', borderRadius: 'var(--radius-xs)' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.2rem' }}>
                                    <span style={{ fontWeight: 700, color: '#1D4ED8', fontSize: '0.7rem' }}>↔ MODIFIED:</span>
                                    <span style={{ fontWeight: 700, color: '#1E40AF', fontSize: '0.76rem' }}>{fieldLabel}</span>
                                  </div>
                                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.15rem 0.5rem', fontSize: '0.72rem', paddingLeft: '0.5rem', borderLeft: '2px solid #93C5FD' }}>
                                    <span style={{ color: 'var(--ink-muted)', fontWeight: 600 }}>v{fromCompareVer}:</span>
                                    <span style={{ color: 'var(--ink-primary)' }}>{item.from || 'Not Specified'}</span>
                                    <span style={{ color: 'var(--ink-muted)', fontWeight: 600 }}>v{toCompareVer}:</span>
                                    <span style={{ color: '#1E40AF', fontWeight: 700 }}>{item.to || 'Not Specified'}</span>
                                  </div>
                                </div>
                              );
                            })}
                            {scalarAdded.map((item, idx) => {
                              const fieldLabel = item.field_name || (item.field ? item.field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Field');
                              return (
                                <div key={`sa-${idx}`} style={{ backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', padding: '0.4rem 0.65rem', borderRadius: 'var(--radius-xs)', fontSize: '0.74rem', color: '#047857' }}>
                                  <span style={{ fontWeight: 700 }}>+ ADDED: </span>{fieldLabel}: {item.value || item.description}
                                </div>
                              );
                            })}
                            {scalarRemoved.map((item, idx) => {
                              const fieldLabel = item.field_name || (item.field ? item.field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Field');
                              return (
                                <div key={`sr-${idx}`} style={{ backgroundColor: '#FEF2F2', border: '1px solid #FECACA', padding: '0.4rem 0.65rem', borderRadius: 'var(--radius-xs)', fontSize: '0.74rem', color: '#B91C1C' }}>
                                  <span style={{ fontWeight: 700 }}>− REMOVED: </span>{fieldLabel}: {item.value || item.description}
                                </div>
                              );
                            })}
                            {keywordAdded.length > 0 && (
                              <div style={{ fontSize: '0.73rem', color: '#047857' }}>
                                <strong>Added Keywords:</strong> {keywordAdded.map(k => k.value).join(', ')}
                              </div>
                            )}
                            {keywordRemoved.length > 0 && (
                              <div style={{ fontSize: '0.73rem', color: '#B91C1C' }}>
                                <strong>Removed Keywords:</strong> {keywordRemoved.map(k => k.value).join(', ')}
                              </div>
                            )}
                            {totalTechDeltas === 0 && (
                              <div style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontStyle: 'italic' }}>
                                No technical metadata or indexing keyword changes between revisions.
                              </div>
                            )}
                          </div>
                        </details>

                        {/* Comparison Footer */}
                        <div style={{ borderTop: '1px solid #F1F5F9', paddingTop: '0.65rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
                          <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)' }}>
                            {currentComp.ai_provider === 'mock' || currentComp.ai_provider === 'deterministic' ? (
                              <span>Provider: <strong>Mock (offline heuristics)</strong></span>
                            ) : (
                              <span>Provider: <strong>Google Gemini</strong> · {currentComp.ai_model || 'gemini-2.0-flash'}</span>
                            )}
                            {currentComp.comparison_duration_ms !== null && currentComp.comparison_duration_ms !== undefined && (
                              <span> · {currentComp.comparison_duration_ms} ms</span>
                            )}
                            {currentComp.updated_at && (
                              <span> · {formatDate(currentComp.updated_at)}</span>
                            )}
                          </div>

                          {canManageDoc && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ fontSize: '0.72rem', padding: '0.2rem 0.55rem' }}
                              onClick={() => handleRunComparison(fromCompareVer, toCompareVer, true)}
                              disabled={runningComparisonKey === currentCompKey}
                              title="Force re-generation of AI comparison between these revisions"
                            >
                              ↻ Re-run Comparison
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}

              {/* Revision Upload Form Modal Overlay */}
              {isUploadRevisionOpen && (
                <div
                  ref={revisionSectionRef}
                  style={{ backgroundColor: '#F8FAFC', border: '1px solid #CBD5E1', borderRadius: 'var(--radius-sm)', padding: '1.25rem', marginBottom: '1.5rem' }}
                >
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
                                style={{
                                  fontSize: '0.72rem',
                                  padding: '0.2rem 0.5rem',
                                  backgroundColor: selectedMetaVersion === v.version_number ? '#EEF2FF' : 'transparent',
                                  color: selectedMetaVersion === v.version_number ? '#4338CA' : 'var(--ink-secondary)',
                                  borderColor: selectedMetaVersion === v.version_number ? '#C7D2FE' : 'var(--border-color)',
                                }}
                                onClick={() => {
                                  setSelectedMetaVersion(v.version_number);
                                  if (!metadataMap[v.version_number]) {
                                    loadVersionMetadata(v.version_number);
                                  }
                                }}
                                title="Inspect AI-extracted metadata for this revision"
                              >
                                🤖 AI Metadata
                              </button>

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
                                <span className="badge" style={{ backgroundColor: '#F1F5F9', color: '#64748B', border: '1px solid #CBD5E1', fontWeight: 600, fontSize: '0.68rem', padding: '0.05rem 0.4rem' }}>
                                  ⚠ NOT VERIFIED
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

              {/* Forensic Audit Trail & Chain of Custody Section */}
              <div className="audit-trail-section">
                <div className="audit-trail-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div className="serif-heading" style={{ fontSize: '0.98rem' }}>
                      Forensic Audit Trail &amp; Chain of Custody
                    </div>
                    <span className="badge" style={{ fontSize: '0.7rem', backgroundColor: 'var(--bg-subtle)', color: 'var(--ink-secondary)' }}>
                      {auditTotal} event{auditTotal === 1 ? '' : 's'}
                    </span>
                  </div>

                  <div className="audit-trail-controls">
                    {/* Action Filter */}
                    <select
                      value={auditActionFilter}
                      onChange={(e) => {
                        const val = e.target.value;
                        setAuditActionFilter(val);
                        loadAuditTrail(val, auditVersionFilter);
                      }}
                      className="audit-filter-select"
                    >
                      <option value="">All Actions</option>
                      <option value="DOCUMENT_CREATED">Created</option>
                      <option value="VERSION_CREATED">Revision Created</option>
                      <option value="DOCUMENT_VERIFIED">Verified</option>
                      <option value="VERSION_VERIFIED">Version Verified</option>
                      <option value="DOCUMENT_TAMPERED">Tamper Detected</option>
                      <option value="DOCUMENT_SHARED">Shared</option>
                      <option value="DOCUMENT_SHARE_REVOKED">Share Revoked</option>
                      <option value="DOCUMENT_DOWNLOADED">Downloaded</option>
                      <option value="DOCUMENT_VIEWED">Viewed</option>
                      <option value="AI_METADATA_EXTRACTED">AI Metadata Extracted</option>
                      <option value="AI_METADATA_EXTRACTION_FAILED">AI Extraction Failed</option>
                      <option value="ACCESS_DENIED">Access Denied</option>
                    </select>

                    {/* Version Filter */}
                    <select
                      value={auditVersionFilter}
                      onChange={(e) => {
                        const val = e.target.value;
                        setAuditVersionFilter(val);
                        loadAuditTrail(auditActionFilter, val);
                      }}
                      className="audit-filter-select"
                    >
                      <option value="">All Versions</option>
                      {versions.map((v) => (
                        <option key={v.version_number} value={v.version_number}>
                          v{v.version_number}
                        </option>
                      ))}
                    </select>

                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ fontSize: '0.72rem', padding: '0.2rem 0.5rem' }}
                      onClick={() => loadAuditTrail(auditActionFilter, auditVersionFilter)}
                      disabled={auditLoading}
                      title="Refresh audit events"
                    >
                      {auditLoading ? '...' : '↻'}
                    </button>
                  </div>
                </div>

                {auditLoading && (
                  <div className="audit-loading-indicator">
                    <span style={{ fontSize: '0.78rem', color: 'var(--ink-muted)' }}>Updating audit records...</span>
                  </div>
                )}

                {auditError && (
                  <div style={{ fontSize: '0.78rem', color: '#B91C1C', backgroundColor: '#FEF2F2', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-xs)', marginBottom: '0.75rem', border: '1px solid #FECACA' }}>
                    {auditError}
                  </div>
                )}

                {auditEvents.length === 0 && !auditLoading ? (
                  <div style={{ fontSize: '0.8rem', color: 'var(--ink-muted)', padding: '0.75rem 1rem', backgroundColor: 'var(--bg-subtle)', borderRadius: 'var(--radius-xs)', border: '1px solid var(--border-color)', width: '100%', boxSizing: 'border-box' }}>
                    No audit records match the selected filters.
                  </div>
                ) : (
                  <div className="audit-event-list">
                    {auditEvents.map((evt) => {
                      const actionStyle = getActionBadgeStyle(evt.action);
                      const resultStyle = getResultBadgeStyle(evt.result);
                      return (
                        <div
                          key={evt.id}
                          className="audit-event-card"
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.35rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                              <span
                                className="badge"
                                style={{
                                  fontSize: '0.68rem',
                                  padding: '0.12rem 0.45rem',
                                  fontWeight: 700,
                                  ...actionStyle,
                                }}
                              >
                                {evt.action}
                              </span>

                              {evt.version_number && (
                                <span
                                  className="badge"
                                  style={{
                                    backgroundColor: '#EDE9FE',
                                    color: '#5B21B6',
                                    fontSize: '0.65rem',
                                    fontWeight: 700,
                                    padding: '0.1rem 0.35rem',
                                  }}
                                >
                                  v{evt.version_number}
                                </span>
                              )}

                              <span
                                className="badge"
                                style={{
                                  fontSize: '0.65rem',
                                  padding: '0.1rem 0.35rem',
                                  ...resultStyle,
                                }}
                              >
                                {evt.result}
                              </span>
                            </div>

                            <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                              {formatDate(evt.created_at)}
                            </span>
                          </div>

                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: 'var(--ink-primary)', fontSize: '0.78rem' }}>
                            <div>
                              <span style={{ fontWeight: 600 }}>{evt.actor_name || 'System / Anonymous'}</span>
                              {evt.actor_role && (
                                <span className="badge" style={{ marginLeft: '0.4rem', fontSize: '0.62rem', padding: '0.08rem 0.3rem', backgroundColor: 'var(--bg-subtle)' }}>
                                  {evt.actor_role}
                                </span>
                              )}
                            </div>

                            {evt.metadata && evt.metadata.shared_with_name && (
                              <div style={{ fontSize: '0.72rem', color: 'var(--ink-secondary)' }}>
                                Shared with: <strong>{evt.metadata.shared_with_name}</strong> ({evt.metadata.shared_with_role})
                              </div>
                            )}
                          </div>

                          {evt.reason && (
                            <div style={{ fontSize: '0.72rem', color: evt.result === 'TAMPERED' || evt.result === 'DENIED' ? '#DC2626' : 'var(--ink-secondary)', fontStyle: 'italic' }}>
                              {evt.reason}
                            </div>
                          )}

                          {evt.metadata && evt.metadata.current_hash && evt.metadata.blockchain_hash && (
                            <div style={{ fontSize: '0.68rem', backgroundColor: '#FEF2F2', padding: '0.35rem 0.5rem', borderRadius: 'var(--radius-xs)', border: '1px solid #FECACA', fontFamily: 'var(--font-mono)' }}>
                              <div><strong>Calculated:</strong> {evt.metadata.current_hash}</div>
                              <div><strong>On-Chain:</strong> {evt.metadata.blockchain_hash}</div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

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
