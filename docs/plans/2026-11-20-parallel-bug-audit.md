# 并行源码审计与回归修复

状态：本轮源码审计与修复完成，完整离线验收通过（含明确 SKIP）；未发布。日期：2026-11-20。

## 用户结果与范围

在上一轮发布复核通过的工作区上继续审计，修复有复现证据的控制器缺陷。
保留既有修改，以隔离回归验证真实边界；源码验收不代替在线供应商、已安装服务
和桌面 GUI 的发布验收。基线为 `38aba47d68f173b4f412bc28d19ed9dc114b297e`
及上一轮未提交补丁，参见 [发布复核记录](2026-11-20-post-review-gate-boundaries.md)。

## 分工与步骤

1. 核对 cwd、origin、工作区和上轮源码指纹，阅读贡献、排障与状态契约。
2. 六个独立分支分别审计 runner 状态机、看门狗安装生命周期、会话适配器、
   provider 与 watcher、CLI 与桌面用户状态、测试 harness 与独立审查。
3. 主线程审计共享锁、队列、候选快照及验收事务，整合各分支最小修复。
4. 每个行为缺陷先增加失败回归，再修根因、检查相邻分支并跑目标套件。
5. 合并稳定后统一执行 full，记录检查数量、失败、SKIP、源码指纹和证据位置。

实际改动集中于 `ck-leaf.py`、`burn-watch.sh`、`ck-zcode-session.py`、`ck-common.sh`、`codexc-loop`。
主线程另核对 dsh 事件与会话归属、provider supervisor 信号与等待流程、interaction
占用记录、桌面状态读取、harness 检查清单和 isolator 清理路径；这些核查未追加
已确认的行为修复，其回归范围由最终 full 的对应套件记录。此范围不表示穷尽
所有源码路径或对真实服务作零缺陷保证。

## 硬约束

- 不写生产队列、会话、凭证和注册表；不调用真实模型或操作线上服务。
- shell 保持 Bash 3.2，运行脚本通过新文件加原子替换更新；状态遵守原子写入。
- 各分支写入范围互斥，保留当前未提交改动；不提交、不推送、不公开发布。
- 看门狗存在共享进程组风险，安装副本与运行实例版本分别核对，不强制重启。
- 全量测试由主线程统一运行，保留首次失败，不通过弱化断言获得通过。

## 验证与证据

上轮 115 份源码指纹在本轮修改前全部匹配。尝试启动的六个子 Agent 均被上游
并发限制或 HTTP 429 中断，均未产出完整交付；runner 分支留下三项失败回归，
主线程核对并接续修复，其余未发现文件产出。分支均已关闭，隔离测试仍并行执行。
不能将分支已分配记为已完成独立审查。

已确认并修复：

| 缺陷 | 旧实现失败 | 修复后的目标验证 |
|---|---|---|
| FIFO journal 阻塞验收 | 3 秒有界调用超时 | 立即拒绝，队列保持未勾选、pending 保留 |
| journal 符号链接误信外部回执 | recovery 返回成功并验收 | 拒绝跟随链接，外部文件不变、pending 保留 |
| 复燃 runner 与 watchdog 共用进程组 | 真实子进程 PGID 等于 watchdog | 独立 PGID，终止 watchdog 组后 runner 继续心跳 |
| 配额提示跨年时间漏算 | 12 月 31 日解析次年 1 月 1 日返回空 | 正确解析，仍拒绝过期、远期、非法日期 |
| 非法时区覆盖 quota 分类 | worker 输出 unknown | 保留 quota，无虚构时间、无 traceback |
| TUI gate 中断后丢失验收阶段 | 队列一直未验收，等待已经消费的完成事件 | 保留 gate 阶段，原 worker 回合只执行一次 |
| TUI review 中断误算失败与预算 | window-closed 被当作解析失败，任务停炉 | 125 单独处理，保留审查预算、人工 halt 和零缺陷计数 |
| gate/review 长暂停误触发 worker stall | 模拟窗口关闭十分钟后停炉 | 仅 work 阶段计无进展超时，恢复后完成验收 |
| gate 脚本退出 125/126 冒充控制器信号 | 125 无限重试且不消耗预算，126 被误判为证据错误 | 两通道共享 gate 将脚本退出码映射为普通失败，日志保留原码 |
| gate/review 暂停后完成证据丢失 | rollout 清空后无限等待，队列既不验收也不停炉 | 明确停炉并保留未完成任务，不重复投喂或伪造验收 |

修复前后日志为 `/private/tmp/ck-fanout-{leaf,watchdog,quota}-{before,after}.log`。
叶子事务另验证普通日志失败、半行恢复与部分写失败，五项通过；watchdog 两项
通过；quota 两项通过。首轮目标套件 5/5 通过：leaf-runtime 28、watch-window 45、
watchdog-deploy 19（含 2 项实装 SKIP）、zcode-quota 21、evidence-retention 7。
quick 5/5 通过，Swift 探针超时 SKIP 保留。

首轮 full 在发现 runner 分支未完成回归后通过其独占 isolator SIGTERM 取消，
退出 130、清理完成，报告 `/private/tmp/ck-fanout-full-20261120.json`；该报告不作
成功证据。主线程修正夹具的模拟 gate 避免虚假超时，确认三项旧实现失败后修复，
再增加长窗口暂停失败回归。四项最终均通过，日志为
`/private/tmp/ck-fanout-runners-{before,after,stall-before,final}.log`。
新增审计 `runner-boundaries` 已自动发现；runner-boundaries、loop-daily、window
三个套件通过、无 SKIP，报告 `/private/tmp/ck-fanout-runners-targeted-20261120.json`。
更新后的 quick 5/5 通过，仍保留 Swift 探针超时 SKIP，报告
`/private/tmp/ck-fanout-final-quick-20261120.json`。
第二轮 full 的源码指纹为 `/private/tmp/ck-fanout-source-final-20261120.json`。
该轮在只读复核发现退出码冲突及完成证据丢失后取消，退出 130、清理完成、已完成
9 项检查；报告 `/private/tmp/ck-fanout-full-verified-20261120.json` 虽然名称含
verified，实际状态为 cancelled，不能作为成功证据。其 Swift 语法与桌面检查已通过。

只读复核 Agent 此次成功指出两个相邻缺陷，主线程增加失败回归并修复；再次请求
复核遇到 HTTP 429，已关闭 Agent，不将最终补丁记为独立审查通过。修复前日志为
`/private/tmp/ck-fanout-review-before.log` 和
`/private/tmp/ck-fanout-review-siblings-before.log`；修复后 runner-boundaries
全部 8 项通过，日志 `/private/tmp/ck-fanout-review-after.log`。共享 gate 的
acceptance、window 相邻套件 2/2 通过、无 SKIP、清理完成，报告
`/private/tmp/ck-fanout-shared-gate-20261120.json`。重新冻结 116 份源码指纹至
`/private/tmp/ck-fanout-source-acceptance-20261120.json`；该轮 full 已完成 56/56 项，
其中 provider-supervisor 失败，退出 1，清理完成；报告
`/private/tmp/ck-fanout-full-final-20261120.json`，不是成功证据。Swift 语法探针超时
及两项真实安装检查保留 SKIP，桌面套件通过。

2026-11-20 18:36（Asia/Singapore）续接时，116 份指纹仍全部一致。失败位于
OpenCode 自定义数据目录测试的临时目录清理：私有 tmux 已关闭，但独立会话中的
watcher 状态写入尚未结束，删除目录时重新出现 `status.json`。新增两秒延迟写入
回归稳定证明旧清理提前返回；修复等待该私有项目记录的 watcher 进程组全部退出，
包括父进程先退出后仍运行的子进程。相同清理用于 startup 审计；不会向项目文件
中的 PID 发信号，也不忽略目录清理异常。增加组长退出、其他夹具并行存活的相邻
断言。修复前后证据为
`/private/tmp/ck-fanout-watcher-cleanup-{before,after}-20261120.log`。
provider-supervisor（31 项）、startup、harness 三套目标检查全部通过、无 SKIP，
清理完成，报告 `/private/tmp/ck-fanout-watcher-cleanup-targeted-20261120.json`。
116 份源码指纹重新冻结至 `/private/tmp/ck-fanout-source-cleanup-20261120.json`。
完整重验报告 `/private/tmp/ck-fanout-full-cleanup-verified-20261120.json`：
56/56 项全部执行，无缺项、重复项或失败，退出 0，`cleanup_complete=true`，
耗时约 33 分钟。结果为 53 项 pass、2 项 pass_with_skips、1 项 keys 库存报告，
整体 `passed_with_skips`。完成后 116 份源码指纹全部匹配，`git diff --check` 通过。

SKIP 为语法阶段 Swift 探针超时，以及 watchdog-deploy 的运行副本、安装 plist
两项检查（私有 HOME 中未部署）。desktop 套件随后实际编译通过并验证状态解析、
单实例争用、崩溃恢复与符号链接拒绝；这不替代已安装桌面 GUI 验收，也不抹掉
语法阶段的 SKIP。四种 TUI 并行集成、headless 集成、故障注入和所有 43 套审计
均执行完成。本轮没有真实模型调用。

本轮证据归档至
`~/.codingkeeper/verification/2026-11-20-parallel-bug-audit/`：保留修复前后失败
与成功日志、取消的两轮 full、清理竞态导致失败的一轮 full、最终成功报告、各阶段
日志、源码指纹和只读安装比对。历史失败报告未被覆盖为成功。
上一轮 55/55 完整检查是基线证据，不能代替本轮变化后的验收。

## 未解决项

本轮已确认缺陷均已修复并完成回归；不据此保证未审计路径零缺陷。
发布仍受上一轮在线工具失败、看门狗运行版本切换及制品整理约束。
只读安装比对显示看门狗文件已被既有自动刷新更新，而安装目录中的 `ck-common.sh`、
`ck-leaf.py` 与 `ck-zcode-session.py` 尚未同步；`~/.codex/bin` 两条 runner 是指向
源码的符号链接。本轮没有执行安装或服务重启，文件一致也不等于运行进程已加载。
续接后的只读比对记录 `/private/tmp/ck-fanout-installed-cleanup-20261120.json`；
以上安装差异仍存在。独立复核最后一次请求受 HTTP 429 限制，未将其记为通过。
