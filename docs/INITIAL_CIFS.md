# 初始 CIF 准备 / Initial CIF preparation

`prepare-cifs` 生成可载入后续拟合软件的初始平均结构。当前相族为 Ti 常见的
α（hcp，194）、β（bcc，229）和 α″（Cmcm，63）。它检查结构是否适合该母相
原型，不判断实验里有哪些相，不进行精修，也不把数据库或相近合金参数当作
当前样品的实测值。

## 最短使用路径

```powershell
diffractscout prepare-cifs TC4 -o outputs/TC4_initial --offline
diffractscout verify outputs/TC4_initial
```

主窗口的“初始 CIF”菜单提供同一功能，可选相、选成分基准、浏览参数文件和
逐相模板，完成后载入 `initial/` 中的 CIF 继续分析。输出目录必须是一个新目录。

TC4、Ti64、Ti-6Al-4V 在这个准备入口中默认展开为名义 6 wt% Al、4 wt% V、
余量 Ti。其它合金必须给出完整百分比。例如：

```powershell
diffractscout prepare-cifs Ti-Nb -o outputs/TiNb_initial --at Ti=80,Nb=20 --offline
```

百分比必须为正，合计 100±0.05。质量分数先按原子量换算成原子分数，占位
保留五位小数且和为 1。宿主由最大的原子分数确定，平分时须用 `--host`。
显式宿主必须属于输入体系。该成分描述的是金属替代位点；O、N、C 等间隙
元素需要独立位点模型，不能以百分比直接替代金属位点。

`discover`、`run` 的同名牌号仍只表示元素集合。`prepare-cifs` 的名义成分
语义不改变已有分析行为。

## 提供目标相的参数

复制 [phase_parameters.template.json](../examples/phase_parameters.template.json)，
只填写有来源的值：

```powershell
Copy-Item examples/phase_parameters.template.json my_phase_parameters.json
diffractscout prepare-cifs TC4 -o outputs/TC4_cited --offline --parameters my_phase_parameters.json
```

文件使用 `schema: "diffractscout_phase_parameters_v1"` 和 `phases` 对象。
每相接受以下字段，未知字段、重复字段、无效数值和未选中的相会被拒绝：

| 字段 | 含义 |
|---|---|
| `lattice` | a、b、c（Å）和 alpha、beta、gamma（°）；空对象保留原型 |
| `fract` | 分数坐标 x、y、z；空对象保留原型 |
| `citation` | 晶格或坐标有输入时必填；建议 DOI、论文、表/图位置 |
| `conditions` | 参数的温度、热处理、应力/应变状态、测量方法及适用范围 |
| `weight_percent` | 该相的完整质量百分比字符串，如 `Ti=90,Al=6,V=4` |
| `atomic_percent` | 该相的完整原子百分比字符串；与其它成分基准互斥 |
| `nominal` | 该相明确采用名义牌号时使用；与其它成分基准互斥 |

整体成分是默认起始假设。相参数中显式给出的成分会替代该相的整体成分，
报告写成 `caller_supplied_phase`；软件不会把调用者输入自行认证为实测相成分。
马氏体可能继承母相成分，平衡 α/β 通常存在元素分配；这两种情况需要调用者
根据证据选择。没有相成分时仍可生成初始模型，但报告明确其假设。

晶格只需填写独立参数：α 的 a、c，β 的 a，α″ 的 a、b、c。
六方/四方 a=b、立方 a=b=c 会自动联动，并在 `.adapt.json` 中记录。
显式输入互相冲突的等价轴、破坏所需对称性的角度或坐标，会让该相失败。
Cmcm 的 y 是独立内坐标；没有文献或拟合依据时保留来源值，并列为待调整项。

程序不会获取或解析论文。代理或使用者查文献时，应优先匹配目标合金、相、
温度和处理条件，并记录引用；输入引用本身不等于软件已验证引用内容。
没有目标证据时允许交付明确标注的原型起始模型，不能称为目标样品的实测结构。

## 原型选择与质量检查

明确指定的 `--template alpha=path.cif` 等逐相模板具有最高优先级。
模板不适配时该相失败，不会静默换成别的模板。

在线模式读取 `MP_API_KEY`（CLI/GUI）或显式 `api_key`（API）。先查询宿主
单质，再按需查询体系子集；访问前检查 `--max-subsystems`（默认 64）。候选
排序优先宿主单质，其次能量和 ID。不会以 energy-above-hull 阈值排除亚稳
母相。每相默认最多尝试 8 个数据库候选，可用 `--max-prototype-attempts`
增加尝试数；未尝试的候选数、选择/拒绝依据留在 `preparation.json`，避免将
预算限制误报为所有候选均不合格。`max_subsystems` 控制查询个数，不控制
每次查询返回的条目总量；需要更窄检索时使用明确模板和相选择。

实际 CIF 必须同时满足：

- 声明空间群、Gemmi 读取和 spglib 搜索一致；
- 实际原子构成一条完全占据的金属替代轨道，常规晶胞有 2/2/4 个金属位点；
- Cmcm 原型为 4c 轨道；多轨道化合物不能仅凭空间群编号混入；
- 位点占位和为 1，目标元素、正体积和质量可检查；
- 最终化学式、Z、化学式质量与展开后的占位/多重性一致。

数据库 P1 CIF 可以由其完整、带元素/混合占位身份的原子列表独立恢复空间群，
使用 `symprec=0.001 Å` 的标准常规晶胞。恢复过程会理想化容差内的坐标/晶格；
报告记录容差与恢复状态，原始文件原样归档。错误的非 P1 声明不能借此被强行
改成指定空间群。相关算法定义见 [spglib dataset 文档](https://spglib.readthedocs.io/en/latest/dataset.html)。

Ti 缺少合格数据库结构、网络不可用或处于离线模式时，有三份带出处的备用原型：

| 相族 | 来源 | 必须保留的解释 |
|---|---|---|
| α | COD 1522498，McHargue 等，1953 | Ti–2.6 at% Nb 原型，晶格不属于目标 TC4 |
| β | COD 9008554 / AMCSD 0011232，Wyckoff，1963 | 纯 β-Ti，来源为 1173 K，不是目标合金室温测量 |
| α″ | COD 1523304，Brown 等，1964 | Ti–20 at% Nb 原型，y=0.20 不是目标合金内坐标 |

这些备用原型只用于 Ti 宿主。其它宿主需要合格数据库候选或明确模板，
不会收到 Ti 的备用文件。声明的相族不等于相在当前样品中存在。
原始 CIF 的许可/引用保留，见 [NOTICE.md](../NOTICE.md)。

## 输出与完成状态

| 文件 | 用法 |
|---|---|
| `initial/*.cif` | 交付的初始模型；显式完整空间群操作和混合占位 |
| `initial/*.adapt.json` | 逐相成分基准、参数变更、联动轴、原型来源和输入/输出哈希 |
| `sources/*.cif` | 未改写的原始来源，包含原始文献及许可信息 |
| `prototypes/*.cif` | 经过实际原子检查的适配原型 |
| `report.md` | 逐相条件、初始假设、继承参数和后续拟合建议 |
| `initial_cifs.csv` | 易于浏览的逐相状态索引 |
| `peak_preview.csv` | 5–120° 理论峰表，默认 λ=1.5406 Å；`--preview-wavelength` 可改 |
| `preparation.json` | 结构检查、候选/拒绝依据、provider 元数据、输入参数及软件版本 |
| `manifest.json` | 所有文件的 SHA-256 和大小，可用 `diffractscout verify` 复核 |

`lattice_basis` 为 `prototype_lattice`、`mixed_cited_and_prototype_lattice`
或 `caller_cited_lattice`，分别表示原型、混用、独立晶轴全部使用引用输入。
`ready` 表示可读取且符合该原型的结构检查，不代表已经完成样品精修。
初始 CIF 清除原来源的测量/物性标签，避免把原型温度、密度或文献信息当成
派生模型的实测属性；原始信息仍在 `sources/` 与来源记录中。

峰表的 q=2π/d，强度在每相内独立归一到 100，是平均结构的运动学理论参考，
不能用于确定相含量。不同相的归一强度不可直接比较。

退出码：0 为所有请求相均生成；3 为部分相生成；2 为无可用 CIF 或致命输入
错误。逐相失败也会有报告和可校验包；输入格式错误在创建包前报错。
所有输出先在私有临时目录生成并检查，再发布到新目录；已有目录、源 CIF
及实验数据不会被覆盖。可进一步运行：

```powershell
diffractscout analyze outputs/TC4_initial/initial -o outputs/TC4_peak_tables
```
