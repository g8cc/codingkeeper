# Codex 子 Agent 日志隔离

状态：源码修复与离线验收完成；真实会话切换待用户选择。日期：2026-11-16。

## 用户结果与现场

Obsidian 的主 Codex 回合遇到 `exceeded retry limit, last status: 429 Too Many Requests` 后没有自动输入 continue。已直接读取用户 tmux pane，确认主回合 idle、错误仍可见；owner 与 watcher 均存活。

主会话 rollout 在 10:01:30（UTC+8）记录 task_complete.error；三个子 Agent 使用相同 cwd，随后分别完成。项目 status 却显示最后一个子 Agent 的结论，watch 日志没有该主回合的错误或自动发送记录。watcher 与 loop 的日志发现均按项目 cwd、mtime 选择文件，没有排除 session_meta.source.subagent。

## 范围与约束

修复 Codex 日志发现的主/子会话隔离，覆盖 watcher 的进程文件与目录回退路径及 loop 相同问题；保留历史事件不重放、配额禁重试、次数上限和工具忙闲检查。保留当前真实会话，不更改其源码或历史，不将人工发送 continue 冒充 watcher 自动恢复。

## 步骤

- [x] 核对仓库和用户视图，读取主/子会话元数据、事件及 watcher 状态。
- [x] 用隔离夹具复现三条发现路径被较新子 Agent 抢占，以及主回合 429 未自动继续。
- [x] 在共享 helper 统一筛选项目归属与主会话，补日志可观测性。
- [x] 对应回归、相邻协议和 full 门禁通过，更新文档和验证记录。
- [x] 返回用户视图核对；明确源码修复与现有 watcher 切换/旧错误重放的边界。

## 验证记录

四个发现回归在原实现失败，修复后通过。目标入口 `tests/run-all --suite codex-watch --suite startup --suite loop-daily --suite tool-watchers --keep-artifacts --report /private/tmp/ck-codex-watch-focused-20261116.json` 退出 0：codex-watch 9 项、startup 22 项、loop-daily 18 项、tool-watchers 3 项均通过。使用假 tmux/进程及本地 JSONL，无真实模型请求。

原 watcher 的动态复现失败于“main 429 was not continued”；新实现验证文本与 Enter 分开发送、单个错误仅发送一次，同时不消费子 Agent 完成、不重放历史错误、不重试 usage limit，达到次数上限后退出。夹具在写入历史事件后重新将子会话 mtime 设为较新，避免错误地测成“主会话本来就是最新”。

运行中的 codexc / codexc-loop 通过写新文件再原子替换更新，旧 Bash 保留原 inode。新发现逻辑集中在已安装的 ck-watcher.py，无需新增安装入口。全量验收前后，源码及回归文件的 SHA-256 一致。

全量命令 `tests/run-all --profile full --keep-artifacts --report /private/tmp/ck-codex-watch-full-20261116.json` 退出 0，52/52 检查均已记录，无失败，报告状态为 `passed_with_skips`。包含 39 个 audit、四种 TUI 集成、headless 集成、故障注入、40 项 conformance、文档和离线环境清单；新增 codex-watch 9 项通过。完整日志保留在 `/private/tmp/ck-tests-sob4uqzq`。

未验证边界：syntax 的 Swift trivial 探针编译失败/超时，Swift 编译层跳过；watchdog-deploy 的两项已安装副本/plist 比对因隔离 HOME 未部署而跳过。keys 仅做离线库存，不调用真实模型。桌面源码审计通过不代表已安装桌面或真实 GUI、launchd 已验收。文档链接检查、Python 3.11 语法解析与 `git diff --check` 通过。

已返回同一个 Obsidian pane 只读复核：主回合仍显示 429 后等待输入，status 仍显示子 Agent 的完成结论；未向真实会话发送按键或发起模型请求，也未更换运行中的 watcher。源码修复仅对新 watcher 生效；更换 watcher 默认从 EOF 开始，不重放当前历史错误。现有会话的 watcher 切换及是否发送一次 continue 等待用户选择，不计为真实自动恢复验收。
