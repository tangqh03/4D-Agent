#!/usr/bin/env python
"""Patch installed pi-ai to handle cumulative streaming tool-call arguments.

The AMAP gateway (qwen) streams `tool_calls[].function.arguments` cumulatively
(each chunk repeats the full prefix), while the OpenAI spec sends incremental
deltas. Unpatched pi-ai concatenates chunks, producing garbled tool args like
`{"command": "ff{"}`. This patch auto-detects the style per chunk: if the new
chunk extends the accumulated string, it replaces instead of appends.

Re-run after any `npm install/update` under third_party/pi-runtime.

Usage: /opt/conda/bin/python scripts/patch_pi_cumulative_args.py
"""
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(
    PROJ, "third_party", "pi-runtime", "node_modules", "@earendil-works",
    "pi-coding-agent", "node_modules", "@earendil-works", "pi-ai",
    "dist", "api", "openai-completions.js")

OLD = """                            if (toolCall.function?.arguments) {
                                delta = toolCall.function.arguments;
                                block.partialArgs = (block.partialArgs ?? "") + toolCall.function.arguments;
                                block.arguments = parseStreamingJson(block.partialArgs);
                            }"""

NEW = """                            if (toolCall.function?.arguments) {
                                // PATCHED (ViSTR): some gateways stream cumulative
                                // arguments instead of incremental deltas.
                                const _args = toolCall.function.arguments;
                                const _prev = block.partialArgs ?? "";
                                if (_prev.length > 0 && _args.length >= _prev.length && _args.startsWith(_prev)) {
                                    delta = _args.slice(_prev.length);
                                    block.partialArgs = _args;
                                }
                                else {
                                    delta = _args;
                                    block.partialArgs = _prev + _args;
                                }
                                block.arguments = parseStreamingJson(block.partialArgs);
                            }"""


def main():
    with open(TARGET) as f:
        src = f.read()
    if "PATCHED (ViSTR)" in src:
        print("already patched:", TARGET)
        return
    if OLD not in src:
        print("ERROR: expected code block not found (pi version changed?)")
        sys.exit(1)
    with open(TARGET, "w") as f:
        f.write(src.replace(OLD, NEW, 1))
    print("patched:", TARGET)


if __name__ == "__main__":
    main()
