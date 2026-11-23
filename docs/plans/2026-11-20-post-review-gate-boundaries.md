# 发布复核：门禁边界、监督夹具与看门狗归属

状态：源码修复与离线验收已完成；五工具在线补验与看门狗安全重载待完成。日期：2026-11-20。

## 用户结果与范围

继续发布验收时发现工作区已有暂存的 `codexc-headless` 和 acceptance 回归，
与上一轮 115 份源码指纹相比恰有这两份变化。保留原暂存内容，在工作区补齐
审查修复后门禁重试的边界；不把上一轮 full 结果当作当前代码的验收。

验收期间观察到 HEAD 从 `88b20c5` 前进到 `38aba47`，提交内容恰为开始时已有的
两份暂存补丁；本轮没有执行该提交。当时推进 HEAD 没有改变已受测文件内容，
后续修复另冻结新指纹。最终 full 的起始与结束 HEAD 均为 `38aba47`，115 份源码
与最终 full 启动时指纹全部一致；本轮新增修复留在工作区。

门禁重试应尊重 `CODEXC_GATE_RETRIES=0`；候选变化或证据保存失败返回 126 时
应立即停炉，保留任务与现场，不再把它当普通测试失败投喂修复。

## 步骤

- [x] 核对实际源码、暂存 diff、相邻 gate 分支和已有回归。
- [x] 新增零预算和两处证据失败回归，保存旧实现失败证据。
- [x] 补齐边界，核对认证、配额、临时故障、人工停止和 BLOCKED。
- [x] 目标回归、迭代 quick 与最终 full 完成，记录 SKIP 补验及安装差异。
- [x] 同步当前指南、在线验收记录和发布结论。

## 最终结果

2026-11-20 01:23:46–01:52:52（Asia/Singapore）完成最终 full，退出 0。
55/55 项实际执行，52 项 pass、2 项 pass_with_skips、1 项 keys 库存 report，
零失败、零缺失，测试环境清理完成。重点套件：acceptance 39 项、
provider-supervisor 30 项、watch-window 44 项全部通过；四工具与 headless 集成、
故障注入、文档导航及 diff 空白检查通过。

两个带 SKIP 的检查保留原始报告：syntax 的 Swift 探针超时由单独类型检查补验通过，
最终 desktop 实际编译与行为断言也通过；watchdog-deploy 在私有 HOME 下跳过的
两项安装检查在真实 HOME 下重新通过，无 SKIP。最终安装检查记录为
`/private/tmp/ck-post-review-installed-final-20261120.json`。

持久证据归档：`~/.codingkeeper/verification/2026-11-20-post-review-gate`，包含
`final-verification.json`、最终 full JSON/日志、115 份源码指纹、修复前后的失败与
通过记录。首次失败和中间取消的 full 未覆盖、未删除；新报告仅验证最终源码。

## 验证记录

原有暂存版本 acceptance 通过：`/private/tmp/ck-online-acceptance-20261120.json`。
新增三个回归在修复前均失败：`/private/tmp/ck-post-review-before-confirmed-20261120.json`；
更早的 `/private/tmp/ck-post-review-before-20261120.json` 中证据夹具没有建立候选快照，
修正夹具后重新确认相同三个失败，未将夹具错误作为根因证据。

修复后的 acceptance 39 项通过：`/private/tmp/ck-post-review-after-20261120.json`，
覆盖零预算、首次/再次复检证据失败，以及 quota、transient、BLOCKED、125 取消与
原有 auth、成功修复和持续失败预算。quick 5/5 零失败，但 Swift trivial 探针在
90 秒预算内超时，syntax 标记 SKIP：`/private/tmp/ck-post-review-quick-20261120.json`。
首轮源码 115 份指纹另存 `/private/tmp/ck-post-review-source-20261120.json`。

首轮 full 在 provider-supervisor 的 SIGINT 清理测试发现失败，原始报告保留为
`/private/tmp/ck-post-review-full-20261120.json`。注入子进程一秒启动延迟后，
实际 supervisor 退出 130、CLI 与后代进程均已消失，但因信号处理器尚未装好，
没有写出退出标记；固定 0.1 秒等待导致误报。独立复现记录为
`/private/tmp/ck-supervisor-start-race-20261120.json`。

为 SIGINT 与 SIGTERM 增加慢启动回归，修复前两项均失败；假 CLI 的子进程安装完
处理器后发布专属 PID 就绪标记，测试等待该标记，不再猜测启动时间。保留原有退出
标记断言并增加真实 PID 无活跃进程的检查，修复后普通/慢启动四项均通过。生产
`ck-tool-supervisor.py` 未修改。前后日志为
`/private/tmp/ck-supervisor-start-before-20261120.log` 和
`/private/tmp/ck-supervisor-start-after-20261120.log`。

相对首轮完整验证仅 `tests/provider-supervisor-audit.py` 指纹变化；新指纹保存在
`/private/tmp/ck-post-review-final-source-20261120.json`。最终 full 使用独立报告
`/private/tmp/ck-post-review-full-final-20261120.json` 启动后，首轮又暴露下述 watchdog
问题，因此该中间重跑通过受管 isolator 的 SIGTERM 清理后取消（退出 130），
保留部分报告，不将其当作最终验收。

首轮 `watchdog-deploy` 的真实 nohup 复燃断言失败；单独运行同一测试也在 60 秒后
失败，排除了仅凭“并行负载”解释失败。检查发现 `proj_alive_scan` 在 `lsof` 无 cwd
时执行 `cd ""`，Bash 成功沿用当前目录，从而把巡逻目录误判为已有活 runner。
确定性回归对空输出、只有 PID 字段、相对目录三种情况在旧代码均失败；不存在的
绝对路径与后续有效 runner 作为对照。修复只接收绝对 cwd，再按既有逻辑验证目录。
新回归、扫描缓存、每轮重扫及非 UTF-8 参数四项通过；前后证据为
`/private/tmp/ck-watchdog-cwd-before-20261120.log`、
`/private/tmp/ck-watchdog-cwd-after-20261120.log`、
`/private/tmp/ck-watchdog-fd-recheck-20261120.json` 和
`/private/tmp/ck-watchdog-fd-after-20261120.json`。

相同的真实 nohup/锁描述符测试在修复前 60 秒失败，修复后约 3 秒通过。
当前 115 份指纹已冻结到 `/private/tmp/ck-post-review-verified-source-20261120.json`；
包含全部修复的最终完整验收写入 `/private/tmp/ck-post-review-full-verified-20261120.json`。

Swift 补查使用独立 HOME 和空模块缓存，将 trivial AppKit 探针预算扩大到 300 秒，
仍超时退出 2；只据此确认本机编译验证受阻，没有把“工具链损坏”的通用提示当作
已定位具体 SDK 错配。记录归档到
`~/.codingkeeper/verification/2026-11-20-post-review-gate/swift-probe-result.json`。
桌面源码及已安装二进制哈希与前一天部署清单一致，但这不能补成当前编译检查通过。

后续最终 full 的 desktop 审计实际编译成功（224 秒），全部行为断言通过。
使用该轮已生成的私有模块缓存单独补跑
`tests/swift-gate.sh desktop/CodingKeeperBar.swift`，1.93 秒退出 0、无 SKIP；
记录 `/private/tmp/ck-post-review-swift-typecheck-20261120.json`。原 syntax 阶段的
超时 SKIP 保留，由这份独立成功记录补充覆盖，不回写原报告。

修改 watchdog 之前，在实际 HOME 下只读补验两项安装检查，两项通过、无 SKIP：
`/private/tmp/ck-post-review-installed-watchdog-20261120.json`。22 份 runtime 与
当时的部署清单及源码均一致，详情在在线验收归档的 `installed-comparison.json`。
新增 watchdog 补丁之后重新确认 22/22 runtime 与当前源码一致，只有 `burn-watch.sh`
相对前次部署发生预期变化，记录在持久归档的 `installed-runtime-final.json`。
实际加载版本另按下一段核对，不延用此前一致性结论。

watchdog 的既有自刷新已将安装副本原子更新为当前源码；旧版与候选备份、安装
指纹保存在 `~/.codingkeeper/deployments/2026-11-20-watchdog-cwd`。运行 PID 37189
仍与多个活动项目共用进程组，当前 launchd 配置未声明放弃组清理，因此没有执行
预备的强制重载，以保留正在运行的任务。新副本不等于该 PID 已加载修复；待安全
维护窗口或正常日期切换 re-exec 后核对运行版本，此项明确保留为部署边界。
只读 `lsof` 进一步确认 PID 37189 的脚本 FD 255 仍绑定 inode 455128612，
安装路径的 inode 已为 456063786；记录 `running-script-inode.json`。因此确实存在
运行脚本与新安装文件的版本切换边界，不能用文件哈希一致替代加载验收。

## 未解决项

真实模型验证另见 [在线验收](2026-11-19-online-release.md)。本机 CLI 链接
`~/.codex/bin/codexc-headless` 直接指向仓库；源码通过新文件 + mv 原子替换，
新进程会读取补丁，已有 Bash 进程未强制重启。22 份独立 runtime 副本不包含
`codexc-headless`，不能混淆这两种安装形态；之前部署记录保持为当时事实。
本轮未执行提交、推送或公开发布。发布仍需处理五工具在线失败、完成看门狗安全
重载及运行态验收，再整理版本与发布制品；不能据当前结果宣称全部 bug 已消除。
