import React, { useState, useEffect, useCallback } from 'react';
import { fetchSystemAuditTrail } from '../services/api';
import { formatISTDateTime } from '../utils/timezone';

export default function SystemAuditModal({ isOpen, onClose }) {
  const [events, setEvents] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Filters
  const [actionFilter, setActionFilter] = useState('');
  const [resultFilter, setResultFilter] = useState('');
  const [docIdFilter, setDocIdFilter] = useState('');
  const [actorIdFilter, setActorIdFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const loadAuditEvents = useCallback(async (customOffset = offset) => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        limit,
        offset: customOffset,
      };
      if (actionFilter) params.action = actionFilter;
      if (resultFilter) params.result = resultFilter;
      if (docIdFilter.trim()) params.document_id = parseInt(docIdFilter.trim(), 10);
      if (actorIdFilter.trim()) params.actor_id = parseInt(actorIdFilter.trim(), 10);

      const res = await fetchSystemAuditTrail(params);
      setEvents(res.events || []);
      setTotalCount(res.total_count || 0);
    } catch (err) {
      console.warn('System audit fetch error:', err);
      setError(err.message || 'Failed to fetch system audit logs');
    } finally {
      setLoading(false);
    }
  }, [actionFilter, resultFilter, docIdFilter, actorIdFilter, offset]);

  useEffect(() => {
    if (isOpen) {
      loadAuditEvents(0);
      setOffset(0);
    }
  }, [isOpen, actionFilter, resultFilter]);

  // Handle ESC key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const getActionBadgeStyle = (action) => {
    switch (action) {
      case 'LOGIN_SUCCESS':
      case 'LOGOUT':
        return { backgroundColor: '#F0FDF4', color: '#15803D', border: '1px solid #BBF7D0' };
      case 'LOGIN_FAILED':
      case 'ACCESS_DENIED':
      case 'ACTION_DENIED':
        return { backgroundColor: '#FFF1F2', color: '#BE123C', border: '1px solid #FECDD3' };
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
      case 'VAULT_RESET':
        return { backgroundColor: '#FEF3C7', color: '#D97706', border: '1px solid #FCD34D' };
      default:
        return { backgroundColor: '#F8FAFC', color: '#475569', border: '1px solid #E2E8F0' };
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

  const totalPages = Math.ceil(totalCount / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="modal-backdrop" onClick={onClose} style={{ zIndex: 1100 }}>
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '1080px', width: '95%', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <h3 className="serif-heading" style={{ margin: 0, fontSize: '1.25rem' }}>
              System Forensic Audit Trail
            </h3>
            <span className="badge" style={{ backgroundColor: '#EEF2FF', color: '#4338CA', border: '1px solid #C7D2FE', fontSize: '0.72rem', fontWeight: 700 }}>
              ADMIN OVERSIGHT
            </span>
          </div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        {/* Filter Controls Bar */}
        <div style={{ padding: '1rem 1.25rem', backgroundColor: 'var(--bg-subtle)', borderBottom: '1px solid var(--border-color)', display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem', alignItems: 'center' }}>
            {/* Action Filter */}
            <div>
              <label style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--ink-secondary)', display: 'block', marginBottom: '0.15rem' }}>
                Event Action
              </label>
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                className="audit-filter-select"
              >
                <option value="">All Actions</option>
                <option value="LOGIN_SUCCESS">Login Success</option>
                <option value="LOGIN_FAILED">Login Failed</option>
                <option value="LOGOUT">Logout</option>
                <option value="DOCUMENT_CREATED">Document Created</option>
                <option value="VERSION_CREATED">Version Created</option>
                <option value="DOCUMENT_VERIFIED">Document Verified</option>
                <option value="VERSION_VERIFIED">Version Verified</option>
                <option value="DOCUMENT_TAMPERED">Document Tampered</option>
                <option value="VERSION_TAMPERED">Version Tampered</option>
                <option value="DOCUMENT_SHARED">Document Shared</option>
                <option value="DOCUMENT_SHARE_REVOKED">Share Revoked</option>
                <option value="DOCUMENT_DOWNLOADED">Document Downloaded</option>
                <option value="VERSION_DOWNLOADED">Version Downloaded</option>
                <option value="ACCESS_DENIED">Access Denied</option>
                <option value="ACTION_DENIED">Action Denied</option>
                <option value="VAULT_RESET">Vault Reset</option>
              </select>
            </div>

            {/* Result Filter */}
            <div>
              <label style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--ink-secondary)', display: 'block', marginBottom: '0.15rem' }}>
                Outcome
              </label>
              <select
                value={resultFilter}
                onChange={(e) => setResultFilter(e.target.value)}
                className="audit-filter-select"
              >
                <option value="">All Outcomes</option>
                <option value="SUCCESS">Success</option>
                <option value="VERIFIED">Verified</option>
                <option value="TAMPERED">Tampered</option>
                <option value="DENIED">Denied</option>
                <option value="FAILED">Failed</option>
                <option value="UNAVAILABLE">Unavailable</option>
              </select>
            </div>

            {/* Doc ID Filter */}
            <div>
              <label style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--ink-secondary)', display: 'block', marginBottom: '0.15rem' }}>
                Doc ID
              </label>
              <input
                type="number"
                placeholder="e.g. 1"
                value={docIdFilter}
                onChange={(e) => setDocIdFilter(e.target.value)}
                className="audit-filter-select"
                style={{ width: '80px' }}
              />
            </div>

            {/* Actor ID Filter */}
            <div>
              <label style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--ink-secondary)', display: 'block', marginBottom: '0.15rem' }}>
                Actor ID
              </label>
              <input
                type="number"
                placeholder="e.g. 2"
                value={actorIdFilter}
                onChange={(e) => setActorIdFilter(e.target.value)}
                className="audit-filter-select"
                style={{ width: '80px' }}
              />
            </div>

            <div style={{ alignSelf: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => loadAuditEvents(0)}
                disabled={loading}
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.75rem' }}
              >
                {loading ? 'Filtering...' : 'Apply Filters'}
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--ink-secondary)' }}>
              Total Logged Events: <strong>{totalCount}</strong>
            </span>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => loadAuditEvents(offset)}
              disabled={loading}
              title="Refresh audit log"
            >
              {loading ? '...' : '↻ Refresh'}
            </button>
          </div>
        </div>

        {/* Audit Log Table */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '1rem 1.25rem' }}>
          {error && (
            <div style={{ backgroundColor: '#FEF2F2', color: '#B91C1C', padding: '0.75rem 1rem', borderRadius: 'var(--radius-xs)', marginBottom: '1rem', fontSize: '0.82rem' }}>
              {error}
            </div>
          )}

          {events.length === 0 && !loading ? (
            <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--ink-muted)' }}>
              <div style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>📋</div>
              <div style={{ fontWeight: 600 }}>No audit events found</div>
              <div style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>Try adjusting your filter criteria</div>
            </div>
          ) : (
            <table className="docket-table" style={{ fontSize: '0.8rem' }}>
              <thead>
                <tr>
                  <th style={{ width: '160px' }}>Timestamp (IST)</th>
                  <th style={{ width: '140px' }}>Action</th>
                  <th style={{ width: '180px' }}>Actor</th>
                  <th style={{ width: '150px' }}>Target Resource</th>
                  <th style={{ width: '100px' }}>Result</th>
                  <th>Forensic Details &amp; Metadata</th>
                </tr>
              </thead>
              <tbody>
                {events.map((evt) => {
                  const actionStyle = getActionBadgeStyle(evt.action);
                  const resultStyle = getResultBadgeStyle(evt.result);
                  return (
                    <tr key={evt.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--ink-secondary)', whiteSpace: 'nowrap' }}>
                        {formatISTDateTime(evt.created_at)}
                      </td>
                      <td>
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
                      </td>
                      <td>
                        <div>
                          <span style={{ fontWeight: 600, color: 'var(--ink-primary)' }}>
                            {evt.actor_name || 'System / Anonymous'}
                          </span>
                          {evt.actor_role && (
                            <span className="badge" style={{ marginLeft: '0.35rem', fontSize: '0.62rem', padding: '0.08rem 0.3rem', backgroundColor: 'var(--bg-subtle)' }}>
                              {evt.actor_role}
                            </span>
                          )}
                        </div>
                        {evt.actor_email && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                            {evt.actor_email}
                          </div>
                        )}
                        {evt.ip_address && (
                          <div style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                            IP: {evt.ip_address}
                          </div>
                        )}
                      </td>
                      <td>
                        {evt.document_id ? (
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--accent-navy)' }}>
                              Doc #{evt.document_id}
                            </span>
                            {evt.document_filename && (
                              <div style={{ fontSize: '0.72rem', color: 'var(--ink-secondary)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: '140px' }} title={evt.document_filename}>
                                {evt.document_filename}
                              </div>
                            )}
                            {evt.version_number && (
                              <span className="badge" style={{ backgroundColor: '#EDE9FE', color: '#5B21B6', fontSize: '0.65rem', fontWeight: 700, padding: '0.08rem 0.3rem', marginTop: '0.15rem' }}>
                                v{evt.version_number}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span style={{ color: 'var(--ink-muted)', fontSize: '0.75rem' }}>
                            {evt.resource_type || 'System'}
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className="badge"
                          style={{
                            fontSize: '0.68rem',
                            padding: '0.12rem 0.4rem',
                            ...resultStyle,
                          }}
                        >
                          {evt.result}
                        </span>
                      </td>
                      <td>
                        {evt.reason && (
                          <div style={{ fontSize: '0.74rem', color: evt.result === 'TAMPERED' || evt.result === 'DENIED' || evt.result === 'FAILED' ? '#DC2626' : 'var(--ink-primary)', marginBottom: '0.25rem' }}>
                            {evt.reason}
                          </div>
                        )}
                        {evt.metadata && Object.keys(evt.metadata).length > 0 && (
                          <div style={{ fontSize: '0.7rem', color: 'var(--ink-secondary)', fontFamily: 'var(--font-mono)', backgroundColor: 'var(--bg-subtle)', padding: '0.3rem 0.5rem', borderRadius: 'var(--radius-xs)' }}>
                            {evt.metadata.shared_with_name && (
                              <div>Shared with: {evt.metadata.shared_with_name} ({evt.metadata.shared_with_role})</div>
                            )}
                            {evt.metadata.current_hash && (
                              <div>Current Hash: {evt.metadata.current_hash.slice(0, 16)}...</div>
                            )}
                            {evt.metadata.blockchain_hash && (
                              <div>Chain Hash: {evt.metadata.blockchain_hash.slice(0, 16)}...</div>
                            )}
                            {evt.metadata.documents_deleted !== undefined && (
                              <div>Deleted Docs: {evt.metadata.documents_deleted}, Files: {evt.metadata.files_deleted}</div>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination Bar */}
        <div style={{ padding: '0.75rem 1.25rem', backgroundColor: 'var(--bg-subtle)', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--ink-muted)' }}>
            Showing {events.length > 0 ? offset + 1 : 0} to {Math.min(offset + limit, totalCount)} of {totalCount} events (Page {currentPage} of {totalPages})
          </div>

          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                const newOffset = Math.max(0, offset - limit);
                setOffset(newOffset);
                loadAuditEvents(newOffset);
              }}
              disabled={offset === 0 || loading}
              style={{ fontSize: '0.75rem' }}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                const newOffset = offset + limit;
                setOffset(newOffset);
                loadAuditEvents(newOffset);
              }}
              disabled={offset + limit >= totalCount || loading}
              style={{ fontSize: '0.75rem' }}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
