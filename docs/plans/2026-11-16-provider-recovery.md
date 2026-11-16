# Provider 配置切换后自动恢复

状态：源码修复与离线验收完成；真实 provider/GUI 仍待部署环境验证。日期：2026-11-16。

## 用户结果

已启动的工具仍使用旧 provider；额度耗尽、认证或连接失败后，即便用户已更新配置，也必须退出再恢复会话。目标是在同一终端或 headless runner 内识别新有效配置，续接确切原会话与当前任务，不要求用户退出重进。

## 设计与边界

- 六工具覆盖：Codex、Claude Code、Pi、OpenCode 的 TUI，以及 ZCode、dsh 的 headless 车道。
- 共享适配层比较有效连接配置指纹，避免信任/重试等无关字段触发恢复；不写出密钥或配置原文。
- TUI supervisor 持有自己启动的 CLI，watcher 只发布本代际新鲜的 provider 故障；同时核验 pane、owner、物理 cwd、原会话归属和空闲状态，再有界停止自己的进程并 exact resume。主终端和 loop 保持运行。
- headless 共享 turn 在 provider 故障后等待新配置，保留 session 文件、任务及验收阶段；人工 halt、交互占用和运行窗口优先。
- 配置缺失/损坏、不支持的参数覆盖、归属不明、没有 provider 变化、重复失败配置均不盲重启，不新建上下文兜底。自然退出不当成 provider 故障。
- 既有瞬时错误续跑保留；额度类错误仅在配置切换后允许恢复，不通过无限 continue 绕过额度限制。

## 步骤与验收

- [x] 核对 cwd、origin、Git 状态，保留已有主/子 Agent 日志隔离修复。
- [x] 核对六工具实际配置路径、环境优先级、exact resume 参数和会话归属。
- [x] 增加配置指纹、TUI 生命周期、headless 等待/切换回归，确认旧实现失败。
- [x] 实现共享适配、TUI supervisor 与 headless 恢复，补安装和运维说明。
- [x] 目标回归、quick、full 验收，记录 SKIP 与未执行的真实服务边界。

## 证据

此前主/子 Agent 隔离的 52 项 full 结果仅证明当时源码，不能代替本次 provider 恢复变更的验证。开发和测试不操作 Obsidian 的真实会话，不调用真实模型，不改用户 provider 配置。

修复前反证使用 `HEAD:codexc` 的物理临时脚本与相邻 helper，在私有 tmux 中确认原假 CLI 启动、旧 watcher 实际消费新 `usage limit exhausted`，随后配置更新，但 12 秒内没有恢复进程，按预期失败。证据 `/private/tmp/ck-provider-supervisor-before-20261116.txt`。另外，同一 cwd 子 Agent 抢日志的旧失败证据见 [前一计划](2026-11-16-codex-subagent-watcher.md)。

定向结果：provider-config 26 项、provider-supervisor 28 项、provider-headless 28 项通过。supervisor 包括四种 TUI 的真实 watcher→配置变化→同 pane/owner exact resume→完成事件全链，以及 Pi 原生目录、OpenCode XDG 目录、loop 等待超过 stall 的场景；CLI 都是假实现，无模型调用。OpenCode 的原生本地 API 切模型和 ZCode 的 `/model` 在同会话持久选择验证后才允许继续。headless 包括真实 wrapper→假 CLI→session 协议、gate/review 修复阶段只验收一次、配置早于本轮变更、健康会话与关闭恢复不改模型、原瞬时退避、unknown 任务错误不当 provider 故障。

quick 命令 `tests/run-all --profile quick --keep-artifacts --report /private/tmp/ck-provider-quick-20261116.json` 退出 0，5/5 检查通过，有 Swift trivial 探针跳过。桌面 provider 等待状态另外完成真实 Swift 审计编译及运行，未安装桌面应用。最终 full 执行前已将 16 个源码/测试文件的 SHA-256 保存到 `/private/tmp/ck-provider-source-20261116.json`，完整验收后再次核对。

中间失败未删日志：首次 tool-watchers 因独立 source 缺 helper 失败，已将 helper 放入共享脚本；supervisor 的进程清理在 Darwin 只剩僵尸组时出现 EPERM，已以实际存活成员核验并补进程回归；OpenCode API fixture 还未支持 help 时的失败报告保留在 `/private/tmp/ck-provider-final-focused-20261116.json`，随后协议与断言补齐。都未通过删除行为断言换绿灯。

最终 full 命令 `tests/run-all --profile full --keep-artifacts --report /private/tmp/ck-provider-full-final-20261116.json` 退出 0，55/55 检查完整记录，无失败，报告状态 `passed_with_skips`；产物 `/private/tmp/ck-tests-u302zc9p`。包含 42 个 audit、四种 TUI 集成、headless 集成、故障注入、conformance、docs 和 keys。Swift trivial 探针因本机工具链编译失败/超时跳过；watchdog-deploy 两项因隔离 HOME 未部署运行副本/plist 跳过。桌面 provider 等待状态的定向 Swift 审计实际通过。keys 的真实回合仍是离线报告，不代表真实 provider 可用。

最终源码/测试哈希与 full 启动前保存的 `/private/tmp/ck-provider-source-20261116.json` 一致；full 之后再次执行 Python 3.11 AST、Bash `-n`、`git diff --check` 和 docs-check 均通过。未启动真实 provider、未修改全局配置、未操作 Obsidian 会话、未提交或推送。

当前本机配置只读检查：Codex、Claude、Pi、OpenCode 的标准配置可判定；ZCode 多 provider 未设置明确默认选择，dsh 的 profile YAML 存在重复 key，均按无法安全核验处理。未修改这两份外部配置，不能声称这两套当前真实配置已恢复成功。源码覆盖的是有明确默认且可解析的配置合同。
