/**
 * Unit tests for the pure spatiotemporal helpers + mapEvent in
 * evidence_closure.ts (and clampT in vistr_video_tools.ts).
 * Loads the REAL extension source via jiti.
 */
import assert from "node:assert/strict";
import { test, loadExtension } from "./harness.mjs";

const closure = await loadExtension(
	"/workspace/Spatial-Agent/4D-Agent/agent/pi_ext/evidence_closure.ts");
const videoTools = await loadExtension(
	"/workspace/Spatial-Agent/4D-Agent/agent/pi_ext/vistr_video_tools.ts");

const { timeSubset, timeStrict, spaceSubset, spaceStrict, fmtTime, fmtSpace, mapEvent } = closure;
const { clampT, segmentPreviewTimes, parseChatReply, thinkingBlock } = videoTools;

// ── timeSubset ───────────────────────────────────────────────────────
test("timeSubset: point inside interval", () => {
	assert.equal(timeSubset({ kind: "point", t: 5 }, { kind: "interval", t0: 0, t1: 10 }), true);
	assert.equal(timeSubset({ kind: "point", t: 11 }, { kind: "interval", t0: 0, t1: 10 }), false);
});

test("timeSubset: point on interval boundary within EPS", () => {
	assert.equal(timeSubset({ kind: "point", t: -0.1 }, { kind: "interval", t0: 0, t1: 10 }), true);
	assert.equal(timeSubset({ kind: "point", t: -0.2 }, { kind: "interval", t0: 0, t1: 10 }), false);
	assert.equal(timeSubset({ kind: "point", t: 10.1 }, { kind: "interval", t0: 0, t1: 10 }), true);
	assert.equal(timeSubset({ kind: "point", t: 10.2 }, { kind: "interval", t0: 0, t1: 10 }), false);
});

test("timeSubset: interval inside interval", () => {
	assert.equal(timeSubset({ kind: "interval", t0: 2, t1: 4 }, { kind: "interval", t0: 0, t1: 10 }), true);
	assert.equal(timeSubset({ kind: "interval", t0: 0, t1: 10 }, { kind: "interval", t0: 2, t1: 4 }), false);
});

test("timeSubset: discrete points within interval", () => {
	const pts = { kind: "discrete", ts: [0.5, 2, 7.5] };
	assert.equal(timeSubset(pts, { kind: "interval", t0: 0, t1: 10 }), true);
	const partly = { kind: "discrete", ts: [0.5, 20] };
	assert.equal(timeSubset(partly, { kind: "interval", t0: 0, t1: 10 }), false);
});

test("timeSubset: discrete vs discrete within EPS", () => {
	const a = { kind: "discrete", ts: [1.0, 2.0] };
	const b = { kind: "discrete", ts: [1.1, 2.1] }; // within EPS=0.15
	assert.equal(timeSubset(a, b), true);
	const far = { kind: "discrete", ts: [1.0, 2.5] };
	assert.equal(timeSubset(far, b), false);
});

test("timeSubset: interval is never subset of discrete/point (can't know coverage)", () => {
	const iv = { kind: "interval", t0: 0, t1: 10 };
	assert.equal(timeSubset(iv, { kind: "discrete", ts: [0, 5, 10] }), false);
	assert.equal(timeSubset(iv, { kind: "point", t: 5 }), false);
});

test("timeSubset: unknown kinds never subset", () => {
	assert.equal(timeSubset({ kind: "point", t: 5 }, { kind: "unknown" }), false);
	assert.equal(timeSubset({ kind: "unknown" }, { kind: "interval", t0: 0, t1: 10 }), false);
});

test("timeSubset: EMPTY discrete has no evidence support", () => {
	assert.equal(timeSubset({ kind: "discrete", ts: [] }, { kind: "point", t: 5 }), false);
});

// ── timeStrict ───────────────────────────────────────────────────────
test("timeStrict: point strictly inside interval", () => {
	assert.equal(timeStrict({ kind: "point", t: 5 }, { kind: "interval", t0: 0, t1: 10 }), true);
});

test("timeStrict: identical intervals are not strict", () => {
	assert.equal(timeStrict({ kind: "interval", t0: 0, t1: 10 }, { kind: "interval", t0: 0, t1: 10 }), false);
});

test("timeStrict: identical points are not strict", () => {
	assert.equal(timeStrict({ kind: "point", t: 5 }, { kind: "point", t: 5 }), false);
});

test("timeStrict: near-identical points within EPS are NOT strict (both directions)", () => {
	assert.equal(timeStrict({ kind: "point", t: 5 }, { kind: "point", t: 5.1 }), false);
});

// ── spaceSubset ──────────────────────────────────────────────────────
test("spaceSubset: bbox inside global", () => {
	const box = { kind: "bbox", box: [10, 20, 100, 200], frame: [320, 240] };
	assert.equal(spaceSubset(box, { kind: "global" }), true);
	assert.equal(spaceSubset({ kind: "global" }, box), false);
});

test("spaceSubset: bbox inside bbox, same frame", () => {
	const a = { kind: "bbox", box: [10, 10, 50, 50], frame: [320, 240] };
	const b = { kind: "bbox", box: [0, 0, 100, 100], frame: [320, 240] };
	assert.equal(spaceSubset(a, b), true);
	assert.equal(spaceSubset(b, a), false);
});

test("spaceSubset: larger bbox is not subset (5% tolerance)", () => {
	const a = { kind: "bbox", box: [0, 0, 100, 100], frame: [320, 240] };
	const b = { kind: "bbox", box: [10, 10, 50, 50], frame: [320, 240] };
	assert.equal(spaceSubset(a, b), false);
});

test("spaceSubset: slightly-larger a within b+tol is subset (tolerance)", () => {
	const a = { kind: "bbox", box: [-2, -2, 52, 52], frame: [320, 240] };
	const b = { kind: "bbox", box: [0, 0, 50, 50], frame: [320, 240] };
	// tol = 5% of max(50,50)=2.5 -> a.x0=-2 >= -2.5 OK, a.y1=52 <= 52.5 OK
	assert.equal(spaceSubset(a, b), true);
});

test("spaceSubset: different frame sizes never subset", () => {
	const a = { kind: "bbox", box: [0, 0, 50, 50], frame: [320, 240] };
	const b = { kind: "bbox", box: [0, 0, 100, 100], frame: [640, 480] };
	assert.equal(spaceSubset(a, b), false);
});

test("spaceSubset: unknown kinds never subset", () => {
	assert.equal(spaceSubset({ kind: "unknown" }, { kind: "global" }), false);
	assert.equal(spaceSubset({ kind: "bbox", box: [0, 0, 5, 5], frame: [320, 240] }, { kind: "unknown" }), false);
});

// ── spaceStrict ──────────────────────────────────────────────────────
test("spaceStrict: proper subset is strict, equal is not", () => {
	const a = { kind: "bbox", box: [10, 10, 50, 50], frame: [320, 240] };
	const b = { kind: "bbox", box: [0, 0, 100, 100], frame: [320, 240] };
	assert.equal(spaceStrict(a, b), true);
	assert.equal(spaceStrict(a, a), false);
});

// ── fmt helpers (feed the VLM checker summary) ───────────────────────
test("fmtTime formats all kinds", () => {
	assert.equal(fmtTime({ kind: "interval", t0: 0, t1: 10.005 }), "[0.00, 10.01]s");
	assert.equal(fmtTime({ kind: "discrete", ts: [0.5, 1.25] }), "{0.50, 1.25}s");
	assert.equal(fmtTime({ kind: "point", t: 2.5 }), "{2.50}s");
	assert.equal(fmtTime({ kind: "unknown" }), "unknown");
});

test("fmtSpace formats all kinds", () => {
	assert.equal(fmtSpace({ kind: "global" }), "global");
	assert.equal(fmtSpace({ kind: "bbox", box: [10, 20, 300, 400], frame: [320, 240] }), "bbox[10,20,300,400]");
	assert.equal(fmtSpace({ kind: "unknown" }), "unknown");
});

// ── mapEvent: tool result -> evidence mapping ────────────────────────
test("mapEvent: index_video -> DERIVATION discrete timeline", () => {
	const ev = mapEvent("index_video", {}, { times: [0, 1.1, 2.2] });
	assert.deepEqual(ev, {
		source: "index_video",
		world_time: { kind: "discrete", ts: [0, 1.1, 2.2] },
		space: { kind: "global" },
		epistemic_type: "DERIVATION",
		producer_metadata: { num_frames: 3 },
	});
});

test("mapEvent: index_video without times -> unknown time", () => {
	const ev = mapEvent("index_video", {}, {});
	assert.equal(ev.world_time.kind, "unknown");
});

test("mapEvent: read_video_sequence -> PERCEPTION interval", () => {
	const ev = mapEvent("read_video_sequence", {}, { times: [0.5, 1.5, 2.5] });
	assert.equal(ev.epistemic_type, "PERCEPTION");
	assert.deepEqual(ev.world_time, { kind: "interval", t0: 0.5, t1: 2.5 });
});

test("mapEvent: empty or malformed frame details do not create visual evidence", () => {
	assert.equal(mapEvent("read_video_sequence", {}, { times: [] }), null);
	assert.equal(mapEvent("read_multiframe", {}, { times: [] }), null);
	assert.equal(mapEvent("read_multiframe", {}, { times: [1, NaN] }), null);
	assert.equal(mapEvent("semantic_crop", {}, {}), null);
	assert.equal(mapEvent("read_crop", {}, { pixels: [0, 0, 10, 10] }), null);
	assert.equal(mapEvent("semantic_crop", {}, { time_s: NaN, crop_bbox: [0, 0, 10, 10], frame_size: [320, 240] }), null);
});

test("mapEvent: read_multiframe -> PERCEPTION discrete", () => {
	const ev = mapEvent("read_multiframe", {}, { times: [1, 3] });
	assert.equal(ev.epistemic_type, "PERCEPTION");
	assert.deepEqual(ev.world_time, { kind: "discrete", ts: [1, 3] });
});

test("mapEvent: semantic_crop -> PERCEPTION point bbox with target", () => {
	const ev = mapEvent("semantic_crop",
		{ target: "the ball" },
		{ time_s: 2.5, crop_bbox: [10, 20, 30, 40], frame_size: [320, 240] });
	assert.equal(ev.epistemic_type, "PERCEPTION");
	assert.deepEqual(ev.world_time, { kind: "point", t: 2.5 });
	assert.deepEqual(ev.space, { kind: "bbox", box: [10, 20, 30, 40], frame: [320, 240] });
	assert.deepEqual(ev.producer_metadata, { target: "the ball" });
});

test("mapEvent: semantic_crop without time_s -> unknown time", () => {
	const ev = mapEvent("semantic_crop", { target: "x" }, { crop_bbox: [1, 2, 3, 4], frame_size: [320, 240] });
	assert.equal(ev.world_time.kind, "unknown");
});

test("mapEvent: read_crop -> PERCEPTION point bbox", () => {
	const ev = mapEvent("read_crop", {}, { time_s: 1.5, pixels: [0, 0, 50, 50], source: [320, 240] });
	assert.equal(ev.epistemic_type, "PERCEPTION");
	assert.deepEqual(ev.world_time, { kind: "point", t: 1.5 });
	assert.deepEqual(ev.space, { kind: "bbox", box: [0, 0, 50, 50], frame: [320, 240] });
});

test("mapEvent: read of image -> PERCEPTION, unknown time/space", () => {
	const ev = mapEvent("read", { path: "/tmp/a.jpg" }, {});
	assert.equal(ev.epistemic_type, "PERCEPTION");
	assert.equal(ev.world_time.kind, "unknown");
	assert.equal(ev.space.kind, "unknown");
	assert.deepEqual(ev.producer_metadata, { path: "/tmp/a.jpg" });
});

test("mapEvent: read of non-image / unknown tools -> null", () => {
	assert.equal(mapEvent("read", { path: "/tmp/a.txt" }, {}), null);
	assert.equal(mapEvent("read", { path: "/tmp/a.pdf" }, {}), null);
	assert.equal(mapEvent("bash", { command: "ls" }, {}), null);
	assert.equal(mapEvent("submit_answer", {}, {}), null);
});

test("mapEvent: index_video with missing times still maps (unknown time)", () => {
	const ev = mapEvent("index_video", {}, { times: undefined });
	assert.equal(ev.source, "index_video");
	assert.equal(ev.world_time.kind, "unknown");
});

// ── parseChatReply / thinkingBlock (vistr_video_tools subcall replies) ─
test("parseChatReply: content string is used, whitespace trimmed", () => {
	assert.deepEqual(parseChatReply({ choices: [{ message: { content: "  42  " } }] }),
		{ content: "42", reasoning: "" });
});

test("parseChatReply: content null + reasoning_content -> separated, no crash", () => {
	// The exact vLLM qwen3-thinking shape that used to crash .trim()/.match().
	assert.deepEqual(
		parseChatReply({ choices: [{ message: { content: null, reasoning_content: "let me think" } }] }),
		{ content: "", reasoning: "let me think" });
});

test("parseChatReply: reasoning aliases (reasoning / reasoning_text), first non-empty wins", () => {
	assert.equal(parseChatReply({ choices: [{ message: { content: null, reasoning: "r" } }] }).reasoning, "r");
	assert.equal(parseChatReply({ choices: [{ message: { content: null, reasoning_text: "rt" } }] }).reasoning, "rt");
	assert.equal(parseChatReply(
		{ choices: [{ message: { content: null, reasoning_content: "rc", reasoning: "r" } }] }).reasoning, "rc");
});

test("parseChatReply: both fields null/absent -> {content:'', reasoning:''}", () => {
	assert.deepEqual(parseChatReply({ choices: [{ message: { content: null } }] }), { content: "", reasoning: "" });
	assert.deepEqual(parseChatReply({ choices: [{ message: {} }] }), { content: "", reasoning: "" });
});

test("parseChatReply: malformed payloads never throw", () => {
	assert.deepEqual(parseChatReply(null), { content: "", reasoning: "" });
	assert.deepEqual(parseChatReply({}), { content: "", reasoning: "" });
	assert.deepEqual(parseChatReply({ choices: [] }), { content: "", reasoning: "" });
	assert.deepEqual(parseChatReply({ choices: [{ message: { content: 42 } }] }), { content: "", reasoning: "" });
});

test("thinkingBlock: empty reasoning -> null (no empty labeled block)", () => {
	assert.equal(thinkingBlock("", "x"), null);
	assert.equal(thinkingBlock("   ", "x"), null);
});

test("thinkingBlock: non-empty reasoning -> labeled text block", () => {
	assert.deepEqual(thinkingBlock("deliberation", "selection subcall"),
		{ type: "text", text: "[selection subcall thinking]\ndeliberation" });
});

test("thinkingBlock: long reasoning capped at 600 chars with note", () => {
	const long = "a".repeat(700);
	const b = thinkingBlock(long, "caption subcall");
	assert.equal(b.text.startsWith("[caption subcall thinking]\n"), true);
	assert.equal(b.text.length, "[caption subcall thinking]\n".length + 600 + "… (+100 chars)".length);
	assert.ok(b.text.endsWith("… (+100 chars)"));
	assert.ok(!b.text.includes("a".repeat(601)), "must not include more than 600 content chars");
});

// ── clampT (vistr_video_tools) ───────────────────────────────────────
test("clampT: clamps to [0, dur-0.1]", () => {
	assert.equal(clampT(-5, 10), 0);
	assert.equal(clampT(10, 10), 9.9);
	assert.equal(clampT(15, 10), 9.9);
	assert.equal(clampT(5, 10), 5);
	assert.equal(clampT(0, 0), 0);
	assert.equal(clampT(2, 0), 0);
});

test("segmentPreviewTimes: final preview stays inside derived clip", () => {
	assert.deepEqual(segmentPreviewTimes(2), [0, 1, 1.9]);
	const short = segmentPreviewTimes(0.1);
	assert.deepEqual(short.slice(0, 2), [0, 0.05]);
	assert.ok(Math.abs(short[2] - 0.09) < 1e-12);
	assert.ok(segmentPreviewTimes(2).every((t) => t >= 0 && t < 2));
});
