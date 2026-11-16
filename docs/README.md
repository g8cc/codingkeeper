# 文档总览

这里索引当前运行指南、开发契约和历史证据。当前行为以源码、可重复的回归与下列指南共同核对；带日期的审计描述当时的发现和验证范围，不能直接当成今天的服务健康证明。

## 按目标阅读

| 目标 | 入口 |
|---|---|
| 第一次使用、安装、选择工具 | [English README](../README.md) / [中文 README](../README.zh-CN.md) |
| 修改控制器并验证 | [贡献流程](../CONTRIBUTING.md) → [架构](ARCHITECTURE.md) → [测试指南](../tests/README.md) |
| 理解整个 Agent harness | [Harness 契约](HARNESS.md)：输入、执行、验收、恢复及代码映射 |
| 查队列、停炉、时段、quota 和桌面状态 | [运行手册](OPERATIONS.md) |
| 查状态所有者、原子写和恢复边界 | [状态与恢复契约](STATE-CONTRACTS.md) |
| 上游故障后切换 provider 并续接原会话 | [Provider 自动恢复](PROVIDER-RECOVERY.md) |
| 报障与查残留会话 | [排障手册](triage-playbook.md)；先回到用户看到的界面 |
| 选择工具或核对真实兼容范围 | [工具矩阵与凭证](TOOLS.md) |
| 选择持续改进任务与领域包 | [改进燃料](FUEL.md) / [领域指南](FUEL-DOMAINS.md) |
| 跨模块任务与会话续接 | [计划与交接](plans/README.md) |
| 发布、安装与回滚 | [发布流程](RELEASE.md) / [变更记录](../CHANGELOG.md) |
| 源码目录改名、持久化 cwd 修复 | [本地迁移](LOCAL-RENAME-2026-11-14.md) |
| 产品方向与商业假设 | [商业化路线](COMMERCIALIZATION.md) |
| Agent 进入仓库的硬约束 | [AGENTS.md](../AGENTS.md) |

## 当前验证入口

```bash
tests/run-all --list                     # 从代码生成当前阶段和套件清单
tests/run-all --profile quick            # 开发反馈；不替代 full
tests/run-all --profile full --keep-artifacts --report /private/tmp/ck-report.json
```

`docs` 阶段校验仓库内 Markdown 本地链接、顶层文档的索引覆盖和完整提交门禁契约；`--suite docs` 对校验器做失败注入。它不访问外链，不证明说明文字的语义一定正确，也不替代人工审阅命令与当前行为。

## 历史审计与证据

| 日期 / 专题 | 范围 |
|---|---|
| [2026-11-15 执行质量](AUDIT-EXECUTION-QUALITY-2026-11-15.md) | 历史 receipt、用户流程、候选保留与产品门禁漏跑 |
| [2026-11-15 harness 与文档交付](plans/2026-11-15-harness-docs.md) | 本轮范围、回归与验证记录 |
| [2026-11-12 领域扩展](AUDIT-FUEL-EXTENSION-2026-11-12.md) | 17 包、85 类、容量与轮转 |
| [2026-11-12 配额调度](AUDIT-QUOTA-DISPATCH-2026-11-12.md) | 调度、quota 与复燃 |
| [2026-11-12 复审](AUDIT-2026-11-12.md) | 改进燃料和受管进程 |
| [2026-11-06 审计](AUDIT-2026-11-06.md) | 多工具协议、会话双库与确认方式 |
| [2026-11-05 深审](AUDIT-2026-11-05.md) | 启动、生命周期、性能和兼容边界 |
| [2026-11-05 ZCode 窗口](ZCODE-WINDOW-2026-11-05.md) | 套餐时段与旧后台实例 |
| [2026-11-05 叶子审计](LEAF-AUDIT-2026-11-05.md) | 队列合同、验收事务及项目证据 |
| [叶子框架](leaf-audit/framework/README.md) | 工单分类、适用条件、调度与预算参考 |

历史 JSON、补丁和 prepared 草案由对应审计报告链接；prepared 中的代码是历史材料，不是当前控制器的运行入口。

## 维护规则

新增 `docs/` 顶层 Markdown 时在本页登记；新增指南说明用户目标、真实入口、验证方法与边界。跨模块实现更新相应契约与测试指南，历史报告保留原始时间与结论。操作步骤不要引用本机临时目录作为唯一证据，也不要把某次历史全绿推广为持续在线健康。
