/**
 * Evidence Ledger — evidence-only Structured Evidence Ledger for pi.
 *
 * Registers NO new LLM-callable tools. Three hooks:
 *   tool_result  -> deterministic per-tool mapper -> ledger entry
 *                   (facts come ONLY from event.input/details; no LLM summaries)
 *   context      -> inject ONE compact <EVIDENCE_STATE> dashboard before each
 *                   LLM call (index/provenance only; no images, no reasoning)
 *   appendEntry  -> persist entries/transitions into the pi session JSONL
 *
 * Core distinction: agent_step (when the agent saw it) vs world_time_support
 * (which part of the video it describes) plus spatial_support. If a new
 * observation's spatiotemporal support is a strict subset of an older one,
 * it is recorded as REFINES(old) — never an implicit supersede.
 *
 * Usage: pi -p -e vistr_video_tools.ts -e evidence_ledger.ts "..."
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

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

const EPS = 0.15; // seconds tolerance for timestamp membership

function timeSubset(a: WorldTime, b: WorldTime): boolean {
	// is a ⊆ b ?
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
		case "bbox": return `bbox[${s.box.map((v) => Math.round(v)).join(",")}] of ${s.frame.join("x")}`;
		default: return "unknown";
	}
}

export default function evidenceLedger(pi: ExtensionAPI) {
	const ledger: Evidence[] = [];
	let step = 0;

	function mapEvent(toolName: string, input: any, details: any): Omit<Evidence,
		"id" | "agent_step" | "lifecycle" | "relations"> | null {
		const times: number[] | undefined = details?.times;
		switch (toolName) {
			case "index_video":
				return { source: toolName,
					world_time: times?.length ? { kind: "discrete", ts: times } : { kind: "unknown" },
					space: { kind: "global" }, epistemic_type: "DERIVATION",
					producer_metadata: { num_frames: times?.length ?? null, caption_backend: "vlm" } };
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
					producer_metadata: {
						target: details?.target ?? input?.target ?? null,
						grounding_phrase: details?.grounding_phrase ?? null,
						grounding_score: details?.grounding_score ?? null, // producer score only
						candidate_count: details?.candidate_count ?? null,
						selection_mode: details?.selection_mode ?? null,
					} };
			}
			case "read_crop": {
				const t = details?.time_s;
				return { source: toolName,
					world_time: typeof t === "number" ? { kind: "point", t } : { kind: "unknown" },
					space: details?.pixels && details?.source
						? { kind: "bbox", box: details.pixels, frame: details.source }
						: { kind: "unknown" },
					epistemic_type: "PERCEPTION",
					producer_metadata: { bbox_norm1000: input?.bbox ?? null } };
			}
			case "read": {
				const p = String(input?.path ?? "");
				if (!/\.(jpe?g|png|gif|webp|bmp)$/i.test(p)) return null; // text reads: not visual evidence
				// No fragile bash/filename parsing: video timestamp unknown by design.
				return { source: "read(image)",
					world_time: { kind: "unknown" }, space: { kind: "unknown" },
					epistemic_type: "PERCEPTION", producer_metadata: { path: p } };
			}
			default:
				return null;
		}
	}

	pi.on("tool_result", async (event: any) => {
		if (event.isError) return;
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
		pi.appendEntry("evidence-ledger", { transition: "ADD", evidence: ev });
	});

	pi.on("context", async (event: any) => {
		if (!ledger.length) return;
		const lines = ledger.map((e) => {
			const rel = e.relations.length
				? `\n   relation = ${e.relations.map((r) => `${r.type}(${r.of})`).join(", ")}` : "";
			const extra = e.source === "semantic_crop" && e.producer_metadata.target
				? ` target="${e.producer_metadata.target}"` : "";
			return `${e.id} | ${e.source}${extra} | step ${e.agent_step} | ${e.epistemic_type}` +
				`\n   world-time = ${fmtTime(e.world_time)}\n   space = ${fmtSpace(e.space)}${rel}`;
		});
		const dashboard =
			"<EVIDENCE_STATE>\n" + lines.join("\n") + "\n\n" +
			"Evidence obtained later in agent time does not automatically supersede " +
			"evidence with broader world-time/spatial support. A REFINES entry adds " +
			"local detail to its parent; it does not replace it.\n" +
			"</EVIDENCE_STATE>";

		// Mode "tail" (S2.5a): append as a synthetic trailing message. pi converts
		// role:"custom" to role:"user" in the provider payload, so this reads as a
		// brand-new user turn and hijacks task framing (verified negative result).
		if ((process.env.VISTR_LEDGER_MODE ?? "anchor") === "tail") {
			const messages = [...event.messages, {
				role: "custom", customType: "evidence-ledger",
				content: dashboard, display: false, timestamp: Date.now(),
			}];
			return { messages };
		}

		// Mode "anchor" (S2.5b): transiently rewrite the ORIGINAL first user message,
		// prefixing the dashboard BEFORE the task text, so the task/options/FINAL
		// requirements stay closest to the end of that turn. No extra message is added.
		const messages = event.messages.map((m: any) => ({ ...m }));
		const first = messages.find((m: any) => m.role === "user");
		if (!first) return;
		if (typeof first.content === "string") {
			first.content = dashboard + "\n\n" + first.content;
		} else if (Array.isArray(first.content)) {
			first.content = [{ type: "text", text: dashboard }, ...first.content];
		}
		return { messages };
	});
}
