---
status: raw
created: 2026-08-09
author: tqh
---

# 调试笔记:s26 agent 抽帧类 bug 汇总(待续)

> 草稿,先记录,等找完问题后统一整理修改。
> 本文件只保留 **s26 运行**(S2.6 结构化工具,2026-08-08,7875 viewer 当前展示)的 bug。
> (dev_fix 运行的发现已移出,留存于 fork 审计 `docs/working_logs/runs/2026-08-09_pi_trajectory_tool_audit.md`。)

> 2026-08-09 修复状态：null subcall、64k 上下文、accepted submit 恢复、
> `read_crop` 0-1 契约和失败 timeline 误入 ledger 已修并通过原失败题 smoke。
> closure 的 claim→answer 蕴含、对象一致性和时空覆盖仍是独立待实验问题。

## 1. s26 工具崩溃:index_video/semantic_crop 内部 VLM subcall 空 content 崩溃

### 现象

- 全量 session: `index_video null.trim` **241 次**、`semantic_crop null.match` **414 次**,共 **655 次** null 崩溃。
- s26 dev403 运行: 403 case 中 **333 个(83%)** 含 ≥1 次工具崩溃(合计 622 次),单次 142 / 多次 191(最多 6 次)。
- 崩溃 case acc 52.3% vs 无崩溃 case 55.7%——直接准确率损失不大(agent 会绕路),但观察被盲化(没有时间线 → 猜时间窗),如 #817。

### 根因(vistr_video_tools.ts)

两个崩溃是同一根因: **gateway VLM subcall 返回 `message.content: null`,代码未加空值保护**:

| 崩溃 | 位置 | subcall | 原因 |
|---|---|---|---|
| `null.trim` | L120 `captionTimeline()` | index_video 的 caption 生成(max_tokens=1000) | thinking 模型输出只有思考块(无正文)时 content=null |
| `null.match` | L167 `selectCandidate()` | semantic_crop 的候选框选择(max_tokens=**8**) | max_tokens=8 对 thinking 模型结构性饿死:qwen3 模板强制 `<think>\n` 开头,8 token 连思考块都出不完 → content=null |

- s26 运行配置 `VISTR_CAPTION_PROVIDER=vllm-local VISTR_CAPTION_MODEL=qwen3-vl-8b-thinking`(handoff 明示),subcall 用的就是 thinking 模型。
- semantic_crop 只有候选框 ≥2 才走 selectCandidate(candidates=1 直接裁剪,0 走优雅路径)——所以崩溃即"grounding 找到框了但 VLM 选择崩了";全 run `No region found` 优雅路径 0 次。

### 修复(已实现 2026-08-09;**不采用 thinking 当 content**)

判定:thinking 是 deliberation 不是 committed 输出——selectCandidate 解析取
"第一个数字",而思考里出现的数字常是被否掉的候选(会取错);captionTimeline
的 `t=...` 格式契约思考文本不满足;且 max_tokens=8 下模型根本没机会生成数字,
塞思考只是拿到截断残片。正确方向是让 subcall 得到与主 agent 相同的待遇
(思考进 thinking 槽、正文进 content),而非反向混用。

落地(vistr_video_tools.ts,配套测试 93/93 过):

1. 新增 `parseChatReply()`:统一解析 subcall 回复——`content` 进正文、
   `reasoning_content/reasoning/reasoning_text` 进 thinking 槽(与 pi-ai 的
   reasoningFields 对齐);content=null 不再崩,返回 `{ok:false, error, reasoning}`。
2. `selectCandidate` max_tokens 8 → **128**(thinking 模型结构性饿死修复)。
3. 数字解析改严格:纯数字行优先 → 正文中最后一个出现的候选 id → 兜底首候选;
   **只解析 content,从不解析 thinking**。
4. 工具结果里把 subcall 思考以带标签文本块呈现(`[caption subcall thinking]` /
   `[selection subcall thinking]`,>600 字符截断),正文与思考互不污染;
   失败时给可操作错误(如 "Retry semantic_crop with a more specific target description"),
   不再出现 "Cannot read properties of null"。
5. `captionTimeline` max_tokens 1000 → 1500(留出 `<think>` 前导预算)。
6. 放弃方向:subcall 切非 thinking 模型——牺牲全本地评测(handoff 明示 s26
   显式设 vllm-local 是为了全本地 qwen3)。

## 2. case #114:初始判断正确(蓝快)被 read_crop 幻觉带偏,closure 二次放行错误答案 [s26 运行]

Relative_Velocity,gt=Blue。S1(基线)答对 Blue;S2(pi+closure)答错 Green。
轨迹 59 步,证据链:

### 关键节点

| 步 | 动作 | 内容 |
|---|---|---|
| [10] | index_video | **崩溃** `Cannot read properties of null (reading 'trim')`(subcall 空 content,§1 已修)→ 无时间线 |
| [14] | read_video_sequence | 4 全帧 t=0/1.21/2.43/3.64 |
| [24] | 思考 | **初始判读正确**:"gap 增大 → 蓝车更快 → 答案应 Blue"(反复得出) |
| [26-38] | read_crop ×3 | **同一固定 bbox** [250,300,350,400] @ t=1.21/2.43/3.64(盲猜区域,无时间线可依) |
| [34] | 思考 | 从 3 张 crop "看到" 绿车在后→并行→在前,断言绿车超车 → **答案翻转为 Green** |
| [41] | submit Green | **closure 正确拒绝**:"key claim lacks direct visual confirmation" |
| [45] | read_multiframe | 重看**相同帧相同时间**(1.21/2.43/3.64,与 [14] 内容重复,零新信息) |
| [55] | submit Green | 改写措辞("overtakes, moving from behind to ahead")→ **checker 接受** → FINAL: Green 错 |

### 根因

1. **index_video 崩溃(§1)**:无语义时间线 → agent 盲猜观测时间与 bbox。
2. **read_crop 固定 bbox 误用 + 幻觉**:像素分析确认——3 张 crop 里
   **0 个绿框/蓝框像素**(框随车移动,不可能出现在固定区域),但 crop 间
   mean abs diff 35-52(区域里有**别的车**经过)。agent 从与两目标无关的
   过车区域"看"出了"绿超蓝"的相对运动叙事,纯属幻觉。
   全帧量化:绿框 x 质心 114→72→66→43(位移 71px),蓝框 185→179→157→142
   (43px)——即便像素上绿更快,也有透视失真;crop 证据根本不支持任何结论。
3. **closure 盲点(§1 已知的扩展)**:第一次拒绝是对的;但 agent 用"重看相同帧 +
   改写措辞"通过了第二次——checker 只校验"时间上有没有观察",不校验
   **观察内容是否真的支持声明**(空间覆盖/是否包含所声称的物体)。#114 的观察
   里两个框选车辆从未同时出现,checker 照样放行。
4. 正确窗口:初始判读(Blue)在 read_crop 之前;closure 从没见过 Blue 提交——
   "调用 closure 后反而错"实为"closure 未挽回 read_crop 造成的翻转,且第二次放行了它"。

### 处理(分阶段,第一阶段已实现 2026-08-09)

- 已在 `read_crop` 描述中明确固定 bbox 不是 tracker，移动目标必须逐时刻重定位；
  原 #114 smoke 仅作行为观察，不以准确率为门禁。
- checker 的空间/内容覆盖、claim→answer 蕴含和强制新观察会改变实验定义，暂缓为
  独立实验，不混入本批 bug fix。

## 3. read_crop 系统性"裁不相关区域":盲猜坐标无反馈闭环 [s26 全量扫描]

### 量化(403 轨迹,框选类视频 165 case)

- read_crop 共 159 次,其中 **82 次(53%)crop 不含任何框选目标**(框色像素检测
  全 0);**143 次(90%)发生在 index_video 崩溃之后**——无时间线 → 时间空间双盲猜。
- 91 case 用过 read_crop:17 case **只用 read_crop 从不用 semantic_crop**;
  74 case 也用过 semantic_crop。
- **7 case 固定 bbox 跨时间复用**(共 20 次):#114 ×3、#332 ×3、#908 全帧 ×2、
  #405/#712 等 ×2——固定区域测"相对运动",测到的是路过车辆的错置归因。

### 根因链(#114 为标本)

1. **index_video 崩溃(§1)是主前因**:90% 的 read_crop 是崩溃后的盲猜。
   #114 的 bbox [250,300,350,400] 在思考里 **0 次被提及**(凭空出现),像素上
   距目标车 ~70-100px(640 尺度)落空,区域里只有别的车经过。
2. **坐标驱动无反馈闭环**:read_crop 输入 0-1000 归一化坐标、输出小图,工具不返回
   "此区域含目标/为空"任何信号;agent 拿 640 宽帧记忆换算坐标,
   尺度+位置误差叠加。落空时无信号 → 照单全收(→ #114 幻觉超车叙事)。
   契约误用还有硬错误路径:#863 传 **0-1 坐标**([0.5,0.4,0.7,0.6])→ 映射
   (0,0,0,0) → `bbox too small or inverted after mapping` 错误——发生在
   gate 拒绝后的重观察节骨眼,直接掐断第二次提交(见 §4 Ego_Motion 组)。
3. **semantic_crop(按文本目标、免坐标)存在但被绕过**:17 case 完全没用;
   #114 思考 [43] 里计划"用 semantic_crop 拿精确位置"却没执行,改用了
   重看相同帧的 read_multiframe。
4. **固定 bbox 时序误用**:固定区域不能跟踪移动目标,被当作"时间对比"工具用。

### 处理(分阶段,第一阶段已实现 2026-08-09)

- `read_crop` 检测四个坐标均在 0-1 时返回定向错误，明确要求 0-1000、乘以
  1000 或改用 `semantic_crop`；不自动换算以免隐藏误用。
- 工具描述明确固定区域不能跟踪移动目标。crop 内容有效性检测和目标跟踪反馈暂缓。

## 4. 无答案 case 127/403(31.5%):会话中途终止,从未产出 FINAL [s26 运行]

### 现象(#118 为标本,非 viewer 渲染问题)

- #118(Relative_Velocity):viewer 显示 s2.raw 为空、轨迹停在 `ls -l video.mp4` 后——
  与源数据一致:**JSONL 里 final_answer='' / raw_answer=''**。不是渲染问题。
- #118 耗时 74.9s(远超 900s 上限之下结束),3 个工具全是 ffprobe 语法纠错
  (`,`→`;` 都错)+ 18K 字符思考,至截断仍在探索("call ls video.mp4"),从未接近提交。
- viewer 里 pred="Green" 来自 eval 的**思考兜底**(最后提到的选项;思考里
  Green 15 次 vs Blue 7 次),不是 agent 提交的答案。

### 系统性扫描(403 case)

- **127 case(31.5%)无 final_answer**;有答案的 276 case acc 55.4%,无答案 case 靠
  思考兜底猜对 60/127(≈随机),总体 52.9%——无答案把 acc 拖低 ~2.5pp。
- 127 个里 **59 个调用过 submit_answer**(含 7 个 checker 已 CLOSURE: YES,但
  会话在写 FINAL 前终止),68 个从未到达 gate。
- 耗时分布:median 147s,散布 30-645s(非单一超时事件);工具数 1-18 都有;
  **tool_errors 全部 = 0**、无 error 字段——pi 进程退出码为 0,会话在循环中途安静终止。

### 根因(已确认 2026-08-09,本地 session 文件铁证,无需 gpu01 日志)

**127/127 无答案会话的尾部都是同一个 vLLM 400**(逐一核对,一例不差):

```
400: This model's maximum context length is 40960 tokens. However, you requested
32768 output tokens and your prompt contains at least 8193 input tokens, for a
total of at least 40961 tokens. (parameter=input_tokens, value=8193)
```

- 机制链:vLLM `max_model_len=40960`(`configs/vllm_qwen3_vl_8b_thinking_gpu01_s26.json`),
  而 **pi 每轮固定请求 `max_tokens=32768` 输出** → 输入预算只剩
  `40960-32768 = 8192 token`。任何请求输入 ≥8193 → vLLM 硬拒 400,pi 压缩重试
  仍 ≥8193 → 放弃(exit 0、无 tool error——400 是 pi 层 provider 错误,不是工具错误,
  与 tool_errors=0 吻合)。
- **session 文件里 400 的记录格式**:一条 `role=assistant、content:[], 
  stopReason:"error"` 的空消息(usage 全 0,**报错文本不在 session 里**,只在 vLLM 侧)
  ——所以会话"安静终止"只是审计方法问题:数 `stopReason=error` 空消息即可,
  不依赖 gpu01 日志。注意解析器若只按 content 过滤会把这些事件漏掉
  (本文件 4 例 Ego_Motion 组初查即漏,见下)。
- 为什么 thinking 模型特别容易触发:每轮思考 8-25K 字符(≈2-6K token),
  几轮就把 8192 输入预算顶穿。**#118 74.9s 即死于 message 8**:上一轮 input=7968,
  该轮思考 ~1800 token + toolResult 后 → 8193 → 400。不是"跑得少",是**思考太话痨**。
- elapsed 散布 30-645s 的成因:pi 的 compaction 会保命——把旧历史压成摘要、
  输入钉在恰好 8192(8192+32768=40960 恰好卡线),所以 #332 能撑 645s 到第二次提交;
  最后"Answer accepted" toolResult 追加 ~15 token → 8193 → 400 → 再压缩重试仍
  ≥8193(摘要+"No prior history" 也压不进 8192)→ 放弃。**这就是"7 个 CLOSURE:YES
  却无 FINAL"的成因**。
- 不是超时:全 run 最长 elapsed 657s < 900s,--timeout 从未触发。
- 另有 **10 个有答案**的会话尾部也以同款 400 结束(在 8192 线内写完答案,
  线外那轮才死)——说明 400 不是判断失败,是"写完之后的收尾请求被拒"。
- **快速死亡变体(纯思考自然顶穿,无压缩)**:#81/#96/#330/#832 全程 **0 次
  compaction**——大思考块(15-24K 字符,实际 ≈3 字符/token,我此前按 4:1 低估)
  2-4 轮内把输入自然顶到 8193+,pi 来不及压缩即 400。图像不是必要条件
  (这 4 例无图像;#1086/#1134 的图像 ~7.2K token 是放大器之一)。
- **#229 全绿标本(compaction 卡线型)**:6/6 工具全成功、无 §1 崩溃、
  **closure CONFIRMED 正确答案**(Ego_Motion gt=Back-right,提交 Back-right),
  仍死于 FINAL 写出一轮的 400——"7 个 CLOSURE:YES 却无 FINAL"族群的最完整
  标本:证明 400 死法**独立于工具健康**,纯 token 预算问题。序列:压缩 1 次
  (tokensBefore=14198)→ submit 请求成功(压后输入 ≤8192 恰卡线)→ accepted
  toolResult 追加 ~15 token → 8193 → 400 → 重试仍 400 → 放弃(324s)。
- 未到 gate 的快速死 4 例(#81/#96/#330/#832,63-83s)均 Vehicle_Movement、
  gt=Yes、pred=No(思考兜底错),其中 3 例卡在 ffprobe 语法纠错(见下),
  1 例(#330)是 §1 index_video 崩溃后盲走 ls 即撞线。
- **ffprobe 语法纠错 churn = 反复出现的预算烧毁器**(4 个标本:#118/#81/#96/#832):
  agent 在 bash 里写 `-of default=noprint_wrappers=1:pretty` 时用**逗号**分隔
  选项(`1,pretty` / `1,print_options=0`)→ ffprobe 按选项列表解析报
  "Unable to parse ... as boolean" → agent 改写成变体重试,每轮重试烧一轮
  5-18K 字符思考,3-4 轮即可顶穿 8192。根因:bash 工具文档无 ffprobe 语法示例,
  且**视频工具自带时长信息**(index_video/read_video_sequence 输出即含
  "duration 4.57s" 之类),ffprobe 前奏是纯浪费——agent 却在调观察工具前
  先查时长/帧率,把宝贵预算烧在自查上。

### 处理(已实现并完成定向 smoke 2026-08-09)

- vLLM 切到 GPU 0-3 TP=4、`max_model_len=65536`；pi 客户端
  `contextWindow=65536`、`maxTokens=32768`、`compaction.reserveTokens=32768`。
- eval 保存 `tool_result.details`、assistant `stopReason/errorMessage`；S2.6 无合法
  FINAL 时只取最后一次 `accepted=true` 的 `submit_answer`，否则 `pred=null`，
  不再从 reasoning 猜答案。非 S2.6 保留原 fallback。
- 原失败题 #114/#118/#229/#332/#863/#866/#909 smoke：7/7 完成，62/62 工具
  执行、0 tool error、0 provider error、0 null 崩溃、0 context 400。

### #332 标本:两次正确提交被"最后一步终止 + 兜底误提取"吞掉

- Relative_Velocity,gt=Blue。agent 两次 submit **都是 Blue(正确)**:
  第一次被 gate 拒(拒绝合理——crop 都是不相关区域,见 §3,声明无直接观察支撑),
  耗时重观察(semantic_crop 成功 + 固定 bbox crop 复用)后第二次 **ACCEPTED**
  ("Answer accepted... FINAL: Blue")。
- **但会话在 agent 写 FINAL 前终止**(645s,同 §4 无答案模式):final_answer='',
  viewer 显示 pred=Green、raw 空——"错误答案"其实是 **eval 思考兜底误提取**。
- 终止点(已确认,见上):"Answer accepted... FINAL: Blue" toolResult 之后的下一次
  生成请求即被 400 拒——compaction 后输入钉在 8192 恰好卡线(8192+32768=40960),
  toolResult 追加 ~15 token → 8193 → 40961 > 40960,差一个 token 越界。
- 误提取细节:eval 取"思考中最后出现的选项",而 #332 思考结尾是
  "...submit answer \"Blue\" with the key claim being the decreasing distance
  between **blue and green** over 0.5s"——"green"(pos 197087)排在
  "Blue"(pos 197015)**后面**,于是 pred=Green。agent 承诺的 Blue 被关系性短语
  里的 green 顶掉。验证:`extract_answer` 在该 reasoning 上复现返回 Green。
- 两个报错 [7] `null.trim`(index_video)、[40] `null.match`(semantic_crop)均在场——
  即 §1 已修 bug 的完整标本。
- 教训:无答案 case 的兜底是"最后提到的选项",对关系型表述("A 与 B 之间距离")
  会系统性偏向后说的那个;兜底猜对率 ≈50% 不是巧合,而是结构性问题。

### Ego_Motion 组 4 例(#863/#866/#901/#909,2026-08-09 补):静态物体任务,全死于同一 400

| id | 工具 | §1 崩溃 | 压缩 | submit | 结局 |
|---|---|---|---|---|---|
| #863 | 6 | 0(全绿) | 1 | Front-right 被拒(合理) | 400→压缩→400 死 217s |
| #866 | 5 | 1(semantic_crop) | 0 | 从未 | 400 死 138s |
| #901 | 4 | 0(全绿) | 1 | Back-right **被放行(错)** | 400→压缩→400 死 174s |
| #909 | 11 | 2(index+semantic) | 0 | 从未 | 400 死 144s |

- **#863(正确答案被合理拒绝后,重观察工具出错,无第二次提交)**:ffprobe ✓ →
  index_video ✓ → sequence ✓ → semantic_crop ✓(全无 §1 崩溃)→ submit
  **Front-right(=gt,正确)**,claim 是"洗衣机在 sink 右侧"——gate 拒:
  claim 涉及**两个物体**而观察里只有洗衣机(且 crop 时间是 4.41s 中段,
  对"最终位置"问题证据不足,拒绝本身合理)→ 重观察 read_crop 用 **0-1
  坐标**(工具契约是 0-1000)→ 映射 (0,0,0,0) → `bbox too small or inverted
  after mapping` 错误(新错误路径,见 §3)→ 无第二次 submit → 400 → 压缩
  (summary 1379 字符)重试仍 400 → 死。pred=Back-left 思考兜底,错。
- **#866(§1 崩溃 + 大思考块自然顶穿)**:ffprobe **同命令重复 ×2** → index ✓ →
  sequence ✓(4 帧图)→ semantic_crop **null.match 崩(§1)** → 下一轮 400 死,
  0 压缩。24K 字符思考块是压垮预算的主因。从未 submit。pred=Back-left,错。
- **#901(门禁盲点 #3:首次提交即放行错误答案)**:工具全绿(ffprobe ✓ sequence ✓
  semantic_crop ✓,但 grounding 短语被截成残片 "the bookshelf side the the",
  score 0.637,84×213px 小 crop)→ submit Back-right **首次即 ACCEPTED**
  ("Evidence closure confirmed"),而 gt=Front-left——claim"书柜在画面右侧
  (9.21s 直接可见)+ 相机向其移动"每句都真,但结论 Back-right 不成立
  (右侧 + 相机向前 → 应 Front-right)。**checker 校验"观察是否支撑 claim",
  不校验"claim 是否推出答案"** → 放行错误答案(对照 #114 需改写才过、#817
  改写措辞即过——本例子首次提交即过,更宽)→ 随后 400 → 压缩(1991 字符)
  重试仍 400 → 死。pred=Back-right 兜底恰好等于被放行的错误答案。
- **#909(§1 崩溃 + 无反馈重试烧预算)**:单轮 **5 连发**工具调用(THINK 3.3K +
  ffprobe ×2 重复 + index_video **null.trim 崩** + sequence ✓ + semantic_crop
  **null.match 崩**)→ semantic_crop 换措辞重试 ×4("the tv"→"the tv on the
  wall"→"the tv on the left wall")**全崩**——崩溃是确定性的,重试无意义
  (§1 修复后这 4 次会成功);read_crop ×2 盲猜 [300,200,400,300]/[500,100,600,200]
  → 64×48px 600 字节空小图当证据(§3 无反馈闭环)→ 400 死,0 压缩。从未 submit。
  pred=Front-left,错。
- **共性**:① 4 例尾巴全是同款 400 空消息;#863/#901 压缩 1 次(重试仍 400,
  #229 同款"摘要也压不进 8192"分支),#866/#909 0 压缩自然顶穿。
  ② 与 Vehicle_Movement 组对比:ffprobe 语法这次**全对**(冒号分隔,无 churn),
  但仍是 4 例全有的前奏(2 例还重复调用);§1 崩溃只 2/4 例;
  **全绿也死 2/4 例(#863/#901)**——再证 400 独立于工具健康。
  ③ 4 例 committed 判断全被吞:#863 submit 正确却被拒(拒绝合理,重观察
  又死在坐标错误上);#901 被放行但本身错;pred 全来自思考兜底,3 错 1 对
  (与 #332"正确 commit 被吞"同族)。

### 处理(已实现并完成定向 smoke 2026-08-09)

- 新 4 卡 64k 服务已部署并保留给 Claude Code 全量复跑；eval 新增
  `answer_source/no_answer/termination`。
- #332 历史形态有确定性测试：accepted Blue + reasoning 末尾 Green → 必须取 Blue；
  本次在线 #332 随机改为 accepted Green 且正常 FINAL Green，因此只验证了无崩溃/
  无 400，不能把该次错误归因于恢复逻辑。
- `read_crop` 0-1 输入已有定向错误，#863 本次未再次发送该错误输入。

## 4.5 closure checker 回复被 max_tokens=2048 截断(64k 修复运行,2026-08-09 发现)

### 现象(#250 起报,viewer/JSONL 里 checker 回复句中截断)

- #250(Basketball_Shot)的 submit_answer details.checker_reply 7258 字符,
  尾部 "…PERCEPTION evidence. The"——句中硬切。非个例:运行前 37 次 checker
  回复中 **35 次(95%)句中截断**。
- 但 #250 的裁决不受影响:"CLOSURE: YES" 在**第 1367 字符**就已写出(裁决已捕获),
  截断发生在裁决行之后的续写(模型写完 CLOSURE: YES 又写了 5879 字符
  继续自说自话)。agent 正常收到 accepted、写出 FINAL: Yes(答对)。

### 根因(evidence_closure.ts L357)

- checker VLM subcall `max_tokens=2048`(S2.6 早期修复时设的防饿死预算),
  8b 模型在 enable_thinking=false 下仍超话痨(单次回复 6.2-8.4K 字符 ≈
  1800-2200 token)——**回复普遍顶到 2048 token 上限被 vLLM 长度截断**,
  35/37 的回复未写完就没了。
- 截断位置与裁决行的相对关系决定了危害:
  - 裁决行在截断前(29/37)→ 正则已捕获 CLOSURE: YES/NO,截断只是尾部丑陋,无害;
  - **裁决行未及写出即被截断(8/37 = 22%)→ 正则无匹配 → 落入 CLOSURE_NO 分支
    (accepted=false, oneShotUsed=true) → 有效 claim 被误拒**,agent 被迫
    重观察一轮。若重观察工具再出错(#863 坐标误用型),会话直接死,
    连第二次提交都没有。
- 8 个误拒标本:全部 Basketball_Shot、全部在 submit#2/#3(说明首轮后重提,
  又被截断拒一轮)、回复 6.2-8.4K 字符全在裁决行前被切(#1/#750/#260/#762/
  #765/#775/#783/#788/#813)。
- **eval 侧审计 artifact**:JSONL 的 `closure.checker_reply` 只有 "We are given:"
  (多行回复被 stdout 按行拆开,eval 只取 `checker reply:` 首行)——完整(仍
  截断的)回复在 `tool_results[].details.checker_reply`。看 closure 字段会
  误判"回复被截成一行",实际是 eval 解析 artifact。

### 处理(待定)

- 等用户命令。候选:checker max_tokens 2048 → 8192(或 4096);或改解析——
  若回复未含 CLOSURE 行,视为"checker 截断"而非硬拒绝(区分 truncation 与
  genuine NO,拒绝时不给 oneShotUsed 或提示重试 checker);或限制模型
  回复长度(few-shot 强调只输出一行)。eval 侧 closure.checker_reply 改从
  tool_results details 取(修复审计字段)。

## 5. viewer 思考块截断到 1000 字符(误读为"思考中断")[s26 观察]

### 现象

7875 检查 #9 时,长思考块总在 ~1000 字符处词中硬切("...check if the basketb"),
viewer 却标注 `💭 思考 (1198 字符)`——显示文本与标注字数不符。

### 根因(build_case_viewer.py,非模型/非 pi)

- `build_case_viewer.py:64` `MAX_THINK = 1000`(注释:截断长度,`chars` 字段保留全长),
  L125-126 `{"t":"think", "text": t[:MAX_THINK], "chars": len(t)}`——**渲染层截断**,
  所有 >1000 字符的思考块被切到 1000,词中间硬切。
- 上游完整:prediction JSONL 该 case `reasoning` **10708 字符**,结尾完整
  ("Just output the final answer as instructed.");eval_pi_agentic.py 提取无截断
  (L215-216 全 thinking blocks join)。
- 链路:pi session → eval 提取(完整)→ JSONL(完整)→ **build_case_viewer 截断** → cases.json(1000)→ viewer。
- 同类截断:result 文本 `txt[:600]`(L122)、text `txt[:MAX_TEXT]`(L120)——看结果时
  尾部报错也可能被藏(dev_fix 期已发现 "already exists" 报错被截)。
- 影响:调试时误判"模型思考中断/思考长度异常";尾部内容(常是最终判断)不可见。

### 处理(已修复 2026-08-09,用户指示不要上限)

- `build_case_viewer.py` 移除 MAX_THINK 截断(`MAX_THINK = None`,思考全文进 cases.json;
  chars 字段保留)。前端 `.ev-think` 本就无裁切(CSS 只有 `.ev-result` 120px 滚动)。
- 重建 cases.json(403 case,156MB bundle)并重启 7875/7877 验证:#9 的 1198 字符
  思考完整返回,结尾 "I need to confirm visually.",不再词中硬切。
- 未动:result `txt[:600]`、text `txt[:MAX_TEXT]=1500`、args `[:500]`——同类截断仍存在
  (调试时看长结果尾部仍可能被藏),后续按需处理。

### 其它 s26 观察

- closure gate 起效: 132 case(32.7%)首次 submit_answer 被拒后重试(129 case submit_calls=2,3 case =3)。
- gate 盲点(#817): 首次被拒后改写措辞("net remains fully intact at 2.9/3.3"→ 全局结论)即被接受——
  checker 不校验**时间覆盖**:采样 2 个时刻的"无球"≠ 全程无进球。
- #817 s26 完整失败链: index_video 崩溃(无时间线)→ 猜时间窗 2.5-3.5s、1.5-2.5s → semantic_crop ×4 全崩 →
  只看 1.5-3.5s 未见球 → "No"(gt=Yes,错)。与 dev_fix 版对比:dev_fix 完全不看帧,s26 看了但窗口错。

## 6. token 分配问题:窗口 40960 被 max_tokens=32768 切成输入预算 8192 [s26 运行]

### 分配账本(与 §4 的 400 机制是同一根因的两面:§4 记现象/死法,本节记分配与修法)

- vLLM `max_model_len=40960`(2 卡 TP=2,`configs/vllm_qwen3_vl_8b_thinking_gpu01_s26.json`);
  pi 每轮固定请求 **`max_tokens=32768`**(`~/.pi/agent/models.json` 的 maxTokens,
  2026-08-07 修复 B 时按用户要求设 32k)。
- → **输入预算 = 40960 − 32768 = 8192 token**。思考模型每轮思考 2-6K token,
  几轮顶穿;127/127 无答案死于同一 400(机制详见 §4),另有 10 个有答案会话
  尾部同款 400——"写完之后的收尾请求被拒"。
- 40960 是 2 卡**保守起点**(handoff 明示"40960/2 是保守起点,非调参;显存有余量
  才升 61440")——s26 全量跑的时候没执行升级,127 个 case 全部撞线。

### 档位对比(同模型,同 8× RTX 4090 24GB 机器,实测/核算)

| 配置 | 卡数 (TP) | max_model_len | 输入预算(=窗口−32768) | 状态 |
|---|---|---|---|---|
| gpu01_s26 | 2 (0,1) | 40960 | **8192(死线)** | s26 实测,已停 |
| 旧 4 卡 baseline | 4 (4,5,6,7) | 61440 | 28672 | 2026-08-07 baseline 实测 |
| **新 gpu0-3_64k** | **4 (0,1,2,3)** | **65536** | **32768** | 已部署,定向 smoke 通过 |
| recovery_8gpu | 8 (0–7) | 131072(原生) | 98304 | 2026-08-07 修复 C 实测 |

### 修复(已部署并通过定向 smoke 2026-08-09)

- 新配置 `configs/vllm_qwen3_vl_8b_thinking_gpu0-3_64k.json`:TP=4、GPU 0–3、
  `max_model_len=65536`、`max_num_seqs=16`、mm_processor_cache 50GB、port 8001;
  显存核算(TP=4 每卡):权重 ~5.4 GiB(16.33GiB/4 + mm encoder data 模式重复 ~1.3)
  + KV 65536×16/4×36.8KB ≈ 9.6 GiB ≈ 15.1/21.6 GiB,16 并发安全;
  KV 单位成本由本机日志自洽推出:TP=8 12.75GiB/725,504tok ≈ 18.4KB/tok/卡 → 总 ~147KB/tok。
- 输入预算 32768；客户端 contextWindow 同步为 65536，compaction reserve 设为
  32768，在超过服务输入预算前主动压缩；**maxTokens=32768 不动**。
- dry-run、serving 补丁 6/6、离线测试 93/93+21/21 和原失败题 smoke 均通过；
  详见 `docs/working_logs/runs/2026-08-09_s26_bugfix_64k_smoke.md`。
- 未采用:max_tokens 调小(与 32k 要求冲突,需改 models.json);8 卡 131072(占满整机,
  影响同机其他任务)。
