#!/usr/bin/env python3
"""pi Case Viewer — Flask 前端(S1/S2 对比 + Stage2 工具轨迹回放)。

参考 v3_case_viewer.py (7874) 的代理友好模式:单页 HTML + 相对路径 API,
无 websocket,可经 notebook 代理 /proxy/<port>/ 访问。

用法:
    /opt/conda/bin/python scripts/pi_case_viewer.py --port 7875
    # 访问: http://<notebook-host>:8080/proxy/7875/  (或对应代理路径)

数据: 先运行 scripts/build_case_viewer.py 生成 web/case_viewer/data/。
"""

import argparse
import json
import os

from flask import Flask, jsonify, request, send_file, abort

app = Flask(__name__)

PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJ_DIR, "web", "case_viewer", "data")
BENCH_DIR = os.path.join(PROJ_DIR, "data", "benchmarks", "ViSTR-Bench-Public")

with open(os.path.join(DATA_DIR, "cases.json")) as f:
    CASES = json.load(f)
BY_ID = {c["id"]: c for c in CASES}


@app.route("/api/cases")
def api_cases():
    slim = [{k: c[k] for k in
             ("id", "task", "dimension", "question", "options", "gt")} |
            {"s1": {"pred": c["s1"]["pred"], "correct": c["s1"]["correct"]},
             "s2": {"pred": c["s2"]["pred"], "correct": c["s2"]["correct"]},
             "s21": ({"pred": c["s21"]["pred"], "correct": c["s21"]["correct"]}
                     if c.get("s21") else None),
             "s22": ({"pred": c["s22"]["pred"], "correct": c["s22"]["correct"]}
                     if c.get("s22") else None),
             "s23": ({"pred": c["s23"]["pred"], "correct": c["s23"]["correct"]}
                     if c.get("s23") else None),
             "s24": ({"pred": c["s24"]["pred"], "correct": c["s24"]["correct"]}
                     if c.get("s24") else None)}
            for c in CASES]
    return jsonify(slim)


@app.route("/api/case_detail")
def api_case_detail():
    c = BY_ID.get(request.args.get("id", type=int))
    if not c:
        abort(404)
    return jsonify(c)


@app.route("/api/video")
def api_video():
    c = BY_ID.get(request.args.get("id", type=int))
    if not c:
        abort(404)
    path = os.path.realpath(os.path.join(BENCH_DIR, c["video"]))
    if not path.startswith(os.path.realpath(BENCH_DIR)) or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/api/img")
def api_img():
    src = request.args.get("src", "")
    path = os.path.realpath(os.path.join(DATA_DIR, src))
    if not path.startswith(os.path.realpath(os.path.join(DATA_DIR, "images"))) \
            or not path.endswith(".jpg") or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/jpeg")


HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>ViSTR pi Case Viewer</title>
<style>
:root { --bg:#12141a; --panel:#1b1e27; --line:#2b2f3d; --fg:#dde1ea; --dim:#8b91a3;
        --ok:#3fb96d; --bad:#e05656; --accent:#5b8def; --tool:#c9a04e; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:14px/1.5 "SF Mono",Consolas,Menlo,monospace; display:flex; height:100vh; }
#side { width:380px; min-width:380px; border-right:1px solid var(--line);
        display:flex; flex-direction:column; }
#filters { padding:10px; border-bottom:1px solid var(--line); }
#filters select, #filters input { background:var(--panel); color:var(--fg);
        border:1px solid var(--line); border-radius:4px; padding:4px 6px;
        margin:2px 4px 2px 0; font:inherit; }
#stats { padding:6px 10px; color:var(--dim); font-size:12px; border-bottom:1px solid var(--line); }
#list { flex:1; overflow-y:auto; }
.item { padding:8px 10px; border-bottom:1px solid var(--line); cursor:pointer; }
.item:hover { background:var(--panel); }
.item.sel { background:#232a3d; }
.item .q { color:var(--dim); font-size:12px; white-space:nowrap;
           overflow:hidden; text-overflow:ellipsis; }
.badge { display:inline-block; padding:0 6px; border-radius:3px; font-size:12px; margin-right:4px; }
.b-ok { background:rgba(63,185,109,.15); color:var(--ok); }
.b-bad { background:rgba(224,86,86,.15); color:var(--bad); }
.b-task { background:rgba(91,141,239,.15); color:var(--accent); }
#main { flex:1; overflow-y:auto; padding:16px 22px; }
h2 { margin:4px 0 10px; font-size:16px; }
.row { display:flex; gap:18px; flex-wrap:wrap; margin-bottom:14px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
        padding:12px 14px; }
video { max-width:480px; border-radius:8px; background:#000; }
.pred-grid { display:grid; grid-template-columns:auto auto; gap:4px 16px; }
.ev { margin:8px 0; }
.ev-text { white-space:pre-wrap; }
.ev-final { white-space:pre-wrap; border-left:3px solid var(--ok);
            background:rgba(63,185,109,.08); padding:6px 10px; }
.ev-tool { color:var(--tool); background:rgba(201,160,78,.08);
           border-left:3px solid var(--tool); padding:4px 8px;
           white-space:pre-wrap; word-break:break-all; }
.ev-result { color:var(--dim); font-size:12px; white-space:pre-wrap;
             border-left:3px solid var(--line); padding:2px 8px;
             max-height:120px; overflow-y:auto; }
.ev-img img { max-width:320px; border-radius:6px; border:1px solid var(--line);
              cursor:zoom-in; }
.ev-img img.zoom { max-width:100%; cursor:zoom-out; }
.dim { color:var(--dim); }
#empty { color:var(--dim); margin-top:40vh; text-align:center; }
.tab-btn { background:var(--panel); color:var(--fg); border:1px solid var(--line);
           border-radius:5px 5px 0 0; padding:5px 14px; font:inherit; cursor:pointer; }
.tab-btn.tab-sel { background:#233052; color:var(--accent); border-color:var(--accent); font-weight:bold; }
</style></head><body>
<div id="side">
  <div id="filters">
    <select id="f-task"><option value="">全部任务</option></select>
    <select id="f-flip">
      <option value="">全部结果</option>
      <option value="s2win">S2✓ S1✗ (工具赢)</option>
      <option value="s1win">S1✓ S2✗ (工具输)</option>
      <option value="bothok">双✓</option>
      <option value="bothbad">双✗</option>
      <option value="has21">有 S2.1 (90题子集)</option>
    </select>
    <input id="f-q" placeholder="搜索题目/id" size="16">
  </div>
  <div id="stats"></div>
  <div id="list"></div>
</div>
<div id="main"><div id="empty">加载中…</div></div>
<script>
let CASES = [], sel = null;
const $ = s => document.querySelector(s);

fetch('api/cases').then(r => r.json()).then(d => {
  CASES = d;
  const tasks = [...new Set(d.map(c => c.task))].sort();
  for (const t of tasks) {
    const o = document.createElement('option');
    o.value = o.textContent = t;
    $('#f-task').appendChild(o);
  }
  render();
  $('#empty') && ($('#empty').textContent = '← 从左侧选择 case');
});

['#f-task', '#f-flip'].forEach(s => $(s).addEventListener('change', render));
$('#f-q').addEventListener('input', render);

function filtered() {
  const t = $('#f-task').value, fl = $('#f-flip').value,
        q = $('#f-q').value.toLowerCase();
  return CASES.filter(c => {
    if (t && c.task !== t) return false;
    if (fl === 's2win' && !(c.s2.correct && !c.s1.correct)) return false;
    if (fl === 's1win' && !(c.s1.correct && !c.s2.correct)) return false;
    if (fl === 'bothok' && !(c.s1.correct && c.s2.correct)) return false;
    if (fl === 'bothbad' && (c.s1.correct || c.s2.correct)) return false;
    if (fl === 'has21' && !c.s21) return false;
    if (q && !(c.question.toLowerCase().includes(q) || String(c.id) === q)) return false;
    return true;
  });
}

function pct(a, b) { return b ? (a / b * 100).toFixed(1) + '%' : '-'; }
function esc(s) { return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;'); }

function render() {
  const rows = filtered();
  const s1c = rows.filter(c => c.s1.correct).length,
        s2c = rows.filter(c => c.s2.correct).length;
  $('#stats').textContent =
    `${rows.length} cases | S1 ${pct(s1c, rows.length)} | S2 ${pct(s2c, rows.length)}`;
  const list = $('#list');
  list.innerHTML = '';
  for (const c of rows) {
    const div = document.createElement('div');
    div.className = 'item' + (sel === c.id ? ' sel' : '');
    div.innerHTML =
      `<span class="badge b-task">${c.task}</span>` +
      `<span class="badge ${c.s1.correct ? 'b-ok' : 'b-bad'}">S1</span>` +
      `<span class="badge ${c.s2.correct ? 'b-ok' : 'b-bad'}">S2</span>` +
      (c.s21 ? `<span class="badge ${c.s21.correct ? 'b-ok' : 'b-bad'}">S2.1</span>` : '') +
      (c.s22 ? `<span class="badge ${c.s22.correct ? 'b-ok' : 'b-bad'}">S2.2</span>` : '') +
      (c.s23 ? `<span class="badge ${c.s23.correct ? 'b-ok' : 'b-bad'}">S2.3</span>` : '') +
      (c.s24 ? `<span class="badge ${c.s24.correct ? 'b-ok' : 'b-bad'}">S2.4b</span>` : '') +
      `<span class="dim">#${c.id}</span>` +
      `<div class="q">${esc(c.question)}</div>`;
    div.onclick = () => { sel = c.id; render(); show(c.id); };
    list.appendChild(div);
  }
}

function trajHtml(traj, title) {
  if (!traj || !traj.length) return '';
  let s = `<div class="card" style="margin-bottom:14px"><b>${title}</b> <span class="dim">(${
        traj.filter(e => e.t === 'tool').length} 次工具调用, ${
        traj.filter(e => e.t === 'img').length} 张图)</span>`;
  for (const ev of traj) {
    if (ev.t === 'text') {
      const cls = /FINAL[:：]/.test(ev.text) ? 'ev-final' : 'ev-text';
      s += `<div class="ev ${cls}">${esc(ev.text)}</div>`;
    } else if (ev.t === 'tool') {
      s += `<div class="ev ev-tool">▶ ${ev.name} ${esc(ev.args)}</div>`;
    } else if (ev.t === 'result') {
      s += `<div class="ev ev-result">${esc(ev.text)}</div>`;
    } else if (ev.t === 'img' && ev.src) {
      s += `<div class="ev ev-img"><img loading="lazy"
            src="api/img?src=${encodeURIComponent(ev.src)}"
            onclick="this.classList.toggle('zoom')"></div>`;
    }
  }
  return s + `</div>`;
}

async function show(id) {
  const c = await (await fetch('api/case_detail?id=' + id)).json();
  const m = $('#main');
  let h = `<h2><span class="badge b-task">${c.task}</span> #${c.id}
           <span class="dim">${c.dimension}</span></h2>`;
  h += `<div class="card" style="margin-bottom:14px">
        <div>${esc(c.question)}</div>
        <div class="dim">选项: ${c.options.join(' / ')} | GT: <b>${c.gt}</b></div></div>`;
  h += `<div class="row">`;
  h += `<div><video controls preload="metadata" src="api/video?id=${c.id}"></video></div>`;
  h += `<div class="card"><div class="pred-grid">
        <span>Stage 1 (纯问答)</span>
        <span class="${c.s1.correct ? 'b-ok' : 'b-bad'} badge">${c.s1.pred ?? '—'}</span>
        <span>Stage 2 (工具)</span>
        <span class="${c.s2.correct ? 'b-ok' : 'b-bad'} badge">${c.s2.pred ?? '—'}</span>
        ${c.s21 ? `<span>Stage 2.1 (多图工具)</span>
        <span class="${c.s21.correct ? 'b-ok' : 'b-bad'} badge">${c.s21.pred ?? '—'}</span>` : ''}
        ${c.s22 ? `<span>Stage 2.2 (index+证据帧)</span>
        <span class="${c.s22.correct ? 'b-ok' : 'b-bad'} badge">${c.s22.pred ?? '—'}</span>` : ''}
        ${c.s23 ? `<span>Stage 2.3 (read_crop)</span>
        <span class="${c.s23.correct ? 'b-ok' : 'b-bad'} badge">${c.s23.pred ?? '—'}</span>` : ''}
        ${c.s24 ? `<span>Stage 2.4b (semantic_crop)</span>
        <span class="${c.s24.correct ? 'b-ok' : 'b-bad'} badge">${c.s24.pred ?? '—'}</span>` : ''}
        <span class="dim">S2/S2.1 耗时</span><span class="dim">${c.s2.elapsed}s${c.s21 ? ' / '+c.s21.elapsed+'s' : ''}</span>
        </div></div>`;
  h += `</div>`;
  const trajs = [];
  if (c.traj24 && c.traj24.length) trajs.push(['S2.4b (semantic_crop)', c.traj24]);
  if (c.traj23 && c.traj23.length) trajs.push(['S2.3 (read_crop)', c.traj23]);
  if (c.traj22 && c.traj22.length) trajs.push(['S2.2 (index+证据帧)', c.traj22]);
  if (c.traj21 && c.traj21.length) trajs.push(['S2.1 (多图工具)', c.traj21]);
  if (c.traj && c.traj.length) trajs.push(['S2 (原生工具)', c.traj]);
  if (trajs.length) {
    window._trajs = trajs;
    h += `<div id="traj-tabs" style="margin-bottom:8px">` + trajs.map((t, i) =>
      `<button class="tab-btn" id="tab-${i}" onclick="showTraj(${i})">${t[0]}</button>`
    ).join(' ') + `</div><div id="traj-pane"></div>`;
  } else {
    h += `<div class="card"><b>Stage 2 原始回答(无轨迹)</b>
          <div class="ev-text dim">${esc(c.s2.raw)}</div></div>`;
  }
  m.innerHTML = h;
  m.scrollTop = 0;
  if (trajs.length) showTraj(0);
}

function showTraj(i) {
  const [title, traj] = window._trajs[i];
  document.querySelectorAll('.tab-btn').forEach((b, j) =>
    b.classList.toggle('tab-sel', j === i));
  document.getElementById('traj-pane').innerHTML = trajHtml(traj, title + ' 轨迹');
}
</script></body></html>"""


@app.route("/")
def index():
    return HTML


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7875)
    args = parser.parse_args()
    print(f"[INFO] {len(CASES)} cases loaded")
    print(f"[INFO] Starting on http://0.0.0.0:{args.port}")
    app.run(host="0.0.0.0", port=args.port)
