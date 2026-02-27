#!/usr/bin/env python3
"""
D-Tools Cloud API Client — Symphony Smart Homes
Bridge module for Bob (The Conductor) to read/write D-Tools Cloud data.

Auth: Basic Auth (fixed header) + X-API-Key (user-specific)
Base URL: https://dtcloudapi.d-tools.cloud/api/v1/
SI API:   https://api.d-tools.com/si/
"""

import os
import json
import time
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLOUD_BASE = "https://dtcloudapi.d-tools.cloud/api/v1"
SI_BASE    = "https://api.d-tools.com/si"

BASIC_AUTH  = "Basic RFRDbG91ZEFQSVVzZXI6MyNRdVkrMkR1QCV3Kk15JTU8Yi1aZzlV"

logger = logging.getLogger("dtools_bridge")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


class DToolsCloudClient:
    """Thin REST client for D-Tools Cloud API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DTOOLS_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "D-Tools API key required. Set DTOOLS_API_KEY env var or pass api_key."
            )
        self.session = self._build_session()

    # ---------- session setup ----------
    def _build_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "Authorization": BASIC_AUTH,
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503])
        adapter = HTTPAdapter(max_retries=retries)
        s.mount("https://", adapter)
        return s

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict:
        logger.info("GET %s  params=%s", url, params)
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, url: str, payload: Dict) -> Dict:
        logger.info("POST %s", url)
        r = self.session.post(url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, url: str, payload: Dict) -> Dict:
        logger.info("PUT %s", url)
        r = self.session.put(url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    # =====================================================================
    # CLOUD API  (dtcloudapi.d-tools.cloud)
    # =====================================================================

    # ---------- Opportunities ----------
    def get_opportunities(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        """
        List opportunities (quotes / proposals).
        Status: Open, Won, Lost, etc.
        """
        params: Dict[str, Any] = {"Page": page, "PageSize": page_size}
        if status:
            params["Status"] = status
        return self._get(f"{CLOUD_BASE}/Opportunities/GetOpportunities", params)

    def get_opportunity(self, opportunity_id: str) -> Dict:
        """Get a single opportunity by ID."""
        return self._get(
            f"{CLOUD_BASE}/Opportunities/GetOpportunity",
            {"OpportunityId": opportunity_id},
        )

    # ---------- Projects ----------
    def get_projects(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        """List projects. Status: Active, Completed, OnHold, etc."""
        params: Dict[str, Any] = {"Page": page, "PageSize": page_size}
        if status:
            params["Status"] = status
        return self._get(f"{CLOUD_BASE}/Projects/GetProjects", params)

    def get_project(self, project_id: str) -> Dict:
        """Get a single project by ID."""
        return self._get(
            f"{CLOUD_BASE}/Projects/GetProject",
            {"ProjectId": project_id},
        )

    # ---------- Clients ----------
    def get_clients(self, page: int = 1, page_size: int = 50) -> Dict:
        """List all clients."""
        return self._get(
            f"{CLOUD_BASE}/Clients/GetClients",
            {"Page": page, "PageSize": page_size},
        )

    def get_client(self, client_id: str) -> Dict:
        """Get a single client by ID."""
        return self._get(
            f"{CLOUD_BASE}/Clients/GetClient",
            {"ClientId": client_id},
        )

    # ---------- Catalog ----------
    def search_catalog(
        self,
        keyword: str,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        """Search the product catalog."""
        params: Dict[str, Any] = {
            "Keyword": keyword,
            "Page": page,
            "PageSize": page_size,
        }
        if category:
            params["Category"] = category
        return self._get(f"{CLOUD_BASE}/Catalog/SearchCatalog", params)

    # =====================================================================
    # SI API  (api.d-tools.com/si)
    # =====================================================================

    def si_get_projects(self, page: int = 1, page_size: int = 50) -> Dict:
        """List projects via SI API."""
        return self._get(
            f"{SI_BASE}/Projects",
            {"page": page, "pageSize": page_size},
        )

    def si_get_tasks(self, project_id: str) -> Dict:
        """Get tasks for a SI project."""
        return self._get(f"{SI_BASE}/Projects/{project_id}/Tasks")

    def si_get_service_orders(self, project_id: str) -> Dict:
        """Get service orders for a project."""
        return self._get(f"{SI_BASE}/Projects/{project_id}/ServiceOrders")

    def si_get_purchase_orders(self, project_id: str) -> Dict:
        """Get purchase orders for a project."""
        return self._get(f"{SI_BASE}/Projects/{project_id}/PurchaseOrders")

    def si_get_clients(self) -> Dict:
        """List all clients via SI API."""
        return self._get(f"{SI_BASE}/Clients")

    # =====================================================================
    # CONVENIENCE / BOB HELPERS
    # =====================================================================

    def get_active_pipeline(self) -> Dict:
        """
        Get a unified view of active work:
        open opportunities + active projects.
        Returns a dict Bob can reason over.
        """
        opps = self.get_opportunities(status="Open")
        projects = self.get_projects(status="Active")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "open_opportunities": opps,
            "active_projects": projects,
        }

    def snapshot(self) -> Dict:
        """
        Quick snapshot of the D-Tools account.
        Useful for daily digest or Telegram /dtools command.
        """
        try:
            opps = self.get_opportunities(page_size=5)
            projects = self.get_projects(page_size=5)
            clients = self.get_clients(page_size=5)
            return {
                "status": "connected",
                "timestamp": datetime.utcnow().isoformat(),
                "recent_opportunities": opps,
                "recent_projects": projects,
                "recent_clients": clients,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def find_client_projects(self, client_name: str) -> Dict:
        """
        Find all projects for a client by name search.
        Bob uses this to pull context for proposals.
        """
        clients = self.get_clients(page_size=100)
        matched = []
        client_list = clients.get("Data", clients.get("data", []))
        for c in client_list:
            name = c.get("Name", c.get("name", ""))
            if client_name.lower() in name.lower():
                matched.append(c)

        results = []
        for client in matched:
            cid = client.get("Id", client.get("id", ""))
            projects = self.get_projects(page_size=100)
            proj_list = projects.get("Data", projects.get("data", []))
            client_projects = [
                p for p in proj_list
                if str(p.get("ClientId", p.get("clientId", ""))) == str(cid)
            ]
            results.append({
                "client": client,
                "projects": client_projects,
            })
        return {"matches": results, "query": client_name}

    def mark_opportunity_notes(self, opportunity_id: str, notes: str) -> Dict:
        """
        Add notes to an opportunity — this is how you 'mark out things'
        for Bob to pick up later.
        """
        try:
            return self._put(
                f"{CLOUD_BASE}/Opportunities/UpdateOpportunity",
                {"OpportunityId": opportunity_id, "Notes": notes},
            )
        except requests.HTTPError as e:
            logger.warning("Update failed (endpoint may differ): %s", e)
            return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# CLI for quick testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="D-Tools Cloud CLI")
    parser.add_argument("command", choices=[
        "snapshot", "opportunities", "projects", "clients",
        "catalog", "pipeline", "find-client",
    ])
    parser.add_argument("--status", default=None)
    parser.add_argument("--keyword", default=None)
    parser.add_argument("--client", default=None)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    client = DToolsCloudClient(api_key=args.api_key)

    if args.command == "snapshot":
        print(json.dumps(client.snapshot(), indent=2))
    elif args.command == "opportunities":
        print(json.dumps(client.get_opportunities(status=args.status), indent=2))
    elif args.command == "projects":
        print(json.dumps(client.get_projects(status=args.status), indent=2))
    elif args.command == "clients":
        print(json.dumps(client.get_clients(), indent=2))
    elif args.command == "catalog":
        if not args.keyword:
            print("--keyword required for catalog search")
        else:
            print(json.dumps(client.search_catalog(args.keyword), indent=2))
    elif args.command == "pipeline":
        print(json.dumps(client.get_active_pipeline(), indent=2))
    elif args.command == "find-client":
        if not args.client:
            print("--client required for find-client")
        else:
            print(json.dumps(client.find_client_projects(args.client), indent=2))
