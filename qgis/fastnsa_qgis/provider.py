"""Processing provider for FastNSA."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider

from .algorithms.nearest_edge import FastNearestEdgeMatchingAlgorithm
from .algorithms.network_k_function import FastNetworkKFunctionAlgorithm
from .algorithms.network_kde import FastNetworkKdeAlgorithm
from .algorithms.spatiotemporal_network_k_function import FastSpatiotemporalNetworkKFunctionAlgorithm


class FastNsaProvider(QgsProcessingProvider):
    """Registers FastNSA algorithms in the QGIS Processing Toolbox."""

    PROVIDER_ID = "fastnsa"
    PROVIDER_NAME = "FastNSA"

    def loadAlgorithms(self):
        self.addAlgorithm(FastNearestEdgeMatchingAlgorithm())
        self.addAlgorithm(FastNetworkKdeAlgorithm())
        self.addAlgorithm(FastNetworkKFunctionAlgorithm())
        self.addAlgorithm(FastSpatiotemporalNetworkKFunctionAlgorithm())

    def id(self):
        return self.PROVIDER_ID

    def name(self):
        return self.PROVIDER_NAME

    def longName(self):
        return self.PROVIDER_NAME

    def icon(self):
        return QIcon(self.iconPath())

    def iconPath(self):
        return str(Path(__file__).resolve().parent / "resources" / "icon.png")

    def supportsNonFileBasedOutput(self):
        return True
