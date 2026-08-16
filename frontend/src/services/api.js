/**
 * LegalVault API Service
 * Interacts with the FastAPI backend on http://127.0.0.1:8000
 */

const API_BASE = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Authentication failed');
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
    throw new Error('Session expired or invalid token');
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

export async function fetchDocumentById(documentId) {
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

export const fetchDocumentDetail = fetchDocumentById;

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

export async function uploadDocument({ file, caseNumber, uploadedBy, allowDuplicate = false }) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('case_number', caseNumber);
  if (uploadedBy) {
    formData.append('uploaded_by', uploadedBy);
  }
  if (allowDuplicate) {
    formData.append('allow_duplicate', 'true');
  }

  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const errorMsg = typeof err.detail === 'string' ? err.detail : err.detail?.message || `Upload failed with status ${res.status}`;
    const errorObj = new Error(errorMsg);
    errorObj.status = res.status;
    errorObj.data = err.detail || err;
    throw errorObj;
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
    const errorMsg = typeof err.detail === 'string' ? err.detail : err.detail?.message || `Integrity verification failed with status ${res.status}`;
    const errorObj = new Error(errorMsg);
    errorObj.status = res.status;
    errorObj.data = err.detail || err;
    throw errorObj;
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

export async function resetDevelopmentVault() {
  const res = await fetch(`${API_BASE}/admin/dev/reset-vault`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to reset development vault (${res.status})`);
  }

  return await res.json();
}

// --- Version History API Functions ---

export async function fetchDocumentVersions(documentId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch versions for document #${documentId}`);
  }

  return await res.json();
}

export async function fetchVersionDetail(documentId, versionIdentifier) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions/${versionIdentifier}`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Version ${versionIdentifier} not found`);
  }

  return await res.json();
}

export async function uploadDocumentVersion(documentId, { file, uploadedBy, allowDuplicate = false }) {
  const formData = new FormData();
  formData.append('file', file);
  if (uploadedBy) {
    formData.append('uploaded_by', uploadedBy);
  }
  if (allowDuplicate) {
    formData.append('allow_duplicate', 'true');
  }

  const res = await fetch(`${API_BASE}/documents/${documentId}/versions`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const errorMsg = typeof err.detail === 'string' ? err.detail : err.detail?.message || `Version upload failed with status ${res.status}`;
    const errorObj = new Error(errorMsg);
    errorObj.status = res.status;
    errorObj.data = err.detail || err;
    throw errorObj;
  }

  return await res.json();
}

export async function downloadVersionFile(documentId, versionIdentifier, filename) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions/${versionIdentifier}/download`, {
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
  a.download = filename || `document_${documentId}_v${versionIdentifier}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function verifyDocumentVersion(documentId, versionIdentifier) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions/${versionIdentifier}/verify`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const errorMsg = typeof err.detail === 'string' ? err.detail : err.detail?.message || `Version verification failed with status ${res.status}`;
    const errorObj = new Error(errorMsg);
    errorObj.status = res.status;
    errorObj.data = err.detail || err;
    throw errorObj;
  }

  return await res.json();
}

export async function logoutUser() {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: {
        ...getAuthHeader(),
      },
    });
  } catch (err) {
    console.warn('Backend logout notification failed:', err);
  } finally {
    localStorage.removeItem('legalvault_token');
  }
}


// --- Audit Trail API Functions ---

export async function fetchDocumentAuditTrail(documentId, params = {}) {
  const query = new URLSearchParams();
  if (params.limit) query.append('limit', params.limit);
  if (params.offset) query.append('offset', params.offset);
  if (params.action) query.append('action', params.action);
  if (params.version_number !== undefined && params.version_number !== null) {
    query.append('version_number', params.version_number);
  }
  if (params.result) query.append('result', params.result);

  const qs = query.toString() ? `?${query.toString()}` : '';
  const res = await fetch(`${API_BASE}/documents/${documentId}/audit${qs}`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch audit trail for document #${documentId}`);
  }

  return await res.json();
}

export async function fetchSystemAuditTrail(params = {}) {
  const query = new URLSearchParams();
  if (params.limit) query.append('limit', params.limit);
  if (params.offset) query.append('offset', params.offset);
  if (params.action) query.append('action', params.action);
  if (params.actor_id) query.append('actor_id', params.actor_id);
  if (params.document_id) query.append('document_id', params.document_id);
  if (params.result) query.append('result', params.result);

  const qs = query.toString() ? `?${query.toString()}` : '';
  const res = await fetch(`${API_BASE}/audit${qs}`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch system audit trail`);
  }

  return await res.json();
}

export async function fetchAdminDashboard() {
  const res = await fetch(`${API_BASE}/admin/dashboard`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch admin dashboard data`);
  }

  return await res.json();
}

// --- AI Metadata API Functions ---

export async function extractVersionMetadata(documentId, versionIdentifier, force = false) {
  const url = `${API_BASE}/documents/${documentId}/versions/${versionIdentifier}/metadata/extract?force=${force ? 'true' : 'false'}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const errorMsg = typeof err.detail === 'string' ? err.detail : err.detail?.message || `AI metadata extraction failed with status ${res.status}`;
    const errorObj = new Error(errorMsg);
    errorObj.status = res.status;
    errorObj.data = err.detail || err;
    throw errorObj;
  }

  return await res.json();
}

export async function fetchVersionMetadata(documentId, versionIdentifier) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions/${versionIdentifier}/metadata`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch metadata for Version ${versionIdentifier}`);
  }

  return await res.json();
}

export async function fetchDocumentMetadata(documentId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/metadata`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch metadata for document #${documentId}`);
  }

  return await res.json();
}

// --- AI Summarization API Endpoints ---

export async function generateVersionSummary(documentId, versionIdentifier, force = false) {
  const query = force ? '?force=true' : '';
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions/${versionIdentifier}/summary${query}`, {
    method: 'POST',
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const errorMsg = typeof err.detail === 'string' ? err.detail : err.detail?.message || `AI summarization failed with status ${res.status}`;
    const errorObj = new Error(errorMsg);
    errorObj.status = res.status;
    errorObj.data = err.detail || err;
    throw errorObj;
  }

  return await res.json();
}

export async function fetchVersionSummary(documentId, versionIdentifier) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/versions/${versionIdentifier}/summary`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch summary for Version ${versionIdentifier}`);
  }

  return await res.json();
}

export async function fetchDocumentSummary(documentId) {
  const res = await fetch(`${API_BASE}/documents/${documentId}/summary`, {
    headers: {
      ...getAuthHeader(),
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch summary for document #${documentId}`);
  }

  return await res.json();
}


