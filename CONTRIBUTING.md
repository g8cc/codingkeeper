# 开发与贡献

CodingKeeper 的智能决策由 Agent 完成，Keeper 只负责可测试的协议、调度、生命周期与验收。完整导航见 [文档总览](docs/README.md)，仓库硬约束见 [AGENTS.md](AGENTS.md)。

## 准备工作

```bash
pwd -P
git remote get-url origin
git status --short --branch
git config core.hooksPath .githooks
tests/run-all --list
```

远端应为 `https://github.com/g8cc/codingkeeper.git`；本机源码目录为 `codingKeeper`。遇到历史 `codexc` cwd，按 [迁移指南](docs/LOCAL-RENAME-2026-11-14.md) 修复持久化会话路径，不创建旧目录。不要为了测试执行安装或启动真实项目 runner。

运行环境：macOS、Bash 3.2、Python 3.11+、tmux 3.5+、sqlite3；桌面类型检查需要健康的 Swift/AppKit 工具链。离线套件使用假 CLI，不要求任何模型登录；真实 CLI、终端和桌面验证另记结果。

## 从任务到验收

1. 先阅读相关实现与现有测试；排障先读 [triage playbook](docs/triage-playbook.md)。记录用户可观察的问题、复现方式和验收条件。
2. 保留已有 staged/unstaged/untracked 内容。跨模块工作使用 [执行计划](docs/plans/README.md)，把待验证事项、证据和未解决问题保存在仓库中。
3. 行为修复先增加会失败的回归，再修改最靠近根因的共享实现。检查相邻工具、异常分支、重启/迁移路径，避免把三车道的共享语义各抄一份。
4. 开发中运行命中的套件，再跑 quick；提交前运行 full。修复测试失败时保留首次失败日志，不能通过删断言、改成跳过或手工标 done 获得绿灯。
5. 更新当前指南、测试映射和必要的历史审计索引。提交说明写用户行为变化、测试命令、跳过项和仍待人工验收的边界。

```bash
tests/run-all --suite harness-runner
tests/run-all --profile quick
tests/run-all --profile full --keep-artifacts --report /private/tmp/ck-full-report.json
```

`quick` 用于迭代，不代替完整验收。pre-commit 固定运行 full；首次 Swift 编译及故障注入可能耗时较长。仅检查工作区不代表验证了某个不同的暂存快照；提交前再次审查 `git diff` 和 `git diff --cached`，确保测试对象与拟提交内容一致。

## 修改位置与验证

| 改动 | 实现入口 | 优先回归 |
|---|---|---|
| 队列、锁、状态与共享验收 | `ck-common.sh`、`ck-leaf.py` | acceptance、leaf-runtime、leaves、status、evidence-retention |
| TUI 启动、事件与续命 | `codexc`、`codexc-loop`、`ck-watcher.py`、`ck-watch-tools.sh`、`ck-provider.py`、`ck-tool-supervisor.py` | startup、codex-watch、provider-config、provider-supervisor、loop-daily、tool-watchers、integration、faultinjection |
| headless 运行与会话归属 | `codexc-headless`、`codexc-*-worker`、`ck-*-session.py` | provider-headless、burn-runtime、zcode-session、dsh-session、session-hygiene |
| gate、审查与受管子进程 | `ck-common.sh`、`ck-review-process.py`、`codexc-review-leaf` | acceptance、leaf-runtime、review-leaf、faultinjection |
| 时段、配额、人工占用 | `ck-window.py`、`ck-interaction.py` | window、zcode-window、watch-window、zcode-quota、interaction |
| 燃料、待决策和晨报 | `ck-prompts.py`、`ck-fuel-packs.py`、`ck-morning.py` | prompts、fuel-extension、product-fuel |
| 安装、看门狗、日志与桌面 | `install.sh`、`packaging/`、`burn-watch.sh`、`desktop/` | install-deps、watchdog-deploy、watchdog-install、log-location、desktop、swift-gate |
| 测试基础设施与文档 | `tests/run-all`、`tests/harness.py`、`tests/isolate.py` | harness-runner、harness、isolate-cleanup、docs，及 docs 阶段 |

所有 `tests/*-audit.py` 自动进入 audit 阶段。新增文件不必修改手工名单；测试本身仍要证明真实行为，不能只检查实现中是否出现某个字符串。完整命名以 `tests/run-all --list` 为准。

## 增加工具适配

先决定 TUI/headless 通道，遵守 [harness 契约](docs/HARNESS.md)。将会话发现、归属、事件成功/失败和退出语义留在适配层，共享队列与验收语义继续复用 `ck-common.sh` / `ck-leaf.py`。补 fake CLI 或真实私有 tmux 场景，覆盖首次失败、续接失败、空/损坏输出、超时、跨项目 ID、配额、取消与清理。

同时更新 [工具矩阵](docs/TOOLS.md)、双语 README、相关 conformance 声明和测试说明。离线假 CLI 通过，只能证明受测协议，不等于当前真实服务、权限弹窗或未来 CLI 版本兼容。

## 安全修改与证据

状态文件同目录写临时文件后原子替换；持有对应锁再更新。Shell 保持 Bash 3.2 兼容，不用关联数组。不要原地编辑运行中的脚本；本地修改不等于已安装副本更新，发布按 [发布流程](docs/RELEASE.md) 操作。

任何会话清理均需核对 CLI DB、桌面 tasks-index、dsh 投影及成员关系。具体恢复边界见 [状态与恢复契约](docs/STATE-CONTRACTS.md)。证据中不要提交凭证、完整用户会话、私有源码快照或本机测试目录。
