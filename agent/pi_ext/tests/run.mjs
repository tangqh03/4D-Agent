/**
 * Test runner: imports every *.test.mjs, runs all registered tests.
 *
 * Usage:
 *   node agent/pi_ext/tests/run.mjs                 # all tests
 *   node agent/pi_ext/tests/run.mjs --filter ledger  # subset by name
 *   node agent/pi_ext/tests/run.mjs --filter=ledger # equivalent spelling
 */
import { runRegisteredTests } from "./harness.mjs";

await import("./helpers.test.mjs");
await import("./ledger.test.mjs");
await import("./submit_answer.test.mjs");
await import("./video_tools.test.mjs");

const filterIndex = process.argv.findIndex((a) => a === "--filter");
const filter = filterIndex >= 0
	? process.argv[filterIndex + 1]
	: process.argv.find((a) => a.startsWith("--filter="))?.slice("--filter=".length);
await runRegisteredTests(filter);
