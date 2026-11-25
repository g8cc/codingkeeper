# 实装漂移与真实交互验收

状态：安装审计修复、实装同步与原生终端验收完成；提交门禁与远端结果按下述交付记录
核对，当前 GUI 交互仍未验证。沿用已授权的审计、修复、本机部署与提交推送；不创建公开发布。

## 目标与范围

以 `27fa35d` 已通过的本地 full 与远端 CI 为基线，补齐安装检查漏掉的共享辅助文件，
复核实际终端输入和桌面交互。私有测试与生产会话隔离；凭据和截图证据保存在仓库外。

## 步骤

1. 核对实装副本及真实消费者，先复现现有安装审计的漏报，再补有意义的回归。
2. 备份并原子替换漂移副本，核对全部运行文件和 launchd 状态。
3. 并行验证私有原生 TUI 的输入、换行、detach/reattach，以及当前桌面实际交互。
4. 记录失败、SKIP 和未验证边界，运行目标测试与提交所需 full，正常提交推送。

## 已有证据

- `27fa35d` 远端 run `45204941766` 的 full、证据收集与上传均成功。
- 56 是顶层检查行数；该基线含 619 个 unittest 用例（包括两项隔离 HOME 的安装跳过），
  以及 shell、自检、集成场景，不代表行覆盖率或商业质量保证。
- 11 月 24 日两个实装 watchdog 检查与 Swift 类型检查通过，但全文件比对仅 21/22
  一致，`~/.codingkeeper/bin/ck-provider.py` 漂移。现有实装测试只比较主 watchdog。
- 同日原生 smoke 三入口可见；未验证输入、换行或续接，不能算完整 TUI 验收。

## 完成结果与边界

### 安装审计与部署

根因是源代码修复后只同步了部分运行文件，而原实装审计只核对 `burn-watch.sh`；
plist 审计只覆盖两个作业，按原作者路径比较原始字节，还会把部分安装误记为 SKIP。
五项新回归实际调用安装审计方法，对全部 runtime 文件逐个注入缺失/漂移，并验证
部分安装、未部署、异地 HOME、二进制 plist 和三个作业的损坏场景。
旧实现产生 46 个失败子场景，修复后五项通过；加强后的真实安装检查首先准确报出
`ck-provider.py` 漂移，再完成部署后通过，两份日志均保留。

独立复审另发现分类独自判定“未部署”会漏掉整组 runtime/plist 缺失。新增第六项回归
覆盖两种整组缺失，旧判定两个子场景均失败，修复后通过。现在仅两组完全没有部署
痕迹时 SKIP；任何部分安装都失败。对应 `component-before.log` / `component-after.log`。

备份旧 helper 后以新 inode 原子替换，22/22 runtime 哈希与 `27fa35d` 一致。
三个实际 launchd 标签均加载；watchdog PID 6281 持续运行，其他两个定时作业空闲，
最近退出码为 0。进程库存未发现使用 runtime 目录 provider/supervisor 的常驻实例，
本次没有重启生产作业；不清理会话、队列或 halt。真实 HOME 的两项加强版安装检查通过。
目标 watchdog-deploy、watchdog-install 套件通过，隔离 HOME 仍明确跳过两项实装检查。

### 原生终端

macOS 26.7.1 / Intel、Codex CLI 0.170.0、tmux 3.6a。私有 HOME、socket 与仅绑定而
不监听的 localhost provider 三组测试中，direct、wrapped、default 均完成草稿输入、
CSI-u Shift+Enter 两行、Ctrl+a d 分离及重新附着。原 pane、Codex PID/启动时间与
两行未提交草稿保持一致；输入记录无提交键，私有事件审计无已提交回合，自有进程清理为零残留。

default 的 F2 警告明确表明 supervisor 配置覆盖导致 embedded 回退，不当作共享
daemon 验收。前两轮装置的 Node PATH 与旧就绪文案问题保留失败证据，修正后复验通过；
未修改应用行为。实体键盘、IME、真实模型响应/认证/切换仍不在这项终端资格范围内。

### 桌面与交付边界

cua-driver 识别已安装 `com.codingkeeper.desktop`、PID 46262，保持后台启动。
该 statusBar 面板没有普通 layer-0 窗口；首次桌面截图接口返回
`could not create image from display`，随后重试恢复，可见 codex 待处理 1、zcode
待处理 16。未发送无截图依据的点击；桌面点击涉及前台操作，按 cua-driver 规则
单独征询授权。仅截图与当前进程存活不能写作本轮展开/收起通过。

本轮证据保存在 `~/.codingkeeper/verification/2026-11-25-installed-qualification/`：
`audit-before.log` / `audit-after.log`、`installed-before.log` / `installed-after.log`、
`runtime-before.json` / `runtime-after.json`、`target-report.json`、`native/qualification-final.json`。
提交由原有 pre-commit 执行 full，日志与原退出码归档到 `commit-output.log`、
`commit-result.json` 和 `precommit-artifacts/`；推送后的 SHA 与 CI 结果另记 `delivery.json`。
报告副本可能早于 isolator 清理，最终清理和提交成功以原命令退出码为准。

当前不声称零 bug。GUI、在线 provider 故障切换、受控长期运行、下游产品业务质量
与商业化仍需各自的真实验收。顶层检查仍为 56 行，不能用增加行数代替覆盖缺口的修复。
