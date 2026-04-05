#!/usr/bin/env python3
"""
dtools_browser_agent.py — D-Tools Cloud Browser Automation Agent

Automates D-Tools Cloud via browser to:
1. Create new projects
2. Import equipment CSV
3. Set project phases
4. Export proposals

Uses Playwright for browser automation (headless or visible).

Usage:
    python agents/dtools_browser_agent.py --login                    # Test login
    python agents/dtools_browser_agent.py --create "Mitchell"        # Create project
    python agents/dtools_browser_agent.py --import "Mitchell"        # Import CSV
    python agents/dtools_browser_agent.py --full "Mitchell"          # Full workflow
    python agents/dtools_browser_agent.py --batch                    # All pending
"""

import argparse
import logging
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

EXPORTS_DIR = BASE_DIR / "knowledge" / "exports"
SELECTORS_FILE = BASE_DIR / "integrations" / "dtools" / "page_selectors.yaml"
DTOOLS_URL = os.environ.get("DTOOLS_PORTAL_URL", "https://d-tools.cloud")


def _load_selectors() -> Dict:
    """Load page selectors from YAML. Edit integrations/dtools/page_selectors.yaml to teach the team."""
    if not SELECTORS_FILE.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(SELECTORS_FILE.read_text()) or {}
    except Exception:
        return {}


def _sel(section: str, key: str, default: str = "") -> str:
    """Get selector for section.key, with optional default."""
    sel = _load_selectors()
    val = (sel.get(section) or {}).get(key)
    return (val or default).strip()


def _sel_list(section: str, key: str, default: str = "") -> List[str]:
    """Get list of selectors to try (comma-separated). First match wins."""
    raw = _sel(section, key, default)
    return [s.strip() for s in raw.split(",") if s.strip()]

# D-Tools credentials from env (DTOOLS_USERNAME preferred, DTOOLS_EMAIL fallback)
DTOOLS_EMAIL = os.environ.get("DTOOLS_USERNAME", os.environ.get("DTOOLS_EMAIL", ""))
DTOOLS_PASSWORD = os.environ.get("DTOOLS_PASSWORD", "")


class DToolsBrowserAgent:
    """Browser automation for D-Tools Cloud."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.page = None
        self.logged_in = False

    async def _try_selectors(self, selectors: List[str], timeout: int = 5000):
        """Try each selector until one matches. Returns element or None."""
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _fill_first(self, selectors: List[str], value: str, timeout: int = 3000) -> bool:
        """Fill first matching input selector."""
        if value is None:
            return False
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout)
                if el:
                    await el.fill(str(value))
                    return True
            except Exception:
                continue
        return False

    async def _click_first(self, selectors: List[str], timeout: int = 3000) -> bool:
        """Click first matching selector."""
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=timeout)
                if el:
                    await el.click()
                    return True
            except Exception:
                continue
        return False
    
    async def start(self):
        """Start browser."""
        try:
            from playwright.async_api import async_playwright
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                slow_mo=100  # Slow down for reliability
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )
            self.page = await self.context.new_page()
            print(f"🌐 Browser started ({'headless' if self.headless else 'visible'})")
            return True
        except Exception as e:
            print(f"❌ Browser start failed: {e}")
            print("   Run: pip install playwright && playwright install chromium")
            return False
    
    async def stop(self):
        """Stop browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("🌐 Browser closed")
    
    async def login(self) -> bool:
        """Login to D-Tools Cloud. Uses page_selectors.yaml when available."""
        if not DTOOLS_EMAIL or not DTOOLS_PASSWORD:
            print("❌ DTOOLS_EMAIL and DTOOLS_PASSWORD required in .env")
            return False

        login_path = _sel("login", "url", "/login").lstrip("/") or "login"
        success_url = _sel("login", "success_url", "**/dashboard**")

        try:
            print(f"🔐 Logging into D-Tools...")
            await self.page.goto(f"{DTOOLS_URL}/{login_path}", wait_until="networkidle")

            email_sel = _sel_list("login", "email_input", 'input[type="email"], input[name="email"]')
            pw_sel = _sel_list("login", "password_input", 'input[type="password"], input[name="password"]')
            btn_sel = _sel_list("login", "submit_button", 'button[type="submit"], button:has-text("Sign In")')

            for sel in email_sel:
                try:
                    await self.page.fill(sel, DTOOLS_EMAIL)
                    break
                except Exception:
                    continue
            for sel in pw_sel:
                try:
                    await self.page.fill(sel, DTOOLS_PASSWORD)
                    break
                except Exception:
                    continue
            for sel in btn_sel:
                try:
                    await self.page.click(sel)
                    break
                except Exception:
                    continue

            await self.page.wait_for_url(success_url, timeout=15000)
            self.logged_in = True
            print("✅ Logged in successfully")
            return True
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return False
    
    async def ensure_logged_in(self) -> bool:
        """Ensure we're logged in."""
        if self.logged_in:
            return True
        return await self.login()
    
    async def search_project(self, project_name: str) -> Optional[Dict]:
        """Search for a project by name."""
        if not await self.ensure_logged_in():
            return None
        
        try:
            await self.page.goto(f"{DTOOLS_URL}/projects", wait_until="networkidle")
            
            # Search
            search_input = await self.page.wait_for_selector(
                'input[placeholder*="search"], input[type="search"]',
                timeout=5000
            )
            await search_input.fill(project_name)
            await self.page.keyboard.press("Enter")
            
            # Wait for results
            await self.page.wait_for_timeout(2000)
            
            # Check if project found
            rows = await self.page.query_selector_all('table tbody tr, [data-testid="project-row"]')
            
            for row in rows:
                text = await row.inner_text()
                if project_name.lower() in text.lower():
                    return {
                        "found": True,
                        "name": project_name,
                        "row_text": text
                    }
            
            return {"found": False, "name": project_name}
        except Exception as e:
            return {"found": False, "name": project_name, "error": str(e)}
    
    async def create_project(self, project_name: str, client_name: str = None, 
                            address: str = "", notes: str = "") -> Dict:
        """Create a new project in D-Tools."""
        if not await self.ensure_logged_in():
            return {"success": False, "error": "Not logged in"}
        
        # Check if already exists
        existing = await self.search_project(project_name)
        if existing and existing.get("found"):
            return {
                "success": False,
                "error": f"Project '{project_name}' already exists",
                "existing": existing
            }
        
        try:
            print(f"📝 Creating project: {project_name}")

            proj_path = _sel("projects", "url", "/projects").lstrip("/") or "projects"
            await self.page.goto(f"{DTOOLS_URL}/{proj_path}", wait_until="networkidle")

            new_sel = _sel_list("projects", "new_button", 'button:has-text("New"), a:has-text("New Project")')
            new_btn = await self._try_selectors(new_sel)
            if new_btn:
                await new_btn.click()
            else:
                raise Exception("Could not find New Project button")

            name_sel = _sel_list("create_project_form", "project_name_input", 'input[name="name"], input[name="projectName"]')
            name_el = await self._try_selectors(name_sel)
            if name_el:
                await name_el.fill(project_name)
            else:
                await self.page.fill('input[name="name"], input[name="projectName"]', project_name)

            if client_name:
                client_sel = _sel_list("create_project_form", "client_input", 'input[name="clientName"]')
                client_el = await self._try_selectors(client_sel, timeout=2000)
                if client_el:
                    await client_el.fill(client_name)

            if address:
                addr_sel = _sel_list("create_project_form", "address_input", 'input[name="address"]')
                addr_el = await self._try_selectors(addr_sel, timeout=2000)
                if addr_el:
                    await addr_el.fill(address)

            if notes:
                notes_sel = _sel_list("create_project_form", "notes_input", 'textarea[name="notes"]')
                notes_el = await self._try_selectors(notes_sel, timeout=2000)
                if notes_el:
                    await notes_el.fill(notes)

            submit_sel = _sel_list("create_project_form", "submit_button", 'button[type="submit"], button:has-text("Create"), button:has-text("Save")')
            for sel in submit_sel:
                try:
                    await self.page.click(sel)
                    break
                except Exception:
                    continue
            
            # Wait for success
            await self.page.wait_for_timeout(3000)
            
            # Verify created
            current_url = self.page.url
            
            return {
                "success": True,
                "project_name": project_name,
                "url": current_url,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"success": False, "error": str(e), "project_name": project_name}
    
    async def import_csv(self, project_name: str, csv_path: str = None, **kwargs) -> Dict:
        """Import equipment CSV into a project."""
        if not await self.ensure_logged_in():
            return {"success": False, "error": "Not logged in"}
        
        # Find CSV file
        if csv_path is None:
            # Look for project's CSV in exports
            possible_csvs = list(EXPORTS_DIR.glob(f"*{project_name}*DTools*.csv"))
            if not possible_csvs:
                possible_csvs = list(EXPORTS_DIR.glob(f"*{project_name}*.csv"))
            
            if not possible_csvs:
                return {"success": False, "error": f"No CSV found for {project_name}"}
            
            csv_path = str(possible_csvs[0])
        
        csv_path = Path(csv_path)
        if not csv_path.exists():
            return {"success": False, "error": f"CSV not found: {csv_path}"}
        
        try:
            print(f"📥 Importing CSV into {project_name}...")
            print(f"   File: {csv_path.name}")
            
            # Navigate to project
            project = await self.search_project(project_name)
            if not project or not project.get("found"):
                return {"success": False, "error": f"Project not found: {project_name}"}

            # Click to open project
            await self.page.click(f'tr:has-text("{project_name}")')
            await self.page.wait_for_timeout(2000)

            # Import button (from page_selectors.yaml)
            import_sel = _sel_list("import", "import_button", 'button:has-text("Import"), [data-testid="import-button"]')
            import_btn = await self._try_selectors(import_sel, timeout=8000)
            if import_btn:
                await import_btn.click()
            else:
                raise Exception("Could not find Import button")

            csv_sel = _sel_list("import", "csv_option", 'button:has-text("CSV"), [data-testid="import-csv"]')
            csv_el = await self._try_selectors(csv_sel, timeout=3000)
            if csv_el:
                await csv_el.click()

            file_sel = _sel_list("import", "file_input", 'input[type="file"]')
            file_el = await self._try_selectors(file_sel)
            if file_el:
                await file_el.set_input_files(str(csv_path))
            else:
                raise Exception("Could not find file input")

            await self.page.wait_for_timeout(2000)
            confirm_sel = _sel_list("import", "confirm_button", 'button:has-text("Import"), button:has-text("Confirm")')
            for sel in confirm_sel:
                try:
                    btn = await self.page.query_selector(sel)
                    if btn:
                        await btn.click()
                        break
                except Exception:
                    continue
            
            # Wait for completion
            await self.page.wait_for_timeout(5000)
            
            return {
                "success": True,
                "project_name": project_name,
                "csv_file": csv_path.name,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"success": False, "error": str(e), "project_name": project_name}

    async def create_product(self, product: Dict) -> Dict:
        """
        Create a catalog product in D-Tools Cloud.
        Best effort with resilient selectors for the New Product modal.
        """
        if not await self.ensure_logged_in():
            return {"success": False, "error": "Not logged in", "product": product}

        model = (product.get("model") or "").strip()
        if not model:
            return {"success": False, "error": "model is required", "product": product}

        try:
            products_path = _sel("products", "url", "/products").lstrip("/") or "products"
            await self.page.goto(f"{DTOOLS_URL}/{products_path}", wait_until="networkidle")

            opened = await self._click_first(
                _sel_list(
                    "products",
                    "new_product_button",
                    'button:has-text("New Product"), a:has-text("New Product"), button:has-text("New")'
                ),
                timeout=7000,
            )
            if not opened:
                return {
                    "success": False,
                    "error": "Could not find New Product button",
                    "product": product,
                }

            await self.page.wait_for_timeout(800)

            # Brand can be a select or input.
            brand = (product.get("brand") or "").strip()
            if brand:
                filled_brand = await self._fill_first(
                    [
                        'input[placeholder="Brand"]',
                        'input[name*="brand" i]',
                        'input[id*="brand" i]',
                    ],
                    brand,
                )
                if not filled_brand:
                    clicked_brand = await self._click_first(
                        [
                            'button:has-text("Brand")',
                            'label:has-text("Brand") + *',
                        ],
                        timeout=1500,
                    )
                    if clicked_brand:
                        try:
                            await self.page.keyboard.type(brand)
                            await self.page.keyboard.press("Enter")
                        except Exception:
                            pass

            await self._fill_first(
                [
                    'input[placeholder="Model"]',
                    'input[name*="model" i]',
                    'input[id*="model" i]',
                ],
                model,
            )

            part_number = (product.get("part_number") or "").strip()
            if part_number:
                await self._fill_first(
                    [
                        'input[placeholder*="Part" i]',
                        'input[name*="part" i]',
                        'input[id*="part" i]',
                    ],
                    part_number,
                )

            # Category picker.
            category = (product.get("category") or "").strip()
            if category:
                opened_category = await self._click_first(
                    [
                        'button:has-text("Select category")',
                        'button:has-text("Category")',
                        '[aria-label*="category" i]',
                    ],
                    timeout=2500,
                )
                if opened_category:
                    try:
                        option = await self.page.wait_for_selector(
                            f'text="{category}"',
                            timeout=2000,
                        )
                        await option.click()
                    except Exception:
                        # Fall back to keyboard type/enter.
                        try:
                            await self.page.keyboard.type(category)
                            await self.page.keyboard.press("Enter")
                        except Exception:
                            pass

            short_description = (product.get("short_description") or "").strip()
            if short_description:
                await self._fill_first(
                    [
                        'textarea[placeholder*="description" i]',
                        'textarea[name*="description" i]',
                        'textarea[id*="description" i]',
                    ],
                    short_description[:300],
                )

            keywords = (product.get("keywords") or "").strip()
            if keywords:
                await self._fill_first(
                    [
                        'input[placeholder*="Keywords" i]',
                        'input[name*="keyword" i]',
                        'input[id*="keyword" i]',
                    ],
                    keywords,
                )

            # Pricing fields
            unit_price = product.get("unit_price")
            unit_cost = product.get("unit_cost")
            msrp = product.get("msrp")

            if unit_price is not None:
                await self._fill_first(
                    [
                        'xpath=//label[contains(.,"Unit Price")]/following::input[1]',
                    ],
                    f"{float(unit_price):.2f}",
                )
            if unit_cost is not None:
                await self._fill_first(
                    [
                        'xpath=//label[contains(.,"Unit Cost")]/following::input[1]',
                    ],
                    f"{float(unit_cost):.2f}",
                )
            if msrp is not None:
                await self._fill_first(
                    [
                        'xpath=//label[contains(.,"MSRP")]/following::input[1]',
                    ],
                    f"{float(msrp):.2f}",
                )

            # Supplier selector
            supplier = (product.get("supplier") or "").strip()
            if supplier:
                opened_supplier = await self._click_first(
                    [
                        'button:has-text("Select supplier")',
                        'button:has-text("Supplier")',
                    ],
                    timeout=2500,
                )
                if opened_supplier:
                    try:
                        option = await self.page.wait_for_selector(
                            f'text="{supplier}"',
                            timeout=2000,
                        )
                        await option.click()
                    except Exception:
                        try:
                            await self.page.keyboard.type(supplier)
                            await self.page.keyboard.press("Enter")
                        except Exception:
                            pass

            created = await self._click_first(
                [
                    'button:has-text("Create")',
                    'button[type="submit"]',
                ],
                timeout=3000,
            )
            if not created:
                return {
                    "success": False,
                    "error": "Could not find Create button",
                    "product": product,
                }

            await self.page.wait_for_timeout(1500)
            return {
                "success": True,
                "model": model,
                "part_number": part_number,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "model": model,
                "part_number": product.get("part_number", ""),
            }
    
    async def full_workflow(
        self,
        project_name: str,
        client_name: str = None,
        address: str = "",
        csv_path: str = None,
    ) -> Dict:
        """Run full workflow: create project, import CSV."""
        results = {
            "project_name": project_name,
            "steps": [],
            "success": False
        }

        # Step 1: Create project (or verify exists)
        print(f"\n{'='*50}")
        print(f"🔧 Full workflow for: {project_name}")
        print(f"{'='*50}\n")

        create_result = await self.create_project(
            project_name,
            client_name=client_name,
            address=address,
        )
        results["steps"].append({"step": "create_project", "result": create_result})

        if not create_result.get("success"):
            # Check if it's because project exists
            if "already exists" in create_result.get("error", ""):
                print(f"   Project exists, continuing...")
            else:
                results["error"] = create_result.get("error")
                return results

        # Step 2: Import CSV
        import_result = await self.import_csv(project_name, csv_path=csv_path)
        results["steps"].append({"step": "import_csv", "result": import_result})

        if import_result.get("success"):
            results["success"] = True
            print(f"\n✅ Workflow complete for {project_name}")
        else:
            results["error"] = import_result.get("error")
            print(f"\n❌ Workflow failed: {import_result.get('error')}")

        return results
    
    async def batch_process(self, project_names: List[str] = None) -> Dict:
        """Process multiple projects."""
        if project_names is None:
            # Find all CSVs in exports
            csvs = list(EXPORTS_DIR.glob("*_DTools*.csv"))
            project_names = []
            for csv in csvs:
                # Extract project name from filename
                name = csv.stem.replace("_DTools", "").replace("_Proposal", "").replace("_Import", "")
                if name not in project_names:
                    project_names.append(name)
        
        results = {
            "total": len(project_names),
            "success": 0,
            "failed": 0,
            "projects": []
        }
        
        for name in project_names:
            print(f"\n{'='*50}")
            print(f"Processing: {name}")
            
            result = await self.full_workflow(name)
            results["projects"].append(result)
            
            if result.get("success"):
                results["success"] += 1
            else:
                results["failed"] += 1
        
        return results


async def main():
    parser = argparse.ArgumentParser(description="D-Tools Browser Agent")
    parser.add_argument("--login", action="store_true", help="Test login")
    parser.add_argument("--search", metavar="NAME", help="Search for project")
    parser.add_argument("--create", metavar="NAME", help="Create project")
    parser.add_argument("--import", dest="import_csv", metavar="NAME", help="Import CSV to project")
    parser.add_argument("--full", metavar="NAME", help="Full workflow (create + import)")
    parser.add_argument("--batch", action="store_true", help="Process all pending")
    parser.add_argument("--visible", action="store_true", help="Show browser window")
    parser.add_argument("--json", action="store_true", help="JSON output")
    
    args = parser.parse_args()
    
    # Check for playwright
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Playwright not installed")
        print("   Run: pip install playwright && playwright install chromium")
        sys.exit(1)
    
    if not (DTOOLS_EMAIL and DTOOLS_PASSWORD):
        logging.warning(
            "DTOOLS_EMAIL/DTOOLS_PASSWORD not set — browser login will fail until credentials are configured"
        )

    agent = DToolsBrowserAgent(headless=not args.visible)
    
    if not await agent.start():
        sys.exit(1)
    
    try:
        if args.login:
            result = await agent.login()
            print("✅ Login successful" if result else "❌ Login failed")
        
        elif args.search:
            result = await agent.search_project(args.search)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                if result.get("found"):
                    print(f"✅ Found: {result['name']}")
                else:
                    print(f"❌ Not found: {args.search}")
        
        elif args.create:
            result = await agent.create_project(args.create)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                if result.get("success"):
                    print(f"✅ Created: {args.create}")
                else:
                    print(f"❌ Failed: {result.get('error')}")
        
        elif args.import_csv:
            result = await agent.import_csv(args.import_csv)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                if result.get("success"):
                    print(f"✅ Imported CSV to: {args.import_csv}")
                else:
                    print(f"❌ Failed: {result.get('error')}")
        
        elif args.full:
            result = await agent.full_workflow(args.full)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                if result.get("success"):
                    print(f"\n✅ Full workflow complete: {args.full}")
                else:
                    print(f"\n❌ Failed: {result.get('error')}")
        
        elif args.batch:
            result = await agent.batch_process()
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"\n{'='*50}")
                print(f"📊 Batch Complete")
                print(f"   Total: {result['total']}")
                print(f"   Success: {result['success']}")
                print(f"   Failed: {result['failed']}")
        
        else:
            parser.print_help()
    
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
