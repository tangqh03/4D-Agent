# Handoff — vLLM 本地部署切换 GPU 0–3、max_model_len 64k（已执行）

- Date: 2026-08-09
- Status: **已部署并通过定向 smoke**；后续执行以
  `2026-08-09_s26_bugfix_64k_dev403_claude.md` 为准
- Config: `configs/vllm_qwen3_vl_8b_thinking_gpu0-3_64k.json`
- Machine: 8× RTX 4090 24GB（GPU 0–7），本机即 gpu01

## 背景与动机

S2.6 全量 dev403（2 卡 TP=2，`max_model_len=40960`）暴露 **31.5%（127/403）无答案**。
根因已确认（tqh.md §4）：pi 每轮固定请求 `max_tokens=32768`（`~/.pi/agent/models.json`
的 maxTokens，2026-08-07 修复 B 时按要求设 32k），而 `40960 − 32768 = 8192` 输入预算
过小 —— 任何请求输入 ≥8193 token 即被 vLLM 400 硬拒（127/127 无答案会话同款报错）。

**本次目标**：换 GPU 0–3（TP=4）、`max_model_len=65536`（64k）：

```
输入预算 = 65536 − 32768 = 32768 token
```

- 修复无答案 bug：pi 压缩后的会话输入 ~4–10K token，远低于 32768，off-by-one 死法根治；
- 兼容现有 maxTokens=32768 配置（无需改 `~/.pi/agent/models.json`）；
- 并发 `max_num_seqs` 2 → 16，评测吞吐 8 倍（403 题全量可大幅提速）；
- TP=4 每卡权重/单 token KV 减半，2 卡时的显存压力同步下降。

## 配置要点

| 参数 | 值 | 说明 |
|---|---|---|
| `cuda_visible_devices` | `"0,1,2,3"` | 物理 GPU 0–3（全空闲，见下） |
| `tensor_parallel_size` | 4 | 与 4 卡一致 |
| `max_model_len` | **65536** | 64k = 64×1024（8 卡 recovery 配置 131072 同规则） |
| `max_num_seqs` | 16 | 与旧 4 卡 baseline 配置一致（显存核算见下） |
| `mm_processor_cache_gb` | 50 | 与旧 4 卡/8 卡配置一致（多模态特征缓存，软上限共享空闲池） |
| `gpu_memory_utilization` | 0.9 | 24GB × 0.9 ≈ 21.6 GiB/卡 |
| `enable_auto_tool_choice` + `tool_call_parser: hermes` | 开 | Bug C 修复项（s26 起必须，pi 工具调用） |
| `reasoning_parser: qwen3` | 开 | thinking 模型思考/正文解析 |
| port | 8001 | 当前空闲（见下） |

其余（model 路径、TRITON_ATTN、prefix caching、mm_encoder_tp_mode=data、
async_scheduling、distributed_executor_backend=mp、client 块）沿用仓库历史配置。

## 显存核算（max_num_seqs=16 可行）

基于本机 vLLM 日志的实测 KV 单位成本（自洽校验）：
- TP=8 日志：可用 KV 12.75 GiB/卡，分配 725,504 tokens/卡 → **18.4 KB/token/卡** → 总 ~147 KB/token；
- TP=2 s26 日志：9.51 GiB / 138,560 tokens ≈ 73.6 KB/token/卡 = 147/2 ✓；
- 故 **TP=4：~36.8 KB/token/卡**。

TP=4 每卡账本（24GB × 0.9 = 21.6 GiB）：
- 权重：checkpoint 16.33 GiB / 4 ≈ 4.1 GiB + mm encoder（data 模式每卡重复 ~1.3 GiB）≈ **5.4 GiB**；
- KV：`65536 × 16 / 4 = 262,144 tokens/卡 × 36.8 KB ≈ 9.6 GiB`；
- CUDA graphs ≈ 0.1 GiB；
- 合计 ≈ **15.1 GiB ≤ 21.6 GiB**，余量 ~6.5 GiB（mm processor cache 软共享）。

→ `max_num_seqs=16` 安全；若启动 OOM，按序降：`max_num_seqs` → `mm_processor_cache_gb` → `gpu_memory_utilization`(0.9→0.85)，每次只改一个并记录。

## 与历史配置对比

| 配置 | 卡数 (TP) | max_model_len | max_num_seqs | 状态 |
|---|---|---|---|---|
| `vllm_qwen3_vl_8b_thinking.json` | 4 (4,5,6,7) | 61440 | 16 | 旧 baseline 配置（不覆盖） |
| `vllm_qwen3_vl_8b_thinking_gpu01_s26.json` | 2 (0,1) | 40960 | 2 | s26 已停，保留复现 |
| **`vllm_qwen3_vl_8b_thinking_gpu0-3_64k.json`** | **4 (0,1,2,3)** | **65536** | **16** | **本次新增，未部署** |
| `vllm_qwen3_vl_8b_thinking_recovery_8gpu.json` | 8 (0–7) | 131072 | 8 | 保留（原生上下文） |

## 当前机器状态（2026-08-09 核验）

- GPU 0–7 全部空闲（15 MiB 基线）；vLLM/perception 均未运行（s26 服务已优雅停止）；
- 端口 8001/7876 已释放；仅 7875/7877 的 pi_case_viewer 在运行（勿动）；
- 无端口/GPU 冲突，部署前不需要杀任何进程。

## 部署步骤（计划，待用户命令执行）

1. 冒烟（已做）：`/opt/conda/bin/python scripts/launch_vllm_qwen3_vl_8b_thinking.py --config configs/vllm_qwen3_vl_8b_thinking_gpu0-3_64k.json --dry-run --python /opt/conda/envs/311/bin/python` → 命令生成正确 ✓
2. 启动：`tmux new-session -d -s vllm-64k "…launch_vllm_qwen3_vl_8b_thinking.py --config configs/vllm_qwen3_vl_8b_thinking_gpu0-3_64k.json --python /opt/conda/envs/311/bin/python > /tmp/vllm_gpu0-3_64k.log 2>&1"`
3. 健康检查：`tail -f /tmp/vllm_gpu0-3_64k.log` 等 `Started server process`；`nvidia-smi` 确认仅 GPU 0–3 有占用；
4. 单样本冒烟（需 perception :7876 配合则先起 perception，GPU 6）：
   `/opt/conda/bin/python -u agent/eval_pi_agentic.py --split dev --ids 1 --workers 1 --timeout 900 --output outputs/predictions/pi_s26_64k_smoke.jsonl`
5. 无答案率回归：建议全量 dev403 复跑（输出新文件，不覆盖 s26），对比无答案占比（s26: 31.5% → 预期接近 0）与 acc。

## 回滚

- 停服：tmux 内 Ctrl-C 优雅停止，确认 GPU 0–3 回落 15 MiB；
- 复现 s26：用 `configs/vllm_qwen3_vl_8b_thinking_gpu01_s26.json`（保留，未改动）。

## 注意事项

- 不盲杀进程：当前无 vLLM/perception 进程，部署前如有发现占用 GPU 0–3 或 8001 的非本项目进程，先报告再定；
- `~/.pi/agent/models.json` 的 maxTokens=32768 不动（65536 窗口下预算 32768，兼容）；
- perception 服务（GPU 6，:7876，`GDINO_PATH` 指向本地 HF 缓存）若需复跑评测需一并启动；
- 如需 64000（十进制）而非 65536，只改配置里 `max_model_len` 一处，其余推导不受影响。
