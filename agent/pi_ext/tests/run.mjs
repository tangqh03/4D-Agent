/**
 * Active S2.8 test runner. Historical closure/ledger coverage remains in
 * run_legacy.mjs but is not part of the current-flow gate.
 *
 * Usage:
 *   node agent/pi_ext/tests/run.mjs                 # all tests
 *   node agent/pi_ext/tests/run.mjs --filter ledger  # subset by name
 *   node agent/pi_ext/tests/run.mjs --filter=ledger # equivalent spelling
 */
import { runRegisteredTests } from "./harness.mjs";

await import("./video_tools.test.mjs");

const filterIndex = process.argv.findIndex((a) => a === "--filter");
const filter = filterIndex >= 0
	? process.argv[filterIndex + 1]
	: process.argv.find((a) => a.startsWith("--filter="))?.slice("--filter=".length);
await runRegisteredTests(filter);
