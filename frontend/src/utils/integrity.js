/**
 * Utility functions for computing and inspecting document and version integrity statuses.
 */

/**
 * Retrieves the verification record for a specific document version.
 *
 * @param {number|string} docId - The ID of the document.
 * @param {number|string} versionNumber - The version number (1, 2, etc.).
 * @param {object} integrityResults - The global integrity cache dictionary.
 * @returns {object|null} The version's verification result object or null if unverified.
 */
export function getVersionIntegrity(docId, versionNumber, integrityResults) {
  if (!docId || !versionNumber || !integrityResults) return null;
  const docData = integrityResults[docId];
  if (!docData) return null;

  // Direct version lookup from versions map
  if (docData.versions && docData.versions[versionNumber]) {
    return docData.versions[versionNumber];
  }

  // Fallback for legacy / single-version result
  if (docData.version_number === Number(versionNumber) || (!docData.versions && Number(versionNumber) === 1)) {
    return docData;
  }

  return null;
}

/**
 * Calculates the overall document integrity based on all verified versions for that document.
 *
 * Rules:
 * 1. If ANY verified version is TAMPERED, overall status is TAMPERED and lists affected versions.
 * 2. If NO version is TAMPERED, but ANY verified version has BLOCKCHAIN_PROOF_UNAVAILABLE, status is BLOCKCHAIN_PROOF_UNAVAILABLE.
 * 3. If at least one version is verified and ALL verified versions are VERIFIED, status is VERIFIED.
 * 4. If no version has been verified, status is UNVERIFIED.
 *
 * @param {number|string} docId - The document ID.
 * @param {object} integrityResults - The global integrity results cache.
 * @returns {object} Calculated integrity status object.
 */
export function getDocumentIntegrity(docId, integrityResults) {
  if (!docId || !integrityResults) {
    return {
      hasResults: false,
      status: 'UNVERIFIED',
      tamperedVersions: [],
      verifiedVersions: [],
      unavailableVersions: [],
      affectedLabel: '',
      summaryText: 'Unverified',
    };
  }

  const docData = integrityResults[docId];
  if (!docData) {
    return {
      hasResults: false,
      status: 'UNVERIFIED',
      tamperedVersions: [],
      verifiedVersions: [],
      unavailableVersions: [],
      affectedLabel: '',
      summaryText: 'Unverified',
    };
  }

  // Collect all version records
  let versionMap = {};
  if (docData.versions && Object.keys(docData.versions).length > 0) {
    versionMap = docData.versions;
  } else if (docData.result) {
    const vNum = docData.version_number || docData.version || 1;
    versionMap = { [vNum]: docData };
  }

  const entries = Object.entries(versionMap);
  if (entries.length === 0) {
    return {
      hasResults: false,
      status: 'UNVERIFIED',
      tamperedVersions: [],
      verifiedVersions: [],
      unavailableVersions: [],
      affectedLabel: '',
      summaryText: 'Unverified',
    };
  }

  const tampered = [];
  const unavailable = [];
  const verified = [];

  for (const [vNumStr, res] of entries) {
    const vNum = parseInt(vNumStr, 10);
    if (res.result === 'TAMPERED' || (res.verified === false && res.result !== 'BLOCKCHAIN_PROOF_UNAVAILABLE')) {
      tampered.push(vNum);
    } else if (res.result === 'BLOCKCHAIN_PROOF_UNAVAILABLE') {
      unavailable.push(vNum);
    } else if (res.result === 'VERIFIED' || res.verified === true) {
      verified.push(vNum);
    }
  }

  tampered.sort((a, b) => a - b);
  unavailable.sort((a, b) => a - b);
  verified.sort((a, b) => a - b);

  // If ANY version is tampered, overall status is strictly TAMPERED
  if (tampered.length > 0) {
    const affectedLabel = tampered.map((v) => `v${v}`).join(', ');
    return {
      hasResults: true,
      status: 'TAMPERED',
      tamperedVersions: tampered,
      verifiedVersions: verified,
      unavailableVersions: unavailable,
      affectedLabel,
      summaryText: `TAMPERED · ${affectedLabel}`,
    };
  }

  // If blockchain proof is missing/unavailable
  if (unavailable.length > 0) {
    const affectedLabel = unavailable.map((v) => `v${v}`).join(', ');
    return {
      hasResults: true,
      status: 'BLOCKCHAIN_PROOF_UNAVAILABLE',
      tamperedVersions: [],
      verifiedVersions: verified,
      unavailableVersions: unavailable,
      affectedLabel,
      summaryText: `PROOF UNAVAILABLE · ${affectedLabel}`,
    };
  }

  // All verified versions are valid!
  if (verified.length > 0) {
    const affectedLabel = verified.map((v) => `v${v}`).join(', ');
    return {
      hasResults: true,
      status: 'VERIFIED',
      tamperedVersions: [],
      verifiedVersions: verified,
      unavailableVersions: [],
      affectedLabel,
      summaryText: `VERIFIED · ${affectedLabel}`,
    };
  }

  return {
    hasResults: false,
    status: 'UNVERIFIED',
    tamperedVersions: [],
    verifiedVersions: [],
    unavailableVersions: [],
    affectedLabel: '',
    summaryText: 'Unverified',
  };
}
