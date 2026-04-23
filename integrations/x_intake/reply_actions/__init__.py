"""
reply_actions — Phase 1 foundation package.

Public API surface for the reply-action loop.
Phase 4 will add handler wiring; this package stays execution-free until then.
"""
from .action_store import ActionContext, ActionStore
from .formatter import format_card, strip_options_block
from .parser import ParsedReply, parse_reply

__all__ = [
    "parse_reply",
    "ParsedReply",
    "ActionStore",
    "ActionContext",
    "format_card",
    "strip_options_block",
]
