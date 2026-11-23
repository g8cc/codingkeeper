# 在线响应与会话续接验收

状态：本轮有界验证与清理已完成，五工具在线验收阻塞。日期：2026-11-19 至 2026-11-20（Asia/Singapore）。

## 用户结果与范围

本机部署及桌面/launchd 验收已完成，见 [实机验收](2026-11-19-release-smoke.md)。
用户在剩余真实供应商及多工具流程明确后要求继续；本轮执行六工具最小在线请求，
每个工具最多两轮，验证当前已配置供应商的真实响应以及确切原会话续接。
会使用少量现有额度；认证、额度或网络失败后记录现场，不通过换供应商或反复请求凑通过。

## 隔离与验证

- 私有临时 HOME/数据目录、空项目，必要连接配置仅在私有目录临时复制；不展示密钥。
- 第一轮记住随机标记，第二轮只请求回忆，不在新提示中重述标记；核对原生会话身份。
- ZCode/dsh 使用真实 worker 适配器，核对主/重试 ID、最终响应、真实数据库项目归属。
- TUI 工具的非交互最小请求只证明相应在线协议，不当作 UI 或故障后 provider 切换通过。
- 不修改生产会话库、注册表、暂停文件或用户配置；结束后清理私有进程及复制的凭证。
- 行为源码未变时不重复已完成 full；续接时发现新的暂存 headless 改动，另按
  [门禁边界计划](2026-11-20-post-review-gate-boundaries.md) 完成失败回归、修复与当前代码 full。

## 步骤

- [x] 核对 cwd/origin/Git、115 份受测源码指纹与 22 份已安装 runtime。
- [x] Codex 首轮记录并发限制；不重试，第二轮未执行。
- [x] Claude Code 首轮记录 HTTP 504；不重试，第二轮未执行。
- [x] Pi / OpenCode 各首轮记录认证或额度失败；第二轮未执行。
- [x] ZCode 两轮通过；dsh 首轮认证失败后原 ID 和持久化 cwd 保留。
- [x] 汇总成功、阻塞、清理与发布边界；文档随当前源码门禁统一校验。

## 实际结果

| 工具 / 版本 | 提交轮数 | 响应与原会话续接 | 证据与下一步 |
|---|---:|---|---|
| Codex 0.170.0 | 1 | 阻塞，未得到成功回答 | 上游 `Concurrency limit exceeded for user`；rollout 会话与 cwd 可核验。待容量恢复后另行补验 |
| Claude Code 2.1.314 | 1 | 阻塞，未得到成功回答 | 原生结构化结果 `api_error_status=504`、`terminal_reason=api_error`，错误含 overloaded。待服务恢复后补验 |
| Pi 0.84.0 | 1 | 阻塞，未得到成功回答 | 原生 assistant `stopReason=error`，HTTP 401 Invalid API key；即使 CLI 退出 0 也未计为通过。需更新当前 provider 的有效凭证 |
| OpenCode 2.0.32 | 1 | 阻塞，未得到成功回答 | 原生错误 HTTP 429、`type=provider.quota`；捕获失败后停止。需处理当前渠道额度 |
| ZCode CLI 0.17.1 | 2 | 通过 | 仓库 worker 两次退出 0、标记与 nonce 完全一致；第二轮没有重述 nonce，主会话 ID、原生事件与 SQLite cwd 全部一致 |
| dsh 0.2.1-rc.5 | 1 | 阻塞，未得到成功回答 | HTTP 401，worker 退出 1；原 session ID 与压缩 JSONL 的 cwd 保留，未偷换会话。需更新当前路由凭证 |

总计 7 次提交。最初并发任务结束后，Pi、OpenCode、ZCode、dsh 顺序执行；
没有为获取成功切换供应商、模型、凭证或重复失败请求。不能从先前并行状态推断
上游并发拒绝的唯一原因。

Claude 原 harness 对完整 JSON 使用关键词分类，误标为 quota；人工复核原生
`api_error_status` 确认是 504 overloaded。原报告保留，汇总报告显式记录更正，
不以含 `fallback_credit` 等字段名的 JSON 关键词命中推断额度状态。

ZCode 原生 usage 两轮分别报告 input/output 7592/746 和 8408/91 token，
第二轮另有 cacheReadTokens=7552；没有据此推算费用。其他失败请求不能按
缺失 usage 推断免费。在线非交互命令不代表 TUI、故障切换或桌面侧栏验收通过。

## 清理与隔离

- 六工具凭证配置副本已删除，未发现本轮私有路径下仍存活的 CLI 进程。
- 生产 registry、Codex/Claude/Pi 配置和 dsh settings 五份基线哈希保持不变；
  这不是对所有生产文件的完整审计。
- ZCode 会话不在生产 CLI DB 或桌面 tasks-index 中；dsh 私有会话未出现在生产
  session 目录及其投影缓存。仅作只读核对，未删除任何生产会话。
- Pi/OpenCode 报告均确认源配置未改、残余凭证文本为零。原始输出仍限制为私有文件；
  持久归档仅含脱敏结果和汇总，不含凭证、原始会话库或原始响应。

后续离线验收期间再次核对：registry、Codex/Claude/Pi 配置仍与基线一致，dsh
settings 的哈希已变化，文件修改时间为 2026-11-20 00:45:29（Asia/Singapore）。
本轮未编辑该生产配置；没有证据确定变更来源，保留现状并记录
`later-baseline-check.json`，不把在线结束时的五份一致性结论延伸到之后。

## 证据

本轮私有产物：`/private/tmp/ck-online-release-20261119-1jq30xzs`。
报告只记录必要的版本、退出结果、会话一致性、用量与脱敏诊断；原始输出不公开提交。
持久汇总：`~/.codingkeeper/verification/2026-11-20-online-release/summary.json`，
同目录保留六份原始结果报告及 Claude 分类更正说明。

## 未解决项

五工具需按上述实际失败处理外部依赖后补验；没有把失败解释成已修好的控制器缺陷。
已安装 `~/.codex/bin/codexc-headless` 链接直接指向仓库，本轮以新 inode 原子替换源码，
后续新进程会使用新版本；没有据此声称既有 runner 已热更新。公开发布、版本提交和
供应商配置变更未执行；当前不具备“六工具均已真实验收通过”的正式发布证据。
