/**
 * Centralized Timezone & Timestamp Utility for LegalVault
 *
 * Standardizes all date and timestamp handling to Indian Standard Time (IST, UTC+05:30)
 * using the canonical IANA timezone 'Asia/Kolkata'.
 *
 * All backend timestamps and blockchain block timestamps are stored/transmitted as
 * canonical UTC (ISO 8601 with 'Z' or Unix epoch seconds). This module ensures consistent,
 * user-facing IST representation across any browser or host machine timezone.
 */

export const IANA_TIMEZONE = 'Asia/Kolkata';
export const TIMEZONE_LABEL = 'IST';

/**
 * Safely parses any date/timestamp representation into a valid UTC Date object.
 *
 * Supported formats:
 * - Date object
 * - Unix timestamp in seconds or milliseconds (number or numeric string)
 * - ISO 8601 string with 'Z' or timezone offset (e.g. '2026-08-16T08:45:00.000Z')
 * - Legacy naive ISO strings (e.g. '2026-08-16 08:45:00') are explicitly parsed as UTC
 *
 * @param {Date|string|number|null|undefined} input
 * @returns {Date|null} Date object representing the UTC instant, or null if invalid.
 */
export function parseUtcInstant(input) {
  if (input === null || input === undefined || input === '') {
    return null;
  }

  if (input instanceof Date) {
    return isNaN(input.getTime()) ? null : input;
  }

  if (typeof input === 'number') {
    if (input === 0 || isNaN(input)) return null;
    // Distinguish seconds (< 1e11) from milliseconds
    const ms = input < 1e11 ? input * 1000 : input;
    const date = new Date(ms);
    return isNaN(date.getTime()) ? null : date;
  }

  if (typeof input === 'string') {
    const trimmed = input.trim();
    if (!trimmed) return null;

    // Check if string is a numeric timestamp (e.g., '1786874299')
    if (/^\d+$/.test(trimmed)) {
      const num = parseInt(trimmed, 10);
      if (num === 0 || isNaN(num)) return null;
      const ms = num < 1e11 ? num * 1000 : num;
      const date = new Date(ms);
      return isNaN(date.getTime()) ? null : date;
    }

    // Normalize ISO string (replace space with T, append Z if naive)
    let iso = trimmed.replace(' ', 'T');
    if (!iso.endsWith('Z') && !/[+-]\d{2}(:\d{2})?$/.test(iso)) {
      iso += 'Z';
    }

    const date = new Date(iso);
    return isNaN(date.getTime()) ? null : date;
  }

  return null;
}

/**
 * Formats a UTC instant to Indian Standard Time (IST) Date and Time.
 * Example: '16 Aug 2026, 2:15 PM IST' or '16 Aug 2026 • 2:15 PM IST'
 *
 * @param {Date|string|number|null|undefined} input
 * @param {object} [options]
 * @param {boolean} [options.includeSeconds=false]
 * @param {string} [options.separator=', ']
 * @returns {string} Formatted IST datetime string or '—' if empty/invalid.
 */
export function formatISTDateTime(input, { includeSeconds = false, separator = ', ' } = {}) {
  const date = parseUtcInstant(input);
  if (!date) return '—';

  try {
    const dateStr = new Intl.DateTimeFormat('en-IN', {
      timeZone: IANA_TIMEZONE,
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    }).format(date);

    const timeOptions = {
      timeZone: IANA_TIMEZONE,
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    };
    if (includeSeconds) {
      timeOptions.second = '2-digit';
    }

    const timeStr = new Intl.DateTimeFormat('en-IN', timeOptions)
      .format(date)
      .replace(/am|pm/i, (match) => match.toUpperCase());

    return `${dateStr}${separator}${timeStr} ${TIMEZONE_LABEL}`;
  } catch (err) {
    console.warn('Timezone formatting error:', err);
    return String(input);
  }
}

/**
 * Formats a UTC instant to Indian Standard Time (IST) Date only.
 * Example: '16 Aug 2026'
 *
 * @param {Date|string|number|null|undefined} input
 * @returns {string} Formatted IST date string or '—' if empty/invalid.
 */
export function formatISTDate(input) {
  const date = parseUtcInstant(input);
  if (!date) return '—';

  try {
    return new Intl.DateTimeFormat('en-IN', {
      timeZone: IANA_TIMEZONE,
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    }).format(date);
  } catch (err) {
    console.warn('Timezone date formatting error:', err);
    return String(input);
  }
}

/**
 * Formats a blockchain block timestamp (Unix epoch seconds) to Indian Standard Time.
 * Example: '16 Aug 2026, 2:15 PM IST'
 *
 * @param {number|string|null|undefined} ts - Unix epoch timestamp in seconds.
 * @returns {string} Formatted IST datetime string or 'Not recorded' if missing.
 */
export function formatBlockTimestampIST(ts) {
  if (!ts || ts === 0 || ts === '0') {
    return 'Not recorded';
  }
  const formatted = formatISTDateTime(ts);
  return formatted === '—' ? 'Not recorded' : formatted;
}

/**
 * Generates a live presentation timestamp formatted in Indian Standard Time with seconds.
 * Note: Authoritative forensic audit timestamps must be provided by the backend in UTC.
 * This helper is only for presentation / live client UI elements.
 *
 * @returns {string} Current timestamp in IST with seconds (e.g. '16 Aug 2026, 2:15:30 PM IST')
 */
export function getLiveAuditTimestampIST() {
  return formatISTDateTime(new Date(), { includeSeconds: true });
}
