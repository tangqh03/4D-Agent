/**
 * Evidence Closure — S2.7 visual evidence store + multimodal closure checker.
 *
 * Silent ledger: records observation provenance via tool_result hook
 * (same mapEvent logic as evidence_ledger.ts) but NEVER injects into
 * context. The agent works freely as in S2.4b.
 *
 * Runtime evidence store: caches image payloads from tool results in
 * memory, keyed by evidence ID. Images are NOT persisted to session JSONL.
 *
 * submit_answer tool: the agent calls this instead of writing FINAL
 * directly. A multimodal VLM checker receives the key claim, relevant
 * evidence metadata, AND the actual images from those observations.
 * If a gap is found, the agent gets ONE chance to re-observe before
 * the answer is auto-accepted.
 *
 * Usage: pi -p -e vistr_video_tools.ts -e evidence_closure.ts "..."
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

// ── Evidence types (same as evidence_ledger.ts) ──────────────────────

type WorldTime =
	| { kind: "interval"; t0: number; t1: number }
	| { kind: "discrete"; ts: number[] }
	| { kind: "point"; t: number }
	| { kind: "unknown" };

type Space =
	| { kind: "global" }
	| { kind: "bbox"; box: number[]; frame: number[] }
	| { kind: "unknown" };

interface ImageRef {
	data: string;      // base64
	mimeType: string;
}

interface Evidence {
	id: string;
	source: string;
	agent_step: number;
	world_time: WorldTime;
	space: Space;
	epistemic_type: "PERCEPTION" | "DERIVATION";
	lifecycle: "ACTIVE";
	relations: Array<{ type: "REFINES"; of: string }>;
	producer_metadata: Record<string, unknown>;
	/** Runtime-only image cache — never persisted to session JSONL. */
	images: ImageRef[];
	/** Brief text snippets from tool result (first text block, truncated). */
	text_snippet: string;
}

// ── Spatiotemporal helpers ───────────────────────────────────────────

const EPS = 0.15;

function timeSubset(a: WorldTime, b: WorldTime): boolean {
	if (b.kind === "unknown" || a.kind === "unknown") return false;
	const pts = (w: WorldTime): number[] | null =>
		w.kind === "point" ? [w.t]
			: w.kind === "discrete" && w.ts.length > 0 && w.ts.every(Number.isFinite) ? w.ts
				: null;
	const within = (t: number): boolean =>
		b.kind === "interval" ? t >= b.t0 - EPS && t <= b.t1 + EPS
		: b.kind === "discrete" ? b.ts.some((x) => Math.abs(x - t) <= EPS)
		: b.kind === "point" ? Math.abs(b.t - t) <= EPS : false;
	const ap = pts(a);
	if (ap) return ap.every(within);
	if (a.kind === "interval") {
		if (b.kind !== "interval") return false;
		return a.t0 >= b.t0 - EPS && a.t1 <= b.t1 + EPS;
	}
	return false;
}

function timeStrict(a: WorldTime, b: WorldTime): boolean {
	return timeSubset(a, b) && !timeSubset(b, a);
}

function spaceSubset(a: Space, b: Space): boolean {
	if (a.kind === "unknown" || b.kind === "unknown") return false;
	if (b.kind === "global") return true;
	if (a.kind === "global") return false;
	if (a.frame.join() !== b.frame.join()) return false;
	const tol = 0.05 * Math.max(b.box[2] - b.box[0], b.box[3] - b.box[1]);
	return a.box[0] >= b.box[0] - tol && a.box[1] >= b.box[1] - tol &&
		a.box[2] <= b.box[2] + tol && a.box[3] <= b.box[3] + tol;
}

function spaceStrict(a: Space, b: Space): boolean {
	return spaceSubset(a, b) && !(a.kind === b.kind && spaceSubset(b, a));
}

function fmtTime(w: WorldTime): string {
	switch (w.kind) {
		case "interval": return `[${w.t0.toFixed(2)}, ${w.t1.toFixed(2)}]s`;
		case "discrete": return `{${w.ts.map((t) => t.toFixed(2)).join(", ")}}s`;
		case "point": return `{${w.t.toFixed(2)}}s`;
		default: return "unknown";
	}
}

function fmtSpace(s: Space): string {
	switch (s.kind) {
		case "global": return "global";
		case "bbox": return `bbox[${s.box.map((v) => Math.round(v)).join(",")}]`;
		default: return "unknown";
	}
}

// ── Tool result → Evidence mapper (same as evidence_ledger.ts) ──────

function mapEvent(toolName: string, input: any, details: any): Omit<Evidence,
	"id" | "agent_step" | "lifecycle" | "relations" | "images" | "text_snippet"> | null {
	const times: number[] | undefined = details?.times;
	const validTimes = (value: unknown): value is number[] =>
		Array.isArray(value) && value.length > 0 && value.every((t) => typeof t === "number" && Number.isFinite(t));
	const validBox = (value: unknown): value is number[] =>
		Array.isArray(value) && value.length === 4 && value.every((v) => typeof v === "number" && Number.isFinite(v));
	const validFrame = (value: unknown): value is number[] =>
		Array.isArray(value) && value.length === 2 && value.every((v) => typeof v === "number" && Number.isFinite(v) && v > 0);
	switch (toolName) {
		case "index_video":
			if (details?.caption_ok === false) return null;
			return { source: toolName,
				world_time: validTimes(times) ? { kind: "discrete", ts: times } : { kind: "unknown" },
				space: { kind: "global" }, epistemic_type: "DERIVATION",
				producer_metadata: { num_frames: times?.length ?? null } };
		case "read_video_sequence":
			if (!validTimes(times)) return null;
			return { source: toolName,
				world_time: { kind: "interval", t0: Math.min(...times), t1: Math.max(...times) },
				space: { kind: "global" }, epistemic_type: "PERCEPTION",
				producer_metadata: { sampled_ts: times } };
		case "read_multiframe":
			if (!validTimes(times)) return null;
			return { source: toolName,
				world_time: { kind: "discrete", ts: times },
				space: { kind: "global" }, epistemic_type: "PERCEPTION",
				producer_metadata: {} };
		case "semantic_crop": {
			if (!validBox(details?.crop_bbox) || !validFrame(details?.frame_size)) return null;
			const t = details?.time_s;
			if (t !== undefined && t !== null && (typeof t !== "number" || !Number.isFinite(t))) return null;
			return { source: toolName,
				world_time: typeof t === "number" ? { kind: "point", t } : { kind: "unknown" },
				space: { kind: "bbox", box: details.crop_bbox, frame: details.frame_size },
				epistemic_type: "PERCEPTION",
				producer_metadata: { target: details?.target ?? input?.target ?? null } };
		}
		case "read_crop": {
			if (!validBox(details?.pixels) || !validFrame(details?.source)) return null;
			const t = details?.time_s;
			if (t !== undefined && t !== null && (typeof t !== "number" || !Number.isFinite(t))) return null;
			return { source: toolName,
				world_time: typeof t === "number" ? { kind: "point", t } : { kind: "unknown" },
				space: { kind: "bbox", box: details.pixels, frame: details.source },
				epistemic_type: "PERCEPTION",
				producer_metadata: {} };
		}
		case "read": {
			const p = String(input?.path ?? "");
			if (!/\.(jpe?g|png|gif|webp|bmp)$/i.test(p)) return null;
			return { source: "read(image)",
				world_time: { kind: "unknown" }, space: { kind: "unknown" },
				epistemic_type: "PERCEPTION", producer_metadata: { path: p } };
		}
		default:
			return null;
	}
}

// ── Test surface ─────────────────────────────────────────────────────
// Pure helpers exported for unit tests (agent/pi_ext/tests/). pi's
// extension loader only consumes the default export, so these are
// behavior-neutral.

// ── VLM gateway config (same as vistr_video_tools.ts) ───────────────

async function gatewayConfig(): Promise<{ baseUrl: string; apiKey: string; model: string }> {
	const raw = await readFile(join(process.env.HOME ?? "~", ".pi", "agent", "models.json"), "utf-8");
	const cfg = JSON.parse(raw);
	const prov = cfg.providers[process.env.VISTR_CAPTION_PROVIDER ?? "amap-gateway"];
	const model = process.env.VISTR_CAPTION_MODEL ?? prov.models[0].id;
	return { baseUrl: prov.baseUrl, apiKey: prov.apiKey, model };
}

// ── Relevance selection: pick evidence entries relevant to key_claim ──

/**
 * Score each PERCEPTION evidence entry for relevance to the key_claim.
 * Uses heuristics: time overlap with claimed timestamps, source type
 * preference (crop > sequence > multiframe), and REFINES chain proximity.
 * Returns top-N entries sorted by relevance score descending.
 */
function selectRelevantEvidence(
	ledger: Evidence[],
	keyClaim: string,
	maxEntries: number,
	maxImages: number,
): Evidence[] {
	// Extract timestamps from key_claim (e.g., "at 2.5s", "t=1.0", "around 3s")
	const timePattern = /(\d+\.?\d*)\s*s/g;
	const claimTimes: number[] = [];
	let m: RegExpExecArray | null;
	while ((m = timePattern.exec(keyClaim)) !== null) {
		claimTimes.push(parseFloat(m[1]));
	}

	const perceptionOnly = ledger.filter((e) => e.epistemic_type === "PERCEPTION");

	const scored = perceptionOnly.map((e) => {
		let score = 0;

		// Time proximity: how close are the claim times to this evidence's time?
		if (claimTimes.length > 0) {
			const evTimes: number[] = [];
			if (e.world_time.kind === "point") evTimes.push(e.world_time.t);
			else if (e.world_time.kind === "discrete") evTimes.push(...e.world_time.ts);
			else if (e.world_time.kind === "interval") {
				// For intervals, check if any claim time falls within
				for (const ct of claimTimes) {
					if (ct >= e.world_time.t0 - EPS && ct <= e.world_time.t1 + EPS) {
						score += 10; // direct containment
					}
				}
				// Also consider interval midpoint distance
				const mid = (e.world_time.t0 + e.world_time.t1) / 2;
				evTimes.push(mid);
			}
			for (const ct of claimTimes) {
				for (const et of evTimes) {
					const dist = Math.abs(ct - et);
					if (dist < 0.3) score += 8;
					else if (dist < 1.0) score += 4;
					else if (dist < 2.0) score += 1;
				}
			}
		}

		// Source type preference: spatially precise tools are more relevant
		switch (e.source) {
			case "semantic_crop": score += 5; break;
			case "read_crop": score += 4; break;
			case "read_multiframe": score += 3; break;
			case "read_video_sequence": score += 2; break;
		}

		// REFINES chain: refined evidence (more specific) gets a bonus
		if (e.relations.length > 0) score += 2;

		// Recency bonus: later observations are more likely to be decisive
		score += e.agent_step * 0.5;

		// Has images?
		if (e.images.length > 0) score += 3;

		return { entry: e, score };
	});

	scored.sort((a, b) => b.score - a.score);

	// Select top entries, respecting image budget
	const selected: Evidence[] = [];
	let imageCount = 0;
	for (const { entry } of scored) {
		if (selected.length >= maxEntries) break;
		const entryImages = Math.min(entry.images.length, 2); // max 2 images per entry
		if (imageCount + entryImages > maxImages) {
			// Try to fit at least 1 image
			if (imageCount < maxImages && entry.images.length > 0) {
				selected.push(entry);
				imageCount += 1;
			}
			continue;
		}
		selected.push(entry);
		imageCount += entryImages;
	}

	return selected;
}

// ── Extension entry point ───────────────────────────────────────────

export default function evidenceClosure(pi: ExtensionAPI) {
	const ledger: Evidence[] = [];
	let step = 0;
	let oneShotUsed = false;
	let accepted = false;

	// ── Silent tool_result hook: record evidence + cache images ────
	pi.on("tool_result", async (event: any) => {
		if (event.isError) return;
		if (event.toolName === "submit_answer") return;
		const mapped = mapEvent(event.toolName, event.input, event.details);
		if (!mapped) return;
		step += 1;

		// Extract images and text snippets from tool result content
		const images: ImageRef[] = [];
		let textSnippet = "";
		const content = event.content as Array<{ type: string; data?: string; mimeType?: string; text?: string }> | undefined;
		if (Array.isArray(content)) {
			for (const block of content) {
				if (block.type === "image" && block.data) {
					images.push({ data: block.data, mimeType: block.mimeType ?? "image/jpeg" });
				} else if (block.type === "text" && block.text && !textSnippet) {
					textSnippet = block.text.slice(0, 200);
				}
			}
		}

		const ev: Evidence = {
			...mapped, id: `E${ledger.length + 1}`, agent_step: step,
			lifecycle: "ACTIVE", relations: [],
			images, text_snippet: textSnippet,
		};
		for (const old of ledger) {
			const tSub = timeSubset(ev.world_time, old.world_time);
			const sSub = spaceSubset(ev.space, old.space);
			const strict = timeStrict(ev.world_time, old.world_time) || spaceStrict(ev.space, old.space);
			if (tSub && sSub && strict) {
				ev.relations.push({ type: "REFINES", of: old.id });
			}
		}
		ledger.push(ev);
		// Persist metadata only (no images) to session JSONL
		const { images: _, ...metadata } = ev;
		pi.appendEntry("evidence-closure", {
			transition: "ADD",
			evidence: { ...metadata, image_count: images.length },
		});
	});

	// ── submit_answer tool ───────────────────────────────────────
	pi.registerTool({
		name: "submit_answer",
		label: "Submit answer",
		description:
			`Submit your final answer after completing your analysis. ` +
			`You MUST call this tool to submit — do not write FINAL directly. ` +
			`Provide your chosen option and the single most decisive visual fact ` +
			`your answer depends on. The system will check whether that fact has ` +
			`been directly observed; if not, you will get one chance to verify it ` +
			`with your observation tools before the answer is accepted.`,
		promptSnippet: "Submit your final answer with its key visual claim for evidence verification",
		parameters: Type.Object({
			answer: Type.String({
				description: "Your chosen option — must be one of the given options exactly",
			}),
			key_claim: Type.String({
				description:
					"The single most decisive visual fact your answer depends on, " +
					"e.g. 'the ball passes through the hoop at ~2.5s' or " +
					"'the car makes contact with the cone between 9s and 10s'",
			}),
		}),
		async execute(_id, params: { answer: string; key_claim: string }) {
			console.error(`[evidence-closure] submit_answer called: answer="${params.answer}" key_claim="${params.key_claim}" ledger_size=${ledger.length} oneshot=${oneShotUsed}`);
			const question = process.env.VISTR_QUESTION ?? "";

			// Once accepted, do not spend another checker call if the model repeats
			// the submission while finishing its final response.
			if (accepted) {
				pi.appendEntry("evidence-closure", {
					transition: "ACCEPT_ALREADY",
					answer: params.answer,
					key_claim: params.key_claim,
				});
				return {
					content: [{
						type: "text",
						text: `Answer already accepted. Now write your final answer on a new line:\nFINAL: ${params.answer}`,
					}],
					details: { accepted: true, closure: "already_accepted" },
				};
			}

			// One-shot gate: second call always accepts
			if (oneShotUsed) {
				accepted = true;
				pi.appendEntry("evidence-closure", {
					transition: "ACCEPT_ONESHOT",
					answer: params.answer,
					key_claim: params.key_claim,
				});
				return {
					content: [{
						type: "text",
						text: `Answer accepted (after verification round). Now write your final answer on a new line:\nFINAL: ${params.answer}`,
					}],
					details: { accepted: true, closure: "oneshot_bypass" },
				};
			}

			// Build compact ledger summary (metadata only, for context)
			const summary = ledger.length === 0
				? "(no observations recorded)"
				: ledger.map((e) => {
					const rel = e.relations.length
						? ` [refines ${e.relations.map((r) => r.of).join(",")}]` : "";
					const img = e.images.length > 0 ? ` (${e.images.length} imgs)` : "";
					return `${e.id} | ${e.source} | ${e.epistemic_type} | time=${fmtTime(e.world_time)} | space=${fmtSpace(e.space)}${img}${rel}`;
				}).join("\n");

			// Quick heuristic: if zero evidence at all, skip VLM call
			if (ledger.length === 0) {
				oneShotUsed = true;
				pi.appendEntry("evidence-closure", {
					transition: "GAP_NO_EVIDENCE",
					answer: params.answer,
					key_claim: params.key_claim,
				});
				return {
					content: [{
						type: "text",
						text:
							`Evidence gap detected: you have not made any visual observations yet. ` +
							`Your key claim "${params.key_claim}" has no supporting evidence.\n\n` +
							`You have ONE chance to verify: use your observation tools ` +
							`(read_video_sequence, read_multiframe, semantic_crop, etc.) to directly ` +
							`confirm or refute your key claim, then call submit_answer again.`,
					}],
					details: { accepted: false, closure: "no_evidence" },
				};
			}

			// Check: any PERCEPTION evidence at all?
			const hasPerception = ledger.some((e) => e.epistemic_type === "PERCEPTION");
			if (!hasPerception) {
				oneShotUsed = true;
				pi.appendEntry("evidence-closure", {
					transition: "GAP_DERIVATION_ONLY",
					answer: params.answer,
					key_claim: params.key_claim,
				});
				return {
					content: [{
						type: "text",
						text:
							`Evidence gap detected: all your observations are text-derived (index_video captions). ` +
							`You have not directly viewed any video frames.\n` +
							`Key claim: "${params.key_claim}"\n\n` +
							`You have ONE chance to verify: use read_video_sequence or read_multiframe ` +
							`to directly view the critical moment, then call submit_answer again.`,
					}],
					details: { accepted: false, closure: "derivation_only" },
				};
			}

			// ── Select relevant evidence with images for the checker ──
			const MAX_CHECKER_IMAGES = 4;
			const MAX_CHECKER_ENTRIES = 3;
			const relevant = selectRelevantEvidence(ledger, params.key_claim, MAX_CHECKER_ENTRIES, MAX_CHECKER_IMAGES);

			// Collect images from selected evidence (respect budget)
			const checkerImages: Array<{ evidenceId: string; source: string; time: string; img: ImageRef }> = [];
			let imgBudget = MAX_CHECKER_IMAGES;
			for (const ev of relevant) {
				for (const img of ev.images) {
					if (imgBudget <= 0) break;
					checkerImages.push({
						evidenceId: ev.id,
						source: ev.source,
						time: fmtTime(ev.world_time),
						img,
					});
					imgBudget--;
				}
			}

			console.error(`[evidence-closure] selected ${relevant.length} evidence entries, ${checkerImages.length} images for checker`);

			// ── Build multimodal checker content ──
			const checkerText =
				`You are an evidence auditor — NOT a problem solver. Do NOT re-answer the question.\n\n` +
				`Question: ${question}\n` +
				`Proposed answer: ${params.answer}\n` +
				`Agent's key claim: ${params.key_claim}\n\n` +
				`Full observation ledger (chronological):\n${summary}\n\n` +
				(checkerImages.length > 0
					? `Below are the actual visual observations most relevant to the key claim. ` +
					  `Examine them carefully to determine if they directly confirm or refute the key claim.\n\n`
					: `No visual evidence images are available for review.\n\n`) +
				`Assess ONLY: Is the key_claim directly confirmed by the visual evidence shown? ` +
				`Do NOT infer or assume — judge only what is visible in the images.\n\n` +
				`Reply EXACTLY one line:\nCLOSURE: YES\nor\nCLOSURE: NO | <one sentence: what visual check is missing>`;

			// Build multimodal content array for OpenAI-compatible API
			const userContent: Array<Record<string, unknown>> = [
				{ type: "text", text: checkerText },
			];
			for (const ci of checkerImages) {
				userContent.push({
					type: "text",
					text: `[${ci.evidenceId}] ${ci.source} @ ${ci.time}:`,
				});
				userContent.push({
					type: "image_url",
					image_url: { url: `data:${ci.img.mimeType};base64,${ci.img.data}` },
				});
			}

			console.error(`[evidence-closure] running multimodal VLM closure check (${checkerImages.length} images)...`);
			try {
				const gw = await gatewayConfig();
				const resp = await fetch(`${gw.baseUrl}/chat/completions`, {
					method: "POST",
					headers: { "Content-Type": "application/json", Authorization: `Bearer ${gw.apiKey}` },
					body: JSON.stringify({
						model: gw.model,
						messages: [{ role: "user", content: userContent }],
						max_tokens: 150,
						temperature: 0,
						// Qwen3 thinking models spend their whole budget in the
						// thinking phase and never emit a content line (content=null
						// -> checker TypeError -> error_bypass). The auditor is a
						// classification task: disable thinking. Harmless for
						// non-thinking models.
						chat_template_kwargs: { enable_thinking: false },
					}),
					signal: AbortSignal.timeout(60_000),
				});
				if (!resp.ok) throw new Error(`checker HTTP ${resp.status}`);
				const data = (await resp.json()) as { choices: Array<{ message: { content: string } }> };
				const reply = (data.choices[0].message.content ?? "").trim();
				console.error(`[evidence-closure] checker reply: ${reply}`);
				const closureMatch = reply.match(/CLOSURE:\s*(YES|NO)\s*(?:\|\s*(.+))?/i);

				if (closureMatch && closureMatch[1].toUpperCase() === "YES") {
					accepted = true;
					pi.appendEntry("evidence-closure", {
						transition: "CLOSURE_YES",
						answer: params.answer,
						key_claim: params.key_claim,
						checker_reply: reply,
						images_sent: checkerImages.length,
					});
					return {
						content: [{
							type: "text",
							text: `Evidence closure confirmed — your key claim is backed by direct visual observation. Now write your final answer on a new line:\nFINAL: ${params.answer}`,
						}],
						details: { accepted: true, closure: "confirmed", checker_reply: reply },
					};
				}

				// CLOSURE: NO
				const gap = closureMatch?.[2]?.trim() ?? "the key claim lacks direct visual confirmation";
				oneShotUsed = true;
				pi.appendEntry("evidence-closure", {
					transition: "CLOSURE_NO",
					answer: params.answer,
					key_claim: params.key_claim,
					checker_reply: reply,
					gap,
					images_sent: checkerImages.length,
				});
				return {
					content: [{
						type: "text",
						text:
							`Evidence gap detected: ${gap}\n\n` +
							`Your key claim "${params.key_claim}" is not yet directly confirmed by visual evidence.\n\n` +
							`You have ONE chance to verify: use your observation tools to directly view ` +
							`the critical moment/region, then call submit_answer again with your ` +
							`(possibly revised) answer.`,
					}],
					details: { accepted: false, closure: "gap", gap, checker_reply: reply },
				};
			} catch (err) {
				// Checker failed — don't block the agent, accept gracefully
				accepted = true;
				pi.appendEntry("evidence-closure", {
					transition: "CHECKER_ERROR",
					answer: params.answer,
					key_claim: params.key_claim,
					error: String(err),
				});
				return {
					content: [{
						type: "text",
						text: `Evidence check unavailable (${err}). Accepting answer. Now write your final answer on a new line:\nFINAL: ${params.answer}`,
					}],
					details: { accepted: true, closure: "error_bypass", error: String(err) },
				};
			}
		},
	});
}

// Test surface (behavior-neutral named exports; see note above).
export { timeSubset, timeStrict, spaceSubset, spaceStrict, fmtTime, fmtSpace, mapEvent };
