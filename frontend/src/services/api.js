/**
 * LegalVault API Service
 * Interacts with the FastAPI backend on http://127.0.0.1:8000
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

function getAuthHeader() {
  const token = localStorage.getItem('legalvault_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function checkApiHealth() {
  try {
    const res = await fetch(`${API_BASE}/`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('API health check failed:', err);
    throw err;
  }
}

export async function loginUser(email, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Authentication failed (${res.status})`);
  }

  return await res.json();
}

export async function fetchCurrentUser() {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Session verification failed (${res.status})`);
  }

  return await res.json();
}

export async function fetchDocuments() {
  const res = await fetch(`${API_BASE}/documents`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch documents (${res.status})`);
  }

  return await res.json();
}

export async function fetchDocumentDetail(documentId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Document #${documentId} not found`);
  }

  return await res.json();
}

export function getDocumentDownloadUrl(documentId) {
  return `${API_BASE}/documents/${documentId}/download`;
}

export async function downloadDocumentFile(documentId, filename) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/download`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Download failed (${res.status})`);
  }

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || `document_${documentId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function uploadDocument({ file, caseNumber, uploadedBy }) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('case_number', caseNumber);
  formData.append('uploaded_by', uploadedBy);

  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Upload failed with status ${res.status}`);
  }

  return await res.json();
}

export async function verifyDocument(documentId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/verify`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Verification failed with status ${res.status}`);
  }

  return await res.json();
}

// --- Sharing API Functions ---

export async function fetchShareableUsers() {
  const res = await fetch(`${API_BASE}/users/shareable`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch recipients (${res.status})`);
  }

  return await res.json();
}

export async function shareDocument(documentId, targetUserId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/share`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeader(),
    },
    body: JSON.stringify({ shared_with_user_id: targetUserId }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to share document (${res.status})`);
  }

  return await res.json();
}

export async function fetchDocumentShares(documentId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/shares`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch shares (${res.status})`);
  }

  return await res.json();
}

export async function revokeDocumentShare(documentId, shareId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/shares/${shareId}`, {
    method: 'DELETE',
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to revoke share (${res.status})`);
  }

  return await res.json();
}
