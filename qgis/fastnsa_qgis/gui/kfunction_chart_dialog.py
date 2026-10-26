"""Chart dialog for displaying FastNSA K-function results inside QGIS."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass
class _SeriesSpec:
    name: str
    x_values: list[float]
    y_values: list[float]
    color: str
    width: float = 2.0
    style: Qt.PenStyle = Qt.SolidLine


class _PlotCanvas(QWidget):
    """Lightweight custom chart canvas that avoids a QtCharts dependency."""

    def __init__(
        self,
        *,
        title: str,
        x_label: str,
        y_label: str,
        series: list[_SeriesSpec],
        band: tuple[list[float], list[float], str] | None = None,
        include_zero: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.title = title
        self.x_label = x_label
        self.y_label = y_label
        self.series = series
        self.band = band
        self.include_zero = include_zero
        self.setMinimumHeight(260)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fcfcfd"))
        self._draw_title(painter)

        x_values, y_values = self._collect_ranges()
        if len(x_values) < 2 or not y_values:
            plot_rect = QRectF(96, 28, max(120, self.width() - 120), max(120, self.height() - 112))
            self._draw_empty_message(painter, plot_rect)
            return

        x_min = min(x_values)
        x_max = max(x_values)
        y_min = min(y_values)
        y_max = max(y_values)

        if self.include_zero:
            y_min = min(y_min, 0.0)
            y_max = max(y_max, 0.0)

        if x_max <= x_min:
            x_max = x_min + 1.0
        if y_max <= y_min:
            pad = 1.0 if y_min == 0.0 else abs(y_min) * 0.1
            y_min -= pad
            y_max += pad

        y_pad = (y_max - y_min) * 0.08
        y_min -= y_pad
        y_max += y_pad

        y_tick_labels = [
            self._format_value(y_min + (y_max - y_min) * index / 5)
            for index in range(6)
        ]
        label_width = max(
            painter.fontMetrics().horizontalAdvance(label)
            for label in y_tick_labels
        )
        left_margin = max(96, label_width + 58)
        right_margin = 24
        top_margin = 28
        bottom_margin = 84
        plot_rect = QRectF(
            left_margin,
            top_margin,
            max(120, self.width() - left_margin - right_margin),
            max(120, self.height() - top_margin - bottom_margin),
        )

        self._draw_axes(painter, plot_rect, x_min, x_max, y_min, y_max)
        self._draw_grid(painter, plot_rect)

        if self.band is not None:
            lo_values, hi_values, color = self.band
            self._draw_band(painter, plot_rect, x_min, x_max, y_min, y_max, x_values, lo_values, hi_values, color)

        for spec in self.series:
            self._draw_series(painter, plot_rect, x_min, x_max, y_min, y_max, spec)

        self._draw_labels(painter, plot_rect)
        self._draw_legend(painter, plot_rect)

    def _collect_ranges(self):
        x_values: list[float] = []
        y_values: list[float] = []
        for spec in self.series:
            x_values.extend(v for v in spec.x_values if isfinite(v))
            y_values.extend(v for v in spec.y_values if isfinite(v))
        if self.band is not None and self.series:
            lo_values, hi_values, _color = self.band
            y_values.extend(v for v in lo_values if isfinite(v))
            y_values.extend(v for v in hi_values if isfinite(v))
        return x_values, y_values

    def _map_point(self, plot_rect: QRectF, x_min: float, x_max: float, y_min: float, y_max: float, x_value: float, y_value: float):
        x_ratio = 0.0 if x_max == x_min else (x_value - x_min) / (x_max - x_min)
        y_ratio = 0.0 if y_max == y_min else (y_value - y_min) / (y_max - y_min)
        x_pos = plot_rect.left() + x_ratio * plot_rect.width()
        y_pos = plot_rect.bottom() - y_ratio * plot_rect.height()
        return QPointF(x_pos, y_pos)

    def _draw_title(self, painter: QPainter):
        painter.save()
        painter.setPen(QColor("#153243"))
        title_font = painter.font()
        title_font.setPointSize(max(title_font.pointSize(), 10))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(16, 4, self.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        painter.restore()

    def _draw_empty_message(self, painter: QPainter, plot_rect: QRectF):
        painter.setPen(QColor("#64748b"))
        painter.drawText(plot_rect, Qt.AlignCenter, "Not enough data to render this chart.")

    def _draw_axes(self, painter: QPainter, plot_rect: QRectF, x_min: float, x_max: float, y_min: float, y_max: float):
        axis_pen = QPen(QColor("#334155"))
        axis_pen.setWidthF(1.1)
        painter.setPen(axis_pen)
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())

        tick_count = 5
        label_pen = QPen(QColor("#475569"))
        painter.setPen(label_pen)
        for index in range(tick_count + 1):
            x_value = x_min + (x_max - x_min) * index / tick_count
            x_point = self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, y_min)
            painter.drawLine(QPointF(x_point.x(), plot_rect.bottom()), QPointF(x_point.x(), plot_rect.bottom() + 4))
            painter.drawText(
                QRectF(x_point.x() - 40, plot_rect.bottom() + 6, 80, 18),
                Qt.AlignHCenter | Qt.AlignTop,
                self._format_value(x_value),
            )

            y_value = y_min + (y_max - y_min) * index / tick_count
            y_point = self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_min, y_value)
            painter.drawLine(QPointF(plot_rect.left() - 4, y_point.y()), QPointF(plot_rect.left(), y_point.y()))
            painter.drawText(
                QRectF(38, y_point.y() - 9, plot_rect.left() - 48, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                self._format_value(y_value),
            )

    def _draw_grid(self, painter: QPainter, plot_rect: QRectF):
        grid_pen = QPen(QColor("#e2e8f0"))
        grid_pen.setStyle(Qt.DashLine)
        painter.setPen(grid_pen)
        tick_count = 5
        for index in range(1, tick_count):
            x_pos = plot_rect.left() + plot_rect.width() * index / tick_count
            y_pos = plot_rect.top() + plot_rect.height() * index / tick_count
            painter.drawLine(QPointF(x_pos, plot_rect.top()), QPointF(x_pos, plot_rect.bottom()))
            painter.drawLine(QPointF(plot_rect.left(), y_pos), QPointF(plot_rect.right(), y_pos))

    def _draw_band(
        self,
        painter: QPainter,
        plot_rect: QRectF,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        x_values: list[float],
        lo_values: list[float],
        hi_values: list[float],
        color: str,
    ):
        if len(lo_values) != len(hi_values):
            return

        polygon = QPolygonF()
        for x_value, hi_value in zip(x_values, hi_values):
            if isfinite(x_value) and isfinite(hi_value):
                polygon.append(self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, hi_value))
        for x_value, lo_value in reversed(list(zip(x_values, lo_values))):
            if isfinite(x_value) and isfinite(lo_value):
                polygon.append(self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, lo_value))
        if polygon.isEmpty():
            return

        fill_color = QColor(color)
        fill_color.setAlpha(55)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_color)
        painter.drawPolygon(polygon)

    def _draw_series(self, painter: QPainter, plot_rect: QRectF, x_min: float, x_max: float, y_min: float, y_max: float, spec: _SeriesSpec):
        path = QPainterPath()
        started = False
        for x_value, y_value in zip(spec.x_values, spec.y_values):
            if not (isfinite(x_value) and isfinite(y_value)):
                started = False
                continue

            point = self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, y_value)
            if not started:
                path.moveTo(point)
                started = True
            else:
                path.lineTo(point)

        pen = QPen(QColor(spec.color))
        pen.setWidthF(spec.width)
        pen.setStyle(spec.style)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_labels(self, painter: QPainter, plot_rect: QRectF):
        painter.setPen(QColor("#334155"))
        painter.drawText(
            QRectF(plot_rect.left(), plot_rect.bottom() + 24, plot_rect.width(), 18),
            Qt.AlignHCenter | Qt.AlignTop,
            self.x_label,
        )

        painter.save()
        painter.translate(20, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(
            QRectF(-plot_rect.height() / 2.0, -12, plot_rect.height(), 24),
            Qt.AlignCenter,
            self.y_label,
        )
        painter.restore()

    def _draw_legend(self, painter: QPainter, plot_rect: QRectF):
        items = list(self.series)
        if self.band is not None:
            items.append(_SeriesSpec("Envelope", [], [], self.band[2], width=5.0))

        legend_rect = self._legend_rect(plot_rect, items)
        painter.setPen(QColor("#cbd5e1"))
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRoundedRect(legend_rect, 6, 6)

        for index, spec in enumerate(items):
            y_pos = legend_rect.top() + 14 + index * 18
            pen = QPen(QColor(spec.color))
            pen.setWidthF(max(2.0, spec.width))
            pen.setStyle(spec.style)
            painter.setPen(pen)
            painter.drawLine(QPointF(legend_rect.left() + 10, y_pos), QPointF(legend_rect.left() + 34, y_pos))
            painter.setPen(QColor("#334155"))
            painter.drawText(
                QRectF(legend_rect.left() + 40, y_pos - 8, legend_rect.width() - 46, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                spec.name,
            )

    def _legend_rect(self, plot_rect: QRectF, items: list[_SeriesSpec]) -> QRectF:
        legend_width = 160.0
        legend_height = 18.0 * len(items) + 12.0
        margin = 10.0

        candidates = [
            QRectF(plot_rect.right() - legend_width - margin, plot_rect.bottom() - legend_height - margin, legend_width, legend_height),
            QRectF(plot_rect.right() - legend_width - margin, plot_rect.top() + margin, legend_width, legend_height),
            QRectF(plot_rect.left() + margin, plot_rect.bottom() - legend_height - margin, legend_width, legend_height),
            QRectF(plot_rect.left() + margin, plot_rect.top() + margin, legend_width, legend_height),
        ]

        x_values, y_values = self._collect_ranges()
        if len(x_values) < 2 or not y_values:
            return candidates[0]

        x_min = min(x_values)
        x_max = max(x_values)
        y_min = min(y_values)
        y_max = max(y_values)

        if self.include_zero:
            y_min = min(y_min, 0.0)
            y_max = max(y_max, 0.0)
        if x_max <= x_min:
            x_max = x_min + 1.0
        if y_max <= y_min:
            pad = 1.0 if y_min == 0.0 else abs(y_min) * 0.1
            y_min -= pad
            y_max += pad
        y_pad = (y_max - y_min) * 0.08
        y_min -= y_pad
        y_max += y_pad

        best_rect = candidates[0]
        best_score = None
        for rect in candidates:
            score = self._legend_overlap_score(rect, plot_rect, x_min, x_max, y_min, y_max)
            if best_score is None or score < best_score:
                best_score = score
                best_rect = rect
        return best_rect

    def _legend_overlap_score(
        self,
        legend_rect: QRectF,
        plot_rect: QRectF,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
    ) -> float:
        score = 0.0

        for spec in self.series:
            for x_value, y_value in zip(spec.x_values, spec.y_values):
                if not (isfinite(x_value) and isfinite(y_value)):
                    continue
                point = self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, y_value)
                if legend_rect.adjusted(-6, -6, 6, 6).contains(point):
                    score += 1.0

        if self.band is not None and self.series:
            band_x = self.series[0].x_values
            lo_values, hi_values, _color = self.band
            for x_value, lo_value, hi_value in zip(band_x, lo_values, hi_values):
                if isfinite(x_value) and isfinite(lo_value):
                    point = self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, lo_value)
                    if legend_rect.contains(point):
                        score += 0.25
                if isfinite(x_value) and isfinite(hi_value):
                    point = self._map_point(plot_rect, x_min, x_max, y_min, y_max, x_value, hi_value)
                    if legend_rect.contains(point):
                        score += 0.25

        return score

    @staticmethod
    def _format_value(value: float) -> str:
        abs_value = abs(value)
        if abs_value >= 1000:
            return f"{value:.0f}"
        if abs_value >= 10:
            return f"{value:.1f}"
        if abs_value >= 1:
            return f"{value:.2f}"
        return f"{value:.3f}"


class KFunctionChartDialog(QDialog):
    """Display FastNSA K-function results as charts and tables."""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("FastNSA K-Function Result")
        self.setMinimumSize(980, 760)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("FastNSA K-Function Result Viewer")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #153243;")
        layout.addWidget(header)

        meta = QLabel(
            f"Method: {self.result.method or 'Unknown'} | "
            f"Distance thresholds: {len(self.result.r)} | "
            f"Points: {self.result.n_points or 'Unknown'} | "
            f"Network length: {self._format_optional(self.result.network_length)}"
        )
        meta.setWordWrap(True)
        layout.addWidget(meta)

        tabs = QTabWidget()
        tabs.addTab(self._build_chart_tab(), "Chart")
        tabs.addTab(self._build_table_tab(), "Table")
        tabs.addTab(self._build_summary_tab(), "Summary")
        layout.addWidget(tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _build_chart_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        info = QLabel(self._interpretation_text())
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)

        main_series = [
            _SeriesSpec("Observed K(r)", self._float_list(self.result.r), self._float_list(self.result.k_obs), "#b91c1c", 2.2),
        ]
        if self.result.k_theo is not None:
            main_series.append(
                _SeriesSpec("Theoretical K(r)", self._float_list(self.result.r), self._float_list(self.result.k_theo), "#0f766e", 1.8)
            )

        band = None
        if self.result.k_lo is not None and self.result.k_hi is not None:
            band = (
                self._float_list(self.result.k_lo),
                self._float_list(self.result.k_hi),
                "#94a3b8",
            )

        main_plot = _PlotCanvas(
            title="Network K-Function",
            x_label="Network distance r",
            y_label="K(r)",
            series=main_series,
            band=band,
        )
        layout.addWidget(self._framed(main_plot), 1)

        residual_plot = _PlotCanvas(
            title="Residual View",
            x_label="Network distance r",
            y_label="Observed - Theoretical",
            series=[
                _SeriesSpec(
                    "Delta K(r)",
                    self._float_list(self.result.r),
                    self._delta_values(),
                    "#1d4ed8",
                    2.0,
                )
            ],
            band=self._delta_band(),
            include_zero=True,
        )
        layout.addWidget(self._framed(residual_plot), 1)

        return container

    def _build_table_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        headers = ["r", "k_obs", "k_theo", "k_lo", "k_hi", "delta", "status"]
        table = QTableWidget(len(self.result.r), len(headers))
        table.setHorizontalHeaderLabels(headers)

        delta_values = self._delta_values()
        statuses = self._status_values()

        for row_index, distance in enumerate(self.result.r):
            values = [
                distance,
                self.result.k_obs[row_index],
                self.result.k_theo[row_index] if self.result.k_theo is not None else "",
                self.result.k_lo[row_index] if self.result.k_lo is not None else "",
                self.result.k_hi[row_index] if self.result.k_hi is not None else "",
                delta_values[row_index],
                statuses[row_index],
            ]
            for col_index, value in enumerate(values):
                if isinstance(value, str):
                    item = QTableWidgetItem(value)
                else:
                    item = QTableWidgetItem("" if value == "" else f"{float(value):.6f}")
                table.setItem(row_index, col_index, item)

        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        return container

    def _build_summary_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText(
            "\n".join(
                [
                    f"Method: {self.result.method or 'Unknown'}",
                    f"Number of distance thresholds: {len(self.result.r)}",
                    f"Number of points: {self.result.n_points or 'Unknown'}",
                    f"Network length: {self._format_optional(self.result.network_length)}",
                    f"Intensity: {self._format_optional(self.result.intensity)}",
                    f"Monte Carlo envelopes: {'Yes' if self.result.k_lo is not None and self.result.k_hi is not None else 'No'}",
                    "",
                    "Interpretation aid:",
                    self._interpretation_text(),
                ]
            )
        )
        layout.addWidget(summary, 1)
        return container

    def _delta_values(self):
        if self.result.k_theo is None:
            return [0.0 for _ in self.result.k_obs]
        return [
            float(obs) - float(theo)
            for obs, theo in zip(self.result.k_obs, self.result.k_theo)
        ]

    def _delta_band(self):
        if self.result.k_lo is None or self.result.k_hi is None or self.result.k_theo is None:
            return None
        lo = [
            float(lo_value) - float(theo_value)
            for lo_value, theo_value in zip(self.result.k_lo, self.result.k_theo)
        ]
        hi = [
            float(hi_value) - float(theo_value)
            for hi_value, theo_value in zip(self.result.k_hi, self.result.k_theo)
        ]
        return (lo, hi, "#cbd5e1")

    def _status_values(self):
        statuses = []
        for index, obs_value in enumerate(self.result.k_obs):
            status = "within envelope"
            if self.result.k_hi is not None and float(obs_value) > float(self.result.k_hi[index]):
                status = "above envelope"
            elif self.result.k_lo is not None and float(obs_value) < float(self.result.k_lo[index]):
                status = "below envelope"
            statuses.append(status)
        return statuses

    def _interpretation_text(self):
        if self.result.k_lo is None or self.result.k_hi is None:
            return "No Monte Carlo envelope was generated, so the chart shows trend shape but not significance bounds."

        above_ranges = self._contiguous_ranges(lambda i: float(self.result.k_obs[i]) > float(self.result.k_hi[i]))
        below_ranges = self._contiguous_ranges(lambda i: float(self.result.k_obs[i]) < float(self.result.k_lo[i]))

        lines = []
        if above_ranges:
            lines.append(f"Observed K(r) exceeds the upper envelope at: {self._format_ranges(above_ranges)}.")
        if below_ranges:
            lines.append(f"Observed K(r) falls below the lower envelope at: {self._format_ranges(below_ranges)}.")
        if not lines:
            lines.append("Observed K(r) stays within the simulated envelope across the sampled distance range.")

        delta_values = self._delta_values()
        if delta_values:
            max_index = max(range(len(delta_values)), key=lambda i: abs(delta_values[i]))
            lines.append(
                "Largest deviation from the theoretical curve occurs near "
                f"r = {self._format_optional(float(self.result.r[max_index]))}, "
                f"with delta = {self._format_optional(delta_values[max_index])}."
            )

        return "\n".join(lines)

    def _contiguous_ranges(self, predicate):
        ranges = []
        start = None
        for index in range(len(self.result.r)):
            if predicate(index):
                if start is None:
                    start = index
            elif start is not None:
                ranges.append((start, index - 1))
                start = None
        if start is not None:
            ranges.append((start, len(self.result.r) - 1))
        return ranges

    def _format_ranges(self, ranges):
        formatted = []
        for start, end in ranges:
            start_r = float(self.result.r[start])
            end_r = float(self.result.r[end])
            if start == end:
                formatted.append(self._format_optional(start_r))
            else:
                formatted.append(f"{self._format_optional(start_r)} to {self._format_optional(end_r)}")
        return ", ".join(formatted)

    @staticmethod
    def _float_list(values):
        return [float(value) for value in values]

    @staticmethod
    def _format_optional(value):
        if value is None:
            return "Unknown"
        return f"{float(value):.6g}"

    @staticmethod
    def _framed(widget: QWidget):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("QFrame { border: 1px solid #dbe3ea; border-radius: 6px; background: #ffffff; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(widget)
        return frame
