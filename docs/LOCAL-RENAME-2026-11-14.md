# CodingKeeper 本地目录迁移审计（2026-11-14）

目标：本地源码目录从 `codexc` 改为 `codingKeeper`，产品名称统一为 CodingKeeper。
本地目录迁移于 2026-11-14 开始；2026-11-15 GitHub 仓库也已重命名为 `g8cc/codingkeeper`。
本机目录继续使用 `codingKeeper`，不因远端使用全小写而再次移动目录。

## 影响清单

| 位置 | 影响 | 处理 |
| --- | --- | --- |
| 源码目录与当前会话 cwd | 现有 Agent、终端和历史会话仍可能使用旧路径 | 移动真实目录；迁移消费者后移除旧入口，避免产生独立副本 |
| `~/.codex/bin` | 现有安装入口的绝对软链接会失效；新增共享 helper 尚未全部安装 | 按 `install.sh` 中的脚本清单重建入口；不覆盖目录，普通文件先备份 |
| `~/.tmux.conf` | 本机配置软链接指向旧源码目录 | 原子重定向到新目录中的 `tmux.conf` |
| `~/.codingkeeper/burn-watch.sh` | 辅助入口软链接指向旧目录 | 原子重定向；后台服务的稳定副本不受影响 |
| `~/.codingkeeper/projects` | 看门狗和桌面面板仍以旧路径发现控制器项目 | 使用既有 `projects.lock`，原子更新该条目并去重 |
| 各项目 `.codingkeeper/review-leaf.sh` | 本机控制器及 16 个其他项目固定引用旧源码位置 | 只替换已识别的控制器调用行，保留项目其他约定；优先使用稳定安装入口 |
| 根目录 `.gitignore` | 运行队列、状态和证据可能被批量暂存 | 忽略 `/.codingkeeper/`；保留文档中的已跟踪审计模板 |
| `.codingkeeper/status.json`、`active-leaf.json` | 当前状态的 project 字段仍为旧目录 | 原子更新当前项目位置，保留任务、配额等待、进度和证据 |
| `~/.codex/config.toml` | 信任配置按绝对项目路径登记 | 迁移原有项目表的路径，保留既有 trust_level 和其他设置 |
| README / AGENTS / 安装器说明 | 产品介绍和 clone 后的本地目录仍叫 codexc | 使用 CodingKeeper；clone 显式指定本地 `codingKeeper` 目录 |
| launchd 三个作业 | 已使用 `~/.codingkeeper/bin` 的稳定可执行副本，无源码目录依赖 | 核对已加载参数；不因改目录重建服务或改变定时策略 |
| 桌面面板 | 可执行文件位于稳定目录，项目名称来自登记表 | 登记表迁移后自然显示新目录名；不需要重新编译 |
| Git 元数据与钩子 | 主仓库 `.git` 随目录移动；钩子为相对 `.githooks` | 保留提交历史、main 分支和钩子设置；GitHub 改名后更新 origin 和本地 Git LFS URL 配置 |
| 历史 journal / evidence / 基准测量 / prepared 部署清单 | 旧路径是当时证据的一部分，改写会破坏审计含义或摘要 | 保留历史原文；重新执行历史部署清单前必须重生成当前路径 |
| 编码工具的历史会话、IDE 最近项目 | 可能继续保存旧 cwd | 保留消息内容，同步迁移执行目录、桌面索引和自动化；不能依赖外层 cwd 或旧路径软链接 |

## 已修复的迁移缺陷

`ck-init-furnace` 原来把源码绝对路径直接插入生成的 shell 字符串：搬走目录后找不到审核器，
路径里的 `$` 还会被当作 shell 变量展开。现在优先使用 `~/.codex/bin/codexc-review-leaf`，
其次查 PATH，最后使用经 shell 引用的原源码路径，保留未安装时直接运行的能力。
找不到时明确提示从新目录重跑安装器。已有用户 gate 和队列不被脚手架重写。

`tests/relocation-audit.py` 用普通路径与含空格、美元符号、单引号的路径复现旧故障，
验证移动前直接使用、移动后通过稳定入口使用，以及参数原样传递；不调用真实模型。

本轮同时接管审查解析重试与测试临时目录回收改动，修复了无效审查未打断
“连续零问题”计数的缺口，并补充新配置的 tmux 透传回归。

## 兼容边界

- `ck` 是多工具入口；`codexc`、`zcodec`、`dshc` 等已有命令保留。
- `CODEXC_*` 配置、launchd label、`.codingkeeper` 状态目录与队列合同不随本地文件夹改名。
- 本机旧路径已于 2026-11-15 移除，没有保留兼容软链接；独立旧 clone 完整归档在本地审计备份中。
- 本地迁移备份放在本轮临时审计目录；备份与运行状态不进入 Git 提交。
- Swift 工具链探针若失败，门禁会明确报告 SKIP；不能把它描述为桌面类型检查通过。

## GitHub 改名后的本地更新（2026-11-15）

```bash
cd /Users/wardonguo/Documents/work/code/AI/AIworkspace/codingKeeper
git remote set-url origin https://github.com/g8cc/codingkeeper.git
git remote -v
git ls-remote --symref origin HEAD refs/heads/main
```

若 `.git/config` 中保存了按旧仓库地址分组的 Git LFS 配置，也需迁到新地址。
该改动不需要重新 clone，不改变当前分支、历史或未提交文件。

## ZCode 会话与自动化迁移（2026-11-15）

本机已在数据库备份后完成以下迁移并读回校验：

- CLI 数据库中 6 个会话的 `directory`、`path` 和路径派生 `project_id`，以及 11 条输入历史的项目 ID。
- 桌面索引中 19 个任务、6 个项目根、活动自动化、121 条运行历史，以及创建命令缓存和分组派生索引。
- 当前和备用设置中的最近项目、上次工作区与活动工作区。

会话 ID、消息和运行结果保留。旧 clone 的唯一提交已保存在本地审计归档中；当前源码已接入经审计的修改。
备份与读回记录位于 `~/.codingkeeper/audits/codexc-reappearance-2026-11-15/`。

重新打开 ZCode 时选择真实 `codingKeeper` 目录；若应用仍显示旧项目，退出并重新打开应用以重新载入索引。
已迁移的旧会话仍带有历史上下文，需要在下一次交互中明确通知 Agent：

> 项目已迁移到 `/Users/wardonguo/Documents/work/code/AI/AIworkspace/codingKeeper`，
> GitHub 已改为 `https://github.com/g8cc/codingkeeper.git`。请先执行 `pwd -P` 和
> `git remote get-url origin`，重新读取 `AGENTS.md` 并检查 `git status`。
> 若实际目录不符，先停止操作并报告，不要重建或 clone 旧 `codexc` 目录。
> 当前存在其他 Agent 留下的未提交改动，请完整保留并审计后再继续。

这是目录与仓库身份迁移；此前自动化记录的 provider 401 认证失败需要单独恢复凭证。
当前记录仅证明数据库、设置和文件读回通过，尚未验证 ZCode 桌面 UI。
