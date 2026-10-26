"""Defer optional CSV loading to Processing's main-thread postprocessing."""

from pathlib import Path

from qgis.core import QgsProcessingContext


def register_csv_for_loading(path, output_name, context, feedback):
    """Register a written CSV table without accessing the GUI from a worker."""
    project = context.project()
    if project is None:
        feedback.pushWarning("CSV was saved, but no QGIS project is available to load it into.")
        return
    context.addLayerToLoadOnCompletion(
        str(path), QgsProcessingContext.LayerDetails(Path(path).stem, project, output_name)
    )
