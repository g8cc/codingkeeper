# 发布验收收敛

状态：本轮代码修复、本机部署与完整验收已完成；外部供应商及当前 GUI 点击验收仍有边界，未公开发布。日期：2026-11-20。

## 用户结果与范围

按用户“开始收敛，继续完成”的要求，在已完成的
[并行源码审计](2026-11-20-parallel-bug-audit.md)基础上，完成本机安装副本、
运行服务与桌面验收，核对真实供应商的剩余限制。源码基线为
`38aba47d68f173b4f412bc28d19ed9dc114b297e` 加现有未提交补丁。
不重复扩展审计范围；不提交、推送、变更版本号或公开发布。

## 步骤与约束

1. 复核 116 份受测源码指纹，复用本日 full 的 56/56 检查结果；行为变化须重跑 full。
2. 建立私有回滚与证据目录，原子更新三个过期辅助副本并核对完整安装清单。
3. 核对看门狗实际加载 inode、共享进程组和任务阶段，再选择安全的升级方式。
   不以文件一致代替进程已升级，不强杀共享组，不改队列、会话、人工 halt 或凭证。
4. 补跑被隔离 HOME 跳过的两个只读安装检查与独立 Swift 探针；保持原报告的 SKIP。
5. 使用 cua-driver 核验已安装桌面的真实显示与可安全执行的后台交互。
6. 复核已有在线验收证据及供应商配置是否变化；必要时做有界、隔离的最小复验，
   不绕过认证或配额，不无限重试，不把离线通过写成在线健康。
7. 归档安装、运行、GUI 与剩余限制，更新本计划并完成 docs 与 diff 校验。

## 验证基线

- full：`/private/tmp/ck-fanout-full-cleanup-verified-20261120.json`，
  exit 0，56/56 检查，零失败，含 Swift 探针和两个真实安装检查的 SKIP。
- 源码指纹：`/private/tmp/ck-fanout-source-cleanup-20261120.json`。
- 持久证据：`~/.codingkeeper/verification/2026-11-20-parallel-bug-audit/`。
- 开始时三个过期副本：`ck-common.sh`、`ck-leaf.py`、`ck-zcode-session.py`。
- 看门狗 PID 37189 仍加载旧 inode，与四个现有 headless runner 共用 PGID；
  全量安装脚本会 bootout 服务，因此不能直接执行。

## 实机发现与修复

实机复验发现 OpenCode 2.0.32 在 assistant 后追加 idle，watcher 因只读最后一行
漏掉完成和 provider 错误；相邻 loop 只筛 assistant 又会跨新用户回合重放旧结果。
新增回归已分别证明旧实现失败，修复两处当前回合选择后，目标测试与重新执行的
full 均通过。只采纳紧邻且成功/失败一致的 idle + assistant，保留 assistant
的事件身份；拒绝跨 user/tool、未完成 assistant、取消和不一致 idle。
独立只读复核另通过 15 个边界用例，未发现新增可复现问题。

本机 22/22 runtime 已对齐，四个空闲 runner 已迁入独立进程组；watchdog 已重载
并确认当前 inode 和连续推进的心跳。185 项受保护状态未变。两个真实安装检查和 Swift
typecheck 通过。桌面当前显示待处理 17，等于 13 暂停加 4 等待；后台点击未生效，
原已验证桌面源码与二进制哈希仍一致，不把本轮点击记作通过。

在线复验：Codex 原会话双回合通过；Claude 原生 api_error_status=504；dsh
原生 AUTH/status=401。OpenCode 配置指纹变化后双回合真实响应和原会话回忆均成功，
watcher 漏读触发了上述修复。修复后同一真实私有 SQLite 的 watcher 和 loop 均读回
`clean` 与准确最终文本，之前的 429 原生记录也正确读回 `error`。Pi 配置指纹未变，
保留历史401，不重复无效请求。ZCode 复用本日早先真实双回合成功记录，明确为历史证据。
本轮共六次提交，失败后均不提交第二回合；所有请求独立于生产会话。

## 最终验证与部署结果

- 最终 full：2026-11-20 20:00:02–20:30:48（Asia/Singapore），exit 0，
  **56/56 检查**，54 pass、1 pass_with_skips、1 inventory report；零失败、
  零漏跑，清理完成且无清理错误。43 个审计、四工具并行 TUI 集成、headless 集成、
  故障注入均通过。报告 `/private/tmp/ck-release-convergence-full-20261120.json`。
- 唯一 SKIP 来自 watchdog-deploy 在私有 HOME 找不到真实安装的两个检查；本轮在
  真实 HOME 逐个只读执行并通过，保留 full 原始 SKIP。Swift 探针、typecheck 和桌面套件
  在本次 full 均实际通过，不再有 Swift 跳过。
- 修复前 watcher 两项失败、loop 三个子场景失败的日志均保留；修复后 watcher 六项、
  loop 四项目标测试通过。原在线 harness 丢弃 `session_message.type` 的误报保留并另附更正，
  不覆盖失败证据或重置在线预算。
- 新 full 的 116 份源码指纹与完成后代码一致；通过后原子同步 `ck-watch-tools.sh`，
  22/22 安装 runtime 与源码匹配。CLI 的源码链接使用当前版本。最后修复不涉及 watchdog
  主程序或已迁移 headless runner，因此没有再次重启它们。
- 桌面二进制与之前通过真实展开/收起的候选哈希一致；本轮真实菜单和状态计数吻合。
  当前后台点击没有展开，不将工具“已投递”写作交互成功；没有请求前台接管。
- 本轮私有 CLI 均已退出，凭证副本已删除，拥有的在线产物未检出本轮所核对的凭证值；
  OpenCode 私有会话未写入生产库，dsh 原生会话隔离核对通过。本轮启动的 CUA daemon
  在无剩余会话后关闭，保留用户原有桌面进程。

持久证据和回滚程序副本：
`~/.codingkeeper/deployments/2026-11-20-release-convergence/`。
目录中 `summary.json`、`final-full-report.json`、56 份完整日志、
`online-summary.json`、安装前后清单、进程迁移、GUI 裁剪和回归前后日志可复核。
私有在线原始证据另在 `/private/tmp/ck-convergence-online-20261120`。

## 发布边界

后续进展：用户授权的 [KeyDrop 配置恢复](2026-11-20-keydrop-provider-recovery.md)
已补齐 Claude、Pi、dsh 的真实响应与续接验证。以下保留本轮收敛结束时的历史边界，
不能据此认为更换配置后仍是相同认证或服务错误。

本轮可控修复与部署已收敛，不继续扩展无证据的改动。Claude 仍为 HTTP504 overloaded，
dsh 仍为 AUTH/401；Pi 保留配置指纹未变的历史401。需相应服务恢复或提供有效凭证后
完成这些工具的真实响应与续接验收；当前不能声明六工具全部在线健康。
本轮未验证真实 TUI 输入、provider 在线故障切换或当前桌面前台点击。
未提交、推送、变更 VERSION 或公开发布；离线 full 与本机安装成功不构成零缺陷保证。
