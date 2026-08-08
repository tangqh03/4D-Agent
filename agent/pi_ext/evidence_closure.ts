/**
 * Evidence Closure — S2.6 silent ledger + submit_answer gate.
 *
 * Silent ledger: records observation provenance via tool_result hook
 * (same mapEvent logic as evidence_ledger.ts) but NEVER injects into
 * context. The agent works freely as in S2.4b.
 *
 * submit_answer tool: the agent calls this instead of writing FINAL
 * directly. A lightweight VLM checker assesses whether the key claim
 * is backed by direct visual PERCEPTION evidence or only by text
 * inference / DERIVATION. If a gap is found, the agent gets ONE
 * chance to re-observe before the answer is auto-accepted.
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
}

// ── Spatiotemporal helpers ───────────────────────────────────────────

const EPS = 0.15;

function timeSubset(a: WorldTime, b: WorldTime): boolean {
	if (b.kind === "unknown" || a.kind === "unknown") return false;
	const pts = (w: WorldTime): number[] | null =>
		w.kind === "point" ? [w.t] : w.kind === "discrete" ? w.ts : null;
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
	"id" | "agent_step" | "lifecycle" | "relations"> | null {
	const times: number[] | undefined = details?.times;
	switch (toolName) {
		case "index_video":
			return { source: toolName,
				world_time: times?.length ? { kind: "discrete", ts: times } : { kind: "unknown" },
				space: { kind: "global" }, epistemic_type: "DERIVATION",
				producer_metadata: { num_frames: times?.length ?? null } };
		case "read_video_sequence":
			return { source: toolName,
				world_time: times?.length
					? { kind: "interval", t0: Math.min(...times), t1: Math.max(...times) }
					: { kind: "unknown" },
				space: { kind: "global" }, epistemic_type: "PERCEPTION",
				producer_metadata: { sampled_ts: times ?? null } };
		case "read_multiframe":
			return { source: toolName,
				world_time: times?.length ? { kind: "discrete", ts: times } : { kind: "unknown" },
				space: { kind: "global" }, epistemic_type: "PERCEPTION",
				producer_metadata: {} };
		case "semantic_crop": {
			const t = details?.time_s;
			return { source: toolName,
				world_time: typeof t === "number" ? { kind: "point", t } : { kind: "unknown" },
				space: details?.crop_bbox && details?.frame_size
					? { kind: "bbox", box: details.crop_bbox, frame: details.frame_size }
					: { kind: "unknown" },
				epistemic_type: "PERCEPTION",
				producer_metadata: { target: details?.target ?? input?.target ?? null } };
		}
		case "read_crop": {
			const t = details?.time_s;
			return { source: toolName,
				world_time: typeof t === "number" ? { kind: "point", t } : { kind: "unknown" },
				space: details?.pixels && details?.source
					? { kind: "bbox", box: details.pixels, frame: details.source }
					: { kind: "unknown" },
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

// ── VLM gateway config (same as vistr_video_tools.ts) ───────────────

async function gatewayConfig(): Promise<{ baseUrl: string; apiKey: string; model: string }> {
	const raw = await readFile(join(process.env.HOME ?? "~", ".pi", "agent", "models.json"), "utf-8");
	const cfg = JSON.parse(raw);
	const prov = cfg.providers[process.env.VISTR_CAPTION_PROVIDER ?? "amap-gateway"];
	const model = process.env.VISTR_CAPTION_MODEL ?? prov.models[0].id;
	return { baseUrl: prov.baseUrl, apiKey: prov.apiKey, model };
}

// ── Extension entry point ───────────────────────────────────────────

export default function evidenceClosure(pi: ExtensionAPI) {
	const ledger: Evidence[] = [];
	let step = 0;
	let oneShotUsed = false;

	// ── Silent tool_result hook: record evidence, never expose ────
	pi.on("tool_result", async (event: any) => {
		if (event.isError) return;
		if (event.toolName === "submit_answer") return;
		const mapped = mapEvent(event.toolName, event.input, event.details);
		if (!mapped) return;
		step += 1;
		const ev: Evidence = {
			...mapped, id: `E${ledger.length + 1}`, agent_step: step,
			lifecycle: "ACTIVE", relations: [],
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
		pi.appendEntry("evidence-closure", { transition: "ADD", evidence: ev });
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

			// One-shot gate: second call always accepts
			if (oneShotUsed) {
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

			// Build compact ledger summary
			const summary = ledger.length === 0
				? "(no observations recorded)"
				: ledger.map((e) => {
					const rel = e.relations.length
						? ` [refines ${e.relations.map((r) => r.of).join(",")}]` : "";
					return `${e.id} | ${e.source} | ${e.epistemic_type} | time=${fmtTime(e.world_time)} | space=${fmtSpace(e.space)}${rel}`;
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
				// Only DERIVATION (index_video captions) — definite gap
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

			// VLM closure check
			const checkerPrompt =
				`You are an evidence auditor — NOT a problem solver. Do NOT re-answer the question.\n\n` +
				`Question: ${question}\n` +
				`Proposed answer: ${params.answer}\n` +
				`Agent's key claim: ${params.key_claim}\n\n` +
				`Observations the agent made (chronological):\n${summary}\n\n` +
				`PERCEPTION = agent directly viewed video frames (read_video_sequence, read_multiframe, semantic_crop, read_crop)\n` +
				`DERIVATION = text caption from automated timeline (index_video)\n\n` +
				`Assess ONLY: Is the key_claim directly confirmed by PERCEPTION evidence ` +
				`that covers the relevant time and space? Or is it only supported by ` +
				`DERIVATION, text reasoning, or external knowledge?\n\n` +
				`Reply EXACTLY one line:\nCLOSURE: YES\nor\nCLOSURE: NO | <one sentence: what visual check is missing>`;

			console.error(`[evidence-closure] running VLM closure check...`);
			try {
				const gw = await gatewayConfig();
				const resp = await fetch(`${gw.baseUrl}/chat/completions`, {
					method: "POST",
					headers: { "Content-Type": "application/json", Authorization: `Bearer ${gw.apiKey}` },
					body: JSON.stringify({
						model: gw.model,
						messages: [{ role: "user", content: checkerPrompt }],
						max_tokens: 100,
						temperature: 0,
					}),
					signal: AbortSignal.timeout(30_000),
				});
				if (!resp.ok) throw new Error(`checker HTTP ${resp.status}`);
				const data = (await resp.json()) as { choices: Array<{ message: { content: string } }> };
				const reply = data.choices[0].message.content.trim();
				console.error(`[evidence-closure] checker reply: ${reply}`);
				const closureMatch = reply.match(/CLOSURE:\s*(YES|NO)\s*(?:\|\s*(.+))?/i);

				if (closureMatch && closureMatch[1].toUpperCase() === "YES") {
					pi.appendEntry("evidence-closure", {
						transition: "CLOSURE_YES",
						answer: params.answer,
						key_claim: params.key_claim,
						checker_reply: reply,
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
