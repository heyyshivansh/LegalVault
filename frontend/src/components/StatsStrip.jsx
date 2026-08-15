import React from 'react';

export default function StatsStrip({ documents = [] }) {
  const total = documents.length;
  const confirmed = documents.filter(d => d.blockchain_status === 'confirmed').length;
  const pendingOrFailed = total - confirmed;

  return (
    <div className="registry-stats-strip">
      <div className="stat-cell">
        <div className="stat-label">Total Vault Records</div>
        <div className="stat-value">{total}</div>
        <div className="stat-subtext">Cryptographic Custody</div>
      </div>

      <div className="stat-cell">
        <div className="stat-label">On-Chain Anchored</div>
        <div className="stat-value" style={{ color: 'var(--status-verified-text)' }}>
          {confirmed}
        </div>
        <div className="stat-subtext">Immutable Smart Contract</div>
      </div>

      <div className="stat-cell">
        <div className="stat-label">Pending / Unanchored</div>
        <div className="stat-value" style={{ color: pendingOrFailed > 0 ? 'var(--status-pending-text)' : 'var(--ink-muted)' }}>
          {pendingOrFailed}
        </div>
        <div className="stat-subtext">Awaiting EVM Finality</div>
      </div>

      <div className="stat-cell">
        <div className="stat-label">Security Standard</div>
        <div className="stat-value" style={{ fontSize: '1.25rem', paddingTop: '0.2rem' }}>
          SHA-256 / EVM
        </div>
        <div className="stat-subtext">Off-Chain Custody + On-Chain Proof</div>
      </div>
    </div>
  );
}
