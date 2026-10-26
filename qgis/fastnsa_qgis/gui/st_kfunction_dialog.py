"""Dialog for displaying FastNSA spatiotemporal K-function results."""

from __future__ import annotations

import os
from math import isfinite

from qgis.PyQt.QtCore import QLineF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
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


def _temporal_axis_label(result) -> str:
    unit = getattr(result, "time_unit", None)
    return f"Temporal threshold t ({unit})" if unit else "Temporal threshold t"


def _turbo_color(ratio: float) -> QColor:
    colors = [
        QColor("#30123b"),
        QColor("#4145ab"),
        QColor("#4675ed"),
        QColor("#39a2fc"),
        QColor("#1bcfd4"),
        QColor("#5ce36b"),
        QColor("#c8e020"),
        QColor("#f9ba38"),
        QColor("#f56918"),
        QColor("#b41326"),
    ]
    ratio = max(0.0, min(1.0, ratio))
    scaled = ratio * (len(colors) - 1)
    left = int(scaled)
    right = min(len(colors) - 1, left + 1)
    local = scaled - left
    c1 = colors[left]
    c2 = colors[right]
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * local),
        round(c1.green() + (c2.green() - c1.green()) * local),
        round(c1.blue() + (c2.blue() - c1.blue()) * local),
    )


class _HeatmapCanvas(QWidget):
    def __init__(self, result, matrix_getter, title: str, parent=None):
        super().__init__(parent)
        self.result = result
        self.matrix_getter = matrix_getter
        self.title = title
        self.setMinimumSize(700, 420)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fcfcfd"))

        plot_rect = QRectF(84, 28, max(160, self.width() - 160), max(160, self.height() - 110))
        painter.setPen(QColor("#153243"))
        title_font = painter.font()
        title_font.setBold(True)
        title_font.setPointSize(max(title_font.pointSize(), 10))
        painter.setFont(title_font)
        painter.drawText(QRectF(16, 4, self.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)

        matrix = self.matrix_getter()
        if matrix is None:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot_rect, Qt.AlignCenter, "This heatmap is unavailable for the current result.")
            return

        values = [
            float(matrix[s_index][t_index])
            for s_index in range(len(self.result.s))
            for t_index in range(len(self.result.t))
            if isfinite(float(matrix[s_index][t_index]))
        ]
        if not values:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot_rect, Qt.AlignCenter, "No spatiotemporal K-function values available.")
            return

        value_min = min(values)
        value_max = max(values)
        if value_max <= value_min:
            value_max = value_min + 1.0

        n_s = len(self.result.s)
        n_t = len(self.result.t)
        cell_w = plot_rect.width() / max(1, n_t)
        cell_h = plot_rect.height() / max(1, n_s)

        border_pen = QPen(QColor("#e2e8f0"))
        border_pen.setWidthF(0.8)
        painter.setPen(border_pen)
        for s_index in range(n_s):
            for t_index in range(n_t):
                value = float(matrix[s_index][t_index])
                ratio = (value - value_min) / (value_max - value_min)
                color = _turbo_color(ratio)
                rect = QRectF(
                    plot_rect.left() + t_index * cell_w,
                    plot_rect.top() + s_index * cell_h,
                    cell_w,
                    cell_h,
                )
                painter.fillRect(rect, color)
                painter.drawRect(rect)

        painter.setPen(QColor("#334155"))
        label_font = painter.font()
        label_font.setBold(False)
        painter.setFont(label_font)

        max_ticks_t = min(6, n_t)
        for idx in range(max_ticks_t):
            t_index = round(idx * (n_t - 1) / max(1, max_ticks_t - 1))
            x = plot_rect.left() + (t_index + 0.5) * cell_w
            painter.drawText(QRectF(x - 40, plot_rect.bottom() + 6, 80, 18), Qt.AlignHCenter | Qt.AlignTop, self._fmt(self.result.t[t_index]))

        max_ticks_s = min(6, n_s)
        for idx in range(max_ticks_s):
            s_index = round(idx * (n_s - 1) / max(1, max_ticks_s - 1))
            y = plot_rect.top() + (s_index + 0.5) * cell_h
            painter.drawText(QRectF(4, y - 9, plot_rect.left() - 10, 18), Qt.AlignRight | Qt.AlignVCenter, self._fmt(self.result.s[s_index]))

        painter.drawText(
            QRectF(plot_rect.left(), plot_rect.bottom() + 26, plot_rect.width(), 18),
            Qt.AlignHCenter | Qt.AlignTop,
            _temporal_axis_label(self.result),
        )

        painter.save()
        painter.translate(16, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-plot_rect.height() / 2.0, -22, plot_rect.height(), 18), Qt.AlignCenter, "Spatial threshold s")
        painter.restore()

        self._draw_colorbar(painter, plot_rect, value_min, value_max)

    def _draw_colorbar(self, painter: QPainter, plot_rect: QRectF, value_min: float, value_max: float):
        bar_rect = QRectF(plot_rect.right() + 26, plot_rect.top(), 20, plot_rect.height())
        for i in range(int(bar_rect.height())):
            ratio = 1.0 - (i / max(1.0, bar_rect.height() - 1.0))
            painter.fillRect(QRectF(bar_rect.left(), bar_rect.top() + i, bar_rect.width(), 1.2), _turbo_color(ratio))
        painter.setPen(QColor("#334155"))
        painter.drawRect(bar_rect)
        painter.drawText(QRectF(bar_rect.right() + 6, bar_rect.top() - 8, 70, 18), Qt.AlignLeft | Qt.AlignVCenter, self._fmt(value_max))
        painter.drawText(QRectF(bar_rect.right() + 6, bar_rect.bottom() - 10, 70, 18), Qt.AlignLeft | Qt.AlignVCenter, self._fmt(value_min))

    @staticmethod
    def _fmt(value) -> str:
        value = float(value)
        if abs(value) >= 1000:
            return f"{value:.0f}"
        if abs(value) >= 10:
            return f"{value:.1f}"
        if abs(value) >= 1:
            return f"{value:.2f}"
        return f"{value:.3f}"


class _SurfaceCanvas(QWidget):
    def __init__(self, result, matrix_getter, title_getter, parent=None):
        super().__init__(parent)
        self.result = result
        self.matrix_getter = matrix_getter
        self.title_getter = title_getter
        self.setMinimumSize(760, 480)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fcfcfd"))

        title = self.title_getter()
        matrix = self.matrix_getter()
        plot_rect = QRectF(56, 34, max(260, self.width() - 128), max(220, self.height() - 112))

        painter.setPen(QColor("#153243"))
        title_font = painter.font()
        title_font.setBold(True)
        title_font.setPointSize(max(title_font.pointSize(), 10))
        painter.setFont(title_font)
        painter.drawText(QRectF(16, 6, self.width() - 32, 22), Qt.AlignLeft | Qt.AlignVCenter, title)

        if matrix is None:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot_rect, Qt.AlignCenter, "This 3D surface is unavailable for the current result.")
            return

        n_s = len(self.result.s)
        n_t = len(self.result.t)
        if n_s == 0 or n_t == 0:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot_rect, Qt.AlignCenter, "No spatiotemporal K-function values available.")
            return

        values = [
            float(matrix[s_index][t_index])
            for s_index in range(n_s)
            for t_index in range(n_t)
            if isfinite(float(matrix[s_index][t_index]))
        ]
        if not values:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot_rect, Qt.AlignCenter, "No finite values are available for the surface.")
            return

        value_min = min(values)
        value_max = max(values)
        if value_max <= value_min:
            value_max = value_min + 1.0

        painter.setPen(QPen(QColor("#dbe5f0"), 1.0))
        painter.drawRoundedRect(plot_rect, 10, 10)

        # Project the full surface into a normalized view first, then fit it
        # into the available plot rect. This keeps the surface inside bounds
        # regardless of window size or z-range.
        skew_x = 0.62
        skew_y = 0.42
        z_lift = 3.15

        projected = {}
        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")
        for s_index in range(n_s):
            for t_index in range(n_t):
                value = float(matrix[s_index][t_index])
                ratio = (value - value_min) / (value_max - value_min)
                ratio = ratio ** 0.72
                raw_x = float(t_index) + float(s_index) * skew_x
                raw_y = float(s_index) * skew_y - ratio * z_lift
                projected[(s_index, t_index)] = (raw_x, raw_y, ratio)
                min_x = min(min_x, raw_x)
                max_x = max(max_x, raw_x)
                min_y = min(min_y, raw_y)
                max_y = max(max_y, raw_y)

        left_pad = 110.0
        right_pad = 76.0
        top_pad = 38.0
        bottom_pad = 72.0
        inner_rect = QRectF(
            plot_rect.left() + left_pad,
            plot_rect.top() + top_pad,
            max(160.0, plot_rect.width() - left_pad - right_pad),
            max(140.0, plot_rect.height() - top_pad - bottom_pad),
        )
        span_x = max(1e-9, max_x - min_x)
        span_y = max(1e-9, max_y - min_y)
        scale = min(inner_rect.width() / span_x, inner_rect.height() / span_y)
        offset_x = inner_rect.left() + (inner_rect.width() - span_x * scale) / 2.0
        offset_y = inner_rect.top() + (inner_rect.height() - span_y * scale) / 2.0

        def project_point(s_index: int, t_index: int):
            raw_x, raw_y, ratio = projected[(s_index, t_index)]
            px = offset_x + (raw_x - min_x) * scale
            py = offset_y + (raw_y - min_y) * scale
            return px, py, ratio

        base_back_left = self._pointf(*project_point(0, 0)[:2])
        base_back_right = self._pointf(*project_point(0, n_t - 1)[:2])
        base_front_left = self._pointf(*project_point(n_s - 1, 0)[:2])
        top_left = self._pointf(base_back_left.x(), offset_y)

        # Soft ground shadow improves separation from the background.
        shadow_points = [
            (base_back_left.x() + 10, base_back_left.y() + 12),
            (base_back_right.x() + 20, base_back_right.y() + 10),
            (self._pointf(*project_point(n_s - 1, n_t - 1)[:2]).x() + 20, self._pointf(*project_point(n_s - 1, n_t - 1)[:2]).y() + 18),
            (base_front_left.x() + 6, base_front_left.y() + 20),
        ]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(148, 163, 184, 28))
        painter.drawPolygon(self._polygon(shadow_points))

        grid_pen = QPen(QColor(220, 229, 238, 145), 0.75)
        painter.setPen(grid_pen)
        for idx in range(min(6, n_t)):
            t_index = round(idx * (n_t - 1) / max(1, min(6, n_t) - 1))
            p0 = self._pointf(*project_point(0, t_index)[:2])
            p1 = self._pointf(*project_point(n_s - 1, t_index)[:2])
            painter.drawLine(QLineF(p0, p1))
        for idx in range(min(6, n_s)):
            s_index = round(idx * (n_s - 1) / max(1, min(6, n_s) - 1))
            p0 = self._pointf(*project_point(s_index, 0)[:2])
            p1 = self._pointf(*project_point(s_index, n_t - 1)[:2])
            painter.drawLine(QLineF(p0, p1))

        axis_pen = QPen(QColor("#94a3b8"), 1.2)
        painter.setPen(axis_pen)
        painter.drawLine(QLineF(base_back_left, self._pointf(base_back_right.x() + 12, base_back_right.y())))
        painter.drawLine(QLineF(base_back_left, self._pointf(base_front_left.x() - 4, base_front_left.y() + 8)))
        painter.drawLine(QLineF(base_back_left, self._pointf(top_left.x(), top_left.y() - 12)))

        painter.save()
        painter.setClipRect(plot_rect.adjusted(1, 1, -1, -1))

        quad_pen = QPen(QColor(255, 255, 255, 135), 0.65)
        for s_index in reversed(range(max(0, n_s - 1))):
            for t_index in reversed(range(max(0, n_t - 1))):
                p00x, p00y, _ = project_point(s_index, t_index)
                p10x, p10y, _ = project_point(s_index, t_index + 1)
                p11x, p11y, _ = project_point(s_index + 1, t_index + 1)
                p01x, p01y, _ = project_point(s_index + 1, t_index)

                avg_value = (
                    float(matrix[s_index][t_index])
                    + float(matrix[s_index][t_index + 1])
                    + float(matrix[s_index + 1][t_index + 1])
                    + float(matrix[s_index + 1][t_index])
                ) / 4.0
                ratio = (avg_value - value_min) / (value_max - value_min)
                painter.setPen(quad_pen)
                painter.setBrush(_turbo_color(ratio))
                painter.drawPolygon(self._polygon([(p00x, p00y), (p10x, p10y), (p11x, p11y), (p01x, p01y)]))

        # Draw a sparse mesh instead of every row/column to reduce visual noise.
        wire_pen = QPen(QColor(24, 44, 68, 92), 0.8)
        painter.setPen(wire_pen)
        s_step = max(1, n_s // 10)
        t_step = max(1, n_t // 10)
        for s_index in range(0, n_s, s_step):
            points = [self._pointf(*project_point(s_index, t_index)[:2]) for t_index in range(n_t)]
            for idx in range(len(points) - 1):
                painter.drawLine(QLineF(points[idx], points[idx + 1]))
        if (n_s - 1) % s_step != 0:
            points = [self._pointf(*project_point(n_s - 1, t_index)[:2]) for t_index in range(n_t)]
            for idx in range(len(points) - 1):
                painter.drawLine(QLineF(points[idx], points[idx + 1]))

        for t_index in range(0, n_t, t_step):
            points = [self._pointf(*project_point(s_index, t_index)[:2]) for s_index in range(n_s)]
            for idx in range(len(points) - 1):
                painter.drawLine(QLineF(points[idx], points[idx + 1]))
        if (n_t - 1) % t_step != 0:
            points = [self._pointf(*project_point(s_index, n_t - 1)[:2]) for s_index in range(n_s)]
            for idx in range(len(points) - 1):
                painter.drawLine(QLineF(points[idx], points[idx + 1]))

        painter.restore()

        painter.setPen(QColor("#334155"))
        label_font = painter.font()
        label_font.setBold(False)
        label_font.setPointSize(max(8, label_font.pointSize() - 1))
        painter.setFont(label_font)

        max_ticks_t = min(5, n_t)
        for idx in range(max_ticks_t):
            t_index = round(idx * (n_t - 1) / max(1, max_ticks_t - 1))
            x, _y, _ = project_point(0, t_index)
            painter.drawText(QRectF(x - 26, base_back_left.y() + 12, 52, 16), Qt.AlignHCenter | Qt.AlignTop, _HeatmapCanvas._fmt(self.result.t[t_index]))

        max_ticks_s = min(5, n_s)
        for idx in range(max_ticks_s):
            s_index = round(idx * (n_s - 1) / max(1, max_ticks_s - 1))
            x, y, _ = project_point(s_index, 0)
            painter.drawText(QRectF(x - 70, y - 9, 54, 16), Qt.AlignRight | Qt.AlignVCenter, _HeatmapCanvas._fmt(self.result.s[s_index]))

        axis_font = painter.font()
        axis_font.setBold(True)
        axis_font.setPointSize(max(9, axis_font.pointSize()))
        painter.setFont(axis_font)
        painter.drawText(
            QRectF(
                base_back_left.x() + inner_rect.width() * 0.32,
                base_back_left.y() + 30,
                220,
                18,
            ),
            Qt.AlignLeft | Qt.AlignTop,
            _temporal_axis_label(self.result),
        )
        painter.save()
        painter.translate(base_back_left.x() - 66, (base_back_left.y() + base_front_left.y()) / 2.0)
        painter.rotate(-42)
        painter.drawText(QRectF(-70, -12, 140, 20), Qt.AlignCenter, "Spatial threshold s")
        painter.restore()
        painter.drawText(QRectF(base_back_left.x() - 14, top_left.y() - 34, 80, 18), Qt.AlignLeft | Qt.AlignVCenter, "K(s,t)")

        self._draw_colorbar(painter, plot_rect, value_min, value_max)

    def _draw_colorbar(self, painter: QPainter, plot_rect: QRectF, value_min: float, value_max: float):
        bar_rect = QRectF(plot_rect.right() + 18, plot_rect.top() + 24, 18, max(120.0, plot_rect.height() - 48))
        for i in range(int(bar_rect.height())):
            ratio = 1.0 - (i / max(1.0, bar_rect.height() - 1.0))
            painter.fillRect(QRectF(bar_rect.left(), bar_rect.top() + i, bar_rect.width(), 1.2), _turbo_color(ratio))
        painter.setPen(QColor("#334155"))
        painter.drawRect(bar_rect)
        painter.drawText(QRectF(bar_rect.right() + 6, bar_rect.top() - 8, 84, 18), Qt.AlignLeft | Qt.AlignVCenter, _HeatmapCanvas._fmt(value_max))
        painter.drawText(QRectF(bar_rect.right() + 6, bar_rect.bottom() - 10, 84, 18), Qt.AlignLeft | Qt.AlignVCenter, _HeatmapCanvas._fmt(value_min))

    @staticmethod
    def _pointf(x: float, y: float):
        from qgis.PyQt.QtCore import QPointF

        return QPointF(x, y)

    @classmethod
    def _polygon(cls, points):
        return QPolygonF([cls._pointf(x, y) for x, y in points])


class _MatplotlibSurfaceWidget(QWidget):
    def __init__(self, result, payload_getter, title_getter, parent=None):
        super().__init__(parent)
        self.result = result
        self.payload_getter = payload_getter
        self.title_getter = title_getter
        self._figure = None
        self._canvas = None
        self._axes = None
        self._toolbar = None
        self._status_label = None
        self._content_layout = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self._status_label)

        self._content_layout = QVBoxLayout()
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
        layout.addLayout(self._content_layout, 1)
        self.refresh_plot()

    def refresh_plot(self):
        payload = self.payload_getter()
        title = self.title_getter()
        if payload is None:
            self._clear_plot_widgets()
            self._status_label.setText("This matplotlib 3D surface is unavailable for the current result.")
            return

        try:
            figure, canvas, axes, toolbar = self._build_plot_objects()
        except Exception as exc:
            self._clear_plot_widgets()
            self._status_label.setText(f"Matplotlib 3D surface could not be initialized: {exc}")
            return

        import numpy as np

        s = np.asarray(self.result.s, dtype=float)
        t = np.asarray(self.result.t, dtype=float)
        overlay_mode = isinstance(payload, dict)
        overlay_style = payload.get("mode", "envelope") if overlay_mode else None
        z = np.asarray(payload["observed"] if overlay_mode else payload, dtype=float)
        if z.ndim != 2 or z.shape != (len(s), len(t)):
            self._status_label.setText("Surface matrix shape does not match the spatial/temporal sample grid.")
            return

        self._status_label.setText(
            "Drag to rotate, scroll to zoom, and use the toolbar to pan or save the figure."
            if overlay_style != "highlight"
            else "Drag to rotate, scroll to zoom, and use the toolbar to pan or save. Red markers show observed values above the upper envelope; blue markers show observed values below the lower envelope."
        )
        self._figure.clear()
        axes = self._figure.add_subplot(111, projection="3d")
        self._axes = axes
        axes.set_title(title, pad=16, color="#153243")
        t_grid, s_grid = np.meshgrid(t, s)

        surf = axes.plot_surface(
            t_grid,
            s_grid,
            z,
            cmap="turbo",
            linewidth=0.25,
            edgecolor=(1, 1, 1, 0.18),
            antialiased=True,
            rcount=min(120, max(2, len(s))),
            ccount=min(120, max(2, len(t))),
        )

        if overlay_mode:
            lo = np.asarray(payload["lo"], dtype=float)
            hi = np.asarray(payload["hi"], dtype=float)
            axes.plot_wireframe(
                t_grid,
                s_grid,
                lo,
                rstride=max(1, len(s) // 12),
                cstride=max(1, len(t) // 12),
                color="#2563eb",
                linewidth=0.8,
                alpha=0.75,
            )
            axes.plot_wireframe(
                t_grid,
                s_grid,
                hi,
                rstride=max(1, len(s) // 12),
                cstride=max(1, len(t) // 12),
                color="#c2410c",
                linewidth=0.8,
                alpha=0.75,
            )

            if overlay_style == "highlight":
                above_mask = z > hi
                below_mask = z < lo
                z_span = max(1e-9, float(np.nanmax(z) - np.nanmin(z)))
                marker_lift = z_span * 0.012

                if np.any(above_mask):
                    axes.scatter(
                        t_grid[above_mask],
                        s_grid[above_mask],
                        z[above_mask] + marker_lift,
                        color="#dc2626",
                        s=24,
                        depthshade=False,
                        alpha=0.95,
                    )
                    for x_val, y_val, z_obs, z_hi in zip(t_grid[above_mask], s_grid[above_mask], z[above_mask], hi[above_mask]):
                        axes.plot(
                            [x_val, x_val],
                            [y_val, y_val],
                            [z_hi, z_obs],
                            color="#dc2626",
                            linewidth=1.1,
                            alpha=0.75,
                        )

                if np.any(below_mask):
                    axes.scatter(
                        t_grid[below_mask],
                        s_grid[below_mask],
                        z[below_mask] + marker_lift,
                        color="#2563eb",
                        s=24,
                        depthshade=False,
                        alpha=0.95,
                    )
                    for x_val, y_val, z_obs, z_lo in zip(t_grid[below_mask], s_grid[below_mask], z[below_mask], lo[below_mask]):
                        axes.plot(
                            [x_val, x_val],
                            [y_val, y_val],
                            [z_obs, z_lo],
                            color="#2563eb",
                            linewidth=1.1,
                            alpha=0.75,
                        )

        axes.set_xlabel(_temporal_axis_label(self.result), labelpad=12)
        axes.set_ylabel("Spatial threshold s", labelpad=14)
        axes.set_zlabel("K(s,t)", labelpad=10)
        axes.view_init(elev=28, azim=-128)
        axes.set_box_aspect((1.55, 1.1, 0.52))
        axes.grid(True, color="#d7e3ef", linewidth=0.6)
        axes.set_facecolor("#fcfcfd")
        axes.xaxis.pane.set_facecolor((0.96, 0.98, 1.0, 0.88))
        axes.yaxis.pane.set_facecolor((0.96, 0.98, 1.0, 0.88))
        axes.zaxis.pane.set_facecolor((0.985, 0.99, 1.0, 0.88))
        colorbar = self._figure.colorbar(surf, ax=axes, shrink=0.72, pad=0.08, aspect=24)
        colorbar.set_label("Observed K(s,t)" if overlay_mode else "K(s,t)")
        if overlay_mode:
            from matplotlib.lines import Line2D

            legend_handles = [
                Line2D([0], [0], color="#0f172a", lw=6, alpha=0.55, label="Observed surface"),
                Line2D([0], [0], color="#2563eb", lw=1.5, label="Lower envelope"),
                Line2D([0], [0], color="#c2410c", lw=1.5, label="Upper envelope"),
            ]
            if overlay_style == "highlight":
                legend_handles.extend(
                    [
                        Line2D([0], [0], marker="o", color="w", markerfacecolor="#dc2626", markeredgecolor="#dc2626", markersize=6, label="Observed > upper"),
                        Line2D([0], [0], marker="o", color="w", markerfacecolor="#2563eb", markeredgecolor="#2563eb", markersize=6, label="Observed < lower"),
                    ]
                )
            axes.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(0.01, 0.98), frameon=True, facecolor="white", edgecolor="#dbe5f0")
        self._figure.subplots_adjust(left=0.02, right=0.90, bottom=0.04, top=0.93)
        canvas.draw_idle()

    def _build_plot_objects(self):
        if self._figure is not None:
            return self._figure, self._canvas, self._axes, self._toolbar

        os.environ.setdefault("MPLCONFIGDIR", "/tmp/fastnsa-mpl")
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
        except Exception:
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
        from matplotlib.figure import Figure

        self._figure = Figure(figsize=(7.4, 5.6))
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setStyleSheet("background: #fcfcfd; border: 1px solid #dbe5f0; border-radius: 8px;")
        self._axes = self._figure.add_subplot(111, projection="3d")
        self._toolbar = NavigationToolbar(self._canvas, self)
        self._toolbar.setStyleSheet(
            "QToolBar { border: 1px solid #cbd5e1; border-radius: 6px; "
            "background: #eef3f7; spacing: 3px; padding: 2px; }"
            "QToolButton { background: #ffffff; border: 1px solid transparent; "
            "border-radius: 4px; padding: 3px; }"
            "QToolButton:hover { border-color: #7aa7bf; background: #dceaf2; }"
        )
        self._content_layout.addWidget(self._toolbar)
        self._content_layout.addWidget(self._canvas, 1)
        return self._figure, self._canvas, self._axes, self._toolbar

    def _clear_plot_widgets(self):
        if self._canvas is not None:
            self._canvas.hide()
        if self._toolbar is not None:
            self._toolbar.hide()


class SpatiotemporalKFunctionDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("FastNSA Spatiotemporal K-Function Result")
        self.setMinimumSize(980, 760)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QLabel("FastNSA Spatiotemporal K-Function Result Viewer")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #153243;")
        layout.addWidget(header)

        meta = QLabel(
            f"Method: {self.result.method or 'Unknown'} | "
            f"Spatial thresholds: {len(self.result.s)} | "
            f"Temporal thresholds: {len(self.result.t)} | "
            f"Time unit: {self.result.time_unit or 'Unknown'} | "
            f"Points: {self.result.n_points or 'Unknown'}"
        )
        meta.setWordWrap(True)
        layout.addWidget(meta)

        tabs = QTabWidget()
        tabs.addTab(self._build_observed_heatmap_tab(), "Observed")
        tabs.addTab(self._build_theoretical_heatmap_tab(), "Theoretical")
        tabs.addTab(self._build_residual_heatmap_tab(), "Residual")
        tabs.addTab(self._build_significance_heatmap_tab(), "Significance")
        tabs.addTab(self._build_matplotlib_surface_tab(), "Matplotlib 3D")
        tabs.addTab(self._build_table_tab(), "Table")
        tabs.addTab(self._build_summary_tab(), "Summary")
        layout.addWidget(tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _build_observed_heatmap_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        info = QLabel(self._interpretation_text())
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)
        layout.addWidget(
            _HeatmapCanvas(
                self.result,
                lambda: self.result.k_obs,
                "Observed ST K-Function Heatmap",
            ),
            1,
        )
        return container

    def _build_theoretical_heatmap_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        info = QLabel(
            "Theoretical surface is estimated as the Monte Carlo mean under CSR on the network."
            if self.result.k_theo is not None
            else "No Monte Carlo theoretical surface is available. Run with simulations enabled to estimate it."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)
        layout.addWidget(
            _HeatmapCanvas(
                self.result,
                lambda: self.result.k_theo,
                "Theoretical ST K-Function Heatmap",
            ),
            1,
        )
        return container

    def _build_residual_heatmap_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        info = QLabel(
            "Residual surface shows Observed - Theoretical. Positive values indicate observed interaction above the CSR mean."
            if self.result.k_theo is not None
            else "Residual heatmap is unavailable because no Monte Carlo theoretical surface was generated."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)
        layout.addWidget(
            _HeatmapCanvas(
                self.result,
                self._residual_matrix,
                "Residual ST K-Function Heatmap",
            ),
            1,
        )
        return container

    def _build_significance_heatmap_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        info = QLabel(
            "Significance heatmap compares observed values to the Monte Carlo envelope. Red = above envelope, blue = below envelope, light gray = within envelope."
            if self.result.k_lo is not None and self.result.k_hi is not None
            else "Significance heatmap is unavailable because no Monte Carlo envelope was generated."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)
        layout.addWidget(_SignificanceHeatmapCanvas(self.result), 1)
        return container

    def _build_surface_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        control_row = QHBoxLayout()
        control_row.setSpacing(8)
        control_row.addWidget(QLabel("Surface:"))
        surface_combo = QComboBox()
        for key, label in self._surface_options():
            surface_combo.addItem(label, key)
        control_row.addWidget(surface_combo)
        control_row.addStretch(1)
        layout.addLayout(control_row)

        info = QLabel()
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)

        def current_key():
            return surface_combo.currentData()

        canvas = _SurfaceCanvas(
            self.result,
            lambda: self._surface_matrix(current_key()),
            lambda: self._surface_title(current_key()),
        )
        layout.addWidget(canvas, 1)

        def refresh_surface():
            info.setText(self._surface_info(current_key()))
            canvas.update()

        surface_combo.currentIndexChanged.connect(lambda _index: refresh_surface())
        refresh_surface()
        return container

    def _build_matplotlib_surface_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        control_row = QHBoxLayout()
        control_row.setSpacing(8)
        control_row.addWidget(QLabel("Surface:"))
        surface_combo = QComboBox()
        for key, label in self._surface_options():
            surface_combo.addItem(label, key)
        control_row.addWidget(surface_combo)
        control_row.addStretch(1)
        layout.addLayout(control_row)

        info = QLabel(
            "This interactive 3D view uses Matplotlib's mplot3d backend and can be rotated, zoomed, and saved from the toolbar."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #475569;")
        layout.addWidget(info)

        def current_key():
            return surface_combo.currentData()

        widget = _MatplotlibSurfaceWidget(
            self.result,
            lambda: self._matplotlib_surface_payload(current_key()),
            lambda: self._surface_title(current_key()),
        )
        layout.addWidget(widget, 1)

        surface_combo.currentIndexChanged.connect(lambda _index: widget.refresh_plot())
        return container

    def _build_table_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        time_header = (
            f"t ({self.result.time_unit})" if self.result.time_unit else "t"
        )
        headers = ["s", time_header, "k_obs", "k_lo", "k_hi", "status"]
        if self.result.k_theo is not None:
            headers.insert(3, "k_theo")
        rows = len(self.result.s) * len(self.result.t)
        table = QTableWidget(rows, len(headers))
        table.setHorizontalHeaderLabels(headers)

        row = 0
        for s_index, s_value in enumerate(self.result.s):
            for t_index, t_value in enumerate(self.result.t):
                status = self._status_for_cell(s_index, t_index)
                values = [
                    s_value,
                    t_value,
                    self.result.k_obs[s_index][t_index],
                ]
                if self.result.k_theo is not None:
                    values.append(self.result.k_theo[s_index][t_index])
                values.extend(
                    [
                        self.result.k_lo[s_index][t_index] if self.result.k_lo is not None else "",
                        self.result.k_hi[s_index][t_index] if self.result.k_hi is not None else "",
                        status,
                    ]
                )
                for col, value in enumerate(values):
                    if isinstance(value, str):
                        item = QTableWidgetItem(value)
                    else:
                        item = QTableWidgetItem("" if value == "" else f"{float(value):.6f}")
                    table.setItem(row, col, item)
                row += 1

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
                    f"Number of spatial thresholds: {len(self.result.s)}",
                    f"Number of temporal thresholds: {len(self.result.t)}",
                    f"Temporal unit: {self.result.time_unit or 'Unknown'}",
                    f"Time interpretation: {self.result.time_mode or 'Unknown'}",
                    f"Temporal origin: {self.result.time_origin or 'Unknown'}",
                    f"Number of points: {self.result.n_points or 'Unknown'}",
                    f"Network length: {self._fmt_optional(self.result.network_length)}",
                    f"Intensity: {self._fmt_optional(self.result.intensity)}",
                    f"Monte Carlo envelopes: {'Yes' if self.result.k_lo is not None and self.result.k_hi is not None else 'No'}",
                    f"Theoretical surface: {'Yes' if self.result.k_theo is not None else 'No'}",
                    "",
                    "Interpretation aid:",
                    self._interpretation_text(),
                ]
            )
        )
        layout.addWidget(summary, 1)
        return container

    def _status_for_cell(self, s_index: int, t_index: int) -> str:
        obs = float(self.result.k_obs[s_index][t_index])
        if self.result.k_hi is not None and obs > float(self.result.k_hi[s_index][t_index]):
            return "above envelope"
        if self.result.k_lo is not None and obs < float(self.result.k_lo[s_index][t_index]):
            return "below envelope"
        if self.result.k_lo is not None and self.result.k_hi is not None:
            return "within envelope"
        return "unbounded"

    def _interpretation_text(self) -> str:
        flat = []
        for s_index, s_value in enumerate(self.result.s):
            for t_index, t_value in enumerate(self.result.t):
                flat.append((float(self.result.k_obs[s_index][t_index]), s_index, t_index, float(s_value), float(t_value)))
        if not flat:
            return "No spatiotemporal K-function values are available."

        top_value, _s_idx, _t_idx, top_s, top_t = max(flat, key=lambda item: item[0])
        lines = [
            f"Highest observed K(s,t) occurs near s = {self._fmt_optional(top_s)} and t = {self._fmt_optional(top_t)}, with value {self._fmt_optional(top_value)}."
        ]

        if self.result.k_lo is not None and self.result.k_hi is not None:
            above = []
            below = []
            for _obs, s_index, t_index, s_value, t_value in flat:
                status = self._status_for_cell(s_index, t_index)
                if status == "above envelope":
                    above.append((s_value, t_value))
                elif status == "below envelope":
                    below.append((s_value, t_value))
            if above:
                preview = ", ".join(f"(s={self._fmt_optional(s)}, t={self._fmt_optional(t)})" for s, t in above[:5])
                lines.append(f"Cells above the simulation envelope include: {preview}.")
            if below:
                preview = ", ".join(f"(s={self._fmt_optional(s)}, t={self._fmt_optional(t)})" for s, t in below[:5])
                lines.append(f"Cells below the simulation envelope include: {preview}.")
            if not above and not below:
                lines.append("Observed ST K-function stays within the simulated envelope across the sampled grid.")
        else:
            lines.append("No Monte Carlo envelope was generated, so the heatmap shows magnitude patterns but not significance bounds.")

        return "\n".join(lines)

    def _residual_matrix(self):
        if self.result.k_theo is None:
            return None
        return self.result.k_obs - self.result.k_theo

    def _surface_options(self):
        options = [("observed", "Observed K(s,t)")]
        if self.result.k_theo is not None:
            options.append(("theoretical", "Theoretical Mean"))
            options.append(("residual", "Residual"))
        if self.result.k_lo is not None and self.result.k_hi is not None:
            options.append(("observed_envelope", "Observed + Envelope"))
            options.append(("observed_envelope_highlight", "Observed + Envelope Highlights"))
        return options

    def _surface_matrix(self, key: str):
        if key == "observed":
            return self.result.k_obs
        if key == "theoretical":
            return self.result.k_theo
        if key == "residual":
            return self._residual_matrix()
        return self.result.k_obs

    def _matplotlib_surface_payload(self, key: str):
        if key == "observed_envelope":
            if self.result.k_lo is None or self.result.k_hi is None:
                return None
            return {
                "observed": self.result.k_obs,
                "lo": self.result.k_lo,
                "hi": self.result.k_hi,
                "mode": "envelope",
            }
        if key == "observed_envelope_highlight":
            if self.result.k_lo is None or self.result.k_hi is None:
                return None
            return {
                "observed": self.result.k_obs,
                "lo": self.result.k_lo,
                "hi": self.result.k_hi,
                "mode": "highlight",
            }
        return self._surface_matrix(key)

    def _surface_title(self, key: str) -> str:
        titles = {
            "observed": "Observed ST K-Function 3D Surface",
            "theoretical": "Theoretical ST K-Function 3D Surface",
            "residual": "Residual ST K-Function 3D Surface",
            "observed_envelope": "Observed + Envelope ST K-Function 3D Surface",
            "observed_envelope_highlight": "Observed + Envelope Highlighted 3D Surface",
        }
        return titles.get(key, "ST K-Function 3D Surface")

    def _surface_info(self, key: str) -> str:
        if key == "observed":
            return "This surface shows the magnitude of observed K(s,t). Higher ridges indicate stronger interaction at the corresponding spatial and temporal thresholds."
        if key == "theoretical":
            return "This surface shows the Monte Carlo mean under CSR on the network. Compare ridge locations against the observed surface to see whether structure exceeds the simulated baseline."
        if key == "residual":
            return "This surface shows Observed - Theoretical. Peaks above zero mark thresholds where the observed interaction rises above the CSR mean."
        if key == "observed_envelope":
            return "This overlay shows the observed surface together with the lower and upper Monte Carlo envelopes as wireframes, making it easier to inspect where observed peaks rise beyond the simulated bounds."
        if key == "observed_envelope_highlight":
            return "This overlay shows the observed surface with envelope wireframes and explicit red/blue highlights where the observed values rise above the upper envelope or fall below the lower envelope."
        return "3D surface view of the spatiotemporal K-function grid."

    @staticmethod
    def _fmt_optional(value):
        if value is None:
            return "Unknown"
        return f"{float(value):.6g}"


class _SignificanceHeatmapCanvas(QWidget):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        self.setMinimumSize(700, 420)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fcfcfd"))

        plot_rect = QRectF(84, 28, max(160, self.width() - 190), max(160, self.height() - 110))
        painter.setPen(QColor("#153243"))
        title_font = painter.font()
        title_font.setBold(True)
        title_font.setPointSize(max(title_font.pointSize(), 10))
        painter.setFont(title_font)
        painter.drawText(QRectF(16, 4, self.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, "Significance Heatmap")

        if self.result.k_lo is None or self.result.k_hi is None:
            painter.setPen(QColor("#64748b"))
            painter.drawText(plot_rect, Qt.AlignCenter, "No Monte Carlo envelope is available.")
            return

        n_s = len(self.result.s)
        n_t = len(self.result.t)
        cell_w = plot_rect.width() / max(1, n_t)
        cell_h = plot_rect.height() / max(1, n_s)
        border_pen = QPen(QColor("#e2e8f0"))
        border_pen.setWidthF(0.8)
        painter.setPen(border_pen)

        for s_index in range(n_s):
            for t_index in range(n_t):
                obs = float(self.result.k_obs[s_index][t_index])
                lo = float(self.result.k_lo[s_index][t_index])
                hi = float(self.result.k_hi[s_index][t_index])
                if obs > hi:
                    color = QColor("#c81e1e")
                elif obs < lo:
                    color = QColor("#2563eb")
                else:
                    color = QColor("#d1d5db")
                rect = QRectF(
                    plot_rect.left() + t_index * cell_w,
                    plot_rect.top() + s_index * cell_h,
                    cell_w,
                    cell_h,
                )
                painter.fillRect(rect, color)
                painter.drawRect(rect)

        painter.setPen(QColor("#334155"))
        max_ticks_t = min(6, n_t)
        for idx in range(max_ticks_t):
            t_index = round(idx * (n_t - 1) / max(1, max_ticks_t - 1))
            x = plot_rect.left() + (t_index + 0.5) * cell_w
            painter.drawText(QRectF(x - 40, plot_rect.bottom() + 6, 80, 18), Qt.AlignHCenter | Qt.AlignTop, _HeatmapCanvas._fmt(self.result.t[t_index]))
        max_ticks_s = min(6, n_s)
        for idx in range(max_ticks_s):
            s_index = round(idx * (n_s - 1) / max(1, max_ticks_s - 1))
            y = plot_rect.top() + (s_index + 0.5) * cell_h
            painter.drawText(QRectF(4, y - 9, plot_rect.left() - 10, 18), Qt.AlignRight | Qt.AlignVCenter, _HeatmapCanvas._fmt(self.result.s[s_index]))

        painter.drawText(
            QRectF(plot_rect.left(), plot_rect.bottom() + 26, plot_rect.width(), 18),
            Qt.AlignHCenter | Qt.AlignTop,
            _temporal_axis_label(self.result),
        )
        painter.save()
        painter.translate(16, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-plot_rect.height() / 2.0, -22, plot_rect.height(), 18), Qt.AlignCenter, "Spatial threshold s")
        painter.restore()

        legend_x = plot_rect.right() + 24
        self._legend_swatch(painter, legend_x, plot_rect.top() + 10, QColor("#c81e1e"), "above envelope")
        self._legend_swatch(painter, legend_x, plot_rect.top() + 34, QColor("#d1d5db"), "within envelope")
        self._legend_swatch(painter, legend_x, plot_rect.top() + 58, QColor("#2563eb"), "below envelope")

    @staticmethod
    def _legend_swatch(painter: QPainter, x: float, y: float, color: QColor, label: str):
        painter.setPen(QColor("#334155"))
        painter.fillRect(QRectF(x, y, 16, 16), color)
        painter.drawRect(QRectF(x, y, 16, 16))
        painter.drawText(QRectF(x + 24, y - 1, 120, 18), Qt.AlignLeft | Qt.AlignVCenter, label)
