# Referral v1 实现规划

依据：`Referral_Proposal.pdf`（Drive 最终版）、10.21 会议记录、Working List。
目标：先做出一个能在 demo day 现场跑通的端到端原型，再逐步替换成真实 LLM worker 和更完整的评分。

## 1. v1 要证明什么

proposal 第 4 节（Prototype and checks）就是 v1 的验收标准：

| proposal 里的要求 | v1 怎么体现 |
| --- | --- |
| 一个 buyer、四个 instrumented worker（reliable / honest-but-weak / overconfident / newcomer） | `workers.py` 里 4 个人设，外加一个用来演示刷分的 padder |
| 带已知答案、有日期的语料库 | `corpus.py`：虚构公司 Acme Robotics 的 8 家竞争对手，每家有新旧两版资料（旧资料里的融资和人数是过期的） |
| 一条两跳链：reliable 把一个 lookup 分包给 weak | `sim.run_chain_demo()`，每一跳单独签合同、单独检查 |
| 先做等量 trial jobs，再冻结 profile，在固定难度档跑新任务 | `evaluate.py` 的两阶段协议 |
| 成功标准：5 条事实全部通过检查，且在预算和截止时间内；no-match 和超时算失败 | `service.py` 里的 job 结算逻辑 |
| 对比：past success rate vs. outcomes-only profile vs. full Referral，看 successes per dollar、added latency、attribution accuracy | `evaluate.py` 输出对比表 |
| Misuse #1：overconfident 在派单后改预测 → Notary 拒绝，难题改派别人 | `sim.run_misuse_revision()` |
| Misuse #2：worker 用自己给自己派的简单单刷记录 → tier 不变 | `sim.run_misuse_padding()` |

## 2. 架构（一个服务 + 一个 SQLite 库）

```
buyer agent ──MCP──▶ ReferralService ──▶ Matcher   (选人，只输出 tier / 证据强度 / guidance / action)
worker agent ─MCP──▶       │         ──▶ Notary    (append-only、hash-chained 日志，锁预测)
                           │         ──▶ Checker   (逐条核对引用 + 混入隐藏的 known-answer canary)
                           │         ──▶ Scorer    (从日志算 profile → tier → 描述性 insight)
                           ▼
                        SQLite（agents / jobs / notary_log）
```

- **Notary 是唯一的事实来源**：合同、预测、交付、检查结论都写进 `notary_log`，每条记录带 `prev_hash` 和 `hash`，并用该 actor 的密钥做 HMAC 签名。`verify_chain()` 可以发现任何事后篡改。
- **Profile 不单独存**：每次都从日志重新算，保证“只有挂在已锁定、已检查合同上的结果才算数”。
- **黑盒输出**：MCP 工具从不返回原始分数或公式，只返回 tier、证据强度标签和自然语言 guidance。

## 3. MCP 工具（`mcp_server.py`）

| 工具 | 调用方 | 作用 |
| --- | --- | --- |
| `register_agent` | 任何 agent | 首次调用时注册，拿到 agent_id 和签名密钥；声明模型 |
| `declare_model_change` | worker | 换模型 → 开新的 trial profile |
| `request_match` | buyer | 提交任务、语料、验收标准、预算、截止时间，可选 `min_success`（愿意付钱的最低成功率）→ 推荐人 + tier + guidance + action（hire / bounded_trial / no_eligible_match） |
| `hire` | buyer | 锁定合同并把任务和难度档发给 worker |
| `get_assignment` | worker | 外部 worker（比如真实 LLM agent）拉取待办任务 |
| `submit_prediction` | worker | 锁定成功概率、成本、完成时间；只能交一次，且必须在交付前 |
| `submit_delivery` | worker | 交付 5 条带引用的事实 → 自动触发 Checker |
| `subcontract` | worker | 为父任务开一个子合同（两跳链） |
| `get_record` | buyer | 只能看自己的 job：每条事实的检查结果、是否通过、建议 accept / reject_and_rematch |
| `get_insight` | 任何 agent | 某个 worker 的 tier 和 guidance（工具提供方以后可以据此分配权限） |
| `describe_corpus` / `read_document` | 任何 agent | 允许使用的语料库，真实 LLM worker 干活时要读 |
| `get_credential` / `get_issuer_key` / `verify_credential` | 任何 agent | Ed25519 签名的 tier 证明和验证用的公钥，给 ERC-8004 / NANDA AgentFacts 这类注册表引用 |

## 4. 评分（Scorer）——v1 只打 proposal 承诺的三项

1. **Calibration（按难度档算）**：每档单独算 Brier score 和 bias（平均高估多少）。如果只算一个混合 bias，worker 可以简单题故意低报、难题高报，让混合 bias 接近 0，骗到“预测可信”。tier 仍然用整体 Brier：Brier 是 proper scoring rule，在档之间挪预测刷不动它。
2. **Difficulty-weighted quality**：easy / medium / hard 权重 1 / 2 / 3；自己给自己派的单（buyer 和 worker 同一个 owner）只记录、不计分。
3. **Chain attribution**：父任务失败时，沿着 `via_job` 找到出错的那一跳；子任务自己的检查也没过 → 记在分包方头上，否则记在上游。

其余三项（稳定性/趋势、成本与时间超支、delegator quality）v1 只记日志，Scorer 先算出原始值但不进 tier。

**Tier 规则**（v1 的阈值，之后用数据调）：

- `trial`：有效 job 少于 4 个，或刚声明换模型。新 agent 用底层模型的公开 benchmark 分数做 Beta prior。
- `verified`：≥4 个有效 job，Brier ≤ 0.25，加权质量 ≥ 0.4。
- `trusted`：≥15 个有效 job，Brier ≤ 0.18，加权质量 ≥ 0.65，且自己造成的失败少。（trial 阶段每个 worker 做 12 单，所以 trial 结束时最多到 verified。）

**Matcher 估计成功率**：按难度档算 outcome 的 Beta 后验。某一档的预测满足两个条件才算额外证据：至少 3 个预测，且这一档自己的 |bias| < 0.25。bias 越大，权重越低。修正量用这一档的 bias 向整体 bias 收缩后的值（相当于整体 bias 值 4 单）。这样难题上虚高的预测抬不高 hard 估计，insight 也会写成“tends to overstate its chances on hard tasks”。真实模型不在 benchmark 表里时用占位值 0.75。

**Matcher 选人**：在估计成功率 ≥ `min_success`（buyer 可传，默认 0.35）的候选里选最可能成功的；差距 5 个点以内选便宜的。tier 只决定 action 是 `hire` 还是 `bounded_trial`，不过滤候选人；没人过下限就 `no_eligible_match`。

**canary**：实时服务（MCP serve）用 `secrets` 抽 canary 格，代码公开也算不出来；只有模拟（传了 seed）才按 (seed, task) 确定性派生，保证不同策略面对的是同一批抽签。合同里仍然放 canary 的加盐哈希承诺。

**凭证**：`get_credential` 返回仿 W3C Verifiable Credential 结构的 JSON（AgentFacts 就是用 VC 签名的），包括 issuer、validFrom/validUntil（7 天）和 credentialSubject（agent id、名字、模型、domain、tier、证据强度、签发时的 Notary 链头）。`proof` 是对其余内容的 canonical JSON 做的 Ed25519 签名。这是我们自己的简化方案，不是标准的 Data Integrity cryptosuite。凭证里没有任何原始分数，改动任一字段签名就失效。

## 5. Worker 和 Checker 的 v1 简化

- **Worker 是模拟的，但输出是真的**：每个人设对每个难度档有一个单条事实准确率；出错时会产生真实的错误交付（引用旧资料、编造引文、值不在引文里、漏交），Checker 对这些交付做真正的确定性检查。这样 demo 可重复、零成本，也不依赖网络。
- **真实 LLM agent 可以直接接入**：MCP server 是标准 stdio server，Claude Code / Claude Desktop 可以当 buyer 调 `request_match` → `hire` → `get_record`；任何 agent 也可以注册成 worker，用 `get_assignment` / `submit_*` 干活。
- **真实 Claude worker（`LLMWorker`）**：走同一套 service API。先读语料，第一次请求锁 forecast，第二次请求交 facts，两次都用结构化输出，语料放在带缓存的 system block 里。定义了 Opus 5.5 / Sonnet 5.5 / Haiku 5.5 三个 worker。服务端 refusal fallback 故意不开：fallback 会换成别的模型来回答，污染按模型统计的校准数据；遇到拒答就记成 API 错误。`referral live-eval --n 30` 给每个模型同样 30 道题，按档报告平均预测、实际通过率、Brier、bias、耗时和 token 花费，报告里标明是实测数据。需要 `ANTHROPIC_API_KEY`，会先打印计划，必须加 `--yes` 才真正开跑（默认 180 次请求）。单元测试全部用假 client，不联网。
- **Checker 的公开检查**：引文必须逐字出现在允许的语料文档里、值必须出现在引文里、文档必须是那家公司的。**隐藏检查**：每个任务里随机一格是 canary，Checker 知道正确答案（最新值），能抓住“引用了过期资料”的错误。模拟器另外记录真实对错，只用于评估 Checker 本身的漏检率，不给 Referral 看。
- **签名**：日志条目用服务端发放给各 agent 的 HMAC 密钥签名；对外的凭证用 Referral 自己的 Ed25519 密钥签名。v2 再改成 agent 自持私钥。
- **时间**：模拟用 `SimClock`，worker 干活时推进时钟，截止时间按时钟判；MCP 实时流程用真实时钟。

## 6. 文件结构

```
referral/
  pyproject.toml
  README.md                 英文，课程提交用
  docs/plan.md              本文件
  src/referral/
    models.py               数据结构
    notary.py               SQLite + hash chain + HMAC 签名
    credentials.py          Ed25519 签名的 tier 凭证和验证
    corpus.py               语料、ground truth、任务生成
    checker.py              引文核对、canary、链路归因
    scorer.py               profile、tier、insight
    matcher.py              选人和 action
    service.py              ReferralService，所有业务规则和权限
    workers.py              模拟 worker 人设 + LLMWorker（真实 Claude）
    mcp_server.py           MCP 包装
    sim.py                  demo 场景
    evaluate.py             三种策略对比
    live_eval.py            真实模型的校准实测
    cli.py                  python -m referral demo|eval|live-eval|serve
  tests/
```

## 7. v1 results（模拟，2026-10-22，含 P0 改进之后）

协议：每种策略从完全相同的历史出发（每个 worker 12 单等量 trial，padder 另刷 20 单自派简单单），冻结 profile 后每个 seed 跑 30 个请求（每档 10 个），失败可以 rematch 一次，no-match 算失败。同一 worker 做同一任务的结果只取决于 (seed, worker, task)，所以可以按 seed 配对比较。

| seeds 1–30 | Past success rate | Outcomes-only | Full Referral |
| --- | --- | --- | --- |
| 成功率 | 0.827 | 0.867 | 0.878 |
| hard 档成功率 | 0.630 | 0.723 | 0.760 |
| 每美元成功数 | 0.570 | 0.667 | 0.658 |
| 每请求花费 | $1.49 | $1.33 | $1.37 |

- **对 past success rate**：seeds 1–30 上成功率 +5.1 ± 1.5 个点，每美元成功数 +0.089 ± 0.020，每单少花 $0.12；seeds 61–90 上 +1.6 ± 1.3 个点、+0.086 ± 0.016。
- **对 outcomes-only**：成功率 +1.1 ± 0.6（1–30）、+0.9 ± 0.4（31–60）、+0.2 ± 0.3（61–90）；每美元成功数都低约 0.01，不显著。基本打平。
- **链路归因**：失败的两跳任务里，hop 级合同 100% 归因正确；只怪直接承包方是 51–54%。

**成功率下限（seeds 31–60 选的，另外两组验证）**：

| 下限 | 成功率（对 outcomes-only） | 每美元成功数 | no-match |
| --- | --- | --- | --- |
| 0.55（原默认） | −8.2 个点 | +0.037 | 7.8% |
| 0.45 | −2.0 | −0.004 | 1.1% |
| 0.35（现默认） | +0.9 | −0.011 | 0% |

**过程记录**：

1. 最初的 Matcher 会优先选非 trial 的 worker。消融显示这样成功率上没有好处、每单更贵，所以改成 tier 只决定 action。
2. 第一版用一个混合 bias 来判断预测能不能信，forecast 能比 outcome history 多赢 1–2 个点。但这部分优势有一部分来自跨档汇总的校准信息，而这正好是可以刷的漏洞（P0 第 1 条）。
3. 改成按档判断以后，诚实 worker 只有 4 单 trial，每档的 bias 本身就有 ±0.2 的噪声，forecast 权重变小，hard 估计退回到 0.5 左右。原来 0.55 的下限于是频繁触发 no-match，hard 成功率从 0.72 掉到 0.38。
4. 下限本质上是 buyer 的风险偏好，所以改成参数，默认 0.35。

**结论**：机制都跑通了，也明显赢过 public rating 式的 past success rate。按档校准之后，forecast 在选人上和 outcome history 基本打平，它的价值主要在三处：按 Brier 定 tier、写出“在 hard 上高估自己”这类 guidance、留下承诺记录。开放假设仍然开放，下一步用 `live-eval` 在真实模型上测。也可以考虑派单前让候选人报价，把 forecast 变成针对这一单任务的信号。

## 8. 之后的迭代

已完成（P0）：按难度档校准、实时 canary 不可预测、真实 Claude worker 与 `live-eval`、`get_credential` 凭证接口。

还没做：

1. 跑一次 `live-eval`，拿到真实模型的校准数据（需要 API key，会花钱）。
2. 稳定性/趋势、成本超支、delegator quality 进入 tier。
3. Demo day 用的可视化页面：一次 hire 的时间线、profile 变化、三种策略对比图，加上真实模型的校准图。
4. Agent 自持私钥给日志签名；外部 validator 的 verdict 作为额外证据；凭证改成标准 VC Data Integrity 格式。
5. 冷启动：同等曝光的 paired trials（Working List 里的想法）。
6. 派单前报价：让候选人在被雇之前报一个针对这单任务的 forecast。

## 9. 分工建议（按 proposal）

- Yvette：protocol、Notary、insight 文案层 → 重点看 `notary.py`、`scorer.py` 里的 `insights()`、tier 阈值。
- Louis：MCP 集成、Checker、评估 → `mcp_server.py`、`checker.py`、`evaluate.py`。
