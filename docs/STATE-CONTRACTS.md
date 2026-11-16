# 状态与恢复契约

本页解释状态的写入者、读者和恢复边界。日常命令见 [运行手册](OPERATIONS.md)，整体流程见 [Harness](HARNESS.md)。本文不是自动清理脚本，不应据此批量删除真实会话。

## 写入原则

运行状态使用同目录临时文件加原子替换，避免读到半个 JSON 或半份队列。并发更新持有对应锁；原子替换本身不能防止两个写者互相覆盖。锁文件与所有权元数据用途不同，不能只见 `loop.pid` 就杀进程或删锁。Shell 保持 Bash 3.2 兼容。

手工操作前确认真实项目路径、runner/worker 是否仍在运行、当前未提交内容及备份位置。读者包括 CLI、watchdog、桌面面板和其他会话；只改一个存储层不代表用户界面已同步。

## 项目级状态

| 路径（相对 `.codingkeeper/`） | 写入者 / 读者 | 恢复边界 |
|---|---|---|
| `queue.md` | enqueue / 验收事务 / runner / 人工 | 只有 `## ready` 未勾选任务执行；验收和 enqueue 共用 `acceptance.lock`，保留缩进合同 |
| `gate.sh` | 初始化与项目维护者 / runner | 必须核对真实项目命令和测试发现范围；占位文件不能提供验收证据 |
| `runner.lock`、`runner.owner`、`loop.pid` | 共享 runner 锁 / runner 与观察端 | 核实 PID 身份、owner token 与锁占用；不要凭陈旧 PID 终止别的进程 |
| `status.json` | `ck-common.sh` / CLI、桌面、watchdog | 是观察快照，结合心跳、owner 与真实进程核对；不能单独证明任务验收 |
| `provider-<pane>.json`、`provider-supervisor-<pane>.json` | watcher / TUI supervisor | 原子事件绑定本次启动代际与 pane/owner/项目，只保存身份与配置指纹，不保存密钥或错误原文；旧代际不触发恢复，不能凭这些文件终止任意进程 |
| `loop.halt` | 人工或失败停炉 / runner、watchdog | 人工 halt 优先于自动复燃；先解释原因，再解除并按通道需要重启 |
| `quota-until` | headless 配额处理 / runner、watchdog | 持久化等待，不因服务重启清空；坏值须排障，不能视作已恢复额度 |
| `zcode-session-id`、`zcode-session-id.retry` | ZCode 适配器 / 下一轮 | 主 ID 优先，失败保留可续接 ID；归属无法核验时停止，确需重建先同时备份两份 |
| `dsh-session-id` | dsh 适配器 / 下一轮 | 保存本次结构化 session 事件的 ID；失败保留，不静默切新上下文 |
| `active-leaf.json` | leaf 生命周期 / 验收与证据保留 | 活动候选需要保留，不能当作过期缓存删除 |
| `acceptance.pending.json` | `ck-leaf.py` / 启动恢复 | 幂等补齐 queue/journal/receipt；与外部队列编辑冲突时停止人工核对 |
| `journal` | 验收事务 / status、morning、quality-trend | receipt 关联的验收记录；旧格式记录不能追溯成新式完整快照 |
| `evidence/<id>/`、`evidence/.blobs/` | leaf 快照与验证 / reviewer、维护者 | 每份证据含 `blobs/` 引用，共享内容在 `.blobs/`；保留基线、候选、输出与 accepted receipt，按源码权限保护 |
| `burn-cursor.json`、`fuel-packs.json`、`prompts/` | 燃料管理 / runner | 配置与轮转持久化；目录变化触发重扫，不能将等待燃料误当作正在调用模型 |

证据保留由实现核验引用再回收，不直接手动删除共享 blob。默认保留最近 50 份已验收历史；活动、pending 和未验收证据受到保护，journal 不随历史快照回收。单文件内容 blob 上限 16 MiB，快照内容 128 MiB，50,000 路径上限；超限与哈希策略见 [FUEL](FUEL.md)。

## 全局与外部存储

| 存储 | 说明 | 修改约束 |
|---|---|---|
| `~/.codingkeeper/projects` | 物理路径去重的项目登记，配有 `projects.lock` | 锁内原子更新；迁移后核对旧路径、符号链接与重复项 |
| `~/.codingkeeper/*log` | watch、daily 与其他运维时间线 | `CODEXC_LOG_DIR` 可覆盖；日志不是验收 receipt |
| ZCode CLI `db.sqlite` | 会话持久化 directory/path 与关联数据 | 迁移与清理前备份，校验真实 schema；改工作目录外层 `cd` 不能修复 resume cwd |
| ZCode 桌面 `tasks-index.sqlite` | 侧栏任务与 workspace/automation 引用 | 与 CLI 库同步迁移或清理，避免侧栏残留与重新落回旧目录 |
| dsh 历史、投影与 workspace 成员 | 真实数据位置由 dsh 配置决定 | 清理实体时同步派生缓存与成员关系，回到同一用户界面验收 |
| launchd 与已安装脚本/桌面二进制 | 运行中的部署版本 | 修改源码不等于部署；按 [发布流程](RELEASE.md) 核对真实路径与版本 |

具体数据库路径、备份与迁移顺序见 [本地迁移](LOCAL-RENAME-2026-11-14.md)，静态保护由 `session-hygiene`、动态归属由 `zcode-session` / `dsh-session` 等套件覆盖。不要把旧审计中的数据库路径或 schema 当作当前机器的唯一事实。

## 故障恢复顺序

1. 停止新的投喂，保存 status、halt、journal、pending、相关日志及 Git 状态；确认实际运行的是源码还是安装副本。
2. 根据 [排障手册](triage-playbook.md) 观察用户视图，再检查 owner、物理路径、时段、配额与会话归属。
3. 若存在 pending，先让正常恢复逻辑校验；冲突保留现场，不手工勾选队列来消除报错。
4. 会话迁移/清理同时核对真实存储与派生存储。源文件保留、界面无残留和新会话归属正确分别验收。
5. 重新运行对应回归与完整门禁；恢复真实服务属于部署操作，需要核对实际变更范围。

## 测试产物

`tests/isolate.py` 的 `/private/tmp/ck-tests-*` 属于一次测试的私有世界，不是产品状态。成功默认清理，失败或 `--keep-artifacts` 保留。`--report` 可以把结构化报告写到指定位置；日志路径只有在对应产物仍保留时可用。仓库内报告只能写到忽略的 `.codingkeeper/`，避免报告路径误覆盖源码。
