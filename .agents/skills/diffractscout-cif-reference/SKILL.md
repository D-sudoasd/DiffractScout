---
name: diffractscout-cif-reference
description: Generate and verify theoretical XRD peak tables and Excel from local CIFs in DiffractScout. Use for CIF reference exports, not experimental fitting or general code edits.
---

# 本地 CIF 理论峰表

从用户指定的本地 CIF 生成可追溯理论峰表，交付 Excel 与保留来源、设置和完整性信息的结果包。使用现有 `quick-export`、`verify` 和 `inspect`；不另写衍射引擎。

## 输入与选择

- 定位用户指定文件或目录，核对 CIF 身份、有效数据块和原文件哈希。输出使用新目标，与输入目录分离；保留原始 CIF。
- 使用已授权的辐射条件和扫描范围。仅对普通实验室快速参考、且用户未指定实验条件的请求，可以声明采用 `Cu Ka`（λ=1.5406 Å）、2θ=5–120° 的程序默认值。
- 同步辐射或与实测谱比较缺少波长/能量时，先完成文件清点，再询问该关键条件。波长为 Å、能量为 keV，二者选择一种；预设与显式覆盖的规则见 [CLI](../../../docs/CLI.md)。
- 只要峰表时使用 `--no-patterns`；没有合适弹性输入或未请求弹性时使用 `--no-elasticity`。需要谱图或弹性时按请求选择已有选项，不把这些简化参数强加给用户。

## 执行示例

从仓库根目录使用装有依赖的 Python。Windows 已验证系统环境可用 `py -3`；虚拟环境使用其 `Scripts/python.exe`。如下是实验室参考示例，输入、输出和辐射条件按实际请求替换：

```powershell
py -3 scripts/diffractscout_entry.py quick-export "sample.cif" -o "outputs/sample.xlsx" --source "Cu Ka" --two-theta-min 5 --two-theta-max 120 --no-elasticity --no-patterns
py -3 scripts/diffractscout_entry.py verify "outputs/sample_bundle"
py -3 scripts/diffractscout_entry.py inspect "outputs/sample_bundle"
```

`-o sample.xlsx` 同时产生 `sample_bundle/`。以命令返回的实际路径为准。请求的 `.xlsx` 或对应的 `<stem>_bundle/` 任一已存在时，选择新的输出名称；不要自动覆盖、删除旧结果或更改 manifest 使校验通过。

默认文本输出已包含运行摘要。只有需要机器解析时使用 `--json`；完整导出 JSON 可能含大量中间计算，应保存到结果包外的新日志文件，再读取需要的字段，避免把整个响应塞入上下文。

## 核验与交付

- 查看退出码和逐物相诊断。校验成功只说明包的完整性；仍需检查是否有可分析物相、反射，以及失败或警告的 CIF。错误诊断不能被“Excel 已创建”掩盖。
- 对照 `provenance.json`、`phase_summary.csv`、`peak_reference.csv` 和工作簿的 `Peaks`、`Diagnostics`，检查输入身份、辐射条件、扫描范围、峰数和单位是否一致。
- 命名源模式下，`analysis_settings.wavelength_A=null` 表示没有显式波长覆盖；已解析的有效波长从 `phase_summary.csv` 的 `wavelength_A` 读取，不能把设置空值当成未指定辐射条件。
- 用导出波长与 d 独立检查 Bragg 几何，并检查 `q=2π/d`、`g=1/d`；强度通道、系统消光与弹性方向的含义按 [科学约定](../../../docs/SCIENTIFIC_CONTRACTS.md) 解读。未出现的峰还可能涉及范围、阈值或重叠，不能直接视作物相不存在。
- `sample.xlsx` 是结果包中工作簿的副本；交付前核对副本与包内 `results.xlsx` 的哈希。需要编辑时另存副本，保留可验证的包内文件。
- 给出 Excel 和结果包的实际位置、采用的条件、核验结果及具体警告。说明它是 CIF 平均结构的运动学理论参考；实验物相识别、定量结果或机制结论需要各自的实验依据。

完成边界是用户要求的参考文件已经产生并核验。原始输入缺损或关键条件未解决时明确报告缺口，继续完成可独立执行的部分；不把诊断包或空峰表报为完整参考。
