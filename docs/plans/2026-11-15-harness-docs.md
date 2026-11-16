# Harness 与文档体系完善

状态：已完成。日期：2026-11-15。

## 目标与现场

统一测试发现、执行结果与提交门禁；补齐运行时契约、开发验证、状态恢复、发布与文档导航。物理目录为 `codingKeeper`，远端为 `https://github.com/g8cc/codingkeeper.git`。

开始时已有 11 个修改文件：AGENTS、双语 README、ZCode 归属 helper、headless、迁移/运维文档及 acceptance/session-hygiene/zcode-quota/zcode-session 测试。保留原有修改，本轮不安装、不启动真实项目 runner、不改外部项目和会话数据。

## 发现与决策

- 旧 audit 阶段写死文件名单。隔离副本新增 `zz-injected-audit.py` 并退出 23，旧 runner 仍退出 0、输出全绿；改为自动发现并加入回归。
- pre-commit 只跑 syntax/unit/conformance，与 AGENTS 全量要求不一致；统一到 full profile。
- 成功日志实际默认删除，旧测试文档却承诺保留；保持默认回收，新增显式保留和外部报告。
- Swift 工具链不健康时 stdout 有 SKIP，旧总结仍把 syntax 写为普通 PASS；报告明确记录跳过，可选择严格拒绝跳过。
- 文档缺总导航、开发与发布合同，架构把独立上下文写成跨模型；补全指南并校正保证范围。
- 首次 full 捕获通知对等用例的时钟竞态：超大 gap 实际回退 3 秒，用例误假定两次真实调用始终小于 3 秒；隔离重跑通过。保留首次失败记录，改夹具固定时钟并补 2 秒抑制 / 3 秒放行边界，不修改通知运行逻辑。

## 工作清单

- [x] 核对路径、远端、硬约束、未提交现场和基线。
- [x] 以新增必失败审计复现漏跑，增加行为回归。
- [x] 增加自动发现、选择器、分层 profile、原子 JSON 报告与产物保留控制。
- [x] 对齐完整 pre-commit 门禁，接入离线 CI 与文档校验。
- [x] 补齐文档导航、harness、开发、状态恢复和发布指南。
- [x] 完成新增回归、失败注入与 full profile，记录最终结果。

## 验证记录

| 验证 | 结果 |
|---|---|
| 修改前 `tests/run-all syntax unit conformance` | 退出 0；Swift 工具链探针超时，实际 SKIP，旧总结未区分 |
| 新增漏跑回归在旧 runner | 失败，证实新增 audit 未执行仍得到全绿 |
| 新 runner 的 8 项初始回归 | 通过；自动发现、选择、JSON 清单、报告、跳过、非法参数、源码保护及缺失结果检测 |
| 文档校验器的 5 项回归 | 通过；有效文档、坏链、引用链接、索引遗漏、门禁漂移及代码示例边界 |
| harness 的 9 项生命周期回归 | 通过；取消、顽固子进程、清理超时、报告最终状态及成功显式保留 |
| 通知对等的 5 项回归 | 固定时钟与两通道独立夹具状态后通过；2 秒抑制、3 秒放行均断言 |
| 首次 full | 51 项记录完整，退出 1；只失败通知时钟用例。四工具 tmux、headless、故障注入及其他审计通过，原始失败报告保留 |
| 最终 `tests/run-all --profile full --keep-artifacts --report /private/tmp/ck-harness-final-20261115.json` | 51/51 项记录，47 pass、3 pass_with_skips、1 report，0 fail，退出 0；cleanup_complete=true，无清理错误 |
| 文档、Shell/Python 和 CI 配置复核 | 本地链接/导航通过；Bash 3.2 语法及 Python 3.11 语法兼容检查通过；workflow YAML 与产物收集脚本结构/语法通过 |

结构化记录见 [harness-2026-11-15.json](../execution-audit/harness-2026-11-15.json)，含逐检查结果、跳过提示、日志哈希与实现/测试源码哈希。完整原始报告和日志保留在上表路径及报告指向的私有产物目录；临时路径可能过期，仓库内摘要持续保留。

最终三项部分覆盖为 syntax 的 Swift 探针、desktop 审计的工具链探针，以及 watchdog-deploy 的两项真实安装检查。首轮 desktop 行为审计实际通过；最终记录仍如实标跳过，不跨运行拼接为完整覆盖。keys 只报告本地库存。真实模型、原生 TTY、安装桌面二进制、launchd 部署和远端 CI 本轮未执行。

原有实现、会话归属测试与迁移补丁已核对保留；没有推送、安装或操作外部项目状态。2026-11-16 按用户明确要求创建本地 Git 提交，提交范围为本计划中保留的工作区改动；后续发布仍按贡献/发布指南独立执行。

工作期间另有并行补充的 `burn-watch.sh` / `watch-window-audit.py` 配额恢复改动，以及通知夹具的两通道状态隔离改动。本轮未覆盖或回退这些内容；它们已包含在最终 full 的受测源码和哈希记录中，不将其归为本轮单独实现。
