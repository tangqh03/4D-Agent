/**
 * submit_answer tool tests: every branch of the evidence-closure gate,
 * with the VLM checker fetch stubbed. Exercises the REAL extension code.
 */
import assert from "node:assert/strict";
import { test, loadExtension, createMockAPI, installFetch, textBlocks } from "./harness.mjs";

async function makeClosure(routes) {
	const mock = createMockAPI();
	const stub = installFetch(routes);
	(await loadExtension("/workspace/Spatial-Agent/4D-Agent/agent/pi_ext/evidence_closure.ts")).default(mock.api);
	const tool = mock.tools.get("submit_answer");
	assert.ok(tool, "submit_answer must be registered");
	const run = (params) => tool.execute("call_1", params);
	return { ...mock, stub, run };
}

async function observe(emitToolResult, ev) {
	await emitToolResult({
		toolName: ev.toolName, input: ev.input ?? {}, details: ev.details ?? {}, isError: false,
	});
}

// ── zero evidence ────────────────────────────────────────────────────
test("submit_answer: zero observations -> GAP_NO_EVIDENCE, then one-shot accept", async () => {
	const { run, emitToolResult, entries } = await makeClosure({});
	const r1 = await run({ answer: "Yes", key_claim: "the ball crosses the line at 1.5s" });
	assert.equal(r1.details.accepted, false);
	assert.equal(r1.details.closure, "no_evidence");
	assert.ok(textBlocks(r1.content).includes("ONE chance"));
	assert.equal(entries.filter((e) => e.payload.transition === "GAP_NO_EVIDENCE").length, 1);

	// Agent does ONE re-observation, then re-submits -> auto-accept
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [1.0, 1.5, 2.0] } });
	const r2 = await run({ answer: "Yes", key_claim: "the ball crosses the line at 1.5s" });
	assert.equal(r2.details.accepted, true);
	assert.equal(r2.details.closure, "oneshot_bypass");
	assert.ok(textBlocks(r2.content).includes("FINAL: Yes"));
});

// ── derivation-only ──────────────────────────────────────────────────
test("submit_answer: only index_video captions -> GAP_DERIVATION_ONLY", async () => {
	const { run, emitToolResult } = await makeClosure({});
	await observe(emitToolResult, { toolName: "index_video", details: { times: [0, 1, 2] } });
	const r = await run({ answer: "No", key_claim: "the car stops before the cone" });
	assert.equal(r.details.accepted, false);
	assert.equal(r.details.closure, "derivation_only");
	assert.ok(textBlocks(r.content).includes("index_video"));
});

// ── CLOSURE: YES ─────────────────────────────────────────────────────
test("submit_answer: checker CLOSURE YES -> accept with confirmed", async () => {
	let checkerPrompt = null;
	const { run, emitToolResult, stub } = await makeClosure({
		checker: (messages) => {
			checkerPrompt = messages.map((m) => m.content).filter((c) => typeof c === "string").join("\n");
			return "CLOSURE: YES";
		},
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
	await observe(emitToolResult, { toolName: "semantic_crop", input: { target: "the ball" },
		details: { time_s: 1.5, crop_bbox: [0, 0, 20, 20], frame_size: [320, 240] } });
	const r = await run({ answer: "Yes", key_claim: "the ball passes through the hoop at ~2.5s" });
	assert.equal(r.details.accepted, true);
	assert.equal(r.details.closure, "confirmed");
	assert.ok(textBlocks(r.content).includes("FINAL: Yes"));

	// Checker prompt carries question + evidence summary (formatted)
	assert.ok(checkerPrompt.includes("Is the ball in?"));
	assert.ok(checkerPrompt.includes("Options: Yes / No"));
	assert.ok(checkerPrompt.includes("read_video_sequence"));
	assert.ok(checkerPrompt.includes("PERCEPTION"));
	assert.ok(checkerPrompt.includes("[0.00, 10.00]s"));       // fmtTime interval
	assert.ok(checkerPrompt.includes("semantic_crop"));
	assert.ok(checkerPrompt.includes("key_claim"), "prompt should quote the agent's key claim");
	// Zero chat/completions calls besides the checker
	const chatCalls = stub.calls.filter((c) => c.url.includes("/chat/completions"));
	assert.equal(chatCalls.length, 1);
	// Checker request must be shaped for thinking models: thinking disabled +
	// a generous token budget (otherwise content=null -> error_bypass loop).
	const checkerBody = stub.calls.find((c) => c.url.includes("/chat/completions")).body ?? {};
	assert.equal(checkerBody.chat_template_kwargs?.enable_thinking, false,
		"thinking must be disabled for the auditor call");
	assert.ok(checkerBody.max_tokens >= 1024, `max_tokens=${checkerBody.max_tokens} too small`);
});

test("submit_answer: checker content null (thinking model) -> graceful gap, no error_bypass", async () => {
	// vLLM returns content=null when a thinking model exhausts its budget in
	// the thinking phase. Must NOT throw (old code: null.trim() TypeError ->
	// error_bypass which silently disabled the closure gate).
	const { run, emitToolResult } = await makeClosure({
		checker: () => null,
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
	const r = await run({ answer: "Yes", key_claim: "k" });
	assert.equal(r.details.accepted, false);
	assert.equal(r.details.closure, "gap");
});

// ── CLOSURE: NO -> one-shot re-observation -> auto-accept ────────────
test("submit_answer: checker CLOSURE NO -> gap with message, second call auto-accepted", async () => {
	const { run, emitToolResult, entries } = await makeClosure({
		checker: () => "CLOSURE: NO | the sequence does not cover the hoop at 2.5s",
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 2] } });
	const r1 = await run({ answer: "Yes", key_claim: "the ball passes through the hoop at ~2.5s" });
	assert.equal(r1.details.accepted, false);
	assert.equal(r1.details.closure, "gap");
	assert.equal(r1.details.gap, "the sequence does not cover the hoop at 2.5s");
	assert.ok(textBlocks(r1.content).includes("hoop at 2.5s"));

	await observe(emitToolResult, { toolName: "read_multiframe", details: { times: [2.5] } });
	const r2 = await run({ answer: "Yes", key_claim: "the ball passes through the hoop at ~2.5s" });
	assert.equal(r2.details.accepted, true);
	assert.equal(r2.details.closure, "oneshot_bypass");
	assert.equal(entries.filter((e) => e.payload.transition === "CLOSURE_NO").length, 1);
});

// ── checker failure ──────────────────────────────────────────────────
test("submit_answer: checker HTTP failure -> graceful accept (error_bypass)", async () => {
	const { run, emitToolResult } = await makeClosure({
		checker: () => { throw new Error("boom"); },
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
	const r = await run({ answer: "Yes", key_claim: "k" });
	assert.equal(r.details.accepted, true);
	assert.equal(r.details.closure, "error_bypass");
});

test("submit_answer: checker HTTP 500 -> graceful accept", async () => {
	const { run, emitToolResult, stub } = await makeClosure({});
	// override fetch for the checker call to return 500
	const orig = stub.calls; // no-op; use a routes-level trick instead
	// simpler: make checker route throw via fetch stub? The stub throws only on
	// unknown URLs; simulate 500 by wrapping:
	const realFetch = globalThis.fetch;
	globalThis.fetch = async (url, init) => {
		const body = JSON.parse(String(init?.body ?? "{}"));
		const text = JSON.stringify(body.messages ?? []).toLowerCase();
		if (text.includes("evidence auditor")) {
			return new Response("{}", { status: 500, headers: { "Content-Type": "application/json" } });
		}
		return realFetch(url, init);
	};
	try {
		await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
		const r = await run({ answer: "Yes", key_claim: "k" });
		assert.equal(r.details.accepted, true);
		assert.equal(r.details.closure, "error_bypass");
		assert.ok(textBlocks(r.content).includes("FINAL: Yes"));
	} finally {
		globalThis.fetch = realFetch;
	}
});

// ── malformed checker reply ──────────────────────────────────────────
test("submit_answer: checker reply without CLOSURE: line -> treated as gap", async () => {
	const { run, emitToolResult } = await makeClosure({
		checker: () => "I cannot determine this.",
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
	const r = await run({ answer: "Yes", key_claim: "k" });
	assert.equal(r.details.accepted, false);
	assert.equal(r.details.closure, "gap");
	assert.equal(r.details.gap, "the key claim lacks direct visual confirmation");
});

// ── no evidence + no VLM call at all ─────────────────────────────────
test("submit_answer: no PERCEPTION evidence -> no checker VLM call (heuristic short-circuits)", async () => {
	const { run, emitToolResult, stub } = await makeClosure({ checker: () => "CLOSURE: YES" });
	await observe(emitToolResult, { toolName: "index_video", details: { times: [0, 1] } });
	const r = await run({ answer: "No", key_claim: "k" });
	assert.equal(r.details.closure, "derivation_only");
	assert.equal(stub.calls.filter((c) => c.url.includes("/chat/completions")).length, 0);
});

test("submit_answer: VISTR_QUESTION env is passed to checker prompt", async () => {
	let prompt = null;
	const { run, emitToolResult } = await makeClosure({
		checker: (messages) => { prompt = messages[0].content; return "CLOSURE: YES"; },
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
	await run({ answer: "Yes", key_claim: "k" });
	assert.ok(prompt.includes("Is the ball in?"));
});

test("submit_answer: checker summary shows REFINES relations", async () => {
	let prompt = null;
	const { run, emitToolResult } = await makeClosure({
		checker: (messages) => { prompt = messages[0].content; return "CLOSURE: YES"; },
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 10] } });
	await observe(emitToolResult, { toolName: "semantic_crop", input: { target: "the ball" },
		details: { time_s: 1.5, crop_bbox: [0, 0, 20, 20], frame_size: [320, 240] } });
	await run({ answer: "Yes", key_claim: "k" });
	assert.ok(prompt.includes("refines E1"), "summary should show REFINES relation");
});

test("submit_answer: accepted answer does not invoke checker again", async () => {
	let checks = 0;
	const { run, emitToolResult } = await makeClosure({
		checker: () => { checks += 1; return "CLOSURE: YES"; },
	});
	await observe(emitToolResult, { toolName: "read_video_sequence", details: { times: [0, 2] } });
	const first = await run({ answer: "Yes", key_claim: "the ball is visible" });
	const second = await run({ answer: "Yes", key_claim: "the ball is visible" });
	assert.equal(first.details.closure, "confirmed");
	assert.equal(second.details.closure, "already_accepted");
	assert.equal(checks, 1);
});
