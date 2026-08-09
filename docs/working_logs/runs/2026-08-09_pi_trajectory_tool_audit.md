# pi 轨迹工具调用审计(vllm dev_fix run,S2.6)

日期:2026-08-09
数据:395 条精确匹配轨迹(case viewer v2,`web/case_viewer/data/cases.json`)
来源:pi session ~/.pi/agent/sessions/--tmp-pi_ws_* (8b vllm dev_fix run)

## 背景

case viewer 精确匹配上线后(两阶段:toolCall id 精确 395 + 模板级兜底 8),对
#814 轨迹做人工抽查发现 ffprobe 输出异常,遂对全部轨迹做工具调用审计。

## 发现 1:ffprobe 参数混用(3/770,0.4%)

agent 命令:
```
ffprobe -v error -show_streams -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 video.mp4
```
- `-show_streams`(输出流全部字段)与 `-show_entries`(限定字段)混用时,
  ffprobe 输出全字段 value dump(实测复现:40+ 行数字 + und/VideoHandler/SoundHandler),
  而非仅帧率
- 正确用法:去掉 `-show_streams`,仅 `-show_entries stream=r_frame_rate`
  → 输出 `30/1`、`0/0`(视频流 + 音频流帧率)
- 全部 770 次 ffprobe 调用中仅 3 次混用,711 次正确;偶发,非系统性问题
- 影响:40+ 行无 key 噪音,浪费 token、可能干扰推理
- 建议:prompt 工具说明中加规范——"ffprobe 取单字段用 `-show_entries <section>=<field>`,
  不要混用 `-show_streams`"

## 发现 2(重大):专用视频工具调用为 0

395 条轨迹中,evidence-closure 扩展工具全部 0 调用:
| 工具 | 调用次数 |
|------|---------|
| submit_answer | 0 |
| index_video | 0 |
| read_video_sequence | 0 |
| read_multiframe | 0 |
| read_crop | 0 |
| semantic_crop | 0 |

agent 仅用:`read` 2607 次、`bash` 2516 次(ffmpeg/ffprobe/python)、`write` 216 次、
`edit` 3 次。
→ **8b vllm dev_fix run 未加载/未使用 evidence_closure 扩展**。需核实:
run 命令的 `-e agent/pi_ext/evidence_closure.ts` 是否在 vllm 环境实际生效
(参考历史:前次 run 有 "vllm bare-JSON tool call swallowing" 修复)。
若 S2.6 标称的 evidence closure gate(62.2%)依赖 submit_answer 工具,
则该 run 的结果口径需重新确认。

## 发现 3:虚构工具名调用 66 次(2.5%)

agent 调用 pi 不存在的工具(事件 name 为空、args 为 {"path": ...}),pi 返回
`Tool not found`,agent 通常自行纠正("我误用了工具名。应使用 `read`")。
- 66/2673 ≈ 2.5% 的 read 类调用失败一次
- 模型工具名幻觉,可自纠;无工具侧缺陷

## 发现 4:bash 命令小错误(72 次含错误标记,均为探索性/环境差异)

- `ls/rm` 不存在的文件(多数):正常探索行为,agent 据此学习环境
- `bc: command not found`(1 次):agent 用 bc 做浮点运算,环境未装
- 抽帧脚本 `Failed to read frame 50`(1 次):python 脚本帧数越界,小瑕疵

## 结论

- 工具输出"异常"均来自 agent 命令/行为(ffprobe 混用、虚构工具名),工具本身
  如实返回;viewer 显示无失真
- 最值得跟进的是发现 2:扩展工具 0 调用,需确认 fix run 的扩展加载链路

## 建议

1. prompt 加 ffprobe 规范(见发现 1)
2. 核实 eval_pi_agentic.py 8b vllm run 的 EXTENSION 传递与 vllm 环境 tool schema 注册
3. run log 数字口径:本审计基于 395 精确轨迹
