---
status: active
scope: evaluation
last_verified: 2026-08-06
owner: gaozhe
---

# Run Log — pi harness Stage 2 (原生工具) 全量 dev 评测

- **Date**: 2026-08-06
- **Script**: `agent/eval_pi_agentic.py --split dev --workers 4 --resume`
- **Harness**: pi v0.84.0,默认工具集(bash/read/edit/write/grep/find/ls),workspace = 临时目录 + video.mp4 拷贝
- **Model**: qwen3-vl-plus via AMAP gateway
- **前置修复**: 网关流式 tool-call arguments 为累积式(非 OpenAI 增量),pi 拼接后参数乱码 → 补丁 `scripts/patch_pi_cumulative_args.py`
- **Output**: `outputs/predictions/pi_agentic_qwen3-vl-plus_dev_20260806.jsonl`
- **Log**: `outputs/predictions/pi_agentic_dev_20260806.log`

## Result

**217/403 = 53.8%**,0 errors,1 parse-fail,95s/样本(4 并发,总耗时 2.7h)

Agent 行为(session 统计):平均 **14.7 轮 / 13.9 次工具调用 / 看 6.2 张帧**,
典型链路:ffprobe → ffmpeg 选择性抽帧 → read 逐帧查看 → 裁剪放大 → FINAL。

## vs Stage 1 (54.6%, 同模型纯问答)

| Task | S2 | S1 | diff |
|------|----|----|------|
| Basketball_Shot | 54% | 43% | **+11pp** |
| Swimming_Race | 50% | 41% | +9pp |
| Jenga_Stability | 46% | 37% | +9pp |
| Passage_Feasibility | 69% | 62% | +6pp |
| Golf/Interaction/Rotation/Soccer | — | — | 0pp |
| Ego_Motion | 60% | 62% | -2pp |
| Vehicle_Movement | 68% | 71% | -3pp |
| Mikado/Billiards | — | — | -4pp |
| Fall_Direction | 43% | 50% | -7pp |
| Knot_Type | 50% | 62% | -12pp |
| Relative_Velocity | 40% | 68% | **-28pp** |

## Key findings

1. **总体持平(-0.8pp)但结构互补性极强**:S2-only 对 69 题,S1-only 对 72 题,
   **union oracle = 71.7%**(vs 单版最高 54.6%)——两种模式各有擅长,融合空间大
2. **受益任务 = 需要看"关键瞬间"的**:Basketball(入筐帧)、Swimming(终点帧)、Jenga(掉落帧)
3. **受损任务 = 需要整体运动感知的**:Relative_Velocity -28pp 最典型——agent 逐帧看图
   难以判断速度,而 Stage 1 一次看 8 帧反而有"运动直觉"
4. **"Yes" bias 加重**:pred Yes 65% vs gt 56%(agent 看到证据后倾向"确认"假设)
5. 成本:95s/样本、每题 ~15 轮对话,token 消耗约为 Stage 1 的 10 倍

## Next candidates

- **混合路由**:速度/运动类任务走 Stage 1(多帧直贴),瞬间判定类走 Stage 2(工具抽帧)
- 或 Stage 2 prompt 强制先"多帧网格总览"再局部细看,补回运动感知
- 处理 Yes-bias:verify 阶段要求反证
