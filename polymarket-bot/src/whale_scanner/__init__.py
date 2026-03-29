"""Whale Signal Scanner — detects whale trades, insider patterns, and coordinated entries."""

from src.whale_scanner.trade_monitor import TradeMonitor
from src.whale_scanner.whale_detector import WhaleDetector, WhaleSignal
from src.whale_scanner.fresh_wallet_detector import FreshWalletDetector, InsiderSignal
from src.whale_scanner.cluster_detector import ClusterDetector, ClusterSignal
from src.whale_scanner.scanner_engine import ScannerEngine

__all__ = [
    "TradeMonitor",
    "WhaleDetector",
    "WhaleSignal",
    "FreshWalletDetector",
    "InsiderSignal",
    "ClusterDetector",
    "ClusterSignal",
    "ScannerEngine",
]
