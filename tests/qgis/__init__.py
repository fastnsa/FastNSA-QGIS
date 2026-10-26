"""Tests requiring the QGIS Python runtime."""

import atexit


_test_app = None


def qgis_test_application():
    """Own one app in standalone tests, without shutting down a QGIS host."""
    global _test_app
    if _test_app is None:
        from qgis.core import QgsApplication

        _test_app = QgsApplication.instance()
        if _test_app is None:
            _test_app = QgsApplication([], False)
            _test_app.initQgis()
            atexit.register(_shutdown_test_application)
    return _test_app


def _shutdown_test_application():
    # Unload providers before Python/Qt module destruction, avoiding exit crashes.
    import gc
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    from qgis.core import QgsProject

    QgsProject.instance().clear()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()
    _test_app.exitQgis()
