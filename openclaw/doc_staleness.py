"""Document staleness — see repo copy."""
from pathlib import Path
import os
import json, logging, re
from typing import Any, Optional
import event_bus
logger = logging.getLogger("openclaw.doc_staleness")
class DocStalenessTracker:
    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state = {}
        p = self._data_dir / "doc_staleness_state.json"
        if p.is_file():
            try: self._state = json.loads(p.read_text(encoding="utf-8"))
            except Exception: pass
    def _save(self):
        try:
            (self._data_dir / "doc_staleness_state.json").write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("save: %s", e)
    def _redis_url(self):
        return (os.getenv("REDIS_URL") or "").strip()
    def publish_stale(self, *, project_key, client_name, docs, reason, old_value=None, new_value=None, notify_fn=None):
        payload = {"type": "doc.stale", "project_key": project_key, "client_name": client_name, "documents": docs, "reason": reason, "old_value": old_value, "new_value": new_value}
        u = self._redis_url()
        if u:
            try: event_bus.publish_and_log(u, "events:documents", payload)
            except Exception as e: logger.debug("pub: %s", e)
    def process_dtools_pipeline(self, pipeline: dict, *, notify_fn=None, linear_fn=None):
        stats = {"price_checks": 0, "stale_events": 0}
        opps = []
        for key in ("open_opportunities", "won_opportunities"):
            raw = pipeline.get(key) or {}
            if isinstance(raw, dict):
                opps.extend(raw.get("Data", raw.get("opportunities", [])))
        snap = self._state.setdefault("opportunity_prices", {})
        for opp in opps:
            stats["price_checks"] += 1
            oid = str(opp.get("id", opp.get("Id", "")))
            client = (opp.get("clientName", opp.get("ClientName", "")) or "").strip()
            if not oid or not client:
                continue
            try: price = float(opp.get("price", 0) or 0)
            except (TypeError, ValueError): price = 0.0
            ko = f"{client}|{oid}"
            prev = snap.get(ko)
            snap[ko] = price
            if prev is not None and abs(float(prev) - price) > 0.01:
                stats["stale_events"] += 1
                self.publish_stale(project_key=ko, client_name=client, docs=["agreement","deliverables"], reason="D-Tools opportunity price changed", old_value=float(prev), new_value=price, notify_fn=notify_fn)
        self._save()
        return stats
_tracker = None
def get_tracker(data_dir: Optional[Path]=None):
    global _tracker
    if _tracker is None:
        _tracker = DocStalenessTracker(data_dir or Path(os.getenv("DATA_DIR","/app/data")))
    return _tracker
DOCUMENT_REGISTRY = {}
DOC_IMPACT_MAP = []
