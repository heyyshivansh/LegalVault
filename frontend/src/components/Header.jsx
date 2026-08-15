import React from 'react';

export default function Header({ isOnline, onOpenUpload, onRefresh }) {
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
            Blockchain eVault &amp; Cryptographic Evidence Management
          </span>
        </div>

        <div className="header-actions">
          <div className="node-status" title={isOnline ? "Backend API & Blockchain Node operational" : "Backend service unreachable"}>
            <span className={`status-dot ${isOnline ? '' : 'offline'}`}></span>
            <span>{isOnline ? 'EVM NODE · READY' : 'OFFLINE / DISCONNECTED'}</span>
          </div>

          <button 
            type="button" 
            className="btn btn-secondary btn-sm"
            onClick={onRefresh}
            title="Refresh repository records"
          >
            Refresh
          </button>

          <button 
            type="button" 
            className="btn btn-primary btn-sm"
            onClick={onOpenUpload}
          >
            + Deposit Legal Record
          </button>
        </div>
      </div>
    </header>
  );
}
