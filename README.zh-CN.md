# DiffractScout 中文概览

DiffractScout 将候选相检索、CIF 来源记录、结构检查、理论粉末衍射峰计算和晶面法向弹性模量计算合并为一个可追溯流程。

## 主要输入

- 合金牌号，例如 `Ti-6Al-4V`；
- 化学体系，例如 `Ti-Al-V`；
- Materials Project 编号，例如 `mp-149`；
- 本地 CIF 文件或文件夹。

## 主要输出

- 候选相及其 Materials Project 来源；
- CIF 哈希、晶胞、空间群、占位和结构警告；
- `hkl`、`d`、`2θ`、`q`、`g`、多重性、结构因子平方和洛伦兹-偏振项；
- 存在可靠 6×6 `Cij` 时的晶面法向杨氏模量；
- CSV、Excel、来源记录和 SHA-256 清单。

## 离线验证

```bash
python -m pip install -e .
diffractscout demo -o outputs/demo
diffractscout verify outputs/demo
```

演示中的晶体结构和弹性张量均为明确标注的合成测试数据。

## 本地 CIF 分析

```bash
diffractscout analyze D:\path\to\cifs -o D:\results\diffractscout_run
```

## Materials Project 完整流程

```powershell
$env:MP_API_KEY = "your-key"
diffractscout run "Ti-Al-V" -o D:\results\ti_al_v `
  --mode near_stable --e-hull-max 0.05 --max-total 50
```

该流程默认下载常规标准晶胞。自动计算晶面法向杨氏模量时，采用 Materials Project 文档说明与该晶胞设置一致的 raw/POSCAR 格式弹性张量。仅有 IEEE 格式张量时，程序保留其来源与数值，状态标记为 `frame_transform_required`，在缺少显式坐标旋转时不输出方向模量。使用 `--primitive` 时必须同时使用 `--no-elasticity`。所有 DFT 弹性数据均明确标记为计算数据。

## 适用边界

当前版本输出理论粉末衍射参考，不执行实验物相鉴定、Rietveld 精修、定量物相分析、仪器标定、背景估计、织构校正、吸收校正或绝对强度标定。连续峰形用于显示，不代表真实仪器函数。输出中的 `R_hkl` 名称为兼容 CIF2Peaks 旧模式而保留，表示按晶胞体积平方归一化的理论强度通道；它不是晶体学残差因子、标准化定量物相系数或实验标定散射因子。

详细内容见英文 [README](README.md) 和 [科研计算约定](docs/SCIENTIFIC_CONTRACTS.md)。
