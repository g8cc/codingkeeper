# 工具矩阵与凭证（Tools & Credentials）

下表表示全部六种工具的离线协议与管控回归范围。2026-11-20 的
[发布收敛](plans/2026-11-20-release-convergence.md) 已通过 Codex/OpenCode 的两轮真实
响应和原会话续接；ZCode 同日早先通过。随后按用户授权
[从 KeyDrop 恢复配置](plans/2026-11-20-keydrop-provider-recovery.md)，Claude、Pi、dsh
也通过两轮真实响应、原会话续接及 Keeper 读取验证。
此前的 HTTP401、504、429 等失败仍保留在各次记录中。结果对应各次验收时的配置，
不表示服务持续健康，也不覆盖真实 TUI 输入、GUI 点击或在线 provider 故障切换。

六工具的有效 provider 配置变更恢复使用共享适配层；四种 TUI 保留原 pane 并 exact resume，ZCode/dsh 在共享 headless turn 保留任务和 session。未知或模糊配置保留现场，具体路径、控制参数与真实服务边界见 [provider 自动恢复](PROVIDER-RECOVERY.md)。新增覆盖为 provider-config、provider-supervisor、provider-headless。

| 工具 | 通道与入口 | 本轮离线覆盖 | 主要套件 |
|---|---|---|---|
| Codex | TUI：`codexc` / `ck codex` | 启动、当前轮完成/中止、重试、队列/gate/review、清理 | startup、loop-daily、四工具 integration、faultinjection |
| Claude Code | TUI：`ck claude` | 启动、sidechain 隔离、tool_use 非完成、错误续命及配额、验收 | startup、loop-daily、tool-watchers、integration |
| Pi | TUI：`ck pi` | 启动、toolUse 非完成、错误续命及配额、验收 | startup、loop-daily、tool-watchers、integration |
| OpenCode | TUI：`ck opencode` | SQLite 会话/完成读取、特殊路径、稀疏序号、原地流更新、错误续命、验收 | startup、loop-daily、tool-watchers、integration |
| ZCode | headless：`ck zcode run` / `zcodec` | sess_ ID、首次失败/超时续接、最终结果隔离、quota/auth、窗口/复燃、独立审查 | zcode-session、zcode-quota、zcode-window、watch-window、review-leaf |
| dsh | headless：`ck dsh run` / `dshc` | JSON 会话归属、原子保存/续接、超时前保存、final 隔离、失败分类、退出码及损坏文件 | dsh-session、edges、共享 headless integration |

dsh 协议已按本机安装的 dsh-headless 源码及 README 核对：`--json` 首事件为 session（sessionId/cwd），末事件为 final（text），turn_end.reason 与进程退出码共同表示成功。旧版本或自定义 profile 缺少该协议时适配器明确报错。ZCode 同样需要已核对的 stream-json 协议；离线假 CLI 无法证明未来版本保持兼容。

## 钥匙自检

```sh
tests/keys.sh            # 各工具凭证健康报告
echo "Reply OK" | dsh --profile headless -     # dsh 钥匙快速自检
pi -p 'Reply OK'                               # pi 钥匙快速自检
```

## dsh 配置与密钥说明

本机 dsh 0.2.1-rc.5 使用 Cordis profile/patch 配置，`DSH_HOME` 默认是 `~/.dsh`。
配置按以下顺序叠加，后面的层优先：

1. profile 的 `dsh.profile.bundles` 列表中的 bundle patch，按列表顺序加载。
2. `$DSH_HOME/profiles/<profile>/cordis.patch.yml`，headless 对应 `<profile>=headless`。
3. `$DSH_HOME/cordis.patch.yml`，适用于所有 profile，并覆盖各 profile 的同名配置。
4. 命令行 `--patch <file>`，多个 overlay 按参数顺序叠加；应放在 `--json` 等应用参数之前。

启动器的 telemetry 开关在上述配置层之后应用。
`$DSH_HOME/settings.yaml` 是旧格式的一次性迁移输入：启动时先改名为
`settings.yaml.imported`，再把各 section 导入当前 profile；未能导入的 section
保留在该归档文件并记录警告。后续配置变更应写对应的 Cordis patch。

provider（例如 `keydrop-f6788e3a` / `keydrop-cparesid`）位于 `id: llm-pi-ai`
条目的 `config.providers` 字典，使用 `api`、`baseURL`、`models` 和 `apiKeyEnv`
等字段。默认路由由 `id: agent-default-model` 条目的 `config.provider` 与
`config.model` 成对选择，必须匹配已注册的 provider 和其模型 ID；只注册 provider
不会改变默认选择。headless 新建和续接会话均读取本次配置中的这一对值。

`apiKeyEnv` 填凭证引用名（如 `KEYDROP_API_KEY`，不带 `$`），设置该字段本身不会
注入密钥。默认 headless profile 禁用 credentials 服务，引用值按“继承的进程环境
→ 调用 cwd 的 `.env` → `$DSH_HOME/.env`”解析；KeyDrop 或调用方须实际提供相应值。
若 profile/patch 显式启用 credentials 服务，`$DSH_HOME/.credentials.yaml` 中的
引用值优先于上述环境来源。凭证是否有效仍需另行在线验证。
认证失败形态: `dsh --profile headless -` 输出 `AUTH: Authentication Fails`。

## zcode 说明

- CLI 本体: 桌面应用自带 `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`，
  用 Node >= 24 运行；`ZCODE_CJS` 可覆盖。
- 会话库: `~/.zcode/cli/db/db.sqlite`（会话按 directory 字段绑定项目，只读查询）。
- 配额生效提示按 `CODEXC_ACTIVE_TZ` 解析，只接受未来七天内的时间，支持跨年；非法时区保留 quota 分类但不猜测恢复 epoch。
- 官方自动化文档: apps/zcode-cli/docs/usage（zai-org/ZCode 仓库）。

## 自动确认覆盖

Codex、Claude Code、OpenCode 的交互包装入口默认 `CODEXC_AUTO_YES=1`。用户显式传入的审批参数优先。

| 工具 | 默认确认方式 | 限制 |
|---|---|---|
| Codex | `--dangerously-bypass-approvals-and-sandbox`，预设目录信任 | `CODEXC_AUTO_YES=2` 改用 `--ask-for-approval never --sandbox workspace-write`；`0` 关闭 |
| Claude Code | `--dangerously-skip-permissions`，预设目录信任和 bypass 确认 | `2` 使用 `--permission-mode acceptEdits`，仍可能要求其他操作确认；`0` 关闭 |
| OpenCode | `--auto` | 只有 `1` 添加该参数；兼容性取决于安装的 CLI 版本 |
| ZCode 自动 worker | `--mode yolo` | 使用 `ZCODE_MODE` 覆盖，与 `CODEXC_AUTO_YES` 独立；交互透传不自动添加 |
| Pi / dsh | 沿用工具及 profile 配置 | 外层没有额外的通用确认弹窗适配 |

这些机制使用 CLI 原生权限模式。项目尚无识别任意 GUI 按钮并点击 Yes 的通用功能，登录、验证码和新交互弹窗也不属于自动 continue。
