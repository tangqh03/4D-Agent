# Run Log: pi agentic 行为对比 — qwen3-vl-plus vs qwen3-vl-8b-thinking

- 日期: 2026-08-09
- 触发: 用户要求分析 HF 下载的 plus 轨迹与本地 8b-thinking 轨迹的行为差异;并追问"8b 是否只有工具调用没有思考"
- 工具: `scripts/analyze_pi_behavior.py`(新增,复用 build_case_viewer 辅助)
- 数据: plus = `outputs/hf_export/predictions_stage2.jsonl` + HF sessions(manifest 精确匹配 403/403);
  8b_fix = `pi_agentic_qwen3-vl-8b-thinking_vllm_dev_fix.jsonl`(toolCall-id 精确匹配 395/403);
  8b_s26 = `pi_s26_..._dev403_20260808.jsonl`(403/403)。三者同 dev403 题集。

## 核心结论:8b 的"思考"存在,但被链路隐藏

1. 8b session 含完整 thinking part(pi v3 格式,`{"type":"thinking","thinking":...}`)。
   全量扫描 `~/.pi/agent/sessions`: 1460 个 ws session,12478 个非空 thinking part,0 个空。
   例: id=4 dev_fix session 思考 16564+4292+1552+630 字符(英文"Okay, let's tackle this problem...").
2. 不可见的原因:
   - **前端**: `build_case_viewer.py::parse_session` 只保留 text/toolCall/image/toolResult,thinking 被丢弃;
     且 8b 的正文 text 几乎为空(均值 29 字符/case vs plus 2233),最后一条只是 "FINAL: Yes"。
   - **raw_answer**: eval 提取的是正文文本,不含 thinking。
   - pi provider 端(`pi-ai/dist/api/openai-completions.js`): 会识别流式 `reasoning_content`
     (reasoningFields = [reasoning_content, reasoning, reasoning_text]) 并累积进 thinking 块;
     无 enable_thinking 下发(thinkingFormat="openai",无对应分支),但 Qwen3-VL-Thinking 的
     chat_template 结构性强制 `<think>` 前缀,思考由 vLLM `reasoning_parser: "qwen3"` 提取——
     所以思考产生且被 pi 记录,只是下游展示丢弃。

## 行为差异(同工具集对比 plus vs 8b_fix;8b_s26 为当前 S2.6 管线,工具集不同,仅供参照)

| 指标 | plus | 8b_fix | 8b_s26 |
|---|---|---|---|
| accuracy | 53.8% | 51.4% | 52.9% |
| 工具调用/case (均值) | 13.4 | 9.1 | 8.2 |
| 工具构成 | bash 2516 / read 2607 / write 216 / edit 3 | bash 2794 / read 620 / write 151 / edit 26 | bash 796 + index_video 451 / read_video_sequence 510 / semantic_crop 562 / read_crop 322 / submit_answer 490 |
| 看图(case 内 image part) | 均值 6.1 | 均值 1.2,中位 1 | 均值 9.8 |
| thinking 字符/case | 0(非思考模型) | 均值 42,302 | 均值 37,565 |
| text 字符/case | 均值 2,233 | 均值 29 | 均值 23 |
| assistant 轮次 | 14.3 | 9.4 | 9.0 |
| elapsed s (p50/p90) | 85/139 | 121/282 | 156/263 |

要点:
1. **思考-正文分工**: plus 推理全在正文(2233 字符,中英混杂、逐步讲解);8b 推理全在 thinking
   (约 4.2 万字符/case,即每次工具调用前 ~4,500 字符英文思考),正文近乎静默。
2. **观察量差异**: plus 平均看 6.1 帧、多帧时序观察(抽 60-90 帧、末 20 帧、区域裁剪逐步推进);
   8b_fix 平均只看 1.2 帧(中位 1)——抽帧后通常只读 1 张就下结论。8b_s26 靠结构化视频工具
   把观察拉到 9.8 帧。这是 8b_fix 51.4% < plus 53.8% 的最直观行为差。
3. **工具风格**: plus read(2607)>bash(2516),读操作多;8b_fix bash(2794)>>read(620),抽帧用
   bash/ffmpeg、看帧用 read。同为原生工具集,但使用比例相反。
4. **耗时**: 8b 比 plus 慢(中位 121s vs 85s),慢在思考生成(42K 字符/token 消耗),非轮次多。
5. **任务级互补**(详情见表): 8b_fix 强于 Billiards_Shot 52 vs 39、Fall_Direction 57 vs 43、
   Swimming_Race 59 vs 50;plus 强于 Interaction_Direction 76 vs 59、Vehicle_Movement 68 vs 59、
   Basketball_Shot 54 vs 41、Golf_Shot 62 vs 50。
6. **分歧矩阵** plus vs 8b_fix(403): both✓ 134,plus-only 83,fix-only 73,both✗ 113;
   union oracle 290/403 = **72.0%**——两模型错误模式几乎不相交(分歧 156 > 共同正确 134),
   与 HF README 的 plus S1∪S2=71.7% 同一量级。8b_s26 注意点:Passage_Feasibility 25%(plus 69%)。
7. 定性案例 id=32(plus✓ 8b✗): plus 多帧+区域裁剪+修正运动检测误报后判 No;8b 21847 字思考后
   只抽 1 帧(frame_30)即判。id=4 两模型都错(Yes vs 真实 No),同为单帧或局部观察。

## 附注

- 8b_fix 未匹配的 8 行为 src=error(无 tool_trace)行;统计仅用精确匹配 case。
- **思考渲染已实施(同日)**: `build_case_viewer.py::parse_session` 新增 `{"t":"think",
  "text":前1000字符,"chars":全长}` 事件(MAX_THINK=1000);`pi_case_viewer.py` 与
  `web/case_viewer/index.html` 渲染为斜体蓝色块 + "💭 思考 (N 字符)" 标签,统计行加"段思考"。
  两个 viewer(7875/7877)已重启并验证: id=4 返回 4 段思考(首段 16564 字符),事件序
  think→tool×4→result。数据包重建后当前为 8b 版;切回 plus 版: 跑
  `scripts/build_case_viewer_hf.py` 后重启 viewer。
- Smoke test: `scripts/analyze_pi_behavior.py` 正常运行输出上表(退出码 0)。
