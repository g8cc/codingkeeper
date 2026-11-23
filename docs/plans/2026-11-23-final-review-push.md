# 最终复审、提交与推送

状态：源码复审与目标回归已完成，进入完整提交门禁。用户已授权提交并 push；沿用原并行审计授权。

后续：首轮 full 及提交推送已完成；远端发现已退役 runner 镜像，追加最小 CI 修复和回归，
再走同一完整提交门禁。

## 目标与范围

核对待提交修复及六个尚未推送的本地提交，保留已有工作。复核任务验收、
TUI 回合和进程生命周期，并验证 KeyDrop 配置恢复与控制器的有效配置识别一致。
所有新增行为修复先补旧实现失败回归。只在私有测试环境验证，不改真实会话或配置。

## 步骤

1. 核对 cwd、origin、Git 状态、远端进度和中断遗留进程。
2. 并行复审独立模块，本地核对 provider 配置、测试覆盖和提交内容。
3. 对确认缺陷增加回归并修复，运行目标套件。
4. 暂存准确修改，使用现有 pre-commit 执行 full；通过才形成提交。
5. 正常 push 至 origin/main，核对远端提交及 CI 状态，记录 SKIP 和未验证边界。

## 验证与结果

开始时 HEAD 为 `38aba47`，本地 main 比此前 origin/main 超前六个提交；没有暂存改动。
前轮源码和真实工具验收均保留为历史证据，不替代本次提交门禁。
不承诺零缺陷，不创建发布标签或公开 Release。

### 配置读取复审

- dsh 原生已使用全局 `cordis.patch.yml` 选中 KeyDrop 配置，但 Keeper 漏读此层，导致
  snapshot 为不可恢复。补齐 bundle（即使 profile patch 不存在）、profile、全局与重复
  CLI patch 的顺序，保持完整 config 替换，并核对最终禁用状态。
- Pi 原先错误地让 models 密钥优先于 auth，且把裸变量名当引用、漏读 `$NAME`。
  现按 CLI、auth、models、内置环境顺序解析；密钥与 headers 共享原生插值/转义，
  shell 凭证命令不执行，缺失环境引用保留不可恢复结果。
- 八项新增配置回归在旧实现全部失败（含多个子场景）；修复后 provider-config
  35 项、provider-headless 29 项通过。后者包含全局补丁选择后在同一 session 轮换
  凭证恢复的假 CLI 回归。私有报告位于
  `~/.codingkeeper/verification/2026-11-23-final-review/provider-report.json`。
- 本机只读检查确认 Pi/dsh snapshot 均 configured/recoverable；未请求模型或修改凭据。
  前轮真实双回合验收仍按其日期引用，不将本轮只读检查写作在线切换通过。
- 与本机已安装 Pi 解析器比较 500 组人工合成模板，在相同隔离环境下全部一致；
  首次比较因 Node 继承 `_` 环境而测试环境不一致，修正为双方空环境后通过。

### 并行复核追加项

三位独立审查者确认下列可复现边界，均已在限定文件范围修复：

- headless 审查后 gate 修复混用 turn/gate 重试预算，125 暂停后重置审查预算并重复投喂。
- TUI 暂停后复用等长旧 rollout 缓存可误验收失效证据，恢复 gate/review 时状态仍显示等待。
- watchdog 临时目录过滤遗漏告警入口；独立进程组夹具缺少 runner 清理；`ps` 检查失败
  被监督测试当作进程已退出。

合并期间取消了一次刚进入 syntax 的 quick，exit 130、清理完成，避免运行中的脚本
与并行补丁相互干扰；该次记录不计通过。最终全量由真实 pre-commit 执行。
拟推送内容与本机可解析的五份生效凭据做精确比对，未发现匹配；私有证据留仓库外。

TUI 两项修复已完成，新增回归在旧实现有八个失败子场景，最终 loop-daily 28/28
通过；审查代理在完成补丁及部分测试后遇 429，主线程接手续跑完整目标套件并再次
用旧逻辑回放确认失败。watchdog/监督分支新增六项回归先红后绿，目标验证为
watchdog-deploy 21 通过及两项实装 SKIP、provider-supervisor 33/33、watch-window
45/45，退出 0、清理完成。上述日志已归档到本轮私有验证目录。

headless 将三个重复修复循环合并为同一有界回合函数，gate 的 125 在原阶段等待并
重新核对候选；review 暂停扣回未完成的审查次数，保留既有 parse/zero streak 预算。
16 项新增 headless 回归先红后绿，runner-boundaries 全部 24 项、acceptance、
leaf-runtime 28 项通过，清理完成。主线程另发现恢复后 gate/repair 状态仍显示等待，
补一项回归（两个失败子场景）并在每次执行阶段刷新状态，修复后通过。

### 提交门禁与交付证据

源码不再扩大改动，先完成 quick，再由现有 pre-commit 执行 `tests/run-all --profile full`。
正常 push 仅在该门禁成功形成提交后执行；不绕过钩子、不强推。
最终 quick 五项检查无失败，Swift trivial 探针在 90 秒内未完成而标记 SKIP，
保留该环境未覆盖边界；报告为本轮私有目录 `final-quick-report.json`。
为避免成功 full 自动清理日志后失去证据，仓库外监视脚本仅复制测试报告/日志并记录
原始 `git commit` 退出码，不改变钩子或测试配置。最终输出记录在本轮验证目录的
`commit-output.log`、`commit-result.json`、`precommit-artifacts/`；报告副本可能早于
清理完成，清理与提交是否成功以原命令退出码为准。

推送后核对 origin/main 的 SHA 和 GitHub Actions 实际状态；远端 CI 排队或运行中
不会写作通过。本轮源码提交不等同于安装/公开发布，真实 TUI 输入、当前 GUI 点击、
provider 在线故障切换仍未在本轮重测。最终提交号、推送与 CI 状态随交付记录。

### 首次提交与远端检查

2026-11-23 20:48–21:23（Asia/Singapore），真实 pre-commit full 完成 **56/56**，
54 pass、1 pass_with_skips、1 inventory report，零失败。唯一 SKIP 为隔离 HOME 下
两项真实 watchdog 安装检查；Swift 与桌面本次实际通过。187 份受测文件指纹未变，
提交树与受测 index 一致。提交 `32790e3` 已正常 push，origin/main SHA 与本地一致。

GitHub run `45183708043` 在测试开始前被取消，平台 annotation 为
`The configuration 'macos-14-arm64-us-default' is not supported`。
官方 `actions/runner-images` 公告 #13518 确认 GitHub Actions 的 macOS 14 镜像于
2026-11-02 退役，建议迁至 macOS 15 或 26。将本仓库 runner 改为 `macos-15`，
新增拒绝退役标签的回归先在旧配置失败，再在新配置通过；应用运行时代码保持首轮
通过版本。后续提交仍不跳过 full，单独归档在本轮验证目录 `ci-runner/`。
