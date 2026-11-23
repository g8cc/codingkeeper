# Changelog

## 2026-11-23 提交前复审（未发布）

- CI 证据收集按文件类型过滤 socket、FIFO 与符号链接，修复离线测试通过后复制 tmux socket 导致整条 CI 失败；新增直接执行 workflow 收集命令的回归，并明确 56 项为汇总检查数。
- GitHub Actions 切换到 macOS 15；macOS 14 镜像退役导致任务在执行测试前被平台取消，新增已退役镜像标签回归保护。
- dsh 配置恢复读取全局补丁与重复 CLI overlay，按 bundle、profile、全局、CLI 顺序核对最终选择；无 profile patch 时仍读取 bundle，禁用或动态配置保留人工处理。
- Pi 按原生优先级读取生效凭证，解析密钥与请求头的环境引用和转义；不再漏读凭证轮换，也不会因被遮蔽密钥改变误触发恢复。
- TUI 在 gate/review 暂停恢复时重新解析当前完成证据，拒绝等长替换后的旧成功缓存；恢复时同步运行阶段和状态心跳。
- headless gate、review 与修复回合在时段/交互暂停后保留阶段、已用预算和审查计数；修复 worker 失败使用 turn 预算，gate 复检失败使用 gate 预算，避免重复投喂和越界验收。
- watchdog 的临时目录过滤覆盖告警入口；进程测试严格检查退出与清理，避免遗留独立 runner 或把 `ps` 失败当作进程已退出。
- 新增配置失败回归与 dsh 原会话恢复集成用例；复审、完整提交门禁及推送安排见 [执行计划](docs/plans/2026-11-23-final-review-push.md)。

## 2026-11-20 实机验收收敛（未发布）

- OpenCode watcher 识别紧随当前 assistant 的成功或失败 idle 记录，保留最终答复、provider 错误及原事件身份，避免完成和配置恢复被漏读。
- TUI loop 同步限定当前回合：新用户输入、未完成 assistant、取消或不一致的 idle 不得复用上一回合完成结果；补充真实 SQLite 形态的回归。
- 本机安装、进程组迁移、桌面与有界在线复验结果见 [收敛计划](docs/plans/2026-11-20-release-convergence.md)。

## 2026-11-20 并行源码审计修复（未发布）

- 验收日志读写都拒绝 FIFO、符号链接和其他非普通文件，避免无限阻塞或误信外部回执；失败保留待恢复事务和未完成队列。
- 看门狗复燃的 runner 使用独立会话与进程组，不继承锁描述符；回归验证看门狗进程组终止后 runner 仍继续心跳。
- ZCode 配额生效时间支持七天内的跨年日期；非法时区保留 quota 分类、不发布猜测的恢复时间。
- TUI gate 被时段或人工策略中断后保留 gate 阶段，不再等待已消费的完成事件；review 中断保留审查预算与零缺陷计数，不误报解析失败。gate/review 等待不计入 worker 无进展超时。
- gate 脚本自身退出 125/126 时按普通失败计入重试预算，保留原始退出码日志；只有控制器中断或证据错误使用对应内部状态。TUI 在 gate/review 阶段丢失完成证据时明确停炉并保留任务。
- 私有 tmux 回归在删除临时项目之前等待独立 watcher 进程组退出，覆盖父进程退出后继续写状态的子进程，消除清理阶段的目录重建竞态。
- 各缺陷均补修复前失败回归，验证进度及部署边界见 [执行计划](docs/plans/2026-11-20-parallel-bug-audit.md)。

## 2026-11-20 门禁重试、看门狗归属与监督回归（未发布）

- headless 审查修复后的普通 gate 失败进入有界修复；`CODEXC_GATE_RETRIES=0` 时直接保留任务并停炉，不额外调用 worker。
- 候选变化或证据保存失败返回 126 时，无论首次复检还是修复后复检都立即停炉，避免将证据失效当作可重试测试失败。
- 补充零预算、两处证据失败及 quota、transient、BLOCKED、人工取消回归；过程与完整验证见 [执行计划](docs/plans/2026-11-20-post-review-gate-boundaries.md)。
- provider-supervisor 审计等待子进程明确报告信号处理器就绪，替代固定 0.1 秒等待；补充慢启动与真实进程退出断言，避免把已退出的子进程误报为残留。
- watchdog 忽略无法取得或非绝对路径的 runner cwd，避免 `cd ""` 沿用巡逻目录并误判炉子存活、跳过复燃；回归覆盖空结果、缺 cwd 字段、相对路径及后续有效 runner。

## 2026-11-19 Provider 等待计时修复（未发布）

- TUI 等待有效 provider 配置变更时，暂停经过归属与心跳核验的回合计时；恢复后沿用剩余预算，避免等待超过一小时即错误停炉。
- 恢复后状态重新显示执行中；等待计时不跨新任务，失效 supervisor、人工暂停和原超时保护继续生效。
- 新增确定性时间线和私有 tmux 回归，验证长等待后原任务只验收一次、重复暂停、剩余预算及失效状态；验证进度见 [执行计划](docs/plans/2026-11-19-provider-wait-timeout.md)。

## 2026-11-19 运行与验收边界修复（未发布）

- headless gate 修复回合为未分类失败增加有界退避重试，并单独处理 auth、quota、transient 和 BLOCKED；保留任务，修复成功后仍须重新通过 gate。
- 项目登记、watchdog 巡逻和桌面过滤统一排除 macOS 系统临时目录，避免缩窄 TMPDIR 后测试项目混入实际项目列表。
- ck-init-furnace 的 Python gate 直接运行 pytest；收集错误、零测试和测试失败均阻止验收。已有 gate 保留，旧模板需按 [运行手册](docs/OPERATIONS.md) 迁移。

## 2026-11-16 Provider 配置切换恢复（未发布）

- 四种 TUI 在 provider 故障与有效配置变更后，于同一终端续接确切原会话；共享指纹、生命周期监督和工具原生续接，保护草稿、归属、旧事件及重试预算。
- ZCode/dsh headless 在共享 turn 等待新配置，保留任务、session 与验收阶段；配额等待可绑定旧 provider，手动 halt、运行窗口与交互优先。
- 新增 provider 配置、supervisor 与 headless 回归及 [运维说明](docs/PROVIDER-RECOVERY.md)。验证结果见 [执行计划](docs/plans/2026-11-16-provider-recovery.md)。

## 2026-11-16 Codex 自动续跑修复（未发布）

- 修复同目录子 Agent 更新日志后抢占 watcher/loop 的主会话发现，导致主回合 429 被漏读、子 Agent 完成误显示为主任务完成。
- watcher 的进程文件路径与目录回退、loop 共用主会话筛选，同时核验物理项目归属并排除 `session_meta.source.subagent`；新增绑定日志。
- 新增 codex-watch 回归，覆盖主回合 429 自动发送、历史不重放、子会话/跨项目/坏文件隔离、配额禁重试和重试上限。验证记录见 [执行计划](docs/plans/2026-11-16-codex-subagent-watcher.md)。

## 2026-11-15 Harness 与文档体系（未发布）

- audit 改为自动发现 `tests/*-audit.py`，新增失败注入锁定“新增回归漏跑但全绿”的缺口。
- 统一入口增加 quick/full、套件选择、JSON 清单、原子结果报告、显式保留日志与严格 SKIP 模式；报告核对预计检查并记录清理结果。
- pre-commit 按仓库规则运行完整离线门禁，新增 macOS CI 与产物上传。
- 通知对等回归注入固定时钟，避免高负载跨过 3 秒回退间隔导致偶发误报，补 2/3 秒边界断言。
- 新增文档总览、Harness 合同、贡献指南、状态恢复、发布与执行计划；docs 阶段校验本地链接、导航和完整提交门禁。
- 校正独立上下文不等于跨模型、成功日志默认回收与离线/人工验证边界。详细验证见 [执行记录](docs/plans/2026-11-15-harness-docs.md)。

## 2026-11-07 今日变更复审

- 修复夜间接管输入框边框正则误接受字母 s，保留带外围空格的真实边框。
- 夜间 gate 检查改为非阻塞、普通文件校验及 2 MiB 限制，防止 FIFO 或超大文件阻塞监视器。
- 夜间接管新增两项失败复现及回归，共十项；补全自动确认工具矩阵、模式差异和接管时段语义。

## 2026-11-06 全工具复审

- 审计范围明确包含 Codex、Claude Code、Pi、OpenCode、ZCode、dsh；工具矩阵标注离线覆盖与在线验证边界。
- OpenCode 两处 SQLite 只读连接改用转义后的文件 URI，修复数据路径包含 ?/# 时静默丢失会话和完成结果。
- ZCode 主会话及 retry 文件改为非阻塞读取并检查普通文件，修复 FIFO 导致无限等待。
- dsh 使用 --json 的本进程 session/final 事件取代最新目录猜测，原子保存会话、保留失败/超时续接、检查目录/身份并隔离工具文本；认证、配额和网络失败分类并保留退出码。新增 dsh-session 专用回归及安装 helper。

## 2026-11-06 队列性能与状态读取优化

- 移除队列调度、入队扫描和离线审计逐任务复制后续行列表的开销，长队列扫描不再因该复制呈平方增长。
- ck status 非阻塞打开并验证普通文件，限制状态/注册表为 1 MiB、PID 为 32 字节；journal 只读取最后 1 MiB，避免 FIFO 挂起和历史记录无限读取。
- 修复状态基准脚本缺少 CK_COMMON_DIR，按被测版本解析共享 helper；新增 status-audit 回归并纳入完整入口。

## 2026-11-06 任务合同与验收边界复审

- 保留多行队列任务中的代码缩进和段落空行；重复入队按完整合同去重。
- 入队忽略已有任务合同内的代码围栏，发布前确认新任务可被 ready 解析器读回，避免报告成功但任务落到 done 后。
- 离线 leaves 审计不把嵌套验收复选框计作独立任务，代码围栏闭合规则与运行时一致。
- 离线审计读取 queue/gate 前以非阻塞描述符验证普通文件类型，防止 FIFO 无限挂起。
- 验收快照拒绝空子模块误解析为父仓库；显式检查隐藏的未跟踪文件与脏嵌套子模块。
- ZCode worker 和独立审查器只采纳最终结果事件中的回答，子工具输出不能覆盖完成或审查结论。

## 2026-11-06 ZCode 空会话与续接修复

- 修正误用 OpenCode `ses_` 前缀的 ZCode 会话校验，按真实 CLI 的 `sess_` 格式保存与续接；损坏的本地 ID 在调用 CLI 前阻断。
- 使用 stream-json 的 turn.started 提前保存重试会话，首次失败、空响应、配额通知和超时后沿用原会话；有效上下文与待重试上下文分开保存。
- 最终回答仍须成功退出；拒绝续接 ID 突变，子工具事件不替换 worker 会话，保持原有配额分类与输出限制。
- 新增 zcode-session 离线回归；本机 173 个已确认属于 CodingKeeper 的无产出失败会话经完整数据库备份后采用 ZCode 原生软删除，保留当前续接会话及所有内容。

## 2026-11-06 燃炉审计与工程 Prompt 燃料

- 默认全天运行；修复看门狗拒绝无时间窗复燃、复燃丢失显式时段和时区。
- 内置十类工程 Prompt，项目级追加、持久化轮换、并发安全入队；ZCode 默认持续 burn，完整两遍无产出后在线等待新料，动态加料自动恢复。
- worker/gate/reviewer 共享受管进程组及 owner 监护，正常退出和强制终止后不留下组内后台进程。
- 自动入口默认要求真实 gate；验收取得事务锁后再次校验候选；队列解析正确处理代码围栏和嵌套验收标题，各状态计数统一。
- 验收新任务重置空转计数，避免新加料后提前熄火；headless 保存 worker Prompt 与输出证据。
- 默认审查仅认 CLI 最终回答，拒绝陈旧 BUGS: 0；自测失败返回非零，入队保护未迁移旧队列。
- 新增 burn-runtime / prompts 回归，更新原时段测试及操作文档。详见 [审计报告](docs/AUDIT-2026-11-06.md)。

## 2026-11-05 ZCode 套餐时段修复

- ZCode 自动任务默认限定 UTC+8 的 23:00–次日09:00，覆盖 worker、门禁、独立审查和 watchdog 复燃。
- 配额等待持久化到下次开放，修复套餐未生效通知被当普通失败反复请求；截止和人工暂停停止受管子进程。
- 等待/退避不再显示正在执行；桌面防止重复实例。

## v2.1.0 (unreleased)

2026-11-05 深度审计加固（[完整报告](docs/AUDIT-2026-11-05.md)）：
- 修复启动 watcher 阻塞、配置损坏、工具/参数/会话归属与 tmux 环境传播；配置编辑要求 Python 3.11+。
- worker/reviewer 退出码与协议双校验，修复后 gate 强制通过；每次投喂的新鲜度水位防止旧 DONE 被误验收。
- 跨车道原子锁、owner 清理、有效恢复预算、人工 halt 保护；补齐三工具 watcher。
- ZCode 输出文件解析及接力校验，安全安装路径，桌面有界后台读取与极端时间戳保护。
- `ck status` 单进程聚合：本机 100 项目离线基准中位 11.37s → 0.16s。
- 新增离线行为回归和独立 HOME/tmux 全套测试环境，keys 不再发送模型请求。

悬浮条任务面板 + 监督链路自愈（v2.0 的显示与监督体系全面落地）:
- 悬浮条任务面板: 空闲 3px 细线 / 悬停弹出状态计数 (品牌 logo + 转圈运行数 +
  暂停待处理数) / 新任务蓝闪·完成绿闪 4s (10s 去重) / ⛔⏸ 琥珀常驻警示 /
  点击展开自适应任务卡片 (状态色点 + 时长 + 完成时刻, 封顶半屏滚动)
- 生命周期: 会话退出自动收线 (心跳过期语义), 闲置会话持续等待不自弃
- 监督自愈: attach 补挂 watcher、rollout 发现 cwd 匹配 fallback (适配新版
  codex 日期子目录)、逐会话判活、回扫无窗口上限
- codexc 交互默认化: 默认纯交互不自动投喂, 无人值守显式 `codexc loop`
- 通知: 完成绿闪+系统通知、不可续跑错误常驻警示 (stderr 尾带回), 全局弹窗
  间隔总闸 (CODEXC_NOTIFY_GAP)
- 治理: 集成测试 /tmp 世界不再污染项目注册表; 交互会话注册补齐
- 无人值守韧性: 瞬时 park 有界自愈 (10/20/30/40min 退避, CODEXC_AUTO_RESUME) +
  worker 错误分类决策 + 回合心跳 + runner cwd 扫描锁 (双开竞态根治, 配合 tmux 脱管承载)
  worker 错误分类 (auth 即停/quota 等重置/transient 退避) + 回合心跳保活面板
- 产品命名入口: `zcodec`/`dshc` — 与 codexc 家族同构 (裸命令 = 非自动:
  zcodec 唤起 ZCode 应用 / dshc 打印说明, 绝不自动跑; `run` = 夜间 runner;
  其余保留动词或 CLI 参数透传), 补齐 `*c` 命名家族统一
- 诊断: zcode worker 失败带回 stderr 尾; 门禁加 swift -typecheck
- 修复: 投喂消息进程级单行化 (剥离 CR/LF) — 尾随换行被 send-keys -l 字面
  打进 composer 会被 TUI 当作换行而非提交 ("continue 已输入未发送");
  watcher 启动记录消息逐字节形态, 此类事故可直接对账

## v2.0.0 (unreleased)
多工具运行时（CodingKeeper 首个完整版）:
- 工具适配: claude / pi / opencode (TUI), zcode / dsh (headless), 六工具矩阵
- codexc-headless: headless 夜间通道（队列/gate/审查/burn 与 TUI 管线同语义）
- burn 模式（默认开）: 队列空闲自动投喂持续改进指令, 十维收尾审查
- 熄火保护: 连续空转自动停炉通知
- c 家族命令面: claudec / opencodec / pic / zcodec / dshc
- codexc fuel: 四工具燃料表（cc-switch 数据源）
- 可靠性: 新鲜度令牌(防陈旧误收)、runner 锁、kill_tree、双路径信任预种、
  符号链接/CJK 会话名、容量错误续命(rollout 尾检测)
- 测试: 4 工具×13 集成场景 + 7 故障注入 + headless 4 场景 + 一致性矩阵
- 文档: HANDLING.md 处理逻辑手册 + docs/ 体系

## v1.0.0
- 按目录 tmux 会话 + 429 自动续命 watcher + codexc-daily 每日恢复

### Leaf audit hardening (2026-11-05)

- ZCode defaults to queue-only execution and requires a configured gate.
- Capture exact leaf baseline/candidate evidence, detect verification mutation, and recover queue/journal acceptance transactions.
- Preserve reviewer failure/final-output semantics; add offline `ck leaves` audits and complete multiline task contracts.
- Reconcile project leaf queues and the 95-check candidate catalog with source evidence.
