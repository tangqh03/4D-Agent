---
status: active
scope: general
last_verified: 2026-08-01
owner: gaozhe
---

# Dataset Registry

Index of all datasets and data sources used in this project.

## Format

```markdown
### Dataset Name
**Path**: `/absolute/path/or/relative`
**Format**: Description of file structure
**Size**: Approximate (files/GB)
**Used by**: Which scripts consume this
**Notes**: Access restrictions, versioning, etc.
```

---

### ViSTR-Bench (public split)
**Path**: `data/benchmarks/ViSTR-Bench-Public/`
**Format**: `data.json`（670 条：id / dataset / dimension / task / **direct_prompting** / **manual_cot_prompting** / video 相对路径 / answer / options）+ `data/<Dimension>/<Task>/<Dataset>/*.mp4`
**Size**: 670 QA pairs、652 个原始 MP4、约2.63GiB；`.frame_cache` 不属于原始数据且可重建
**Used by**: agent 评测管线（规划中）、`visualize_results.py`
**Notes**: 来源 `homothetic/ViSTR-Bench-Public`，handover 固定 revision `d87a003751e618304ab03743658e8e2f96bb0ae5`；任务/维度名为下划线格式；public split Chance(Frequency)=**52.7%**；私有 held-out 禁止调参。详见 `docs/knowledge/vistr_bench.md`

### ViSTR SkillOpt ID pool and generated splits
**Path**: `configs/skillopt/vistr_public_ids.json`；运行时物化到 `<SkillOpt out_root>/_generated_splits/`
**Format**: 用户 ID 池为 JSON string array；生成目录含 `train/val/test/items.json` 和 `split_manifest.json`
**Size**: 默认选择全部 670 道 Public 题；`2:1:7`、seed 42 生成 134/67/469
**Used by**: `python -m agent.skillopt`
**Notes**: 使用 SkillOpt 原生 ratio splitter；manifest 绑定 ID 池、data.json、ratio、seed 与 SkillOpt commit；不包含 private held-out 数据

### SkillOpt ViSTR/DocVQA 100-item comparison
**Path**: `data/skillopt_comparison/seed43/`（由配置确定性生成，gitignored）
**Format**: `comparison_manifest.json`、`vistr_ids.json`、DocVQA `splits/{train,val,test}/items.csv` 和 `images/`
**Size**: 每个 benchmark 100题，均为20 train / 10 val / 70 test；当前 DocVQA 物化约71MB
**Used by**: `configs/skillopt/{vistr,docvqa}_comparison_100*.yaml`
**Notes**: seed43；ViSTR覆盖15/15 tasks且全部二选；DocVQA来自SkillOpt发布的534-ID validation池，100张图片互异且均有答案；DocVQA CSV 含目标机绝对图片路径，换机器必须重新物化

### DocVQA validation source for SkillOpt pilot
**Path**: `data/benchmarks/DocVQA/DocVQA/validation-*.parquet`
**Format**: Hugging Face parquet，6 shards、5,349条含 gold answers 的 validation records
**Size**: 约1.0GiB；train/test/InfographicVQA 不用于当前 pilot
**Used by**: `agent.skillopt.prepare_comparison`
**Notes**: `lmms-lab/DocVQA` revision `539088ef8a8ada01ac8e2e6d4e372586748a265e`；抽样候选由固定 SkillOpt checkout 的534-ID manifest定义

### ViSTR-Bench paper
**Path**: `references/ViSTR-Bench.pdf`
**Format**: 37 页 arXiv 论文（2607.20868）
**Used by**: 知识文档 `docs/knowledge/vistr_bench.md` 的来源
**Notes**: Appendix B 含全部 15 个 direct-prompting 模板与 Manual CoT 模板
