# CodingKeeper 测试指南

统一入口是 `tests/run-all`。完整开发流程见 [CONTRIBUTING](../CONTRIBUTING.md)，整体契约见 [HARNESS](../docs/HARNESS.md)，其他指南见 [文档总览](../docs/README.md)。测试默认离线，不发送模型请求。

## 环境与常用命令

macOS、Bash 3.2、Python 3.11+、tmux 3.5+、sqlite3。Swift/AppKit 用于桌面检查；健康探针失败会明确 SKIP，不能称桌面已通过。完整 integration 与故障注入需要数分钟以上，首次 Swift 缓存可能更慢。

```bash
tests/run-all --help
tests/run-all --list                     # 实际阶段、profile 和自动发现的 audit
tests/run-all --list --json              # 供脚本读取，不启动隔离世界
tests/run-all --profile quick            # syntax + unit + conformance + docs
tests/run-all --suite zcode-session      # 一个审计；可重复 --suite
tests/run-all --suite window --suite zcode-window
tests/run-all syntax unit docs           # 阶段子集
tests/run-all                            # 无参数就是 full
```

## 阶段与发现规则

| 阶段 | 内容 | 证据边界 |
|---|---|---|
| syntax | Bash 语法、Python 编译、Swift 探针/类型检查 | Swift 可能跳过；不等于真实桌面运行 |
| watchdog | 看门狗内嵌 selftest | 不调用真实 launchd |
| unit | loop/headless 内嵌 selftest | 共享规则与基础行为 |
| audit | 自动发现并排序 `tests/*-audit.py` | 假 CLI、临时仓库、私有进程及状态 |
| integration | Codex/Claude/Pi/OpenCode 四组真实私有 tmux 场景并行，再跑 headless | 真实 tmux + 假 worker/reviewer，无 API 依赖 |
| faultinjection | 进程终止、欺骗、超时、队列改写 | 失败必须阻止虚假验收并清理夹具 |
| conformance | tmux 按键、入口及默认不变量 | 部分为静态声明断言，不替代行为回归 |
| docs | 本地链接、顶层文档索引、导航及完整提交门禁约定 | 不请求外链，不证明全部说明语义 |
| keys | 隔离 HOME 中的本地二进制/配置库存 | 仅报告，不验证真实用户凭证或服务 |

quick 用于迭代，full 是提交与发布前完整离线门禁；pre-commit 固定 full。测试名以 `--list` 为准，不能把阶段与 audit 套件名称混用。

所有 `*-audit.py` 自动接入，无需追加硬编码名单。新增测试须核对清单中能发现它。可选 `native-startup-smoke.py` 和 `benchmark-status.py` 属于人工入口，清单单独列出，不纳入默认套件；前者会启动真实 Codex，后者比较指定版本性能。

## 隔离、报告与保留

`tests/isolate.py` 建立私有 HOME、TMPDIR、工具状态目录、tmux socket 和进程组，重置继承的 `CODEX_*` / `CODEXC_*`、tmux 等运行配置，并屏蔽桌面通知。它不是操作系统网络沙箱；离线行为依靠测试使用假 CLI 和显式门控。结束时终止本次进程组和私有 tmux；取消退出非零，清理失败不能得到通过结论。夹具自己创建的新 session/daemon 要由对应测试显式管理。

```bash
tests/run-all --keep-artifacts --report /private/tmp/ck-full-report.json
# 在具有完整工具链的环境强制拒绝已识别跳过项：
tests/run-all --profile full --strict-skips --keep-artifacts
```

成功默认删除整个 `Test artifacts` 私有目录；失败自动保留以便排障。`--keep-artifacts` 保留成功日志；`--report` 将原子 JSON 结果写到指定绝对位置，不受 scratch 清理影响。外部报告中的日志路径只有在产物仍保留时可用。仓库内报告必须写入忽略的 `.codingkeeper/`，防止误覆盖源码。产物可能含夹具源码，勿上传真实用户会话或凭证。

报告包含 schema_version、源码 revision、选中阶段、预计检查、实际结果、退出码、耗时、日志和跳过提示。runner 先完成阶段结果，isolator 再补最终退出码与 cleanup_complete/cleanup_errors；观察到 running 仅表示尚未形成完整结果。revision 不代表工作区没有未提交改动。

- `pass`：命令成功，未发现标准 SKIP 提示。
- `pass_with_skips`：命令成功但有覆盖未执行，顶层为 `passed_with_skips`。
- `report`：keys 本地库存，不当作服务验收。
- `fail` / 顶层 `failed`：失败、缺少预计检查、严格模式跳过或清理错误。
- 顶层 `cancelled`：收到取消，已有日志与结果保留。

SKIP 识别包括行首 `SKIP:` 和 unittest 的 skipped 汇总/逐项提示；并非通用测试输出解析。`--strict-skips` 只拒绝实际检测出的跳过，不代表运行了未安排的真实设备或在线测试。

## 新增和修复回归

先用最小夹具证明旧实现失败，再修改共享根因。断言用户结果、退出码、精确候选、状态/会话归属和生命周期；不能只断言函数名存在或照抄实现。覆盖错误/空输出、超时、重启、人工停止、并发编辑和相邻工具。测试自己的子进程必须在 finally/tearDown 清理，验证应早于夹具自然退出时间，避免把自然结束误当强杀成功。

较大的测试映射见 [CONTRIBUTING](../CONTRIBUTING.md)。典型选择：

| 能力 | 套件 |
|---|---|
| 队列与精确候选验收 | acceptance、leaf-runtime、leaves、burn-runtime、evidence-retention |
| 工具会话与派生数据 | zcode-session、dsh-session、session-hygiene、relocation |
| 时段、配额与人工会话 | window、zcode-window、watch-window、zcode-quota、interaction |
| 启动、续命和日常调度 | startup、night-loop、loop-daily、tool-watchers |
| Codex 主/子会话隔离与 429 续跑 | codex-watch：文件发现、目录回退、loop、主回合发送及子 Agent 完成隔离 |
| Provider 配置切换后恢复 | provider-config、provider-supervisor、provider-headless：有效配置、exact resume、实际进程、草稿/归属/预算与任务连续性 |
| 燃料、领域包和晨报 | prompts、fuel-extension、product-fuel |
| 状态性能与日志 | status、quality-trend、log-location |
| 部署与桌面 | watchdog-deploy、watchdog-install、install-deps、desktop、swift-gate |
| Harness 自身与文档 | harness-runner、harness、isolate-cleanup、docs |

共享队列、gate、review、迁移和登记在 `ck-common.sh` 维护；改共享规则必须核对 TUI/headless 两条实现。ZCode/dsh 协议均用假 CLI 回归，不能以本地协议测试承诺未来版本兼容。

## 提交门禁与 CI

每个克隆启用一次：

```bash
git config core.hooksPath .githooks
```

pre-commit 执行 `tests/run-all --profile full`，失败拦截提交；测试不能自动证明每个修复都有对应回归，仍需代码审查。GitHub Actions 在 macOS 上安装 tmux、选择 Python 3.11 并运行同一入口，始终尝试上传 JSON 与完整隔离产物，保留 7 天。CI 配置文件为 `.github/workflows/harness.yml`；没有推送运行结果时只能说已配置。

失败时先查看报告的失败检查和 full log，再按 [排障手册](../docs/triage-playbook.md) 回到相同用户视图验证。真实模型、原生 TTY、已安装桌面二进制和 launchd 冒烟按 [发布指南](../docs/RELEASE.md) 独立记录。
