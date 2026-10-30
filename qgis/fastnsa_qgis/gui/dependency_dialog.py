"""Non-modal runtime diagnostics; never downloads or installs packages."""

from pathlib import Path
import platform
import sys

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)
from qgis.core import Qgis, QgsSettings

from ..utils.bootstrap import default_runtime_root, runtime_requirements


class RuntimeSetupDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent, Qt.Window)
        self.plugin = plugin
        self.setWindowTitle("FastNSA Setup")
        self.setWindowModality(Qt.NonModal)
        self.resize(740, 600)
        layout = QVBoxLayout(self)
        title = QLabel("Set up FastNSA", self)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        layout.addWidget(self.message)
        tabs = QTabWidget(self)
        layout.addWidget(tabs)

        diagnostics = QWidget(tabs)
        diagnostic_layout = QVBoxLayout(diagnostics)
        self.details = QTextBrowser(diagnostics)
        diagnostic_layout.addWidget(self.details)
        label = QLabel("Custom installation folder (optional):", diagnostics)
        label.setWordWrap(True)
        diagnostic_layout.addWidget(label)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(diagnostics)
        self.path_edit.setText(QgsSettings().value("FastNSA/runtimePythonRoot", "", type=str))
        self.path_edit.setPlaceholderText("Leave empty to find FastNSA automatically")
        row.addWidget(self.path_edit)
        browse = QPushButton("Browse...", diagnostics)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        diagnostic_layout.addLayout(row)
        self.apply_button = QPushButton("Save and enable", diagnostics)
        self.apply_button.clicked.connect(self._save)
        diagnostic_layout.addWidget(self.apply_button)
        if plugin.runtime_status and plugin.runtime_status.distribution == "bundled":
            self.path_edit.setEnabled(False)
            browse.setEnabled(False)
            self.apply_button.setEnabled(False)
            label.setText("FastNSA is included with this plugin. You do not need to choose an installation folder.")
        self.saved_message = QLabel(diagnostics)
        self.saved_message.setWordWrap(True)
        self.saved_message.setTextFormat(Qt.PlainText)
        diagnostic_layout.addWidget(self.saved_message)
        trust = QLabel(
            "Choose only a trusted FastNSA installation. Packages are not installed automatically.",
            diagnostics,
        )
        trust.setWordWrap(True)
        diagnostic_layout.addWidget(trust)
        tabs.addTab(diagnostics, "Installation status")

        guide = QTextBrowser(tabs)
        guide.setOpenExternalLinks(True)
        path = Path(__file__).resolve().parents[1] / "docs/external-runtime.md"
        if not path.is_file():
            path = Path(__file__).resolve().parents[2] / "docs/external-runtime.md"
        guide.setMarkdown(path.read_text(encoding="utf-8") if path.is_file() else (
            "Install fastnsa==0.3.0 using QGIS's Python, then click Check again. "
            "If QGIS was already using another FastNSA installation, restart QGIS. "
            "For the full guide, visit https://github.com/fastnsa/FastNSA-QGIS."
        ))
        tabs.addTab(guide, "Installation Guide")
        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        refresh = buttons.addButton("Check again", QDialogButtonBox.ActionRole)
        refresh.clicked.connect(self.refresh)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Choose FastNSA installation folder", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def _save(self):
        if not self.path_edit.isEnabled():
            return
        value = self.path_edit.text().strip()
        if value and not (Path(value).expanduser() / "fastnsa/__init__.py").is_file():
            self.saved_message.setText("Choose the folder containing the fastnsa folder, not the fastnsa folder itself.")
            return
        root = str(Path(value).expanduser().resolve()) if value else ""
        status = self.plugin.configure_runtime(root)
        if status.available:
            self.saved_message.setText("Folder saved. FastNSA is ready; no restart is needed.")
        elif status.restart_required:
            self.saved_message.setText(
                "Folder saved. Restart QGIS to use this installation. "
                "Any running analysis will keep using the current installation."
            )
        else:
            self.saved_message.setText("Folder saved, but FastNSA is not ready. Follow the message above, then click Check again.")
        self.refresh(status)

    def refresh(self, status=None):
        # QPushButton.clicked may supply a bool, not a diagnostic result.
        if status is None or isinstance(status, bool):
            self.plugin._ensure_runtime()
            status = self.plugin.pending_runtime_status or self.plugin.runtime_status
        self.message.setText(status.message)
        self.message.setStyleSheet("color: #24634a;" if status.available else "color: #9a4a16;")
        if status.available:
            self.saved_message.setText("FastNSA tools are enabled; no restart is needed.")
        try:
            policy = runtime_requirements()
            requirement = f"FastNSA {policy['version']}; NumPy {policy['numpy_min_version']} or newer"
            default = default_runtime_root()
        except Exception as exc:
            requirement = f"Installation information could not be read: {exc}"
            policy = {}
            default = None
        package_type = {
            "bundled": "FastNSA included",
            "external": "FastNSA installed separately",
            "development": "Development installation",
        }.get(status.distribution, status.distribution)
        fields = {
            "Requirements": requirement,
            "QGIS": Qgis.QGIS_VERSION,
            "Python": sys.version.split()[0],
            "Platform": f"{platform.system()} {platform.machine()}",
            "Package type": package_type,
            "FastNSA version": status.runtime_version or "Not found",
            "Installation folder": status.python_root or "Not found",
            "Currently using": (self.plugin.runtime_status.python_root
                                if self.plugin.runtime_status.available else "Not enabled"),
            "Recommended installation folder": str(default) if default is not None else "Not available for this system",
            "NumPy": status.numpy_version or "Not checked",
            "Restart required": "Yes" if status.restart_required else "No",
            "Notes": "\n".join(status.notices) or "None",
        }
        support = {
            "Status code": status.code,
            "Library compatibility (ABI)": (
                f"Required: {policy.get('native_abi', 'Unknown')}; "
                f"found: {status.native_abi if status.native_abi is not None else 'Not checked'}"
            ),
            "Analysis library": status.native_library or "Not loaded",
        }
        self.details.setPlainText(
            "\n\n".join(f"{key}: {value}" for key, value in fields.items())
            + "\n\nDetails for support\n\n"
            + "\n\n".join(f"{key}: {value}" for key, value in support.items())
        )
