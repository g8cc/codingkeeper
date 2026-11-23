# 发布前实机验收

状态：2026-11-19 的本机部署与实机验收已完成；2026-11-20 源码补丁已完成 full，在线五工具与看门狗安全重载仍待验收。日期：2026-11-19，续记 2026-11-20。

## 用户结果与验收条件

在源码回归通过后，继续验证真实 CLI、已安装桌面和 launchd，给出有证据的发布判断。
只显示启动画面不算输入与续接通过；仓库文件一致不算运行中实例已更新。

2026-11-20 补记：[在线验收](2026-11-19-online-release.md) 已完成本轮有界调用，
ZCode 两轮通过，其余五工具因上游容量、服务、认证或额度失败未通过。
续接时另发现 `codexc-headless` 与 acceptance 的暂存改动，原 115 份指纹有两份
变化；补充 [门禁重试边界修复](2026-11-20-post-review-gate-boundaries.md)。
本文件中的 22/22 安装一致性及 full 记录保持为当时事实，不覆盖后续工作区。

## 范围与约束

- 基线 `88b20c5`，保留 Provider 等待超时补丁及其文档和回归。
- 已完成 full 55/55、零失败；详细记录见 [Provider 等待计划](2026-11-19-provider-wait-timeout.md)。
- 使用私有 HOME/socket 做真实 CLI 冒烟，不提交模型任务。
- 已安装服务与桌面先只读核对；任何隔离实例必须使用独立状态、标签和清理流程。
- 不把离线夹具、启动画面或旧桌面构建当作完整发布验收。
- 用户在查看候选与回滚方案后回复“继续”，授权更新本机安装、重载三个服务及清理
  测试桌面；后续部署在该范围执行，不扩展为 Git 提交、推送、打标签或公开发布。

## 步骤

- [x] 核对物理 cwd、origin、Git 状态及最近完整测试。
- [x] 运行原生 Codex 启动冒烟并检查原始画面。
- [x] 验证原生 CLI 草稿输入、换行与 detach/reattach；区分 embedded 回退。
- [x] 核对桌面安装来源，编译候选并观察实际计数、等待和人工暂停。
- [x] 已安装桌面的实际计数、点击展开与恢复紧凑显示验收。
- [x] 核对三个 launchd 标签路径；独立任务验证人工暂停保护。
- [x] 只读核对真实 ZCode/dsh schema、版本和本项目持久化路径。
- [x] 暂存候选源码、运行文件、安装备份及部署/回滚步骤。
- [x] 完成测试桌面清理、本机部署、独立复核及最终文档校验。

## 验证记录

### 源码与原报告

原 full 报告 `/private/tmp/ck-provider-wait-full-20261119.json` 完整记录 55/55 检查，
退出 0、零失败；53 项 pass、1 项 pass_with_skips、1 项 keys 库存 report。
原始两项安装环境 SKIP 不改写。直接运行 watchdog-deploy 的
`test_runtime_copy_matches_repo_if_present` 和
`test_installed_plist_matches_packaging_if_present`，两项补验通过；报告
`/private/tmp/ck-release-installed-watchdog-checks-20261119.json`。

独立复核 115/115 受测源码指纹、22/22 候选 runtime 文件及桌面哈希一致。
本阶段仅更新 Markdown，没有重复 full，也没有把安装文件比较扩展为运行进程验收。
独立报告 `/private/tmp/ck-release-evidence-review-20261119.md`。

### 原生 CLI

`python3 tests/native-startup-smoke.py` 退出 0，三种入口均显示启动界面；最初产物
`/private/tmp/ck-native-tty-41gi_72j` 只证明启动可见。全新 HOME 后续会进入登录或
模型介绍界面，不能把 `loading` 或输入占位当作已可编辑。

补充隔离 PTY 验证使用 Codex 0.170.0、tmux 3.6a、仓库 tmux 配置及对应
`sync-prefix2.sh`，配置仅指向本机未监听的 provider 地址，不提交模型任务。
原先试验遗漏私有 HOME 中的 tmux helper，错误提示干扰了按键；补齐测试装置后再验收。

- direct `codex --no-daemon`、wrapped `codexc --no-daemon`：草稿输入、Shift+Enter
  换行、detach/reattach 均通过，原 pane、进程和两行未提交草稿保持一致。
- 默认 `codexc` 入口同样可交互，但 supervisor 的配置覆盖参数使当前原生 CLI 回退
  到 embedded 模式；未验证共享 daemon，不将入口标签 `daemon` 当作架构证明。
- 未验证实体键盘、IME、真实认证或模型响应。私有 CLI 进程、daemon 和 socket 已清理。

证据 `/private/tmp/ck-release-native-fsp19rwf/qualification.json`；回退提示
`/private/tmp/ck-release-native-6__qapgx/daemon/warnings.txt`。

### 桌面候选

已安装桌面修改时间为 2026-11-12，开始时没有运行；其哈希与本次候选不同。
使用当前源码 `swiftc -O` 构建成功，候选二进制 231696 字节。另建临时测试 app，
用 `CFFIXED_USER_HOME` 隔离 registry、状态与实例锁，核验私有锁持有。

通过 cua-driver 实际桌面截图观察到：一个运行任务、一个 provider 等待与一个人工暂停
显示运行 1 / 待处理 2；仅保留新鲜 provider 等待时显示“等待 provider 配置变更，
保留原会话”和待处理 1；写入人工 halt 后显示暂停并撤去自动等待承诺。失效心跳后
回到空闲区域。状态夹具按原子写入更新，不访问生产项目状态。

候选目录 `/private/tmp/ck-release-candidate-20261119-brwh1an0` 内保存
`desktop-initial-crop.png`、`desktop-waiting-heartbeat-crop.png`、
`desktop-manual-halt-crop.png` 和 `desktop-smoke.json`。
这证明候选的实际 AppKit 显示与状态刷新，不证明已安装桌面已更新。

早期点击验收受 CUA 的 layer-0 窗口发现限制，后台快捷键返回
`window_target_not_found`；一次性连接退出后清理测试 app 又返回
`foreign_process_termination_denied`，当时未将清理记录为完成。
用户明确授权清理后，核对 PID、精确程序路径与候选哈希，再发送 SIGTERM，确认
测试进程退出；临时 app 从 Applications 注销移出，私有夹具归档。后续安装桌面的
展开已通过持久 CUA 连接、绑定新鲜截图的桌面点击验证，详见下文。

### launchd 与部署库存

三个生产标签均已加载，实际 program/arguments 与安装 plist 一致；watchdog、daily、
alive 主文件的磁盘副本匹配源码。但是 22 个 runtime 文件中，只有 16 个一致，
4 个旧文件为 `ck-common.sh`、`ck-watch-tools.sh`、`ck-watcher.py`、
`ck-zcode-session.py`；缺少 `ck-provider.py` 和 `ck-tool-supervisor.py`。
29 个 CLI 安装链接中也缺少这两个新 helper 链接，其他 27 个指向当前仓库。

独立 launchd 测试标签成功启动候选看门狗，观察到真实心跳、人工 halt 内容保持、
没有 worker/probe 启动；bootout 后确认标签消失、锁释放。
fixture 在临时目录，因此显式设置 `CODEXC_FLEET_TEMP_FILTER=0`，不将该测试当作
生产临时目录过滤的实机证明。记录在候选内 `launchd-smoke/result.json`。

上述为部署前库存，不能用其磁盘文件状态证明旧 Bash 进程已加载新实现。
部署库存保存为 `deployment-inventory.json`。候选保存完整源码快照、源码清单、
工作区补丁、22 个 runtime 文件、优化桌面和旧安装副本；`deployment-plan.md` 与
`deployment-files.py` 提供路径/哈希核对、原子替换及恢复原安装状态的步骤。
准备阶段只运行只读 preflight 与隔离文件操作演练，没有对生产执行 apply/rollback。

### 已授权本机部署结果

部署前再次通过完整快照校验：180 份源码/文档、115 份受测源码指纹、26 个安装文件
目标与 29 个 CLI 链接。按 alive → daily → watchdog 顺序卸载三个标签，确认旧实例
退出后备份 55 个文件/链接目标及原先不存在的项目，再使用新 inode 原子替换安装文件。

实际更新结果：22/22 runtime 文件与候选一致，补齐两个 helper 及其 CLI 链接；
桌面二进制哈希与优化构建一致。按 watchdog → daily → alive 重载，三个实际加载参数
匹配安装 plist；新 watchdog PID 37189，心跳已刷新并继续推进。daily 保留原有定时
调度，没有手工触发任务；16/16 份原有 halt 文件内容保持一致。

新增 `~/Applications/CodingKeeper.app` 为已安装原始桌面程序提供后台启动入口。
包装器只执行 `~/.codingkeeper/bin/CodingKeeperBar`，清除测试专用的
`CFFIXED_USER_HOME`，不会复制或改写项目数据；原先没有此 app，回滚时可单独移除。
通过 cua-driver 启动后核对 PID 46262 的实际 executable、候选哈希和生产实例锁。

已安装桌面真实显示 zcode 待处理 16，与暂停库存一致。持久 CUA 连接取得新鲜截图，
确认目标像素区域未变后立即发送绑定该截图的点击，实际观察到项目暂停明细展开，
后续恢复紧凑显示。最初一次投递无变化、两次过期截图被拒绝，均没有记作通过；
最终成功操作有独立截图，未发现需要修改源码的面板缺陷。

主要证据保存在候选目录内：`deployment-execution.json`、
`deployment-live-backup/index.json`、`deployment-desktop-launcher.json`、
`deployment-desktop-runtime.json`、`production-desktop-before-crop.png`、
`production-desktop-immediate-after-crop.png` 和
`production-desktop-collapse-target-crop.png`。独立只读复核报告为
`/private/tmp/ck-release-postdeploy-review.md`，结果通过；实际部署记录与现场一致。
候选与 55 个目标的备份清单另保存至持久目录
`~/.codingkeeper/deployments/2026-11-19-provider-wait`，24 份原文件备份哈希复核通过；
迁移后的执行路径注意事项见该目录 `ARCHIVE-NOTE.md`。

部署期间未改行为源码，保留既有 full 55/55 零失败结论与原始 SKIP 记录；最终只更新
文档并运行 docs-check、diff whitespace 检查。受测代码指纹仍须与原报告对应。
安装快照包含部署前文档；本节是部署后记录，不能将新增记录误报为行为源码变化。

现有项目 runner 不因这次服务更新被强制终止。已在运行的旧 Bash 实例何时采用新
controller 仍取决于其下次正常启动，不能用 watchdog 重启推断全部项目进程热更新。

### 真实持久化 schema

只读验证两套 SQLite 的必需字段匹配代码；检查范围内的旧项目路径残留与当前 cwd
不匹配计数均为 0。ZCode CLI 0.17.1、应用 3.18.2，dsh 0.2.1-rc.5，Node 24.18.0。
发现本项目两库库存存在 20 条桌面独有和 1 条 CLI 独有记录，尚不能认定为孤儿，未清理。
dsh 的 62 个历史头与 59 个投影均可解析，但没有本项目记录可验证续接。
真实事件协议、失败后 ID 保留及侧栏续接仍需相应用户流程；报告
`/private/tmp/ck-release-schema-review-20261119.md`。

## 交接与未解决项

1. 2026-11-19 的本机安装、三个服务重载、测试桌面清理、已安装桌面点击验收均已完成。
   2026-11-20 新发现并修复门禁边界与 watchdog cwd 误判，最终 full 55 项零失败、
   原 SKIP 已独立补验；见 [最终复核](2026-11-20-post-review-gate-boundaries.md)。
   watchdog 安装副本已自动同步，但运行实例仍持旧 inode 且与活任务共用进程组，
   安全重载与运行态版本确认尚未执行。
2. 在线有界调用已执行：ZCode 两轮响应与原会话续接通过；Codex 并发限制、Claude
   HTTP 504、Pi/dsh HTTP 401、OpenCode HTTP 429 quota 阻塞。按实际依赖处理后
   补验，完整证据见 [在线验收](2026-11-19-online-release.md)。
3. 版本整理尚未执行。独立文档复核建议下一个候选为 2.2.0；本地 2.1.0 标签不能代替
   远端发布记录。本轮未执行提交、推送、打标签或发布；另行提交的原暂存补丁及
   当前工作区的精确对应关系见最终复核计划。
