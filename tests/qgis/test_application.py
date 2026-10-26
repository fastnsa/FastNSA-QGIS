"""Application ownership and orderly standalone QGIS test shutdown."""

import os
import unittest
from unittest.mock import MagicMock, patch

from tests import qgis as application


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from qgis.core import QgsApplication

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python bindings are unavailable")
class QgisApplicationTest(unittest.TestCase):
    def test_standalone_application_initialized_once(self):
        with patch.object(application, "_test_app", None), \
             patch("qgis.core.QgsApplication") as constructor, \
             patch.object(application.atexit, "register") as register:
            constructor.instance.return_value = None
            first = application.qgis_test_application()
            self.assertIs(application.qgis_test_application(), first)
            constructor.assert_called_once_with([], False)
            first.initQgis.assert_called_once_with()
            register.assert_called_once_with(application._shutdown_test_application)

    def test_existing_host_application_is_not_owned(self):
        with patch.object(application, "_test_app", None), \
             patch("qgis.core.QgsApplication") as constructor, \
             patch.object(application.atexit, "register") as register:
            host = constructor.instance.return_value
            self.assertIs(application.qgis_test_application(), host)
            constructor.assert_not_called()
            host.initQgis.assert_not_called()
            host.exitQgis.assert_not_called()
            register.assert_not_called()

    def test_shutdown_clears_project_before_unloading_providers(self):
        calls = MagicMock()
        with patch.object(application, "_test_app", calls.app), \
             patch("qgis.core.QgsProject") as project, \
             patch("qgis.PyQt.QtCore.QCoreApplication.sendPostedEvents") as flush, \
             patch("gc.collect") as collect:
            calls.attach_mock(project.instance.return_value.clear, "clear")
            calls.attach_mock(flush, "flush")
            calls.attach_mock(collect, "collect")
            application._shutdown_test_application()
            self.assertEqual(
                [call[0] for call in calls.mock_calls],
                ["clear", "flush", "collect", "app.exitQgis"],
            )
