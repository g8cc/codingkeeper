# CodingKeeper — 智能全部在 Agent 内, 机械全部在 Keeper 内

GitHub 仓库为 `https://github.com/g8cc/codingkeeper.git`，本地源码目录为 `codingKeeper`。
旧 `codexc` 项目目录已退役；历史会话找不到旧 cwd 时，不要重新 clone 或重建旧目录。
从真实 `codingKeeper` 目录重新打开项目，先核对 `pwd -P` 和 `git remote get-url origin`。
ZCode 续接会话还需确认持久化 cwd，不能只在命令外层切换目录；迁移步骤见
`docs/LOCAL-RENAME-2026-11-14.md`。`codexc` 作为兼容命令仍然保留。

本仓库是 CodingKeeper 控制器本体。改这里之前:

1. **任何行为修复必须带回归测试**, 并通过 `tests/run-all` 全绿后提交
   (pre-commit 钩子会强制执行)。没有测试的 bug 修复等于没修。
2. **排障必须先读 `docs/triage-playbook.md`**——五条铁律: 先看后搜 / 宽松检索变体矩阵 /
   零命中+用户坚持=假定自己漏了 / 验证回到用户视图 / 实体删除同步派生物。
   2026-11-07 的三次误判事件全部源于违反这些规则。
3. 本仓库所有会话状态文件 (status.json / queue.md / loop.halt / registry) 使用原子写入,
   bash 3.2 兼容 (无 declare -A), 运行中的脚本禁止原地编辑 (写新文件 + mv)。
4. 会话/任务对用户可见的存储有两套 (CLI db.sqlite + 桌面侧栏 tasks-index.sqlite /
   dsh 投影缓存)——任何清理必须双库同步, 见 tests/session-hygiene-audit.py 的静态断言。

## 工作入口与完成标准

- [文档总览](docs/README.md) 是导航；改控制器先读 [贡献流程](CONTRIBUTING.md) 与
  [Harness 契约](docs/HARNESS.md)，涉及持久化再读 [状态与恢复](docs/STATE-CONTRACTS.md)。
- 开始工作先核对 cwd、origin、Git 状态并保留用户改动。跨模块任务在
  [docs/plans](docs/plans/README.md) 记录目标、步骤、验证和未解决项，续接时先读计划。
- `tests/run-all --list` 查看实际清单；`--suite <name>` 跑目标审计；`--profile quick`
  用于迭代；提交前 `--profile full`。pre-commit 同样跑 full，不以 quick 代替完整验收。
- `tests/*-audit.py` 自动发现；新增审计必须在清单中可见。修复先证明旧实现失败，
  再证明新实现通过，核对相邻工具与错误分支。
- 文档更新随代码走；新增顶层指南登记到总览，`docs` 阶段校验链接与导航。
  历史审计保留当时结论，不当作当前服务健康。
- 完成时报告实际改动、完整验证结果与 SKIP/未验证边界。离线假 CLI 不代表真实
  模型、GUI、已安装桌面或 launchd 已验收；安装与发布另按 [发布流程](docs/RELEASE.md)。
