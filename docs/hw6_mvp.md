# HW6 MVP：两个真实 agent 通过 Referral 雇佣与交付

## 跑的是什么

`referral mvp` 一条命令完成以下步骤，中间没有人工转发：

1. 启动 Referral MCP server（HTTP，`127.0.0.1:8791/mcp`）。市场里有 5 个模拟 worker，各带 12 个试用任务的记录；另有 1 个 **Claude Haiku 5.5 worker**，还没有任何记录。
2. 启动 **雇主 agent**：Claude Code headless 模式，模型 Claude Sonnet 5.5，名字 `acme-intel-agent`，身份是 Acme Robotics 的竞争情报 agent。它只拿到一个目标（董事会简报要 5 个竞品事实），工具只有 Referral 的 MCP 工具，没有 Bash，也不能读写文件。它自己决定调用顺序：注册 → `request_match` → `hire` → `get_record(wait_seconds)`；如果 Checker 判失败，就换掉这个 worker 重新匹配。
3. Referral 把这单派给 Claude worker 时，派单钩子会启动 worker 的 Claude Code 运行时（作用类似 webhook）。worker 同样只能用 Referral 的 MCP 工具，按顺序执行：`get_assignment` → `submit_prediction`（读文档前锁定预测）→ `read_document` → `submit_delivery`。
4. Checker 逐条核查交付的事实：引文要来自许可文档且逐字一致，取值要在引文里，另外有一个隐藏的抽查格。雇主只用通过核查的事实写简报。
5. `referral audit` 只读账本和雇主的最终答案，独立复核以下几项：
   - 哈希链和签名
   - 预测确实在交付之前锁定
   - 隐藏抽查格的承诺能够正确打开
   - 每条事实的 Checker 判定和真实答案是否一致
   - 简报里的事实是否全部正确，且都来自通过核查的那单

## 怎么跑（录屏时在你自己的终端里跑）

```bash
cd "/Users/louis/Desktop/MIT IDS.865/.claude/worktrees/project-v1-planning-9fd9d4/referral"
PYTHONPATH=src .venv/bin/python -m referral mvp
```

- 跑一次大约 40 秒。用的是本机 `claude` 登录的账号，每次两个 agent 合计约 $0.04。
- 每次运行都会新建 `runs/<时间戳>/`，里面有：
  - `transcript.txt`：人能读的运行记录
  - `buyer.jsonl`、`worker-job-*.jsonl`：两个 agent 的原始 stream-json
  - `referral.sqlite`：账本
  - `answer.json`：雇主的最终简报
  - `audit.json`：审计结果
- 只想重跑审计：`PYTHONPATH=src .venv/bin/python -m referral audit runs/<时间戳>`
- 默认端口 8791。8765 被本机的一个 `python -m http.server` 占着，所以没用它。

## 2026-10-25 的实测结果

在加上"子 agent 不加载本机钩子"之前跑了 3 次，加上之后又跑了 1 次，作为正式证据（`runs/20261025-171910/`）。4 次都端到端通过：

- Referral 把这个困难任务给了 Claude worker，方式是 `bounded_trial`，因为它还没有记录。
- worker 锁定的预测是 50–55%，交付 5/5 通过 Checker，隐藏抽查格也通过。
- 审计结果：账本 253 条记录，链完整；Checker 误判通过为 0；简报 5/5 和真实答案一致，都来自通过核查的那单。
- 这一单之后，Claude worker 仍然是 `trial`，guidance 是 "only one checked hard job so far"。

4 次都是一次就通过，没有触发重新匹配。Checker 拒收错误交付的情况（引用过期文档、认错同名公司、编造引文）在 `referral demo` 的模拟场景和单元测试里有覆盖。

## 1 分钟录屏分镜（建议）

| 时间 | 画面 | 旁白要点 |
|---|---|---|
| 0–8s | 终端里输入命令 | Referral 是给"雇佣别的 agent 的 agent"用的核查和信誉服务，两个 Claude agent 只通过它的 MCP 工具互动 |
| 8–20s | buyer `request_match` → `bounded_trial`，派单 | 雇主 agent 自己发请求；Referral 按难度和记录匹配，新 worker 只能拿到有限试用 |
| 20–35s | worker 锁定预测 → 读文档 → 交付 → Checker passed | 预测先锁定、不能修改；Checker 逐条核对引文和隐藏抽查格 |
| 35–45s | buyer `get_record` 逐条 pass，最终简报 | 雇主只用通过核查的事实 |
| 45–55s | audit：链 ok、5/5 对上真实答案、误判 0 | 不信任 agent 的自述，独立复核 |
| 55–60s | 局限 | 见下面段落最后一句 |

## 提交用的说明段落（英文草稿）

Referral (team: Yvette Ge, Mengxiang (Louis) Liu) is a checking and track-record service for agents that hire other agents. In this MVP, two Claude Code agents interact only through Referral's MCP server. Acme Robotics' competitive-intelligence agent (Claude Sonnet 5.5) asks for five sourced competitor facts. Referral offers it a Claude Haiku 5.5 worker that has no record yet, as a bounded trial. The worker locks its success forecast before it reads any document, then delivers cited facts. Referral's Checker verifies every quote against the permitted corpus, plus one hidden known-answer slot. The buyer builds its brief only from facts that passed. An independent audit then re-checks the hash-chained ledger and compares every delivered fact with ground truth: 5 of 5 correct, no false passes. Limitation: the corpus is a small fictional set, the other five workers are simulated personas, and one checked job is too little evidence, so Referral still lists the Claude worker at the trial tier.
