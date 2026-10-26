# FastNSA QGIS 插件

FastNSA 为 QGIS 桌面端和 Processing Toolbox 提供高性能网络空间分析。
`0.1.0-rc5` 候选版包含四条工作流：

- 最近边预处理，输出可复用的 `edge_id`、`offset`、`distance` 和
  `network_sig`；
- 使用 ADA 或 LION 的网络核密度可视化（NKDV）；
- 使用 NS（精确）或 STARS（近似）的网络 K 函数；
- 使用 RQS、SPS、EAR、MTS 或 EARTH 的时空网络 K 函数。

时空 NKDE、OSM 下载和暂停后继续不属于 `0.1.0` 的发布范围。

## 运行要求

- 候选平台：Linux x86_64 和 Windows AMD64
- QGIS 3.34 或更高版本，使用 Qt5
- QGIS 环境中的 Python 3.11 或更高版本
- QGIS Python 环境中可导入 NumPy
- 与内置原生库兼容的 C++ 系统运行库

发布 ZIP 内含轻量 FastNSA Python runtime，以及 Linux 的 `libfastnsa.so`
或 Windows 的 `fastnsa.dll`，不要求
GeoPandas、Shapely、NetworkX 或 OSMnx。Matplotlib 是可选依赖，仅用于
交互式时空 3D 曲面；缺少它不会影响结果表和二维视图。

候选包由 CI 从已测试的 Linux/Windows wheel 生成。Linux runtime 使用
manylinux2014 构建，旧 RC2 的 GLIBC/GLIBCXX 要求不适用于当前候选包。
请以对应产物的构建信息和验证报告为准。macOS 插件安装包暂不提供。

Windows 验收目标为 QGIS 3.34、Python 3.12.7、NumPy 1.26.4、Qt 5.15.13。
RC4 在该环境的人工测试未发现平台兼容性问题，但本轮源码修复仍需用新包
复测，不能直接沿用旧包的验收结论。CI 覆盖 Python 3.11/3.12 和
NumPy 1.26.4；QGIS 4.x 与 Qt6 暂未纳入发布支持范围。

## 安装

1. 下载与操作系统和架构匹配的插件 ZIP。
2. 在 QGIS 中打开 **插件 > 管理并安装插件 > 从 ZIP 安装**。
3. 选择 ZIP 并启用 **FastNSA**。
4. 从工具栏或插件菜单打开主界面；四个算法也会出现在
   **Processing 工具箱 > FastNSA** 中。

如果 Processing Provider 没有立即出现，请重启 QGIS。启动诊断会报告
NumPy、原生库或 ABI 依赖问题。开发环境和打包说明见
[DEPENDENCIES.md](DEPENDENCIES.md)。

完整文档以英文版 [FastNSA QGIS User Guide](docs/index.md) 为主，中文版
README 和[时间字段指南](docs/TIME_GUIDE_ZH.md)作为补充。

## 数据要求

- 道路输入必须是投影 CRS 下的线图层，地图单位应适合距离分析。
- 事件输入必须是具有有效 CRS 的点图层；必要时会转换到道路 CRS。
- 时空 K 函数还需要非空且至少包含两个不同值的时间字段。

不要直接用经纬度道路图层进行距离分析，应先将道路重投影。

## 推荐流程

1. 如果同一批事件需要多次分析，先运行 **Fast Nearest Edge Matching**。
2. 将 Matched Points 作为 NKDV、Network K 或 ST Network K 的事件输入，
   插件会复用有效的 `edge_id` 和 `offset`，避免重复匹配。
3. 保持道路图层不变。插件会比较 `network_sig`，不兼容时拒绝复用。
4. 探索阶段使用临时输出；需要跨项目保存时使用 GeoPackage 或 CSV。

主界面还会缓存未修改道路对应的原生网络。Activity Log 会记录 cache
hit、cache miss 和 cache invalidated。

## 分析说明

### Network KDE / NKDV

发布界面只开放已验证的 ADA、LION 和 Epanechnikov 核。输出为带 density
字段的 lixel 线段。默认 Turbo 样式支持 Quantile（等量）、Equal interval、
可配置分级数以及零密度独立颜色。归一化会在样式分级之前完成。

### Network K-function

NS（精确）和 STARS（近似）输出距离阈值、观测 K、理论 K 和可选 Monte Carlo 包络。
交互测试默认 5 次模拟；确认数据和阈值无误后再提高模拟次数。主界面可查看
图表；主界面和 Processing 均可输出临时无几何结果表，并独立选择保存 CSV。
epsilon 仅用于 STARS 采样，在 NS 下禁用；它不是保证误差百分比。

### Spatiotemporal Network K-function

时间字段支持自动识别、日期时间、普通数值、Unix 秒和 Unix 毫秒；分析单位
支持秒、分钟、小时和天。详细规则与示例见
[时间字段指南](docs/TIME_GUIDE_ZH.md)。

结果窗口提供表格、摘要、二维曲面和包络视图。仅在 Matplotlib 可用时启用
交互式 3D 曲面。

## 进度与取消

分析以非模态 `QgsTask` 运行，并按情况显示输入验证、道路转换、事件匹配、
原生计算、Monte Carlo、输出写入和样式应用等阶段。

点击 **Hide Windows & Run in Background** 可隐藏任务和插件窗口并继续操作
地图；FastNSA 工具栏按钮或状态栏中的 **Show** 可以恢复任务详情。点击
**Cancel** 会请求协作式取消，较长的原生步骤可能需要到达下一个安全检查点
才会停止；取消后不会完成输出写入。

## 常见问题

- **插件无法加载：** 查看启动诊断中的 NumPy、原生库、GLIBC/GLIBCXX 或
  C++ 运行库信息。
- **无法使用 3D：** 在 QGIS Python 环境安装 Matplotlib；其他功能不受影响。
- **Matched Points 被拒绝：** 道路网络在预处理后发生变化，请重新匹配。
- **运行时间过长：** 先减小阈值网格并使用不超过 5 次模拟，再查看日志中的
  adapter 和 cache 信息。
- **原生崩溃导致 QGIS 退出：** 提交 issue 时附上输入说明、方法、参数、平台、
  QGIS 版本和插件日志。

## 发布状态

候选包拟通过项目自有 release archive 分发。Linux、Windows 和 macOS 原生库及
wheel CI 基线已通过，但不替代 QGIS 插件人工验收；macOS 插件包仍延期。
[QGIS 官方插件仓库要求](https://plugins.qgis.org/docs/publish/)明确禁止插件包包含
二进制文件。当前自包含 ZIP 仅用于项目自有渠道分发，不能直接提交官方仓库。
官方仓库版本还需要实现外部 FastNSA 安装、依赖查找和独立打包，目前尚未提供。

## 算法论文

- 最近边匹配：[Ye 等，KDD 2026](https://doi.org/10.1145/3770855.3817711)
- ADA：[Chan 等，PVLDB 2021](https://doi.org/10.14778/3461535.3461540)
- LION：[Chan 等，PVLDB 2024](https://doi.org/10.14778/3648160.3648168)
- Network K-function：[Chan 等，PVLDB 2022](https://doi.org/10.14778/3551793.3551836)
- STARS：[Ye 等，KDD 2026](https://doi.org/10.1145/3770855.3817709)
- EARTH：[Chan 等，KDD 2026](https://doi.org/10.1145/3770855.3817706)

科研报告中应引用所选方法对应的论文，并同时记录 FastNSA 版本、参数和随机
种子。

## 支持

- 源码：<https://github.com/fastnsa/FastNSA-QGIS>
- 问题反馈：<https://github.com/fastnsa/FastNSA-QGIS/issues>
- 英文用户手册：[docs/index.md](docs/index.md)
- 英文说明：[README.md](README.md)
