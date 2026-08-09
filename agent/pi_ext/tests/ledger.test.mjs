/**
 * Silent-ledger tests: feed tool_result events through the extension's
 * tool_result hook (as pi would) and assert the appendEntry evidence
 * stream + REFINES relations.
 */
import assert from "node:assert/strict";
import { test, loadExtension, createMockAPI } from "./harness.mjs";

async function makeClosure() {
	const { api, entries, emitToolResult } = createMockAPI();
	(await loadExtension("/workspace/Spatial-Agent/4D-Agent/agent/pi_ext/evidence_closure.ts")).default(api);
	return { entries, emitToolResult, api };
}

test("ledger: sequence observation records PERCEPTION interval, step 1", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({
		toolName: "read_video_sequence",
		input: { path: "video.mp4" },
		details: { times: [0, 2, 4, 6, 8] },
		isError: false,
	});
	assert.equal(entries.length, 1);
	assert.equal(entries[0].kind, "evidence-closure");
	assert.equal(entries[0].payload.transition, "ADD");
	const ev = entries[0].payload.evidence;
	assert.equal(ev.id, "E1");
	assert.equal(ev.agent_step, 1);
	assert.equal(ev.source, "read_video_sequence");
	assert.equal(ev.epistemic_type, "PERCEPTION");
	assert.deepEqual(ev.world_time, { kind: "interval", t0: 0, t1: 8 });
	assert.deepEqual(ev.space, { kind: "global" });
	assert.deepEqual(ev.relations, []);
});

test("ledger: crop inside sequence gains REFINES relation", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({ toolName: "read_video_sequence", input: {}, details: { times: [0, 10] }, isError: false });
	await emitToolResult({
		toolName: "semantic_crop", input: { target: "the ball" },
		details: { time_s: 5, crop_bbox: [10, 10, 50, 50], frame_size: [320, 240] },
		isError: false,
	});
	const ev2 = entries[1].payload.evidence;
	assert.equal(ev2.id, "E2");
	assert.equal(ev2.agent_step, 2);
	assert.deepEqual(ev2.relations, [{ type: "REFINES", of: "E1" }]);
});

test("ledger: crop outside sequence time gets NO relation", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({ toolName: "read_video_sequence", input: {}, details: { times: [0, 2] }, isError: false });
	await emitToolResult({
		toolName: "semantic_crop", input: {}, details: { time_s: 9, crop_bbox: [0, 0, 10, 10], frame_size: [320, 240] },
		isError: false,
	});
	assert.deepEqual(entries[1].payload.evidence.relations, []);
});

test("ledger: index_video caption is DERIVATION, never refines, still recorded", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({ toolName: "index_video", input: {}, details: { times: [0, 1, 2] }, isError: false });
	assert.equal(entries[0].payload.evidence.epistemic_type, "DERIVATION");
});

test("ledger: failed index_video caption does not create evidence", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({
		toolName: "index_video", input: {},
		details: { times: [0, 1, 2], caption_ok: false }, isError: false,
	});
	assert.equal(entries.length, 0);
});

test("ledger: read(image) records PERCEPTION unknown time/space", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({ toolName: "read", input: { path: "frame.jpg" }, details: {}, isError: false });
	assert.equal(entries[0].payload.evidence.source, "read(image)");
	assert.equal(entries[0].payload.evidence.epistemic_type, "PERCEPTION");
	assert.equal(entries[0].payload.evidence.world_time.kind, "unknown");
});

test("ledger: error results and non-observation tools are skipped", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({ toolName: "read_video_sequence", input: {}, details: { times: [0, 1] }, isError: true });
	await emitToolResult({ toolName: "bash", input: { command: "ls" }, details: {}, isError: false });
	await emitToolResult({ toolName: "submit_answer", input: { answer: "A", key_claim: "x" }, details: {}, isError: false });
	assert.equal(entries.length, 0);
});

test("ledger: friendly tool errors with empty details are not recorded as perception", async () => {
	const { entries, emitToolResult } = await makeClosure();
	await emitToolResult({ toolName: "semantic_crop", input: { target: "ghost" }, details: {}, isError: false });
	await emitToolResult({ toolName: "read_crop", input: {}, details: {}, isError: false });
	await emitToolResult({ toolName: "read_multiframe", input: {}, details: { times: [] }, isError: false });
	assert.equal(entries.length, 0);
});

test("ledger: same tool registered twice by pi would throw (sanity)", async () => {
	const { api } = await makeClosure();
	assert.throws(() => api.registerTool({ name: "submit_answer", parameters: {} }));
});
