"""Method-dependent controls for the QGIS 3 Processing dialog."""

from processing.gui.wrappers import DIALOG_STANDARD, NumberWidgetWrapper

from ..utils.analysis_options import EPSILON_HELP, GRID_HELP


class MethodNumberWidgetWrapper(NumberWidgetWrapper):
    """Keep dependent values but disable irrelevant controls in standard dialogs.

    Batch/modeler parameters may be expressions, so leave those editable.
    """

    enabled_indices = ()
    help_text = ""

    def postInitialize(self, wrappers):
        super().postInitialize(wrappers)
        self.widget.setToolTip(self.help_text)
        if self.dialogType != DIALOG_STANDARD:
            return
        method = next((wrapper for wrapper in wrappers
                       if wrapper.parameterDefinition().name() == "METHOD"), None)
        if method is None:
            return

        def sync(*_args):
            enabled = method.parameterValue() in self.enabled_indices
            self.widget.setEnabled(enabled)
            if self.label is not None:
                self.label.setEnabled(enabled)
                self.label.setToolTip(self.help_text)

        method.widgetValueHasChanged.connect(sync)
        sync()


class ApproximationEpsilonWidgetWrapper(MethodNumberWidgetWrapper):
    enabled_indices = (1,)
    help_text = EPSILON_HELP


class GridToleranceWidgetWrapper(MethodNumberWidgetWrapper):
    enabled_indices = (1, 2, 3)
    help_text = GRID_HELP
