# Provider 配置切换后的自动恢复

上游额度耗尽、认证失效或连接失败时，Keeper 可以等待工具的有效 provider 配置变更，然后在原项目续接确切原会话。用户更新自己工具的配置即可；Keeper 不代选供应商，不复制会话创建新上下文，也不修改 provider 配置。

## 恢复过程

1. 工具报告新的 provider 错误，watcher 或 headless adapter 保存可验证的会话身份。
2. Keeper 比较有效连接配置指纹，等待 provider、端点、凭证或模型选择发生变化。信任目录、通知和重试参数等无关变更不会触发切换。
3. 只有配置可解析、原会话属于当前物理项目、恢复预算未耗尽时，才在原任务位置恢复。TUI 保留原 pane、外层 owner 与 loop；headless 保留原 session 文件、任务和验收阶段。
4. 原生恢复命令加载新配置并发送一次 continue；headless 使用同一任务。后续成功回合由原协议确认，发起恢复本身不冒充任务成功。

没有有效新配置时，不会对已耗尽额度无限发送 continue。未知会话、损坏配置和无法保留的启动参数会保留现场。普通退出仍然退出，不自动重开。

## 各工具行为

| 工具 | 配置与续接 |
|---|---|
| Codex | 读取 `CODEX_HOME/config.toml`（默认 `~/.codex`）、项目配置、profile 与显式覆盖，包含实际使用的凭证；排除子 Agent，按主会话 ID resume，用独立进程绕开旧后台配置 |
| Claude Code | 读取用户及项目 `.claude/settings*.json`、支持的显式 settings 和环境；加载最新连接环境，按 JSONL 的 sessionId resume，排除 sidechain |
| Pi | 读取 `PI_CODING_AGENT_DIR` / `PI_DIR` / `~/.pi/agent` 的 settings、models 和 auth；凭证按 CLI、auth、models、内置 provider 环境的顺序判定，解析生效凭证及请求头中的环境引用。按原 JSONL 路径恢复，并显式指定当前 provider/model |
| OpenCode | 读取 XDG 配置、项目配置及支持的环境覆盖，核验 SQLite 中的项目归属，按原 session ID 独立启动 |
| ZCode | 读取实际 provider 配置，只有默认模型选择可判定时自动恢复；故障后通过原生 `/model` 切换同一 session，并核验持久选择后才发送原任务。若配置在 turn 前已更新，也会核对失败会话的旧模型选择与最新默认的差异；健康会话不因此自动换模型 |
| dsh | 读取 settings、bundle、profile、`DSH_HOME/cordis.patch.yml` 和按参数顺序排列的 `--patch`，核对凭证引用及 `agent-default-model`；新进程加载最新环境，用原 session 文件续接 |

CLI 的确切续接和独立服务参数会先做本机能力核验。未知参数覆盖、模糊的多 provider 默认、凭证 shell 命令或坏配置可能无法安全核验；此时原任务和上下文保留，等待人工处理。文件变化不等于新 provider 已在线，实际可用性由恢复后的回合证明。

Pi 的 `$NAME` / `${NAME}` 引用、插值和 `$$` / `$!` 转义遵循原生解析；裸变量名仍为
字面量。被高优先级凭证遮蔽的 models 密钥变化不触发恢复。dsh 后层补丁替换完整 config，
最终禁用或动态 provider 行、无法核对的自定义凭据库会关闭自动恢复；正常原生启动仍保留。

## 控制与保护

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `CODEXC_PROVIDER_RECOVERY` | `1` | `0` 禁用配置切换恢复，保留原错误处理 |
| `CODEXC_PROVIDER_MAX_RESTARTS` | `2` | 连续失败期间允许尝试的新配置数量，最多 10 |
| `CODEXC_PROVIDER_POLL` | `2` | 检查配置的间隔秒数 |

TUI supervisor 只终止自己启动的 CLI 进程组，不根据项目 PID 文件杀进程。事件绑定 tool、pane、owner、物理项目和本次启动代际；旧错误与子 Agent 不触发新的恢复。用户未发送草稿、正在执行的回合和人工 halt 优先。headless 还遵守交互让位与运行窗口；等待期间不请求模型。

TUI loop 将有归属、心跳新鲜的 provider 等待视为暂停，保留当前验收阶段，避免用户更新配置前先被普通错误宽限期、stall 或回合总时限挂起。`CODEXC_TURN_TIMEOUT` 默认 3600 秒；只扣除连续两次轮询均核验成功的等待区间，恢复后沿用剩余执行时间，不重新赠予整轮预算。新投喂单独计时。supervisor 消失、心跳陈旧、会话归属改变或工具实际在忙时，不再抵扣时间，正常超时保护继续生效；人工 halt、交互占用和运行窗口仍优先。headless 的瞬时故障仍保留原先有界退避，新配置可提前打断等待；认证和额度故障在配置不变时不自动请求。

同一失败配置不会来回尝试。TUI 的一次成功恢复回合重置连续恢复预算；headless 的预算覆盖当前 turn。显式 provider 覆盖仍然优先，更新未使用的默认 provider 不会把用户钉住的设置替换掉。

新写入的 headless quota 标记可绑定失败 provider 的指纹；只有相应有效配置发生变化，才解除该 provider 的等待。旧的无绑定标记保持原恢复规则，人工 halt 不被清除。

## 升级与验证

新会话启动时会装配 supervisor。已经运行的旧 Bash watcher 和旧 CLI 不会因源码文件变化自动升级；首次采用此能力仍需启动一次新运行时，后续 provider 切换由它处理。只 detach 再 attach 会复用原运行时。

测试使用私有 HOME、tmux 和假 CLI，覆盖配置指纹、主/子会话、实际进程替换、无变化不重试、草稿、损坏配置、归属、次数上限、信号清理及 headless 任务连续性。离线通过不代表真实凭证、当前上游和已安装 GUI 已通过验收；完整结果见 [执行计划](plans/2026-11-16-provider-recovery.md)。

等待与回合时限的补充回归及验证记录见 [2026-11-19 计划](plans/2026-11-19-provider-wait-timeout.md)。
