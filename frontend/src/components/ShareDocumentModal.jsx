import React, { useState, useEffect } from 'react';
import { fetchShareableUsers, shareDocument } from '../services/api';

export default function ShareDocumentModal({ document, isOpen, onClose, onShareSuccess }) {
  const [recipients, setRecipients] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [isLoadingRecipients, setIsLoadingRecipients] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  useEffect(() => {
    if (!isOpen) {
      setSelectedUserId('');
      setErrorMessage('');
      setSuccessMessage('');
      return;
    }

    setIsLoadingRecipients(true);
    fetchShareableUsers()
      .then((users) => {
        setRecipients(users);
        if (users.length > 0) {
          setSelectedUserId(String(users[0].id));
        }
        setIsLoadingRecipients(false);
      })
      .catch((err) => {
        setErrorMessage('Failed to load eligible judicial and client recipients.');
        setIsLoadingRecipients(false);
      });
  }, [isOpen]);

  if (!isOpen || !document) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedUserId) {
      setErrorMessage('Please select a recipient to grant access.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');
    setSuccessMessage('');

    try {
      const res = await shareDocument(document.id, parseInt(selectedUserId, 10));
      setSuccessMessage(`Record successfully shared with ${res.shared_with_name} (${res.shared_with_role}).`);
      if (onShareSuccess) {
        onShareSuccess(res);
      }
      setTimeout(() => {
        onClose();
      }, 1500);
    } catch (err) {
      setErrorMessage(err.message || 'Failed to share record.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">Evault Authorization Protocol</span>
            <h3 className="modal-title">Share Legal Record</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {/* Document Context Card */}
            <div style={{ backgroundColor: 'var(--bg-subtle)', border: '1px solid var(--border-color)', padding: '0.85rem 1rem', borderRadius: 'var(--radius-xs)', marginBottom: '1.25rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                <div>
                  <div className="stat-label">Case Identifier</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.85rem' }}>
                    {document.case_number || 'UNSPECIFIED'}
                  </div>
                </div>
                <div>
                  <div className="stat-label">Document Title</div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--ink-primary)' }}>
                    {document.filename}
                  </div>
                </div>
              </div>
            </div>

            {errorMessage && (
              <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem', padding: '0.75rem 1rem' }}>
                <div className="verdict-explanation" style={{ margin: 0, fontWeight: 500 }}>
                  {errorMessage}
                </div>
              </div>
            )}

            {successMessage && (
              <div className="verdict-banner verified" style={{ marginBottom: '1.25rem', padding: '0.75rem 1rem' }}>
                <div className="verdict-explanation" style={{ margin: 0, fontWeight: 500 }}>
                  {successMessage}
                </div>
              </div>
            )}

            {/* Recipient Selection */}
            <div className="form-group">
              <label className="form-label">Authorized Recipient (Judge or Client)</label>
              {isLoadingRecipients ? (
                <div style={{ fontSize: '0.82rem', color: 'var(--ink-muted)' }}>Loading recipient registry...</div>
              ) : recipients.length === 0 ? (
                <div style={{ fontSize: '0.82rem', color: 'var(--ink-muted)' }}>No eligible Judge or Client recipients found.</div>
              ) : (
                <select
                  className="form-input"
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  required
                >
                  {recipients.map((u) => (
                    <option key={u.id} value={u.id}>
                      [{u.role}] {u.name} — {u.email}
                    </option>
                  ))}
                </select>
              )}
              <div className="form-helper">
                Granting access enables the selected party to inspect, verify on-chain integrity, and download this evidentiary record.
              </div>
            </div>

            {/* Granted Permissions List */}
            <div style={{ marginTop: '1.25rem', borderTop: '1px solid var(--border-color)', paddingTop: '1rem' }}>
              <span className="stat-label" style={{ marginBottom: '0.5rem', display: 'block' }}>
                Granted Evault Permissions
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--ink-secondary)' }}>
                <div>✓ <strong>Inspect &amp; View</strong> — Access off-chain evidence record &amp; provenance trail</div>
                <div>✓ <strong>Verify Cryptographic Hash</strong> — Run live SHA-256 verification against Ethereum smart contract</div>
                <div>✓ <strong>Download File</strong> — Retrieve stored authentic PDF document</div>
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSubmitting || isLoadingRecipients || recipients.length === 0}
            >
              {isSubmitting ? 'Authorizing Share...' : 'Authorize & Share Record'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
