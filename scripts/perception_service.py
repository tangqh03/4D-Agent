#!/usr/bin/env python3
"""Persistent perception model-pool service.

Long-running HTTP service hosting vision backends (GPU-resident after first
load). Extensions/tools call it over HTTP; they must NOT load weights
themselves. Currently deployed: GroundingDINO. The registry pattern leaves
room for SAM2 / DA3 / VGGT later.

Usage:
    nohup /home/admin/.conda/envs/star/bin/python -u scripts/perception_service.py \
        --port 7876 > /tmp/perception_service.log 2>&1 &

Endpoints:
    GET  /health              -> {status, models: {name: loaded|lazy}}
    POST /ground              -> GroundingDINO detection
         {image_b64, text, box_threshold?, text_threshold?, topk?, annotate?}
         -> {width, height, candidates: [{id, bbox, bbox_norm1000, score, phrase}],
             annotated_b64?}   (bbox = pixel xyxy on original image)
    POST /annotate            -> draw one bbox on a thumbnail (grounding receipt)
         {image_b64, bbox}    -> {annotated_b64}
"""
from __future__ import annotations

import argparse
import base64
import io
import threading

from flask import Flask, jsonify, request
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

_MODELS = {}
_LOCK = threading.Lock()
GDINO_PATH = "/mnt/xlab-nas-wm/gaozhe.gz/hf_datasets/grounding-dino-base"
DEVICE = "cuda"


def get_gdino():
    with _LOCK:
        if "grounding-dino" not in _MODELS:
            import torch
            from transformers import AutoProcessor, GroundingDinoForObjectDetection
            print("[pool] loading GroundingDINO ...", flush=True)
            processor = AutoProcessor.from_pretrained(GDINO_PATH)
            model = GroundingDinoForObjectDetection.from_pretrained(
                GDINO_PATH, torch_dtype=torch.float32).to(DEVICE).eval()
            _MODELS["grounding-dino"] = (processor, model)
            print("[pool] GroundingDINO resident on", DEVICE, flush=True)
    return _MODELS["grounding-dino"]


def decode_image(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def encode_image(img: Image.Image, quality=80) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def draw_boxes(img: Image.Image, boxes, labels, max_w=800) -> Image.Image:
    scale = min(1.0, max_w / img.width)
    thumb = img.resize((int(img.width * scale), int(img.height * scale)))
    d = ImageDraw.Draw(thumb)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    colors = ["#ff3b30", "#34c759", "#007aff", "#ff9500", "#af52de", "#00c7be"]
    for i, (b, lab) in enumerate(zip(boxes, labels)):
        x0, y0, x1, y1 = [v * scale for v in b]
        col = colors[i % len(colors)]
        d.rectangle([x0, y0, x1, y1], outline=col, width=3)
        d.text((x0 + 3, max(0, y0 - 26)), str(lab), fill=col, font=font)
    return thumb


@app.route("/health")
def health():
    return jsonify({"status": "ok",
                    "models": {"grounding-dino":
                               "loaded" if "grounding-dino" in _MODELS else "lazy"}})


@app.route("/ground", methods=["POST"])
def ground():
    import torch
    req = request.get_json(force=True)
    img = decode_image(req["image_b64"])
    text = req["text"].strip().lower()
    if not text.endswith("."):
        text += "."
    topk = int(req.get("topk", 6))
    processor, model = get_gdino()
    inputs = processor(images=img, text=text, return_tensors="pt").to(DEVICE)
    with torch.no_grad():
        outputs = model(**inputs)
    res = processor.post_process_grounded_object_detection(
        outputs, inputs.input_ids,
        threshold=float(req.get("box_threshold", 0.25)),
        text_threshold=float(req.get("text_threshold", 0.2)),
        target_sizes=[img.size[::-1]])[0]
    order = res["scores"].argsort(descending=True)[:topk]
    cands = []
    for rank, idx in enumerate(order.tolist(), start=1):
        box = [round(v, 1) for v in res["boxes"][idx].tolist()]
        cands.append({
            "id": rank,
            "bbox": box,
            "bbox_norm1000": [round(box[0] / img.width * 1000),
                              round(box[1] / img.height * 1000),
                              round(box[2] / img.width * 1000),
                              round(box[3] / img.height * 1000)],
            "score": round(float(res["scores"][idx]), 3),
            "phrase": res["text_labels"][idx],
        })
    out = {"width": img.width, "height": img.height, "candidates": cands}
    if req.get("annotate") and cands:
        out["annotated_b64"] = encode_image(
            draw_boxes(img, [c["bbox"] for c in cands],
                       [c["id"] for c in cands]))
    return jsonify(out)


@app.route("/annotate", methods=["POST"])
def annotate():
    req = request.get_json(force=True)
    img = decode_image(req["image_b64"])
    thumb = draw_boxes(img, [req["bbox"]], [req.get("label", "sel")], max_w=640)
    return jsonify({"annotated_b64": encode_image(thumb, quality=70)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7876)
    parser.add_argument("--eager", action="store_true",
                        help="load models at startup instead of first request")
    args = parser.parse_args()
    if args.eager:
        get_gdino()
    print(f"[pool] perception service on 0.0.0.0:{args.port}", flush=True)
    app.run(host="0.0.0.0", port=args.port, threaded=True)
