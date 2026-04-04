"""Document regeneration helpers — wraps tools/generate_agreement.py when mounted at /app/tools."""
from __future__ import annotations
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path as P
from typing import Any

logger = logging.getLogger("openclaw.doc_generator")

@dataclass
class DocGenerator:
    tools_script: P = P("/app/tools/generate_agreement.py")
    signature_path: P = P("/app/knowledge/brand/matt_earley_signature.png")
    symphony_docs: P = P("/data/symphony_docs")

    def signature_ok(self) -> bool:
        return self.signature_path.is_file()

    def generate_agreement_docx(self, *, client: str, project: str, items: str = "", integrations: str = "", support_days: int = 90, approved: bool = False) -> dict[str, Any]:
        if not approved:
            return {"status": "skipped", "reason": "approval_required"}
        if not self.tools_script.is_file():
            return {"status": "error", "reason": "tools_missing", "path": str(self.tools_script)}
        cmd = [sys.executable, str(self.tools_script), "--client", client, "--project", project, "--items", items, "--integrations", integrations, "--support-days", str(support_days)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(self.tools_script.parent))
            out = (proc.stdout or "").strip()
            if proc.returncode != 0:
                return {"status": "error", "stderr": (proc.stderr or "")[:2000]}
            return {"status": "ok", "output_path": out}
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    def plan_regeneration(self, *, client_name: str, pricing_note: str = "", approved: bool = False) -> dict[str, Any]:
        return {"status": "planned" if not approved else "ready", "client": client_name, "date": date.today().isoformat(), "signature_present": self.signature_ok(), "pricing_note": pricing_note}

def get_generator() -> DocGenerator:
    return DocGenerator()
