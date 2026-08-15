import React, { useState } from 'react';
import { downloadDocumentFile } from '../services/api';
import { useAuth } from '../context/AuthContext';

export default function DocumentList({
  documents = [],
  isLoading,
  onVerifyDocument,
  onInspectDocument,
}) {
  const { role, isJudge, isClient, isLawyer } = useAuth();
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [downloadingDocId, setDownloadingDocId] = useState(null);

  const handleDownload = async (docId, filename) => {
    setDownloadingDocId(docId);
    try {
      await downloadDocumentFile(docId, filename);
    } catch (err) {
      alert(err.message || 'Download failed');
    } finally {
      setDownloadingDocId(null);
    }
  };

  const filteredDocs = documents.filter((doc) => {
    const term = searchTerm.toLowerCase().trim();
    const matchesSearch =
      !term ||
      (doc.filename && doc.filename.toLowerCase().includes(term)) ||
      (doc.case_number && doc.case_number.toLowerCase().includes(term)) ||
      (doc.uploaded_by && doc.uploaded_by.toLowerCase().includes(term)) ||
      (doc.shared_by_name && doc.shared_by_name.toLowerCase().includes(term)) ||
      (doc.file_hash && doc.file_hash.toLowerCase().includes(term));

    const matchesStatus =
      statusFilter === 'ALL' ||
      (statusFilter === 'CONFIRMED' && doc.blockchain_status === 'confirmed') ||
      (statusFilter === 'FAILED' && doc.blockchain_status === 'failed') ||
      (statusFilter === 'PENDING' && !doc.blockchain_status);

    return matchesSearch && matchesStatus;
  });

  const formatDate = (isoString) => {
    if (!isoString) return '—';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  const truncateHash = (hash) => {
    if (!hash) return 'Pending Hashing...';
    if (hash.length <= 16) return hash;
    return `${hash.substring(0, 10)}...${hash.substring(hash.length - 8)}`;
  };

  const getEmptyMessage = () => {
    if (searchTerm) return 'No documents match your search query.';
    if (isJudge) {
      return 'No legal dockets are currently shared with your judicial chamber. Documents will appear here when authorized by the case depositor.';
    }
    if (isClient) {
      return 'No legal records are currently accessible to your client account. Documents will appear here when shared by your legal counsel.';
    }
    if (isLawyer) {
      return 'You have not deposited any legal records into the vault yet. Click "+ Deposit Legal Record" to anchor your first evidentiary document on-chain.';
    }
    return 'No legal records found in the vault repository.';
  };

  return (
    <div className="docket-section">
      <div className="docket-controls">
        <div className="search-input-wrapper">
          <input
            type="text"
            className="search-input"
            placeholder="Search by Case No., Document Title, or Depositor/Counsel..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <button
            type="button"
            className={`btn btn-sm ${statusFilter === 'ALL' ? 'btn-secondary' : 'btn-ghost'}`}
            style={{ fontWeight: statusFilter === 'ALL' ? '600' : '400' }}
            onClick={() => setStatusFilter('ALL')}
          >
            All Records ({documents.length})
          </button>
          <button
            type="button"
            className={`btn btn-sm ${statusFilter === 'CONFIRMED' ? 'btn-secondary' : 'btn-ghost'}`}
            style={{ fontWeight: statusFilter === 'CONFIRMED' ? '600' : '400' }}
            onClick={() => setStatusFilter('CONFIRMED')}
          >
            On-Chain ({documents.filter((d) => d.blockchain_status === 'confirmed').length})
          </button>
        </div>
      </div>

      <div className="docket-table-container">
        <table className="docket-table">
          <thead>
            <tr>
              <th style={{ width: '70px' }}>ID</th>
              <th style={{ width: '160px' }}>Case Reference</th>
              <th>Document Title &amp; SHA-256 Hash</th>
              <th style={{ width: '160px' }}>Depositor / Counsel</th>
              <th style={{ width: '160px' }}>Registration Date</th>
              <th style={{ width: '130px' }}>Blockchain</th>
              <th style={{ width: '220px', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--ink-muted)' }}>
                  Loading legal records from repository...
                </td>
              </tr>
            ) : filteredDocs.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem 1.5rem', color: 'var(--ink-muted)' }}>
                  <div style={{ maxWidth: '480px', margin: '0 auto' }}>
                    <div style={{ fontWeight: 600, color: 'var(--ink-primary)', marginBottom: '0.35rem', fontSize: '0.92rem' }}>
                      {searchTerm ? 'No Matching Records' : 'No Records Available'}
                    </div>
                    <div style={{ fontSize: '0.82rem', lineHeight: 1.45 }}>
                      {getEmptyMessage()}
                    </div>
                  </div>
                </td>
              </tr>
            ) : (
              filteredDocs.map((doc) => (
                <tr key={doc.id}>
                  <td className="case-id-cell">#{doc.id}</td>
                  <td className="case-id-cell">
                    {doc.case_number || <span style={{ color: 'var(--ink-subdued)' }}>UNASSIGNED</span>}
                  </td>
                  <td>
                    <div className="doc-name-cell">
                      <span className="doc-name-primary">{doc.filename}</span>
                      <span className="doc-hash-snippet" title={doc.file_hash}>
                        SHA256: {truncateHash(doc.file_hash)}
                      </span>
                    </div>
                  </td>
                  <td>
                    <div style={{ color: 'var(--ink-secondary)', fontSize: '0.82rem' }}>
                      {doc.uploaded_by || 'Unknown'}
                    </div>
                    {doc.is_shared && (
                      <span className="badge" style={{ fontSize: '0.65rem', padding: '0.05rem 0.35rem', marginTop: '0.2rem', backgroundColor: '#EFF6FF', color: '#1E40AF', border: '1px solid #BFDBFE' }}>
                        Shared with You
                      </span>
                    )}
                  </td>
                  <td style={{ color: 'var(--ink-muted)', fontSize: '0.78rem', fontFamily: 'var(--font-mono)' }}>
                    {formatDate(doc.created_at)}
                  </td>
                  <td>
                    {doc.blockchain_status === 'confirmed' ? (
                      <span className="badge badge-confirmed" title={doc.blockchain_tx_hash || ''}>
                        ● Anchored
                      </span>
                    ) : doc.blockchain_status === 'failed' ? (
                      <span className="badge badge-failed">
                        ● Failed
                      </span>
                    ) : (
                      <span className="badge badge-pending">
                        ● Pending
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: '0.4rem', justifyContent: 'flex-end' }}>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        style={{ fontSize: '0.75rem', padding: '0.3rem 0.55rem' }}
                        onClick={() => onVerifyDocument(doc.id)}
                        title="Run real-time cryptographic integrity check against Ethereum smart contract"
                      >
                        Verify Integrity
                      </button>

                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.75rem', padding: '0.3rem 0.55rem' }}
                        onClick={() => onInspectDocument(doc.id)}
                        title="View complete record details, shares, and provenance"
                      >
                        Inspect
                      </button>

                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        style={{ fontSize: '0.75rem', padding: '0.3rem 0.55rem' }}
                        onClick={() => handleDownload(doc.id, doc.filename)}
                        disabled={downloadingDocId === doc.id}
                        title="Download stored original file"
                      >
                        {downloadingDocId === doc.id ? 'Downloading...' : 'Download'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
