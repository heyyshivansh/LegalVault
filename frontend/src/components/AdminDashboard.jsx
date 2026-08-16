import React, { useState, useEffect, useCallback } from 'react';
import { fetchAdminDashboard } from '../services/api';
import { formatISTDateTime } from '../utils/timezone';

export default function AdminDashboard({
  onInspectDocument,
  onOpenSystemAudit,
  onOpenResetVault,
  onSwitchToDocket,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copiedField, setCopiedField] = useState(null);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAdminDashboard();
      setData(res);
    } catch (err) {
      console.warn('Admin dashboard fetch error:', err);
      setError(err.message || 'Failed to retrieve administrative overview metrics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const copyToClipboard = (text, fieldName) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldName);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0.00 MB';
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

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

  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: '3.5rem 1rem', color: 'var(--ink-muted)' }}>
        <div className="serif-heading" style={{ fontSize: '1.25rem', marginBottom: '0.4rem', color: 'var(--ink-primary)' }}>
          LegalVault Administration
        </div>
        <div style={{ fontSize: '0.85rem' }}>Aggregating system custody metrics and threat telemetry...</div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="verdict-banner tampered" style={{ marginBottom: '1.5rem' }}>
        <div>
          <div className="verdict-headline">ADMINISTRATIVE DASHBOARD UNAVAILABLE</div>
          <div className="verdict-explanation">{error}</div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ marginTop: '0.75rem' }}
            onClick={loadDashboard}
          >
            Retry Dashboard Load
          </button>
        </div>
      </div>
    );
  }

  const {
    system_overview: sys,
    integrity_overview: integrity,
    security_overview: sec,
    blockchain_overview: chain,
    attention_documents: attentionDocs = [],
    recent_activity: recentActivity = [],
    generated_at: genAt,
  } = data;

  return (
    <div className="admin-dashboard-container">
      {/* Dashboard Top Navigation & Status Strip */}
      <div className="dashboard-header-bar">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span className="badge" style={{ backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A', fontSize: '0.72rem', fontWeight: 700 }}>
              MASTER ACCESS
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
              Telemetry Snapshot: {formatISTDateTime(genAt)}
            </span>
          </div>
          <h2 className="serif-heading" style={{ fontSize: '1.45rem', marginTop: '0.25rem', color: 'var(--ink-primary)' }}>
            Administrative Forensic Command &amp; Threat Monitor
          </h2>
        </div>

        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={loadDashboard}
            disabled={loading}
            title="Refresh administrative metrics"
          >
            {loading ? 'Refreshing...' : '↻ Refresh Metrics'}
          </button>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ backgroundColor: '#EEF2FF', color: '#4338CA', borderColor: '#C7D2FE', fontWeight: 600 }}
            onClick={onOpenSystemAudit}
            title="Open comprehensive forensic audit log"
          >
            📋 Full Audit Log
          </button>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onSwitchToDocket}
            title="Switch to standard legal docket repository table"
          >
            📁 View Docket Repository
          </button>

          <button
            type="button"
            className="btn btn-danger btn-sm"
            style={{ fontSize: '0.75rem', padding: '0.35rem 0.75rem' }}
            onClick={onOpenResetVault}
            title="Reset development database documents, shares, and upload files while preserving users"
          >
            Reset Development Vault
          </button>
        </div>
      </div>

      {/* 1. Primary System Overview Metric Cards */}
      <div className="registry-stats-strip" style={{ marginBottom: '1.75rem' }}>
        <div className="stat-cell">
          <div className="stat-label">Total Vault Records</div>
          <div className="stat-value">{sys.total_documents}</div>
          <div className="stat-subtext">Storage: {formatFileSize(sys.total_file_size_bytes)}</div>
        </div>

        <div className="stat-cell">
          <div className="stat-label">Document Versions</div>
          <div className="stat-value" style={{ color: 'var(--accent-navy)' }}>
            {sys.total_versions}
          </div>
          <div className="stat-subtext">
            Anchored: {chain.anchored_versions_count} / {sys.total_versions} ({sys.total_versions > 0 ? Math.round((chain.anchored_versions_count / sys.total_versions) * 100) : 100}%)
          </div>
        </div>

        <div className="stat-cell">
          <div className="stat-label">Registered Accounts</div>
          <div className="stat-value">{sys.total_users}</div>
          <div className="stat-subtext" style={{ display: 'flex', gap: '0.35rem', marginTop: '0.35rem', flexWrap: 'wrap' }}>
            <span className="badge" style={{ fontSize: '0.62rem', padding: '0.05rem 0.3rem', backgroundColor: '#EFF6FF', color: '#1E40AF' }}>
              {sys.users_by_role?.LAWYER || 0} Lawyers
            </span>
            <span className="badge" style={{ fontSize: '0.62rem', padding: '0.05rem 0.3rem', backgroundColor: '#F3E8FF', color: '#6B21A8' }}>
              {sys.users_by_role?.JUDGE || 0} Judges
            </span>
            <span className="badge" style={{ fontSize: '0.62rem', padding: '0.05rem 0.3rem', backgroundColor: '#F1F5F9', color: '#334155' }}>
              {sys.users_by_role?.CLIENT || 0} Clients
            </span>
            <span className="badge" style={{ fontSize: '0.62rem', padding: '0.05rem 0.3rem', backgroundColor: '#FEF3C7', color: '#92400E' }}>
              {sys.users_by_role?.ADMIN || 0} Admin
            </span>
          </div>
        </div>

        <div className="stat-cell">
          <div className="stat-label">Active Custody Shares</div>
          <div className="stat-value" style={{ color: sys.total_active_shares > 0 ? '#4338CA' : 'var(--ink-muted)' }}>
            {sys.total_active_shares}
          </div>
          <div className="stat-subtext">Across {sys.shared_documents_count} Unique Dockets</div>
        </div>
      </div>

      {/* 2. Integrity & Threat Perception Dual Deck */}
      <div className="dashboard-grid-2" style={{ marginBottom: '1.75rem' }}>
        {/* Deck A: Authoritative Forensic Integrity Status */}
        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <div>
              <span className="modal-pretitle">Cryptographic Custody</span>
              <h3 className="serif-heading" style={{ fontSize: '1.1rem', margin: 0 }}>
                Forensic Integrity Status
              </h3>
            </div>
            {integrity.attention_required_count > 0 ? (
              <span className="badge badge-failed" style={{ fontWeight: 700 }}>
                ⚠ {integrity.attention_required_count} ACTION REQUIRED
              </span>
            ) : (
              <span className="badge badge-confirmed" style={{ fontWeight: 700 }}>
                ✓ ALL VERIFIED INTACT
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginTop: '1rem' }}>
            <div style={{ backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#065F46', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Verified Intact
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#047857', marginTop: '0.2rem' }}>
                {integrity.verified_documents}
              </div>
              <div style={{ fontSize: '0.68rem', color: '#065F46', marginTop: '0.15rem' }}>
                Authoritative On-Chain
              </div>
            </div>

            <div style={{ backgroundColor: integrity.tampered_documents > 0 ? '#FEF2F2' : 'var(--bg-subtle)', border: `1px solid ${integrity.tampered_documents > 0 ? '#FECACA' : 'var(--border-color)'}`, borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: integrity.tampered_documents > 0 ? '#991B1B' : 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Tamper Incidents
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: integrity.tampered_documents > 0 ? '#B91C1C' : 'var(--ink-muted)', marginTop: '0.2rem' }}>
                {integrity.tampered_documents}
              </div>
              <div style={{ fontSize: '0.68rem', color: integrity.tampered_documents > 0 ? '#991B1B' : 'var(--ink-muted)', marginTop: '0.15rem' }}>
                Hash Mismatch
              </div>
            </div>

            <div style={{ backgroundColor: integrity.proof_unavailable_documents > 0 ? '#FFFBEB' : 'var(--bg-subtle)', border: `1px solid ${integrity.proof_unavailable_documents > 0 ? '#FDE68A' : 'var(--border-color)'}`, borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: integrity.proof_unavailable_documents > 0 ? '#92400E' : 'var(--ink-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Proof Missing
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: integrity.proof_unavailable_documents > 0 ? '#B45309' : 'var(--ink-muted)', marginTop: '0.2rem' }}>
                {integrity.proof_unavailable_documents}
              </div>
              <div style={{ fontSize: '0.68rem', color: integrity.proof_unavailable_documents > 0 ? '#92400E' : 'var(--ink-muted)', marginTop: '0.15rem' }}>
                EVM Record Missing
              </div>
            </div>
          </div>

          <div style={{ marginTop: '1rem', fontSize: '0.78rem', color: 'var(--ink-secondary)', backgroundColor: 'var(--bg-subtle)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-xs)' }}>
            * Integrity status is determined authoritatively by the latest cryptographic on-chain verification proof per docket.
          </div>
        </div>

        {/* Deck B: Access Security & Threat Telemetry */}
        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <div>
              <span className="modal-pretitle">Threat Perception</span>
              <h3 className="serif-heading" style={{ fontSize: '1.1rem', margin: 0 }}>
                Security &amp; Threat Telemetry
              </h3>
            </div>
            <span className="badge" style={{ backgroundColor: '#F1F5F9', color: '#475569', fontSize: '0.68rem', fontWeight: 600 }}>
              24-HOUR SLIDING WINDOW
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem', marginTop: '1rem' }}>
            <div style={{ backgroundColor: sec.failed_logins_24h > 0 ? '#FFF1F2' : 'var(--bg-subtle)', border: `1px solid ${sec.failed_logins_24h > 0 ? '#FECDD3' : 'var(--border-color)'}`, borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: sec.failed_logins_24h > 0 ? '#BE123C' : 'var(--ink-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Failed Logins
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: sec.failed_logins_24h > 0 ? '#E11D48' : 'var(--ink-primary)', marginTop: '0.2rem' }}>
                {sec.failed_logins_24h}
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', marginTop: '0.15rem' }}>
                All-Time: {sec.failed_logins_all_time}
              </div>
            </div>

            <div style={{ backgroundColor: sec.access_denied_24h > 0 ? '#FFF1F2' : 'var(--bg-subtle)', border: `1px solid ${sec.access_denied_24h > 0 ? '#FECDD3' : 'var(--border-color)'}`, borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: sec.access_denied_24h > 0 ? '#BE123C' : 'var(--ink-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Access Denied
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: sec.access_denied_24h > 0 ? '#E11D48' : 'var(--ink-primary)', marginTop: '0.2rem' }}>
                {sec.access_denied_24h}
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', marginTop: '0.15rem' }}>
                All-Time: {sec.access_denied_all_time}
              </div>
            </div>

            <div style={{ backgroundColor: sec.action_denied_24h > 0 ? '#FFF1F2' : 'var(--bg-subtle)', border: `1px solid ${sec.action_denied_24h > 0 ? '#FECDD3' : 'var(--border-color)'}`, borderRadius: 'var(--radius-xs)', padding: '0.85rem 1rem', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: sec.action_denied_24h > 0 ? '#BE123C' : 'var(--ink-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Action Denied
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: sec.action_denied_24h > 0 ? '#E11D48' : 'var(--ink-primary)', marginTop: '0.2rem' }}>
                {sec.action_denied_24h}
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', marginTop: '0.15rem' }}>
                All-Time: {sec.action_denied_all_time}
              </div>
            </div>
          </div>

          <div style={{ marginTop: '1rem', fontSize: '0.78rem', color: 'var(--ink-secondary)', backgroundColor: 'var(--bg-subtle)', padding: '0.65rem 0.85rem', borderRadius: 'var(--radius-xs)' }}>
            * Tracks unauthorized 401/403 security exceptions recorded immediately via isolated database audit commits.
          </div>
        </div>
      </div>

      {/* 3. Documents Requiring Attention Section */}
      <div className="dashboard-card" style={{ marginBottom: '1.75rem' }}>
        <div className="dashboard-card-header">
          <div>
            <span className="modal-pretitle">Forensic Attention Queue</span>
            <h3 className="serif-heading" style={{ fontSize: '1.15rem', margin: 0 }}>
              Documents Requiring Administrative Attention ({attentionDocs.length})
            </h3>
          </div>
        </div>

        {attentionDocs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2rem 1rem', backgroundColor: '#ECFDF5', border: '1px solid #A7F3D0', borderRadius: 'var(--radius-xs)', color: '#065F46', marginTop: '0.75rem' }}>
            <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>✓ All Repository Records In Clear Forensic Standing</div>
            <div style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>
              No current tamper mismatches, missing off-chain files, or unreachable blockchain proofs detected.
            </div>
          </div>
        ) : (
          <div className="docket-table-container" style={{ marginTop: '0.75rem', boxShadow: 'none' }}>
            <table className="docket-table" style={{ fontSize: '0.8rem' }}>
              <thead>
                <tr>
                  <th style={{ width: '70px' }}>Doc ID</th>
                  <th style={{ width: '130px' }}>Case Number</th>
                  <th>Document Title</th>
                  <th style={{ width: '80px' }}>Version</th>
                  <th style={{ width: '140px' }}>Issue Type</th>
                  <th>Forensic Diagnosis</th>
                  <th style={{ width: '110px', textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {attentionDocs.map((item, idx) => (
                  <tr key={`${item.document_id}_${item.version_number || idx}`}>
                    <td className="case-id-cell">#{item.document_id}</td>
                    <td className="case-id-cell">{item.case_number || 'UNASSIGNED'}</td>
                    <td style={{ fontWeight: 600, color: 'var(--ink-primary)' }}>{item.filename}</td>
                    <td>
                      <span className="badge" style={{ backgroundColor: '#EDE9FE', color: '#5B21B6', fontSize: '0.68rem', fontWeight: 700 }}>
                        v{item.version_number || 1}
                      </span>
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          fontSize: '0.68rem',
                          fontWeight: 700,
                          backgroundColor: item.issue_type === 'TAMPERED' ? '#FEF2F2' : item.issue_type === 'PROOF_UNAVAILABLE' ? '#FFFBEB' : '#FFF1F2',
                          color: item.issue_type === 'TAMPERED' ? '#B91C1C' : item.issue_type === 'PROOF_UNAVAILABLE' ? '#92400E' : '#BE123C',
                          border: `1px solid ${item.issue_type === 'TAMPERED' ? '#FECACA' : item.issue_type === 'PROOF_UNAVAILABLE' ? '#FDE68A' : '#FECDD3'}`,
                        }}
                      >
                        {item.issue_type}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--ink-secondary)', fontStyle: 'italic' }}>
                      {item.reason}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        style={{ fontSize: '0.72rem', padding: '0.25rem 0.6rem' }}
                        onClick={() => onInspectDocument(item.document_id)}
                      >
                        Inspect Record
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 4. Recent Forensic Activity & Blockchain Infrastructure Deck */}
      <div className="dashboard-grid-2">
        {/* Left Column: Recent Activity Log */}
        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <div>
              <span className="modal-pretitle">Real-Time Event Stream</span>
              <h3 className="serif-heading" style={{ fontSize: '1.1rem', margin: 0 }}>
                Recent Forensic Audit Activity
              </h3>
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ fontSize: '0.75rem', color: '#4338CA' }}
              onClick={onOpenSystemAudit}
            >
              View All →
            </button>
          </div>

          {recentActivity.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--ink-muted)', fontSize: '0.8rem' }}>
              No recent audit activity logged.
            </div>
          ) : (
            <div className="audit-event-list" style={{ maxHeight: '380px', marginTop: '0.75rem' }}>
              {recentActivity.map((evt) => {
                const actionStyle = getActionBadgeStyle(evt.action);
                return (
                  <div key={evt.id} className="audit-event-card">
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
                          <span className="badge" style={{ backgroundColor: '#EDE9FE', color: '#5B21B6', fontSize: '0.65rem', fontWeight: 700 }}>
                            v{evt.version_number}
                          </span>
                        )}

                        <span
                          className="badge"
                          style={{
                            fontSize: '0.65rem',
                            backgroundColor: evt.result === 'SUCCESS' || evt.result === 'VERIFIED' ? '#ECFDF5' : '#FEF2F2',
                            color: evt.result === 'SUCCESS' || evt.result === 'VERIFIED' ? '#047857' : '#B91C1C',
                            fontWeight: 600,
                          }}
                        >
                          {evt.result}
                        </span>
                      </div>

                      <span style={{ fontSize: '0.72rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                        {formatISTDateTime(evt.created_at)}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.76rem', color: 'var(--ink-primary)' }}>
                      <div>
                        <strong>{evt.actor_name || 'System / Anonymous'}</strong>
                        {evt.actor_role && (
                          <span className="badge" style={{ marginLeft: '0.35rem', fontSize: '0.62rem', padding: '0.05rem 0.3rem', backgroundColor: 'var(--bg-subtle)' }}>
                            {evt.actor_role}
                          </span>
                        )}
                        {evt.actor_email && (
                          <span style={{ fontSize: '0.7rem', color: 'var(--ink-muted)', marginLeft: '0.4rem', fontFamily: 'var(--font-mono)' }}>
                            {evt.actor_email}
                          </span>
                        )}
                      </div>

                      {evt.document_title && (
                        <div style={{ fontSize: '0.72rem', color: 'var(--ink-secondary)' }}>
                          Doc #{evt.document_id}: <strong>{evt.document_title}</strong>
                        </div>
                      )}
                    </div>

                    {evt.reason && (
                      <div style={{ fontSize: '0.72rem', color: evt.result === 'FAILED' || evt.result === 'DENIED' || evt.result === 'TAMPERED' ? '#DC2626' : 'var(--ink-muted)', fontStyle: 'italic' }}>
                        {evt.reason}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right Column: Blockchain Infrastructure & Storage Custody */}
        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <div>
              <span className="modal-pretitle">Distributed Ledger Infrastructure</span>
              <h3 className="serif-heading" style={{ fontSize: '1.1rem', margin: 0 }}>
                Blockchain Custody &amp; Health
              </h3>
            </div>
            <span
              className="badge"
              style={{
                backgroundColor: chain.is_connected ? '#ECFDF5' : '#FEF2F2',
                color: chain.is_connected ? '#047857' : '#B91C1C',
                border: `1px solid ${chain.is_connected ? '#A7F3D0' : '#FECACA'}`,
                fontWeight: 700,
                fontSize: '0.72rem',
              }}
            >
              ● {chain.is_connected ? 'NODE OPERATIONAL' : 'NODE OFFLINE'}
            </span>
          </div>

          <table className="provenance-table" style={{ marginTop: '0.75rem' }}>
            <tbody>
              <tr>
                <td className="field-name">Target Network</td>
                <td className="field-val">{chain.network_name}</td>
              </tr>
              <tr>
                <td className="field-name">EVM Chain ID</td>
                <td className="field-val font-mono">{chain.chain_id || 'Unavailable'}</td>
              </tr>
              <tr>
                <td className="field-name">Smart Contract</td>
                <td className="field-val">
                  <span>{chain.contract_address}</span>
                  {chain.contract_address && (
                    <button
                      type="button"
                      className="copy-btn"
                      onClick={() => copyToClipboard(chain.contract_address, 'dashboard_contract')}
                      title="Copy Contract Address"
                    >
                      {copiedField === 'dashboard_contract' ? '✓' : '⧉'}
                    </button>
                  )}
                </td>
              </tr>
              <tr>
                <td className="field-name">Anchored Revisions</td>
                <td className="field-val">
                  <span className="badge badge-confirmed" style={{ marginRight: '0.4rem' }}>
                    {chain.anchored_versions_count} Confirmed
                  </span>
                  {chain.pending_versions_count > 0 && (
                    <span className="badge badge-pending">
                      {chain.pending_versions_count} Pending
                    </span>
                  )}
                </td>
              </tr>
              <tr>
                <td className="field-name">Latest EVM Anchor TX</td>
                <td className="field-val">
                  {chain.latest_anchor_tx ? (
                    <div>
                      <span className="font-mono">{chain.latest_anchor_tx.substring(0, 24)}...</span>
                      <button
                        type="button"
                        className="copy-btn"
                        onClick={() => copyToClipboard(chain.latest_anchor_tx, 'dashboard_tx')}
                        title="Copy Transaction Hash"
                      >
                        {copiedField === 'dashboard_tx' ? '✓' : '⧉'}
                      </button>
                    </div>
                  ) : (
                    'No transaction yet'
                  )}
                </td>
              </tr>
              <tr>
                <td className="field-name">Latest Anchor Time</td>
                <td className="field-val font-mono">
                  {chain.latest_anchor_time ? formatISTDateTime(chain.latest_anchor_time) : 'N/A'}
                </td>
              </tr>
              <tr>
                <td className="field-name">Total Vault Storage</td>
                <td className="field-val font-mono">{formatFileSize(sys.total_file_size_bytes)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
