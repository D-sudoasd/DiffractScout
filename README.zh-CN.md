<p align="center">
  <img src="docs/assets/hero.svg" width="100%" alt="DiffractScout：可追溯的候选相筛选与理论粉末衍射参考工作流。">
</p>

# DiffractScout 中文说明

**DiffractScout 将合金/化学体系候选相检索、本地 CIF 检查、理论粉末衍射计算、可选晶面法向弹性分析和可验证结果导出连接为一个流程。** 每项结果均可追溯到数据库记录或本地文件、CIF 哈希、辐射条件、计算定义、软件版本和结构化诊断。

[英文主页](README.md) · [GUI 使用说明](docs/GUI.md) · [科研计算约定](docs/SCIENTIFIC_CONTRACTS.md) · [验证策略](docs/VALIDATION.md) · [解析基准](docs/ANALYTIC_BENCHMARKS.md) · [JOSS 准备状态](docs/JOSS_READINESS.md)

## 两类工作流

| 工作流 | 输入 | 主要输出 |
|---|---|---|
| 本地 CIF 分析 | 单个或多个 CIF、CIF 文件夹 | 结构检查、理论峰表、可选 `Cij` 配对、连续显示谱线、诊断和校验清单 |
| Materials Project 流程 | 合金牌号、化学式、化学体系或 `mp-` 编号 | 候选相、常规标准晶胞、可选 DFT 弹性张量、理论衍射表、来源记录和校验清单 |

基础安装可以离线分析本地 CIF。Materials Project 支持为可选依赖，API 密钥由用户自行提供。

## 图形界面

```bash
python -m pip install -e .
diffractscout-gui
# 等价命令：diffractscout gui
```

<p align="center">
  <img src="docs/assets/gui-local.png" width="49%" alt="DiffractScout 本地 CIF 分析界面">
  <img src="docs/assets/gui-materials-project.png" width="49%" alt="DiffractScout Materials Project 流程界面">
</p>

界面提供：CIF 文件与文件夹批量选择、递归扫描、光源/能量/波长、`2θ` 范围、步长、FWHM、伪 Voigt 混合参数、弹性配对、候选相数量上限、倒易空间资源限制、覆盖授权、运行状态、结构化日志和结果目录入口。API 密钥只保存在当前进程内存中，不写入项目文件。

## 安装

本地 CIF 分析：

```bash
git clone https://github.com/D-sudoasd/DiffractScout.git
cd DiffractScout
python -m pip install -e .
```

Materials Project 支持：

```bash
python -m pip install -e ".[mp]"
```

开发与测试：

```bash
python -m pip install -e ".[test]"
pytest -q
```

## 离线验证

```bash
diffractscout demo -o outputs/demo
diffractscout verify outputs/demo
```

演示使用明确标注的合成 FCC 结构和合成各向同性刚度张量，不包含实验材料性能数据。

## 解析科学基准

```bash
diffractscout benchmark -o outputs/analytic_benchmark
```

该命令对简单立方、BCC、FCC、NaCl 和立方晶体方向弹性执行 45 项闭式解检查，并输出固定输入、预期值、容差、软件版本、运行环境、报告和 SHA-256 清单。成功结果为 `45/45 passed`。详见 [docs/ANALYTIC_BENCHMARKS.md](docs/ANALYTIC_BENCHMARKS.md)。

## 本地 CIF 分析

```powershell
diffractscout analyze D:\path\to\cifs -o D:\results\diffractscout_run
```

83 keV 同步辐射示例：

```powershell
diffractscout analyze D:\path\to\cifs -o D:\results\run_83keV `
  --energy-keV 83 --two-theta-min 0.5 --two-theta-max 15 `
  --step 0.005 --fwhm 0.03
```

当 CIF 旁存在唯一、可验证的弹性侧车或索引记录时，软件检查 6×6 `Cij` 并计算晶面法向杨氏模量。`--no-elasticity` 会关闭弹性文件发现、复制和计算。

批处理命令使用明确退出码：`0` 表示全部成功，`3` 表示结果包可用但存在失败对象，`2` 表示没有可分析物相或出现致命输入/配置错误。详细状态保存在 `diagnostics.csv`。

## Materials Project 完整流程

```powershell
$env:MP_API_KEY = "your-key"
diffractscout run "Ti-Al-V" -o D:\results\ti_al_v `
  --mode near_stable --e-hull-max 0.05 `
  --max-subsystem-order 3 --max-subsystems 4096 --max-total 50
```

默认下载常规标准晶胞。自动方向弹性计算采用与该晶胞设置配对的 raw/POSCAR 格式张量。仅有 IEEE 格式张量时，状态标记为 `frame_transform_required`，方向模量保持空值，直至提供经过验证的坐标变换。原胞下载需要同时使用 `--no-elasticity`。软件会在访问数据库前估算化学子体系查询数量，超过 `--max-subsystems`（默认 4096）时停止，避免高元体系产生组合式查询膨胀。

## 结果包与写入安全

程序先在同级临时目录生成全部结果并执行完整性校验，通过后才移动到目标目录。覆盖已有结果需要同时满足：

1. 用户明确授权覆盖；
2. 目标目录包含已识别的 DiffractScout 清单；
3. 现有结果包当前能够通过 SHA-256 和文件清单校验。

查询、计算、导出或校验失败时，上一份有效结果不会被提前删除。

主要文件包括：

- `phase_summary.csv`：CIF 哈希、晶胞、空间群、占位和结构警告；
- `peak_reference.csv`：`hkl`、`d`、`2θ`、`q`、`g`、多重性、结构因子、LP/无 LP 通道及可选方向模量；
- `candidate_index.csv`、`download_index.csv`：候选相、下载和弹性查询状态；
- `diagnostics.csv`：检索、下载、弹性和结构分析中的结构化警告与错误；
- `results.xlsx`：对应的人类可读工作簿；
- `provenance.json`：计算设置、定义、来源与软件版本；
- `manifest.json`：文件 SHA-256 与字节数清单。

`diffractscout verify` 会拒绝文件缺失、内容修改、重复/不安全路径、符号链接以及未列入清单的新增文件。

## 科学适用边界

当前版本输出运动学理论粉末衍射参考。它不执行实验物相自动鉴定、Rietveld/Le Bail/Pawley 精修、定量物相分析、探测器或仪器标定、背景拟合、织构/吸收修正、尺寸与微应变分析或绝对强度标定。

理论强度通道为：

```text
I_no_LP   = 多重性 × |F_xray|²
I_with_LP = I_no_LP × LP(θ)
J_with_LP = I_with_LP / V_cell²
J_no_LP   = I_no_LP / V_cell²
```

兼容字段 `material_scattering_factor_R_hkl` 和 `material_scattering_factor_R_hkl_no_lp` 对应上述两个 `J` 通道。它们不表示晶体学残差因子、标准化定量物相系数或实验标定散射因子。连续伪 Voigt 谱线用于显示，峰宽和混合参数均由用户指定。

详细公式、单位、弹性 Voigt 约定、坐标系规则、资源上限和排除项见 [docs/SCIENTIFIC_CONTRACTS.md](docs/SCIENTIFIC_CONTRACTS.md)。

## 验证与 JOSS 状态

当前离线套件包含 68 项自动测试，并另有 45 项解析科学基准。覆盖范围包括成分解析、子体系枚举及组合数量上限、大小写 CIF 扫描、同名文件防覆盖、CIF 数据块和空间群解析、特殊位置占位转换、系统消光、解析结构因子、Bragg 几何、边界反射、刚度单位换算、弹性张量检查、侧车配对、资源限制、数据库失败语义、事务式输出、电子表格安全、确定性证据归档、严格清单校验和投稿准备检查。GitHub Actions 还配置了多 Python 版本、Windows/macOS、Linux 无头 GUI、wheel 安装、解析基准、发布制品、月度复现审计、依赖更新和 JOSS 论文构建。月度定时运行只记录某一公开提交的可复现状态；只有由真实缺陷、依赖更新、验证、文档改进或用户反馈形成的公开提交、Issue、Pull Request 或 Release 才构成开发活动证据。

JOSS 正式投稿仍需要真实的六个月公开开发记录、归档发布 DOI、真实材料独立验证、研究使用证据和外部互动记录。执行 `python scripts/joss_readiness.py --output build/joss-readiness` 可生成阻塞项报告；工作计划见 [docs/JOSS_6_MONTH_PLAN.md](docs/JOSS_6_MONTH_PLAN.md)。

## 来源与许可

DiffractScout 整合并重构了同一作者维护的两个 MIT 项目中的功能：

- `PhaseScout`
- `CIF2Peaks`

两个原仓库保持独立，未因本项目修改。来源快照、保留功能、架构变化和许可证说明见 [docs/SOURCE_LINEAGE.md](docs/SOURCE_LINEAGE.md) 与 [NOTICE.md](NOTICE.md)。

许可证：MIT。引用元数据见 [CITATION.cff](CITATION.cff)。
