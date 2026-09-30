# 项目开发与 agent 工作流

本指南提供按任务选择的入口和命令。长期协作约定在 [AGENTS.md](../AGENTS.md)，贡献与领域审阅要求在 [CONTRIBUTING.md](../CONTRIBUTING.md)。普通任务只读取需要的部分。

## 环境与日常工作

先确认当前 checkout、未提交修改和实际 Python 解释器。使用装有本项目依赖的解释器；不假定每个工作区都有 `.venv`，也不为文档修改安装完整 Materials Project 或发布依赖。

新建开发环境见贡献指南。以下 `python` 代表选定的同一个解释器：Windows 虚拟环境可将其替换为 `.\.venv\Scripts\python.exe`；已验证依赖的系统环境可用 `py -3`。从仓库根目录运行。

| 改动 | 有意义的本地检查 | 扩大检查的触发条件 |
| --- | --- | --- |
| 文案、链接、项目规则、技能说明 | `python scripts/check_docs.py`、`git diff --check`，核对新增命令与实际接口 | 修改可执行示例时试跑该示例；纯文字不需要数值全量测试 |
| 单个模块修复 | 受影响的 pytest 模块，改动文件的 Ruff 检查 | 共享调用、失败路径或输出变化时增加调用方测试 |
| 衍射、结构解析、弹性或单位定义 | 受影响测试与 `benchmark` 解析基准，检查差异与容差 | 公共数值契约变化时补充独立比较或领域审阅 |
| CLI、API、schema、导出、事务行为 | 相关模块与端到端测试，检查结果包和元数据 | 跨入口影响时扩大到离线非 GUI 套件 |
| GUI | 设置与状态测试，在可用显示环境中执行受影响交互 | Linux Xvfb 命令见 [GUI](GUI.md)；只读代码不能报成功交互 |
| 依赖、打包、正式发布候选 | [完整发布 preflight](RELEASE.md) 与相应 CI | 发布验收仍要求完整通过；简化运行不生成完整验收凭据 |

例如修复快速导出行为时，可从相关模块开始：

```powershell
python -m pytest -q tests/test_quick_export.py tests/test_cli.py
python -m ruff check src/diffractscout/quick_export.py src/diffractscout/cli.py
```

确有共享影响时，运行离线非 GUI 套件：

```powershell
python -m pytest -q --ignore=tests/test_gui.py
```

GUI 模块与启动分类按 [GUI 指南](GUI.md) 和当前 CI 选择。PR 仍须满足配置中的 CI 检查；CI 的全量覆盖不意味着每次局部修改都要在本地手工重复整套发布流程。

演示与基准会保护已有输出。重跑使用新目录，例如：

```powershell
$runId = [guid]::NewGuid().ToString("N")
python -m diffractscout demo -o "outputs/dev-demo-$runId"
python -m diffractscout verify "outputs/dev-demo-$runId"
python -m diffractscout benchmark -o "outputs/dev-benchmark-$runId"
```

这些命令需要已安装当前 checkout。源码 CLI 也可通过 `python scripts/diffractscout_entry.py` 调用。现有目录只在用户授权替换、且满足程序完整性规则时使用 `--overwrite`；无需自动删除旧结果。

## 项目技能的入口

本仓库提供一个具体工作流：[$diffractscout-cif-reference](../.agents/skills/diffractscout-cif-reference/SKILL.md)。例如：“用这个 CIF 生成 Cu Kα、5–120° 的理论峰表，导出 Excel，并核验来源与单位。”

技能位于 Codex 支持的 `.agents/skills/` 仓库目录。其他 agent 可直接读取对应 `SKILL.md`。无需复制到全局技能库或修改全局模型设置；如果当前会话尚未显示新技能，可直接指定文件，或重新打开项目会话检查发现结果。

技能复用现有 CLI 和校验工具；详细公式链接到科学约定。只在本地 CIF 导出与核验时触发。新增技能应解决一个真实重复流程，保持名称和描述短而明确，避免把通用编码任务吸入科研导出流程。

## 完成标准与规则回归

一次修改完成时，用户要求的文件或行为已产生，相关检查通过，未完成部分有具体原因。调查摘要、第一版实现、审阅报告和“可以继续”均不替代已经授权的交付。

维护规则或技能后，用以下场景检查其边界；仅对实际新增或改动的流程试跑，不设每次任务必做的固定清单。

| 场景 | 应有行为 |
| --- | --- |
| “修正文档的一处拼写” | 局部修正与文档检查；不加载发布、投稿或 CIF 导出流程 |
| “修复快速导出并验证” | 调查、实现、检查、修正失败直至交付；不在第一版自动等批准 |
| “从 CIF 导出理论峰表” | 明确辐射与范围，保留原始文件，交付 Excel 和可验证结果包 |
| “把这个峰表用于同步辐射实验比较”，但没有辐射条件 | 先检查输入；询问会改变峰位的波长或能量，不能沿用实验室默认值 |
| “只审阅，不改文件” | 返回证据与建议，遵守只读范围 |
| “准备发布，先让我看” | 完成验证与可审阅材料；最终外部动作等待该请求要求的确认 |

## 本次调整依据

2026-09-30 检查发现本仓库没有独立 `AGENTS.md` 或项目技能；上级工作区文件还保留“先读 MAP”的步骤，是否自动加载取决于宿主的指令发现范围。用户提供的科研协作原则已包含自主执行、按需读取与适度验证；主要需要调整的是贡献指南与 PR 模板堆叠的日常检查。此次新增项目入口并按改动路由检查，同时修正 CI 平台描述、虚拟环境用法和机器专属 PDF 渲染路径。完整发布、输出保护和科学证据要求仍按各自契约执行。

官方依据核对于 2026-09-30：

- [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)：按任务读取文档，精简技能描述与固定步骤，明确完成标准。
- [GPT-6 prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra)：说明自主执行和真实决策边界，按风险选择验证，明确何时并行。
- [AGENTS.md 加载规则](https://learn.chatgpt.com/docs/agent-configuration/agents-md) 与 [技能发现和编写](https://learn.chatgpt.com/docs/build-skills)：项目约定使用标准文件，技能使用仓库 `.agents/skills/` 目录。

这些是工作流设计的依据。科研定义、实验接受标准与软件输出契约来自本项目和实际证据，不能从模型能力推导。
