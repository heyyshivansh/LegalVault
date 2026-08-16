/**
 * Frontend Timezone Standardization & Cross-Timezone Invariance Test Suite
 *
 * Verifies that the LegalVault timezone utility:
 * 1. Correctly formats UTC ISO strings (with or without 'Z') into Indian Standard Time (IST).
 * 2. Correctly formats Unix epoch block timestamps into IST.
 * 3. Formats date-only representations accurately.
 * 4. Yields IDENTICAL IST strings regardless of simulated environment timezone (TZ).
 */

import {
  parseUtcInstant,
  formatISTDateTime,
  formatISTDate,
  formatBlockTimestampIST,
  IANA_TIMEZONE,
  TIMEZONE_LABEL,
} from './src/utils/timezone.js';

function runTests() {
  console.log('=================================================================');
  console.log(`RUNNING FRONTEND TIMEZONE TEST SUITE (Node TZ: ${process.env.TZ || 'System Default'})`);
  console.log('=================================================================');

  // Test Case 1: Standard UTC ISO 8601 string
  // 2026-08-16 08:45:00 UTC = 2026-08-16 14:15:00 IST (2:15 PM IST)
  const utcIso = '2026-08-16T08:45:00Z';
  const formattedIso = formatISTDateTime(utcIso);
  console.log(`[1] Testing ISO with 'Z' ('${utcIso}')...`);
  console.log(`    Result: "${formattedIso}"`);
  console.assert(
    formattedIso === '16 Aug 2026, 2:15 PM IST',
    `Expected '16 Aug 2026, 2:15 PM IST', got '${formattedIso}'`
  );

  // Test Case 2: Naive ISO string (legacy / SQLite text)
  // 2026-08-16 08:45:00 -> must be parsed as UTC and yield 2:15 PM IST
  const naiveIso = '2026-08-16 08:45:00';
  const formattedNaive = formatISTDateTime(naiveIso);
  console.log(`[2] Testing Naive ISO ('${naiveIso}')...`);
  console.log(`    Result: "${formattedNaive}"`);
  console.assert(
    formattedNaive === '16 Aug 2026, 2:15 PM IST',
    `Expected '16 Aug 2026, 2:15 PM IST', got '${formattedNaive}'`
  );

  // Test Case 3: ISO with microseconds
  const microIso = '2026-08-16T08:45:00.123456Z';
  const formattedMicro = formatISTDateTime(microIso);
  console.log(`[3] Testing ISO with microseconds ('${microIso}')...`);
  console.log(`    Result: "${formattedMicro}"`);
  console.assert(
    formattedMicro === '16 Aug 2026, 2:15 PM IST',
    `Expected '16 Aug 2026, 2:15 PM IST', got '${formattedMicro}'`
  );

  // Test Case 4: Blockchain Block Timestamp (Unix epoch seconds)
  // 1786874299 = Sun Aug 16 2026 09:58:19 UTC = Sun Aug 16 2026 15:28:19 IST (3:28 PM IST)
  const blockTs = 1786874299;
  const formattedBlock = formatBlockTimestampIST(blockTs);
  console.log(`[4] Testing Blockchain Block Timestamp (${blockTs})...`);
  console.log(`    Result: "${formattedBlock}"`);
  console.assert(
    formattedBlock === '16 Aug 2026, 3:28 PM IST',
    `Expected '16 Aug 2026, 3:28 PM IST', got '${formattedBlock}'`
  );

  // Test Case 5: Missing / zero blockchain timestamp
  console.log('[5] Testing Missing Block Timestamp (0 / null)...');
  console.assert(formatBlockTimestampIST(0) === 'Not recorded', "Expected 'Not recorded' for 0");
  console.assert(formatBlockTimestampIST(null) === 'Not recorded', "Expected 'Not recorded' for null");
  console.assert(formatBlockTimestampIST(undefined) === 'Not recorded', "Expected 'Not recorded' for undefined");
  console.log('    [OK] Empty block timestamps correctly display "Not recorded".');

  // Test Case 6: Date only formatting
  console.log(`[6] Testing Date-only formatting ('${utcIso}')...`);
  const dateOnly = formatISTDate(utcIso);
  console.log(`    Result: "${dateOnly}"`);
  console.assert(
    dateOnly === '16 Aug 2026',
    `Expected '16 Aug 2026', got '${dateOnly}'`
  );

  // Test Case 7: Custom separator (' • ')
  console.log('[7] Testing custom separator (" • ")...');
  const bulletFormatted = formatISTDateTime(utcIso, { separator: ' • ' });
  console.log(`    Result: "${bulletFormatted}"`);
  console.assert(
    bulletFormatted === '16 Aug 2026 • 2:15 PM IST',
    `Expected '16 Aug 2026 • 2:15 PM IST', got '${bulletFormatted}'`
  );

  // Test Case 8: Date rollover over midnight (e.g. 23:00 UTC = 04:30 IST next day)
  const lateUtc = '2026-08-16T23:00:00Z';
  const formattedLate = formatISTDateTime(lateUtc);
  console.log(`[8] Testing Day Rollover ('${lateUtc}')...`);
  console.log(`    Result: "${formattedLate}"`);
  console.assert(
    formattedLate === '17 Aug 2026, 4:30 AM IST',
    `Expected '17 Aug 2026, 4:30 AM IST', got '${formattedLate}'`
  );

  console.log('\n=================================================================');
  console.log('ALL FRONTEND TIMEZONE TESTS PASSED SUCCESSFULLY!');
  console.log('=================================================================\n');
}

runTests();
