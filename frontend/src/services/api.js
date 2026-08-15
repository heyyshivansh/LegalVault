/**
 * LegalVault API Service
 * Interacts with the FastAPI backend on http://127.0.0.1:8000
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

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

export async function fetchDocuments() {
  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch documents (${res.status})`);
    }
    return await res.json();
  } catch (err) {
    console.error('Error fetching documents:', err);
    throw err;
  }
}

export async function fetchDocumentDetail(documentId) {
  try {
    const res = await fetch(`${API_BASE}/documents/${documentId}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Document #${documentId} not found`);
    }
    return await res.json();
  } catch (err) {
    console.error(`Error fetching document #${documentId}:`, err);
    throw err;
  }
}

export function getDocumentDownloadUrl(documentId) {
  return `${API_BASE}/documents/${documentId}/download`;
}

export async function uploadDocument({ file, caseNumber, uploadedBy }) {
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('case_number', caseNumber);
    formData.append('uploaded_by', uploadedBy);

    const res = await fetch(`${API_BASE}/documents/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed with status ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error('Error uploading document:', err);
    throw err;
  }
}

export async function verifyDocument(documentId) {
  try {
    const res = await fetch(`${API_BASE}/documents/${documentId}/verify`, {
      method: 'POST',
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Verification failed with status ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`Error verifying document #${documentId}:`, err);
    throw err;
  }
}
