# FastNSA QGIS 时空分析时间字段指南

本文是 QGIS 插件的用户文档，随插件发布包一起提供。

## 时间解释选项

Spatiotemporal Network K-Function 会先把时间转换为相对于最早事件的时间差。平移时间起点不会改变事件之间的时间距离，同时可避免直接使用大型 Unix 时间戳造成数值精度问题。

| 时间解释 | 适用数据 | 行为 |
| --- | --- | --- |
| Auto detect | 推荐默认选项 | QGIS 日期/时间和可解析日期字符串按日期时间处理；纯数值字段按普通数值处理。混合字段会被拒绝。 |
| Date / datetime | QGIS Date、DateTime 或 ISO 日期字符串 | 强制按日期时间解析。 |
| Numeric values | 小时序号、天序号等业务数值 | 保留数值之间的差值，不执行 Unix 时间戳换算。 |
| Unix timestamp (seconds) | 例如 `1767225600` | 按 Unix 秒解析，再转换为所选分析单位。 |
| Unix timestamp (milliseconds) | 例如 `1767225600000` | 先除以 1000，再转换为所选分析单位。 |

## 分析时间单位

- `Auto`：日期时间和 Unix 时间戳使用天；普通数值保留图层原单位。
- `Seconds / Minutes / Hours / Days`：日期时间和 Unix 时间戳会转换为对应单位。
- 对普通数值字段，选择的单位只声明数值本身的业务单位，不会再次缩放。例如字段值 `0, 1, 2` 表示天时，应选择 `Numeric values + Days`。

界面中的 Temporal min、max 和 step 必须使用最终分析单位。运行日志、结果窗口、Processing 结果表和 CSV 会显示实际采用的单位、解释模式和时间起点。

## 推荐示例

- QGIS DateTime 字段：选择 `Auto detect + Auto`，时间阈值 `0–30` 表示 0 到 30 天。
- Unix 毫秒字段：选择 `Unix timestamp (milliseconds) + Days`。
- 已计算的事件日序号：选择 `Numeric values + Days`。
- 秒级传感器事件：选择 `Date / datetime + Seconds`，或对 Unix 秒字段选择 `Unix timestamp (seconds) + Seconds`。

## Nearest-edge 预处理复用

Matched Points 会保留原始事件属性，因此时间字段可直接用于后续 ST K-Function。输出还包含 `network_sig`：

- 指纹与当前道路网络一致时，可直接复用 `edge_id` 和 `offset`。
- 指纹不一致时，插件会拒绝运行并要求重新执行 nearest-edge matching。
- 旧图层没有 `network_sig` 时暂时允许运行，但会提示无法验证兼容性。

修改道路几何、CRS、要素顺序或拆分方式后，应重新生成 Matched Points。
