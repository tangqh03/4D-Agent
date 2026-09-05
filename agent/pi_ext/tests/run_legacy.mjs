/** Full historical extension suite, including inactive closure/ledger layers. */
import { runRegisteredTests } from "./harness.mjs";

await import("./helpers.test.mjs");
await import("./ledger.test.mjs");
await import("./submit_answer.test.mjs");
await import("./video_tools.test.mjs");

await runRegisteredTests();
