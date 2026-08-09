/**
 * Test harness for pi extension tools (agent/pi_ext/*.ts).
 *
 * - Loads the real extension TypeScript via jiti (the same loader pi uses),
 *   with aliases mirroring pi's own extension loader.
 * - Provides a mock ExtensionAPI (on/registerTool/appendEntry) and a fetch
 *   stub for the gateway (chat/completions) and perception service
 *   (/ground, /annotate) — no real LLM / GPU involved.
 * - Real ffmpeg/ffprobe from /opt/conda/envs/spatialagent/bin are used for
 *   frame extraction against a tiny generated test video.
 *
 * Run:  node agent/pi_ext/tests/run.mjs
 */

import { createRequire } from "node:module";
import { mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

// ── Environment: real ffmpeg/ffprobe must be reachable by the tools ──
const FF_ENV = "/opt/conda/envs/spatialagent/bin";
const oldPath = process.env.PATH ?? "";
if (!oldPath.includes(FF_ENV)) {
	process.env.PATH = `${FF_ENV}:${oldPath}`;
}
process.env.VISTR_PERCEPTION_URL = "http://perception.test"; // stub-routed, never real
process.env.VISTR_QUESTION = "Is the ball in? Options: Yes / No"; // default for submit_answer tests
// The local ~/.pi/agent/models.json only has vllm-local; the extension's
// default provider (amap-gateway) does not exist here.
process.env.VISTR_CAPTION_PROVIDER ??= "vllm-local";

// ── jiti (reuse pi's own loader dependency) ──────────────────────────
const JITI_STATIC = "/workspace/Spatial-Agent/4D-Agent/third_party/pi-runtime/node_modules/@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti-static.mjs";
const { createJiti } = await import(JITI_STATIC);

const require = createRequire("/workspace/Spatial-Agent/4D-Agent/third_party/pi-runtime/node_modules/@earendil-works/pi-coding-agent/dist/loader.js");
const PI_CODING_AGENT_ENTRY = "/workspace/Spatial-Agent/4D-Agent/third_party/pi-runtime/node_modules/@earendil-works/pi-coding-agent/dist/index.js";

/**
 * Load an extension module and return its full namespace:
 * { default: factory, ...namedExports }.
 * (jiti's `{ default: true }` mode would return only the default export and
 * drop the named test-surface exports.)
 */
export async function loadExtension(extPath) {
	const jiti = createJiti(import.meta.url, {
		moduleCache: false,
		alias: {
			"@earendil-works/pi-coding-agent": PI_CODING_AGENT_ENTRY,
			typebox: require.resolve("typebox"),
		},
	});
	return await jiti.import(extPath);
}

// ── Mock ExtensionAPI ────────────────────────────────────────────────
export function createMockAPI() {
	const hooks = new Map();      // eventName -> [handlers]
	const tools = new Map();      // toolName -> registered tool object
	const entries = [];           // appendEntry(kind, payload) calls
	const api = {
		on(event, handler) {
			if (!hooks.has(event)) hooks.set(event, []);
			hooks.get(event).push(handler);
		},
		registerTool(tool) {
			if (tools.has(tool.name)) throw new Error(`tool already registered: ${tool.name}`);
			tools.set(tool.name, tool);
		},
		appendEntry(kind, payload) {
			entries.push({ kind, payload });
		},
	};
	return {
		api,
		hooks, tools, entries,
		/** Fire a tool_result event through all handlers. */
		async emitToolResult(event) {
			for (const h of hooks.get("tool_result") ?? []) await h(event);
		},
	};
}

// ── Mini test registry + runner ──────────────────────────────────────
export const tests = [];

/** Register a test: test(name, async fn) */
export function test(name, fn) {
	tests.push({ name, fn });
}

export async function runRegisteredTests(filter) {
	let pass = 0;
	const failures = [];
	const selected = tests.filter((t) => !filter || t.name.includes(filter));
	for (const t of tests) {
		if (filter && !t.name.includes(filter)) continue;
		try {
			await t.fn();
			pass++;
			console.log(`  ✓ ${t.name}`);
		} catch (err) {
			failures.push({ name: t.name, err });
			console.log(`  ✗ ${t.name}\n    ${String(err.message ?? err).split("\n").join("\n    ")}`);
		}
	}
	console.log(`\n${pass}/${selected.length} passed`);
	if (failures.length) {
		console.log("\nFailures:");
		for (const f of failures) console.log(`  - ${f.name}: ${f.err.message}`);
		process.exitCode = 1;
	}
	return failures;
}

// ── Fetch stub ───────────────────────────────────────────────────────
/**
 * installFetch(routes):
 *   routes.caption  — fn(messages) -> string   (gateway captionTimeline)
 *   routes.select   — fn(messages) -> string   (semantic_crop candidate selection)
 *   routes.checker  — fn(messages) -> string   (evidence-closure VLM auditor)
 *   routes.ground   — fn(body) -> object       (perception /ground)
 *   routes.annotate — fn(body) -> object       (perception /annotate)
 * Captures every request body in `calls` for later assertions.
 * Restore with restoreFetch().
 */
export function installFetch(routes) {
	const calls = [];
	const original = globalThis.fetch;
	globalThis.fetch = async (url, init) => {
		const u = String(url);
		const bodyText = init?.body != null ? String(init.body) : "";
		let body = null;
		try { body = JSON.parse(bodyText); } catch { /* non-JSON */ }
		calls.push({ url: u, body });
		const messages = body?.messages ?? [];
		// Content may be a plain string (checker) or an array of text/image_url
		// blocks (caption timeline, candidate selection).
		const userText = messages.flatMap((m) => {
			const c = m.content;
			if (typeof c === "string") return [c];
			if (Array.isArray(c)) return c.filter((b) => b.type === "text").map((b) => b.text);
			return [];
		}).join(" ");

		const json = (obj, status = 200) =>
			new Response(JSON.stringify(obj), {
				status,
				headers: { "Content-Type": "application/json" },
			});

		if (u.includes("/ground")) {
			const out = routes.ground ? routes.ground(body) : { width: 320, height: 240, candidates: [] };
			return json(out);
		}
		if (u.includes("/annotate")) {
			return json(routes.annotate ? routes.annotate(body) : { annotated_b64: "ZGF0YQ==" });
		}
		if (u.includes("/chat/completions")) {
			let reply = "";
			if (userText.includes("Which single candidate")) reply = routes.select ? routes.select(messages) : "1";
			else if (userText.includes("evidence auditor")) reply = routes.checker ? routes.checker(messages) : "CLOSURE: YES";
			else reply = routes.caption ? routes.caption(messages) : "t=0.00s: nothing";
			// Routes may return a plain string (content only), null (content
			// null), or { content, reasoning } to simulate a thinking-model
			// reply (content may be null — the crash the extension used to hit).
			const { content, reasoning } = typeof reply === "string"
				? { content: reply, reasoning: "" }
				: reply == null
					? { content: null, reasoning: "" }
					: { content: reply.content ?? null, reasoning: reply.reasoning ?? "" };
			const message = reasoning
				? { content, reasoning_content: reasoning }
				: { content };
			return json({ choices: [{ message }] });
		}
		throw new Error(`fetch stub: unhandled URL ${u}`);
	};
	return {
		calls,
		restore() { globalThis.fetch = original; },
	};
}

// ── Fixtures: tiny real video / image via ffmpeg ─────────────────────
let _fixtureDir = null;
function fixtureDir() {
	if (!_fixtureDir) {
		_fixtureDir = mkdtempSync(join(tmpdir(), "pi_ext_tests_"));
		// 2s, 10fps, 320x240 color-test pattern — H.264 (project rule: libx264 only)
		execFileSync("ffmpeg", ["-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
			"-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", join(_fixtureDir, "video.mp4")]);
		execFileSync("ffmpeg", ["-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=1",
			"-frames:v", "1", join(_fixtureDir, "image.jpg")]);
	}
	return _fixtureDir;
}

export function testVideo() { return join(fixtureDir(), "video.mp4"); }
export function testImage() { return join(fixtureDir(), "image.jpg"); }

/** Read tool-result content image blocks back to plain assertable shapes. */
export function countImages(content) {
	return (content ?? []).filter((c) => c.type === "image").length;
}
export function textBlocks(content) {
	return (content ?? []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
}
