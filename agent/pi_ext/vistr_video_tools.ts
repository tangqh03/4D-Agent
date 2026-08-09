/**
 * ViSTR video observation tools — task-agnostic temporal reading primitives.
 *
 * Adds two tools on top of pi's native `read`:
 *  - read_video_sequence: view a continuous time slice (evenly sampled frames)
 *  - read_multiframe:     jointly view several specified timestamps
 *
 * Both return multiple timestamp-labelled images inside ONE tool result, so
 * frames sit adjacent in model context (preserves temporal continuity).
 * No domain logic (no speed/trajectory analysis, no task routing).
 *
 * Usage: pi -p -e agent/pi_ext/vistr_video_tools.ts "..."
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const run = promisify(execFile);

const MAX_FRAMES = 8;
const SCALE = "scale=640:-2";

async function videoDuration(path: string): Promise<number> {
	const { stdout } = await run("ffprobe", [
		"-v", "error", "-show_entries", "format=duration",
		"-of", "default=noprint_wrappers=1:nokey=1", path,
	]);
	return parseFloat(stdout.trim());
}

// Seeking at exactly t=duration yields no frame; keep a safety margin.
function clampT(t: number, dur: number): number {
	return Math.max(0, Math.min(t, Math.max(0, dur - 0.1)));
}

// ── Subcall reply parsing: thinking goes to its own slot ──────────────
// The gateway model may be a thinking model (qwen3-vl-8b-thinking): vLLM's
// reasoning parser returns the committed answer in `content` and the
// deliberation in `reasoning_content` — and when the model produces only a
// thinking block, `content` is null. Mirror pi-ai's reasoningFields: keep
// the two apart, never substitute reasoning for content (deliberation is
// not a committed answer — e.g. candidate numbers mentioned then rejected).
const REASONING_FIELDS = ["reasoning_content", "reasoning", "reasoning_text"];
const MAX_REASONING_CHARS = 600; // context cap for the surfaced thinking

function parseChatReply(data: unknown): { content: string; reasoning: string } {
	const msg = (data as { choices?: Array<{ message?: Record<string, unknown> }> })
		?.choices?.[0]?.message ?? {};
	const content = typeof msg.content === "string" ? msg.content.trim() : "";
	const reasoning = REASONING_FIELDS
		.map((k) => (typeof msg[k] === "string" ? (msg[k] as string).trim() : ""))
		.find((s) => s.length > 0) ?? "";
	return { content, reasoning };
}

// toolResult has no native thinking part (session format), so the subcall's
// deliberation is surfaced as its own clearly-labeled text block — never
// merged into the answer text.
function thinkingBlock(reasoning: string, label: string): Block | null {
	if (!reasoning.trim()) return null;
	const shown = reasoning.length > MAX_REASONING_CHARS
		? reasoning.slice(0, MAX_REASONING_CHARS) + `… (+${reasoning.length - MAX_REASONING_CHARS} chars)`
		: reasoning;
	return { type: "text", text: `[${label} thinking]\n${shown}` };
}

// Test surface (behavior-neutral named export; pi's loader only consumes
// the default export).
export { clampT, parseChatReply, thinkingBlock };

async function grabFrame(video: string, t: number, outDir: string, i: number): Promise<string> {
	const out = join(outDir, `f_${i}.jpg`);
	await run("ffmpeg", [
		"-y", "-ss", t.toFixed(3), "-i", video,
		"-frames:v", "1", "-vf", SCALE, "-q:v", "5", out,
	]);
	return out;
}

type Block = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };

async function framesContent(video: string, times: number[]): Promise<Block[]> {
	const dir = await mkdtemp(join(tmpdir(), "vistr_frames_"));
	try {
		const content: Block[] = [];
		for (let i = 0; i < times.length; i++) {
			const p = await grabFrame(video, times[i], dir, i);
			const data = (await readFile(p)).toString("base64");
			content.push({ type: "text", text: `[frame ${i + 1}/${times.length} @ t=${times[i].toFixed(2)}s]` });
			content.push({ type: "image", data, mimeType: "image/jpeg" });
		}
		return content;
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}

const INDEX_MAX_FRAMES = 12;
const INDEX_SCALE = "scale=480:-2";

async function gatewayConfig(): Promise<{ baseUrl: string; apiKey: string; model: string }> {
	const raw = await readFile(join(process.env.HOME ?? "~", ".pi", "agent", "models.json"), "utf-8");
	const cfg = JSON.parse(raw);
	const prov = cfg.providers[process.env.VISTR_CAPTION_PROVIDER ?? "amap-gateway"];
	const model = process.env.VISTR_CAPTION_MODEL ?? prov.models[0].id;
	return { baseUrl: prov.baseUrl, apiKey: prov.apiKey, model };
}

// One batch VLM call: objective per-timestamp captions. Deliberately receives
// NO task/question context — it must stay a neutral semantic timeline.
// Returns { ok:false, error, reasoning } when the model produced no answer
// text (thinking-only reply); the caller surfaces the error plus the
// labeled thinking block instead of crashing on a null content.
async function captionTimeline(video: string, times: number[]): Promise<
	{ ok: true; text: string; reasoning: string } | { ok: false; error: string; reasoning: string }> {
	const dir = await mkdtemp(join(tmpdir(), "vistr_index_"));
	try {
		const content: Array<Record<string, unknown>> = [{
			type: "text",
			text:
				"You will see video frames, each preceded by its timestamp label. " +
				"For EACH frame output exactly one line in the format `t=<timestamp>s: <caption>`. " +
				"Captions must be short, objective descriptions of what is visible " +
				"(scene, subjects, poses, object positions). No speculation, no analysis.",
		}];
		for (let i = 0; i < times.length; i++) {
			const out = join(dir, `f_${i}.jpg`);
			await run("ffmpeg", [
				"-y", "-ss", times[i].toFixed(3), "-i", video,
				"-frames:v", "1", "-vf", INDEX_SCALE, "-q:v", "7", out,
			]);
			const b64 = (await readFile(out)).toString("base64");
			content.push({ type: "text", text: `t=${times[i].toFixed(2)}s:` });
			content.push({ type: "image_url", image_url: { url: `data:image/jpeg;base64,${b64}` } });
		}
		const gw = await gatewayConfig();
		const resp = await fetch(`${gw.baseUrl}/chat/completions`, {
			method: "POST",
			headers: { "Content-Type": "application/json", Authorization: `Bearer ${gw.apiKey}` },
			body: JSON.stringify({
				model: gw.model,
				messages: [{ role: "user", content }],
				// Thinking models spend a chunk of the budget on the forced
				// <think> preamble: 1000 tokens frequently ended inside the
				// thinking block (content=null). 1500 leaves room to finish
				// thinking AND emit the caption lines.
				max_tokens: 1500,
				temperature: 0,
			}),
			signal: AbortSignal.timeout(120_000),
		});
		if (!resp.ok) throw new Error(`caption request failed: HTTP ${resp.status}`);
		const data = (await resp.json()) as unknown;
		const parsed = parseChatReply(data);
		const reasoning = parsed.reasoning;
		if (!parsed.content) {
			return { ok: false,
				error: `caption subcall returned no answer text (model produced only a thinking block). ` +
					`Retry index_video, or use read_video_sequence/read_multiframe directly.`,
				reasoning };
		}
		return { ok: true, text: parsed.content, reasoning };
	} finally {
		await rm(dir, { recursive: true, force: true });
	}
}

export default function vistrVideoTools(pi: ExtensionAPI) {
	const PERCEPTION_URL = process.env.VISTR_PERCEPTION_URL ?? "http://127.0.0.1:7876";
	const CROP_MARGIN = 0.15; // fixed tool-level context margin, never task-tuned

	async function extractFullFrame(src: string, time_s: number | undefined, dir: string): Promise<{ path: string; time_s?: number }> {
		const isVideo = /\.(mp4|avi|mov|mkv|webm)$/i.test(src);
		if (!isVideo) return { path: src };
		if (time_s === undefined) throw new Error("time_s is required for video paths");
		const dur = await videoDuration(src);
		const actualTime = clampT(time_s, dur);
		const frame = join(dir, "frame.png");
		await run("ffmpeg", ["-y", "-ss", actualTime.toFixed(3), "-i", src, "-frames:v", "1", frame]);
		return { path: frame, time_s: actualTime };
	}

	// Isolated selection subcall: sees ONLY the annotated candidates and the
	// target expression — never the benchmark question/options/hypotheses.
	// Parses the committed number from `content` ONLY (never from reasoning —
	// deliberation mentions candidates that get rejected). Empty content →
	// { ok:false } so the caller fails gracefully instead of crashing.
	async function selectCandidate(annotatedB64: string, target: string, ids: number[]): Promise<
		{ ok: true; id: number; reasoning: string } | { ok: false; error: string; reasoning: string }> {
		const gw = await gatewayConfig();
		const resp = await fetch(`${gw.baseUrl}/chat/completions`, {
			method: "POST",
			headers: { "Content-Type": "application/json", Authorization: `Bearer ${gw.apiKey}` },
			body: JSON.stringify({
				model: gw.model,
				messages: [{
					role: "user",
					content: [
						{ type: "text", text:
							`The image shows numbered candidate boxes (${ids.join(", ")}). ` +
							`Which single candidate best matches this description: "${target}"? ` +
							`Reply with the number only.` },
						{ type: "image_url", image_url: { url: `data:image/jpeg;base64,${annotatedB64}` } },
					],
				}],
				// Was 8 — a thinking model cannot even finish its forced
				// <think> preamble in 8 tokens, so content was always null.
				max_tokens: 128,
				temperature: 0,
			}),
			signal: AbortSignal.timeout(60_000),
		});
		if (!resp.ok) throw new Error(`selection subcall failed: HTTP ${resp.status}`);
		const data = (await resp.json()) as unknown;
		const parsed = parseChatReply(data);
		const reasoning = parsed.reasoning;
		if (!parsed.content) {
			return { ok: false,
				error: `selection subcall returned no answer text (model produced only a thinking block). ` +
					`Retry semantic_crop with a more specific target description.`,
				reasoning };
		}
		const exact = parsed.content.match(/^(\d+)$/);
		if (exact && ids.includes(parseInt(exact[1], 10))) {
			return { ok: true, id: parseInt(exact[1], 10), reasoning };
		}
		// Non-compliant reply: prefer the last mentioned candidate id (the
		// committed choice tends to come last); else fall back to id[0].
		const mentions = [...parsed.content.matchAll(/\b(\d+)\b/g)]
			.map((m) => parseInt(m[1], 10))
			.filter((n) => ids.includes(n));
		return { ok: true, id: mentions.length ? mentions[mentions.length - 1] : ids[0], reasoning };
	}

	pi.registerTool({
		name: "semantic_crop",
		label: "Semantic crop",
		description:
			`Zoom into the region of an image or video frame that matches a natural-language ` +
			`target description — no coordinates needed. A grounding backend proposes candidate ` +
			`boxes and the best match is cropped from the original high-resolution frame. ` +
			`Returns a grounding receipt (thumbnail with the chosen box drawn) plus the crop; ` +
			`check the receipt, and if the wrong region was chosen, call again with a more ` +
			`specific target description (do not switch to numeric coordinates).`,
		promptSnippet: "Zoom into the region matching a text description (grounding backend)",
		parameters: Type.Object({
			path: Type.String({ description: "Path to an image file or a video file" }),
			target: Type.String({ description: "Referring expression IN ENGLISH for the region to view, e.g. 'the hand touching the lower tower' (the grounding backend only understands English)" }),
			time_s: Type.Optional(Type.Number({ description: "Timestamp in seconds (required when path is a video)" })),
		}),
		async execute(_id, params: { path: string; target: string; time_s?: number }) {
			const src = resolve(params.path);
			const isVideo = /\.(mp4|avi|mov|mkv|webm)$/i.test(src);
			if (params.time_s !== undefined && !Number.isFinite(params.time_s)) {
				return { content: [{ type: "text", text: "Error: time_s must be a finite number." }], details: {} };
			}
			if (isVideo && params.time_s === undefined) {
				return { content: [{ type: "text", text: "Error: time_s is required for video paths." }], details: {} };
			}
			const dir = await mkdtemp(join(tmpdir(), "vistr_sem_"));
			try {
				const extracted = await extractFullFrame(src, params.time_s, dir);
				const frame = extracted.path;
				const actualTime = extracted.time_s;
				const frameB64 = (await readFile(frame)).toString("base64");
				const gresp = await fetch(`${PERCEPTION_URL}/ground`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ image_b64: frameB64, text: params.target, topk: 6, annotate: true }),
					signal: AbortSignal.timeout(120_000),
				});
				if (!gresp.ok) throw new Error(`perception service: HTTP ${gresp.status}`);
				const g = (await gresp.json()) as {
					width: number; height: number;
					candidates: Array<{ id: number; bbox: number[]; score: number; phrase: string }>;
					annotated_b64?: string;
				};
				if (!g.candidates.length) {
					return { content: [{ type: "text", text:
						`No region found for "${params.target}". Try a simpler noun phrase ` +
						`(e.g. object names) or different wording.` }], details: {} };
				}
				let chosen: number;
				let selectReasoning = "";
				if (g.candidates.length === 1) {
					chosen = g.candidates[0].id;
				} else {
					const sel = await selectCandidate(g.annotated_b64!, params.target, g.candidates.map((c) => c.id));
					selectReasoning = sel.reasoning;
					if (!sel.ok) {
						const blocks: Block[] = [{ type: "text", text: `Error: ${sel.error}` }];
						const tb = thinkingBlock(sel.reasoning, "selection subcall");
						if (tb) blocks.push(tb);
						return { content: blocks,
							details: { path: params.path, time_s: actualTime ?? null, target: params.target,
								candidate_count: g.candidates.length, selection_mode: "vlm_select_failed" } };
					}
					chosen = sel.id;
				}
				const cand = g.candidates.find((c) => c.id === chosen)!;
				let [x0, y0, x1, y1] = cand.bbox;
				const mw = (x1 - x0) * CROP_MARGIN, mh = (y1 - y0) * CROP_MARGIN;
				x0 = Math.max(0, Math.round(x0 - mw)); y0 = Math.max(0, Math.round(y0 - mh));
				x1 = Math.min(g.width, Math.round(x1 + mw)); y1 = Math.min(g.height, Math.round(y1 + mh));
				const out = join(dir, "crop.jpg");
				await run("ffmpeg", ["-y", "-i", frame, "-vf", `crop=${x1 - x0}:${y1 - y0}:${x0}:${y0}`, "-q:v", "2", out]);
				const cropB64 = (await readFile(out)).toString("base64");
				const aresp = await fetch(`${PERCEPTION_URL}/annotate`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ image_b64: frameB64, bbox: cand.bbox, label: `#${cand.id}` }),
					signal: AbortSignal.timeout(60_000),
				});
				const receipt = ((await aresp.json()) as { annotated_b64: string }).annotated_b64;
				const outContent: Block[] = [
					{ type: "text", text:
						`semantic_crop "${params.target}"${actualTime !== undefined ? ` @ t=${actualTime.toFixed(2)}s` : ""}: ` +
						`chose candidate #${cand.id} (phrase "${cand.phrase}", score ${cand.score}) of ${g.candidates.length}. ` +
						`Grounding receipt (chosen box on full frame):` },
					{ type: "image", data: receipt, mimeType: "image/jpeg" },
					{ type: "text", text: `High-resolution crop (${x1 - x0}×${y1 - y0}px of ${g.width}×${g.height}):` },
					{ type: "image", data: cropB64, mimeType: "image/jpeg" },
				];
				const tb = thinkingBlock(selectReasoning, "selection subcall");
				if (tb) outContent.push(tb);
				return {
					content: outContent,
					details: {
						path: params.path,
						time_s: actualTime ?? null,
						target: params.target,
						frame_size: [g.width, g.height],
						grounding_bbox: cand.bbox,
						crop_bbox: [x0, y0, x1, y1],
						grounding_phrase: cand.phrase,
						grounding_score: cand.score,
						candidate_count: g.candidates.length,
						selection_mode: g.candidates.length === 1 ? "single" : "vlm_select",
					},
				};
			} finally {
				await rm(dir, { recursive: true, force: true });
			}
		},
	});

	pi.registerTool({
		name: "read_crop",
		label: "Read cropped region",
		description:
			`Zoom into a spatial region of an image file or a video frame and view it at ` +
			`original resolution. Give the region as a normalized bounding box ` +
			`[x0, y0, x1, y1] on a 0-1000 scale of the full frame (0,0 = top-left, ` +
			`1000,1000 = bottom-right) — do NOT compute pixel coordinates yourself. ` +
			`For a video path you must also give time_s. A bbox selects one static image ` +
			`region; it does not track a moving target across timestamps. Re-localize a ` +
			`moving target with semantic_crop or update the bbox at each timestamp. If the ` +
			`crop misses the target, adjust the bbox and call again ` +
			`(ground → crop → re-observe → refine).`,
		promptSnippet: "Zoom into a region of an image/video frame via a normalized bbox",
		parameters: Type.Object({
			path: Type.String({ description: "Path to an image file or a video file" }),
			bbox: Type.Array(Type.Number(), {
				description: "Normalized [x0, y0, x1, y1] on 0-1000 scale of the full frame",
			}),
			time_s: Type.Optional(Type.Number({
				description: "Timestamp in seconds (required when path is a video)",
			})),
		}),
		async execute(_id, params: { path: string; bbox: number[]; time_s?: number }) {
			const src = resolve(params.path);
			const isVideo = /\.(mp4|avi|mov|mkv|webm)$/i.test(src);
			if (!Array.isArray(params.bbox) || params.bbox.length !== 4 ||
				!params.bbox.every((v) => typeof v === "number" && Number.isFinite(v))) {
				return { content: [{ type: "text", text: "Error: bbox must contain exactly four finite numbers." }], details: {} };
			}
			if (params.bbox.every((v) => v >= 0 && v <= 1)) {
				return { content: [{ type: "text", text:
					"Error: bbox appears to use a 0-1 scale, but read_crop requires " +
					"[x0, y0, x1, y1] on a 0-1000 scale. Multiply normalized " +
					"coordinates by 1000, or use semantic_crop to re-localize the target." }], details: {} };
			}
			if (params.time_s !== undefined && !Number.isFinite(params.time_s)) {
				return { content: [{ type: "text", text: "Error: time_s must be a finite number." }], details: {} };
			}
			const dir = await mkdtemp(join(tmpdir(), "vistr_crop_"));
			try {
				let frame = src;
				let actualTime: number | undefined;
				if (isVideo) {
					if (params.time_s === undefined) {
						return { content: [{ type: "text", text: "Error: time_s is required for video paths." }], details: {} };
					}
					const dur = await videoDuration(src);
					actualTime = clampT(params.time_s, dur);
					frame = join(dir, "frame.png");
					await run("ffmpeg", ["-y", "-ss", actualTime.toFixed(3),
						"-i", src, "-frames:v", "1", frame]);
				}
				const { stdout } = await run("ffprobe", ["-v", "error", "-select_streams", "v:0",
					"-show_entries", "stream=width,height", "-of", "csv=p=0", frame]);
				const [w, h] = stdout.trim().split(",").map(Number);
				const nb = params.bbox.map((v) => Math.max(0, Math.min(v, 1000)));
				let [x0, y0, x1, y1] = [
					Math.round((nb[0] / 1000) * w), Math.round((nb[1] / 1000) * h),
					Math.round((nb[2] / 1000) * w), Math.round((nb[3] / 1000) * h)];
				if (x1 <= x0 + 4 || y1 <= y0 + 4) {
					return { content: [{ type: "text", text: `Error: bbox too small or inverted after mapping (${x0},${y0},${x1},${y1}).` }], details: {} };
				}
				const out = join(dir, "crop.jpg");
				await run("ffmpeg", ["-y", "-i", frame,
					"-vf", `crop=${x1 - x0}:${y1 - y0}:${x0}:${y0}`, "-q:v", "2", out]);
				const data = (await readFile(out)).toString("base64");
				return {
					content: [
						{ type: "text", text: `Crop of ${params.path}${actualTime !== undefined ? ` @ t=${actualTime.toFixed(2)}s` : ""}, bbox [${nb.join(", ")}]/1000 → ${x1 - x0}×${y1 - y0}px of ${w}×${h} original:` },
						{ type: "image", data, mimeType: "image/jpeg" },
					],
					details: { path: params.path, time_s: actualTime ?? null,
						pixels: [x0, y0, x1, y1], source: [w, h] },
				};
			} finally {
				await rm(dir, { recursive: true, force: true });
			}
		},
	});

	pi.registerTool({
		name: "index_video",
		label: "Index video",
		description:
			`Build a coarse semantic timeline of a video: uniformly samples frames and ` +
			`returns one short objective caption per timestamp (text only, no images). ` +
			`Use it to discover which moments are worth inspecting, then view the chosen ` +
			`timestamps with read_multiframe or a range with read_video_sequence. ` +
			`Max ${INDEX_MAX_FRAMES} sampled frames per call.`,
		promptSnippet: "Get a coarse captioned timeline of a video to find moments worth viewing",
		parameters: Type.Object({
			path: Type.String({ description: "Path to the video file" }),
			num_frames: Type.Optional(Type.Number({
				description: `Frames to sample uniformly, 4-${INDEX_MAX_FRAMES} (default 8)`,
			})),
		}),
		async execute(_id, params: { path: string; num_frames?: number }) {
			const video = resolve(params.path);
			const dur = await videoDuration(video);
			const requested = params.num_frames ?? 8;
			const n = Math.max(4, Math.min(Number.isFinite(requested) ? Math.round(requested) : 8, INDEX_MAX_FRAMES));
			const times = Array.from({ length: n }, (_, i) => clampT((dur * i) / (n - 1), dur));
			const tl = await captionTimeline(video, times);
			const parts: Block[] = [{
				type: "text",
				text: tl.ok
					? `Video ${params.path} (duration ${dur.toFixed(2)}s), semantic timeline (${n} sampled frames):\n${tl.text}`
					: `Error: ${tl.error}`,
			}];
			const tb = thinkingBlock(tl.reasoning, "caption subcall");
			if (tb) parts.push(tb);
			return { content: parts, details: { times, caption_ok: tl.ok } };
		},
	});

	pi.registerTool({
		name: "read_video_sequence",
		label: "Read video sequence",
		description:
			`Read a continuous time slice of a video and view it as a sequence of ` +
			`evenly-sampled, timestamp-labelled frames returned together in one result ` +
			`(preserves temporal order for motion/trend understanding). ` +
			`Max ${MAX_FRAMES} frames per call; call again on a narrower range to zoom in time.`,
		promptSnippet: "View a continuous video time slice as an ordered frame sequence",
		parameters: Type.Object({
			path: Type.String({ description: "Path to the video file" }),
			start_s: Type.Number({ description: "Slice start time in seconds" }),
			end_s: Type.Number({ description: "Slice end time in seconds" }),
			num_frames: Type.Optional(Type.Number({ description: `Frames to sample, 2-${MAX_FRAMES} (default 6)` })),
		}),
		async execute(_id, params: { path: string; start_s: number; end_s: number; num_frames?: number }) {
			const video = resolve(params.path);
			if (!Number.isFinite(params.start_s) || !Number.isFinite(params.end_s)) {
				return { content: [{ type: "text", text: "Error: start_s and end_s must be finite numbers." }], details: {} };
			}
			if (params.start_s > params.end_s) {
				return { content: [{ type: "text", text: "Error: start_s must be less than or equal to end_s." }], details: {} };
			}
			const dur = await videoDuration(video);
			const start = clampT(params.start_s, dur);
			const end = clampT(params.end_s, dur);
			const requested = params.num_frames ?? 6;
			const n = Math.max(2, Math.min(Number.isFinite(requested) ? Math.round(requested) : 6, MAX_FRAMES));
			const times = Array.from({ length: n }, (_, i) => start + ((end - start) * i) / (n - 1));
			const content = await framesContent(video, times);
			content.unshift({
				type: "text",
				text: `Video ${params.path} (duration ${dur.toFixed(2)}s), slice ${start.toFixed(2)}-${end.toFixed(2)}s, ${n} frames in temporal order:`,
			});
			return { content, details: { times } };
		},
	});

	pi.registerTool({
		name: "read_multiframe",
		label: "Read multiple frames",
		description:
			`Jointly view a set of already-selected evidence frames of a video in one ` +
			`result for cross-frame comparison (each frame is timestamp-labelled). ` +
			`Timestamps need not be uniform — pick moments you have reason to inspect, ` +
			`e.g. after consulting index_video. Max ${MAX_FRAMES} timestamps per call.`,
		promptSnippet: "Jointly view selected evidence frames for cross-frame comparison",
		parameters: Type.Object({
			path: Type.String({ description: "Path to the video file" }),
			times_s: Type.Array(Type.Number(), {
				description: `Timestamps in seconds to view together (1-${MAX_FRAMES})`,
			}),
		}),
		async execute(_id, params: { path: string; times_s: number[] }) {
			const video = resolve(params.path);
			if (!Array.isArray(params.times_s) || params.times_s.length === 0 ||
				!params.times_s.every((t) => typeof t === "number" && Number.isFinite(t))) {
				return { content: [{ type: "text", text: "Error: times_s must contain at least one finite timestamp." }], details: {} };
			}
			const dur = await videoDuration(video);
			const times = params.times_s.slice(0, MAX_FRAMES).map((t) => clampT(t, dur));
			const content = await framesContent(video, times);
			content.unshift({
				type: "text",
				text: `Video ${params.path} (duration ${dur.toFixed(2)}s), ${times.length} requested frames:`,
			});
			return { content, details: { times } };
		},
	});
}
