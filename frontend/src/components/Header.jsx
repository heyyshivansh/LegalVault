import React from 'react';
import { useAuth } from '../context/AuthContext';

export default function Header({ isOnline, onOpenUpload, onRefresh }) {
  const { user, role, logout, canDeposit } = useAuth();

  const getRoleBadgeStyle = (r) => {
    switch (r) {
      case 'ADMIN':
        return { backgroundColor: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' };
      case 'LAWYER':
        return { backgroundColor: '#EFF6FF', color: '#1E40AF', border: '1px solid #BFDBFE' };
      case 'JUDGE':
        return { backgroundColor: '#F3E8FF', color: '#6B21A8', border: '1px solid #E9D5FF' };
      case 'CLIENT':
        return { backgroundColor: '#F1F5F9', color: '#334155', border: '1px solid #CBD5E1' };
      default:
        return { backgroundColor: 'var(--bg-subtle)', color: 'var(--ink-secondary)', border: '1px solid var(--border-color)' };
    }
  };

  return (
    <header className="vault-header">
      <div className="header-inner">
        <div className="brand-section">
          <div className="vault-crest">
            <div className="crest-badge">LV</div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span className="brand-name">LegalVault</span>
            </div>
          </div>
          <span className="brand-tagline">
            E-Vault &amp; Cryptographic Evidence Management
          </span>
        </div>

        <div className="header-actions">
          {/* Node Status */}
          <div className="node-status" title={isOnline ? "Backend API & Blockchain Node operational" : "Backend service unreachable"}>
            <span className={`status-dot ${isOnline ? '' : 'offline'}`}></span>
            <span>{isOnline ? 'EVM NODE · READY' : 'OFFLINE'}</span>
          </div>

          <button 
            type="button" 
            className="btn btn-secondary btn-sm"
            onClick={onRefresh}
            title="Refresh repository records"
          >
            Refresh
          </button>

          {/* Deposit Button: Only for Lawyer and Admin */}
          {canDeposit && (
            <button 
              type="button" 
              className="btn btn-primary btn-sm"
              onClick={onOpenUpload}
            >
              + Deposit Legal Record
            </button>
          )}

          {/* User Session & Role */}
          {user && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginLeft: '0.5rem', paddingLeft: '0.75rem', borderLeft: '1px solid var(--border-color)' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', lineHeight: 1.2 }}>
                <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--ink-primary)' }}>
                  {user.name}
                </span>
                <span
                  className="badge"
                  style={{
                    fontSize: '0.65rem',
                    padding: '0.1rem 0.35rem',
                    marginTop: '0.15rem',
                    ...getRoleBadgeStyle(role),
                  }}
                >
                  {role}
                </span>
              </div>

              <button
                type="button"
                className="btn btn-ghost btn-sm"
                style={{ fontSize: '0.75rem', padding: '0.35rem 0.55rem' }}
                onClick={logout}
                title="Sign out of LegalVault"
              >
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
