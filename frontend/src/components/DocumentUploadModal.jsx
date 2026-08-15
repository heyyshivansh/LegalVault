import React, { useState, useRef } from 'react';
import { uploadDocument } from '../services/api';

export default function DocumentUploadModal({ isOpen, onClose, onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [clientHash, setClientHash] = useState('');
  const [isHashing, setIsHashing] = useState(false);
  const [caseNumber, setCaseNumber] = useState('');
  const [uploadedBy, setUploadedBy] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [uploadResult, setUploadResult] = useState(null);

  const fileInputRef = useRef(null);

  if (!isOpen) return null;

  // Compute SHA-256 in browser using Web Crypto API
  const calculateSha256 = async (selectedFile) => {
    setIsHashing(true);
    setClientHash('');
    try {
      const arrayBuffer = await selectedFile.arrayBuffer();
      const hashBuffer = await crypto.subtle.digest('SHA-256', arrayBuffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
      setClientHash(hashHex);
    } catch (err) {
      console.warn('Could not compute client-side SHA-256:', err);
    } finally {
      setIsHashing(false);
    }
  };

  const handleFileChange = (e) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      calculateSha256(selected);
      setErrorMessage('');
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      setFile(dropped);
      calculateSha256(dropped);
      setErrorMessage('');
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) {
      setErrorMessage('Please select a legal document to deposit.');
      return;
    }
    if (!caseNumber.trim()) {
      setErrorMessage('Please provide a valid Case Reference Number.');
      return;
    }
    if (!uploadedBy.trim()) {
      setErrorMessage('Please enter the Authorized Depositor name or title.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');

    try {
      const result = await uploadDocument({
        file,
        caseNumber: caseNumber.trim(),
        uploadedBy: uploadedBy.trim(),
      });

      setUploadResult(result);
      if (onUploadSuccess) {
        onUploadSuccess(result);
      }
    } catch (err) {
      setErrorMessage(err.message || 'Deposit failed. Please ensure the backend and blockchain are connected.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setClientHash('');
    setCaseNumber('');
    setUploadedBy('');
    setErrorMessage('');
    setUploadResult(null);
  };

  const handleClose = () => {
    handleReset();
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-meta">
            <span className="modal-pretitle">Evault Intake Protocol</span>
            <h3 className="modal-title">Deposit Legal Record</h3>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleClose}>
            ✕
          </button>
        </div>

        {uploadResult ? (
          <div className="modal-body">
            <div className="verdict-banner verified" style={{ marginBottom: '1.25rem' }}>
              <div>
                <div className="verdict-headline">RECORD REGISTERED ON-CHAIN</div>
                <div className="verdict-subheadline">
                  Document ID #{uploadResult.document_id} · SHA-256 Registered
                </div>
                <div className="verdict-explanation">
                  The document has been securely stored off-chain and its cryptographic proof anchored into the Ethereum smart contract.
                </div>
              </div>
            </div>

            <table className="provenance-table">
              <tbody>
                <tr>
                  <td className="field-name">Document Title</td>
                  <td className="field-val">{uploadResult.filename}</td>
                </tr>
                <tr>
                  <td className="field-name">Generated SHA-256</td>
                  <td className="field-val">
                    <span className="hash-tag">{uploadResult.file_hash}</span>
                  </td>
                </tr>
                <tr>
                  <td className="field-name">Blockchain TX Hash</td>
                  <td className="field-val">
                    <span className="hash-tag">{uploadResult.blockchain_tx_hash || 'Pending...'}</span>
                  </td>
                </tr>
                <tr>
                  <td className="field-name">On-Chain Status</td>
                  <td className="field-val">
                    <span className="badge badge-confirmed">
                      ● {uploadResult.blockchain_status}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>

            <div style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
              <button type="button" className="btn btn-secondary" onClick={handleReset}>
                Deposit Another Document
              </button>
              <button type="button" className="btn btn-primary" onClick={handleClose}>
                Done &amp; View Repository
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="modal-body">
              {errorMessage && (
                <div className="verdict-banner tampered" style={{ marginBottom: '1.25rem', padding: '0.75rem 1rem' }}>
                  <div className="verdict-explanation" style={{ margin: 0, fontWeight: 500 }}>
                    {errorMessage}
                  </div>
                </div>
              )}

              {/* File Dropzone */}
              <div className="form-group">
                <label className="form-label">Legal Document File (.pdf, .docx, .txt)</label>
                <div
                  className="dropzone"
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    style={{ display: 'none' }}
                    onChange={handleFileChange}
                  />
                  {file ? (
                    <div>
                      <div className="dropzone-title" style={{ color: 'var(--accent-navy)' }}>
                        {file.name}
                      </div>
                      <div className="dropzone-subtitle">
                        {(file.size / 1024).toFixed(1)} KB · Click to change file
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="dropzone-title">Click to select or drag and drop legal document</div>
                      <div className="dropzone-subtitle">
                        Supported formats: PDF, DOCX, TXT, scanned court dockets
                      </div>
                    </div>
                  )}
                </div>

                {/* Real-time Client-Side SHA256 Preview */}
                {isHashing && (
                  <div className="form-helper mono-text" style={{ color: 'var(--ink-muted)' }}>
                    Computing cryptographic SHA-256 fingerprint...
                  </div>
                )}
                {clientHash && !isHashing && (
                  <div style={{ marginTop: '0.5rem' }}>
                    <span className="form-label" style={{ fontSize: '0.68rem', marginBottom: '0.2rem' }}>
                      Calculated Client Fingerprint (SHA-256):
                    </span>
                    <div className="hash-tag" style={{ width: '100%', wordBreak: 'break-all' }}>
                      {clientHash}
                    </div>
                  </div>
                )}
              </div>

              {/* Metadata Fields */}
              <div className="form-group">
                <label className="form-label">Case Identifier / Docket Reference</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. CASE-SIH-2026-001 or CRL-4412/2024"
                  value={caseNumber}
                  onChange={(e) => setCaseNumber(e.target.value)}
                  required
                />
                <div className="form-helper">
                  Assigned court docket number, arbitral file code, or judicial registry ID.
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Authorized Depositor / Counsel Name</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="e.g. Advocate Rajesh Sharma / High Court Registrar"
                  value={uploadedBy}
                  onChange={(e) => setUploadedBy(e.target.value)}
                  required
                />
                <div className="form-helper">
                  Identity of authorized party or legal institution depositing the record.
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleClose}
                disabled={isSubmitting}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={isSubmitting || !file}
              >
                {isSubmitting ? 'Registering on Blockchain...' : 'Deposit & Anchor Record'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
