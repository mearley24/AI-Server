"""
X (Twitter) Link Intake Pipeline
---------------------------------
Detects X/Twitter URLs in incoming iMessages, fetches post content,
analyzes for trading intelligence, and reports back via iMessage.

Components:
    post_fetcher  - Retrieves post content from X/Twitter URLs
    analyzer      - Analyzes posts for trading signals and market relevance
    pipeline      - Orchestrates the full flow via Redis pub/sub
"""

from .post_fetcher import PostFetcher, PostData
from .analyzer import PostAnalyzer, AnalysisResult
from .bridge import XIntakeBridge
from .pipeline import XIntakePipeline

__all__ = [
    "PostFetcher",
    "PostData",
    "PostAnalyzer",
    "AnalysisResult",
    "XIntakePipeline",
    "XIntakeBridge",
]

__version__ = "1.0.0"
