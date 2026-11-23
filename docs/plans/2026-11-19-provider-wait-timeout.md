# Provider 等待与回合超时

状态：源码修复与离线验收已完成；实机证据见发布前实机验收计划。日期：2026-11-19。

## 用户结果与验收条件

TUI loop 已将 provider 等待当成无进展计时的暂停，但回合总超时在该分支前检查。
等待用户更新配置超过 `CODEXC_TURN_TIMEOUT` 后会写入 halt，原会话无法按承诺继续。
目标是只扣除经过归属和心跳核验的等待时长，恢复后沿用剩余执行预算。
人工 halt、工作时段、交互占用以及失效 supervisor 的保护继续生效。

## 范围与约束

- 基线 `88b20c5`，物理 cwd 与 origin 已核对，开始时工作区干净。
- 修改 `codexc-loop`、对应离线回归与 provider 指南；核对四种 TUI 及 headless 相邻场景。
- 使用临时 HOME、假 CLI 和私有 tmux，不修改真实会话、配置或已安装服务。
- 运行中的 Bash 禁止原地修改；不提交、推送或发布。

## 步骤

- [x] 阅读超时、provider 等待、归属校验和现有回归。
- [x] 增加实际 driver 的确定性时间线回归，确认基线失败。
- [x] 修复等待计时，并核对恢复、失效、人工暂停和新回合。
- [x] 扩展私有 tmux 的原会话恢复验证，更新指南。
- [x] 定向、quick 和 full 验收，记录跳过与发布边界。

## 验证记录

前一版本 full 已完成 55/55 检查，零失败，Swift 语法探针及两个部署环境比较跳过。
该报告只证明基线，不用于本次代码变更的验收。

旧实现的三项时间线回归均失败：首次长等待就生成 halt，无法恢复原任务。失败日志保留在
`/private/tmp/ck-provider-wait-before-20261119.log`。修改后首轮五项定向测试通过，覆盖
重复暂停不重置剩余预算、原任务验收一次、人工 halt、失效心跳/归属/繁忙状态以及已耗尽预算。
额外增加下一任务独立计时与私有 tmux 超过总时限后续接的验证。

定向命令 `tests/run-all --suite loop-daily --suite provider-supervisor --suite provider-headless
--keep-artifacts --report /private/tmp/ck-provider-wait-focused-20261119.json` 退出 0，无 SKIP。
loop-daily 24 项、provider-supervisor 28 项、provider-headless 28 项全部通过；私有 tmux
以 10 秒回合总时限等待 12 秒后更新配置，原 pane/owner/session 和队列任务继续保留。
实际源码与测试的 115 份非 Markdown 文件指纹已保存到
`/private/tmp/ck-provider-wait-source-20261119.json`，供完整门禁后核对。

quick 报告 `/private/tmp/ck-provider-wait-quick-20261119.json`：5/5 检查通过、退出 0、无
SKIP，包含真实 Swift 类型检查。full 报告 `/private/tmp/ck-provider-wait-full-20261119.json`：
55/55 检查完整执行、退出 0、零失败，状态 `passed_with_skips`。四种 TUI 集成、headless
集成、故障注入、桌面编译及行为审计均通过。唯一跳过来源是 watchdog-deploy 的两项
已安装运行副本/plist 比较，隔离 HOME 中没有这些部署文件。keys 只提供离线库存报告。

完整产物保留在 `/private/tmp/ck-tests-u81mdhrb`；临时进程清理完成且无清理错误。
门禁结束后核对 115 份源码与测试指纹，全部与执行前一致。报告中的 revision 为基线
`88b20c5`，实际受测对象包含本次未提交补丁；未提交、推送或安装到真实服务。

## 发布边界

本次修复的定向、quick 和 full 验收已完成。完整报告保留两项隔离安装环境 SKIP；
这两项已在真实已安装文件上独立补验通过，记录与其余实机结果见
[发布前实机验收](2026-11-19-release-smoke.md)。离线回归不证明真实 provider 在线，
文件补验不证明所有运行实例已更新。正式发布仍需完成该计划中的安装与实机边界、
版本整理及发布决策；不能声称所有 bug 已解决。
