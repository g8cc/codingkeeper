# 验证、发布与回滚

源码通过测试、安装副本更新、真实用户流程通过是三项独立事实。开发约束见 [CONTRIBUTING](../CONTRIBUTING.md)，状态边界见 [STATE-CONTRACTS](STATE-CONTRACTS.md)。不要把历史报告的全绿当作本次发布的证据。

## 发布前验证

```bash
pwd -P
git remote get-url origin
git status --short --branch
tests/run-all --profile full --keep-artifacts --report /private/tmp/ck-release-report.json
```

核对完整检查已执行、失败为零、报告中的跳过项与环境限制明确记录。正常开发允许 Swift 工具链探针失败时标 SKIP；要把桌面能力作为本次发布承诺，必须修复工具链再验证。`--strict-skips` 可以把已识别跳过项设为失败，不能据此补出从未运行的真实用户测试。

审查本次 diff、回归与当前指南；更新 `CHANGELOG.md` 和需要变化的 `VERSION`，版本选择依据实际发布范围。记录真实验证的 commit/工作区状态，不把夹具结果写成在线供应商健康。

## 按变更选择人工冒烟

| 变更 | 必须观察的用户结果 | 离线测试不能替代的部分 |
|---|---|---|
| TUI 启动/按键/信任门 | 新会话可见、输入与换行正确、detach/reattach 可用 | 真实终端能力协商、权限弹窗、已安装 CLI 版本 |
| 桌面 | 计数、等待/暂停、点击展开、退出后的状态刷新 | 已安装二进制和实际 AppKit 显示 |
| ZCode/dsh 协议或迁移 | 同一项目续接、失败后 ID 保留、侧栏归属正确 | 真实数据库 schema、当前 CLI 事件协议 |
| 看门狗/launchd | 实际服务指向目标版本，人工 halt 不被清除 | 真实 launchd 调度与安装路径 |
| 业务 gate 或浏览器 | 回到同一用户界面完成被修复流程 | 真实设备、浏览器及项目业务断言 |

可选 `python3 tests/native-startup-smoke.py` 会启动真实 Codex/TUI，使用私有 HOME/socket 且不提交模型任务；可能触发 CLI 自身 daemon 初始化。只在适合的人工环境显式运行。真实模型自检可能消耗额度，应独立获得任务授权并记录工具版本、时间与结果。

## 安装或部署

1. 确定发布目标、当前运行实例和原版本备份。检查安装脚本将写到的路径及将操作的服务，不在测试阶段顺手安装。
2. 先停止目标实例，或准备验证后的新 inode 再原子替换；禁止原地覆盖正在被 Bash 读取的脚本。
3. 在已授权的部署范围运行安装操作。`install.sh` 负责安装入口与桌面编译，`packaging/install-watchdog.sh` 有独立服务影响；修改前阅读当前脚本，而不是照抄历史机器的服务路径。
4. 比较全部 runtime 脚本与共享 helper，不能只比主 watchdog；核对三个已安装 plist
   及 launchd 当前加载参数。通过真实可执行路径、版本和用户视图确认生效。
   只看到仓库 HEAD 更新不能证明部署成功，磁盘副本更新也不证明长驻进程已重新加载。

本仓库的 GitHub Actions 运行相同 full profile 并上传日志/报告；它不安装本机服务、不读取真实工具凭证、不发布制品。远端 CI 结果需要在推送后另行查看，创建 workflow 文件本身不代表 CI 已通过。

## 回滚与记录

部署回滚恢复已知可用的程序版本，保留用户源码、队列、会话、证据与未提交工作。需要状态迁移回退时先核对旧版本兼容性与备份，不能直接用 `git reset --hard` 或删除状态代替恢复。

记录版本、环境、执行命令、退出码、报告位置、SKIP/未验证项、人工观察、部署目标与结果。日志和快照可能含私有内容，公开报告使用必要的摘要与哈希。报告模板可参考 [执行计划模板](plans/TEMPLATE.md)。
