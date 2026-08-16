import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function LoginView() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const demoAccounts = [
    {
      role: 'LAWYER',
      title: 'Lawyer / Counsel',
      email: 'lawyer@legalvault.local',
      password: 'lawyer123',
      desc: 'Can deposit records & verify own evidence',
    },
    {
      role: 'JUDGE',
      title: 'Judge / Magistrate',
      email: 'judge@legalvault.local',
      password: 'judge123',
      desc: 'Can inspect & verify authorized dockets',
    },
    {
      role: 'CLIENT',
      title: 'Client / Litigant',
      email: 'client@legalvault.local',
      password: 'client123',
      desc: 'Can view & verify authorized records',
    },
    {
      role: 'ADMIN',
      title: 'Vault Administrator',
      email: 'admin@legalvault.local',
      password: 'admin123',
      desc: 'Full ledger custody & system administration',
    },
  ];

  const handleFillDemo = (acc) => {
    setEmail(acc.email);
    setPassword(acc.password);
    setErrorMessage('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) {
      setErrorMessage('Please provide both email and password.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');

    try {
      await login(email.trim(), password.trim());
    } catch (err) {
      setErrorMessage(err.message || 'Invalid credentials or backend unreachable.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="login-page-container" style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem 1.5rem', backgroundColor: 'var(--bg-app)' }}>
      <div className="login-card" style={{ width: '100%', maxWidth: '520px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-lg)', overflow: 'hidden' }}>
        
        {/* Institutional Gatekeeper Header */}
        <div style={{ padding: '2rem 2rem 1.5rem', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-subtle)', textAlign: 'center' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '44px', height: '44px', border: '1.5px solid var(--ink-primary)', borderRadius: 'var(--radius-xs)', backgroundColor: 'var(--bg-surface)', fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: '1.2rem', marginBottom: '0.85rem' }}>
            LV
          </div>
          <h1 className="serif-heading" style={{ fontSize: '1.45rem', fontWeight: 700, color: 'var(--ink-primary)', lineHeight: 1.2 }}>
            LegalVault Custody Gateway
          </h1>
          <p style={{ fontSize: '0.8rem', color: 'var(--ink-muted)', marginTop: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
            E-Vault Authentication · Protocol v1.0
          </p>
        </div>

        <div style={{ padding: '2rem' }}>
          {errorMessage && (
            <div className="verdict-banner tampered" style={{ marginBottom: '1.5rem', padding: '0.75rem 1rem' }}>
              <div className="verdict-explanation" style={{ margin: 0, fontWeight: 500 }}>
                {errorMessage}
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Institutional Email Address</label>
              <input
                type="email"
                className="form-input"
                placeholder="e.g. lawyer@legalvault.local"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="form-group" style={{ marginBottom: '1.75rem' }}>
              <label className="form-label">Password</label>
              <input
                type="password"
                className="form-input"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', padding: '0.75rem 1rem', fontSize: '0.9rem' }}
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Authenticating...' : 'Sign In to LegalVault'}
            </button>
          </form>

          {/* Development / Demo Autofill Section */}
          <div style={{ marginTop: '2rem', paddingTop: '1.5rem', borderTop: '1px dashed var(--border-strong)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <span className="stat-label" style={{ fontSize: '0.7rem' }}>
                Dev / Demo Credential Autofill
              </span>
              <span style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                Click to populate form
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
              {demoAccounts.map((acc) => (
                <button
                  key={acc.role}
                  type="button"
                  onClick={() => handleFillDemo(acc)}
                  className="btn btn-secondary btn-sm"
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    padding: '0.5rem 0.65rem',
                    textAlign: 'left',
                    height: 'auto',
                  }}
                  title={acc.desc}
                >
                  <span style={{ fontWeight: 600, fontSize: '0.78rem', color: 'var(--ink-primary)' }}>
                    {acc.title}
                  </span>
                  <span style={{ fontSize: '0.68rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
                    {acc.email}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div style={{ padding: '0.85rem 2rem', backgroundColor: 'var(--bg-subtle)', borderTop: '1px solid var(--border-color)', textAlign: 'center', fontSize: '0.72rem', color: 'var(--ink-muted)', fontFamily: 'var(--font-mono)' }}>
          IMMUTABLE LEDGER ACCESS · SIH1284 PROTOTYPE
        </div>
      </div>
    </div>
  );
}
