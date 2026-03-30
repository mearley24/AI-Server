"""
Symphony Smart Homes — Standardized Project Template
Auto-creates Linear project with 22 issues when a job enters WON phase.

Usage:
    from project_template import create_project_from_template
    create_project_from_template(client_name, address, dtool_proposal, total_price)
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 22-issue template organized by phase
PROJECT_PHASES = [
    {
        "phase": "Phase 1: Pre-Sale & Scope",
        "issues": [
            {
                "title": "Initial client consultation & RFP review",
                "description": "Review client RFP/requirements. Document all preferences, concerns, and special requests. Note client communication style and decision-making pace.",
                "priority": 2,  # High
            },
            {
                "title": "Design system architecture & create proposal",
                "description": "D-Tools proposal creation. Rack elevation, network topology, audio zones, lighting layout. All equipment specified with model numbers.",
                "priority": 2,
            },
            {
                "title": "Build deliverables package",
                "description": "Compile rack elevation drawing, network topology, lighting load schedule, scope summary with change log. Verify ALL claims (warranties, specs, power) against manufacturer data before sending.",
                "priority": 2,
            },
            {
                "title": "Internal review of deliverables",
                "description": "Matthew reviews all documents before anything goes to client. Check: correct client name, correct pricing, correct equipment, no placeholder data, all claims verified.",
                "priority": 1,  # Urgent
            },
            {
                "title": "Send deliverables + proposal to client",
                "description": "Send verified deliverables package and D-Tools proposal to client. Draft email in Zoho, notify Matthew for review, wait for him to send. Log date sent.",
                "priority": 2,
            },
            {
                "title": "Client review & pending decisions",
                "description": "Track all client feedback, questions, and pending decisions. Do not proceed until all open items resolved.",
                "priority": 1,
            },
            {
                "title": "Finalize agreement & contract",
                "description": "Formal agreement/contract signed. ALL paperwork finalized before first check or first wire pulled. No exceptions.",
                "priority": 1,
            },
        ],
    },
    {
        "phase": "Phase 2: Pre-Wire & Procurement",
        "issues": [
            {
                "title": "Collect deposit",
                "description": "Deposit received per payment schedule. Log amount, date, method. No equipment ordered until deposit clears.",
                "priority": 1,
            },
            {
                "title": "Order equipment from Snap One / D-Tools",
                "description": "Pull equipment list from D-Tools opportunity. Submit purchase orders. Track lead times. No substitutions without written client approval.",
                "priority": 2,
            },
            {
                "title": "On-site walkthrough with client",
                "description": "Walk every room with client. Confirm device placement, keypad locations, speaker positions, AP mounting points. May reduce device count through consolidation. Document all decisions.",
                "priority": 2,
            },
            {
                "title": "Pre-wire rough-in",
                "description": "Run all low-voltage cabling. Speaker wire, Cat6, control wiring. Photo-document all runs before drywall.",
                "priority": 3,  # Medium
            },
            {
                "title": "Pre-wire inspection & sign-off",
                "description": "Verify all runs, label everything, photo-document. Collect pre-wire completion payment per schedule.",
                "priority": 3,
            },
        ],
    },
    {
        "phase": "Phase 3: Trim & Installation",
        "issues": [
            {
                "title": "Rack build & equipment mounting",
                "description": "Mount rack, install all equipment per rack elevation drawing. Cable management, power connections, ventilation clearances per manufacturer specs.",
                "priority": 2,
            },
            {
                "title": "Network commissioning",
                "description": "Configure VLANs, firewall rules, DHCP reservations, WiFi SSIDs. Assign IPs per network topology document. Populate MAC/serial fields.",
                "priority": 2,
            },
            {
                "title": "Audio system commissioning",
                "description": "Wire amps to speakers, configure zones in AMS, test every zone. Level matching and EQ.",
                "priority": 3,
            },
            {
                "title": "Lighting programming",
                "description": "Program all scenes, keypads, schedules. Test every load. Confirm no ghosting.",
                "priority": 3,
            },
            {
                "title": "Control4 programming & integration",
                "description": "Full system programming: lighting scenes, audio zones, shade integration, scheduling, touchscreen/remote UI.",
                "priority": 2,
            },
            {
                "title": "Trim completion payment",
                "description": "Collect trim completion payment per schedule.",
                "priority": 3,
            },
        ],
    },
    {
        "phase": "Phase 4: Commissioning & Handoff",
        "issues": [
            {
                "title": "Full system QA & punch list",
                "description": "Test every subsystem end-to-end. Create punch list. Fix all issues before client walkthrough.",
                "priority": 2,
            },
            {
                "title": "Client walkthrough & training",
                "description": "Walk client through entire system. Demonstrate all scenes, zones, remotes, touchscreens. Address every question.",
                "priority": 2,
            },
            {
                "title": "Final sign-off & completion payment",
                "description": "Client signs off on completed system. Collect final payment per schedule.",
                "priority": 1,
            },
            {
                "title": "Warranty documentation & handoff",
                "description": "Provide all warranty info, manuals, login credentials, network diagram. Store in client's project folder on iCloud.",
                "priority": 3,
            },
        ],
    },
]

WORKFLOW_RULES = """
## Workflow Rules (apply to every Symphony project)

1. All outbound emails drafted in Zoho, never auto-sent. Bob drafts the email in
   Zoho Mail drafts folder, then notifies Matthew via iMessage that a draft is
   ready for review. Matthew reviews, requests changes, or sends it himself.
2. ALL paperwork finalized before first check or first wire pulled.
3. No substitutions without written client approval.
4. Verify all claims against manufacturer data.
5. When a step needs client input, the next step is always "Send to client + wait."
6. Document every client decision with approval reference (email subject, date, who).
7. Photo-document all pre-wire runs before drywall closes.
8. Populate commissioning fields on-site (MAC, serial, switch port) — not before.
9. Client preferences tracked from day one.
"""


def build_issue_list(
    client_name: str,
    address: str,
    dtool_proposal: str = "",
    total_price: str = "",
) -> list[dict]:
    """
    Returns the 22 issues with client-specific details interpolated into descriptions.
    """
    issues = []
    sort_order = -10000.0

    for phase in PROJECT_PHASES:
        for issue in phase["issues"]:
            desc = issue["description"]
            # Interpolate client details where relevant
            desc = desc.replace("client", f"client ({client_name})")
            if dtool_proposal and "D-Tools" in desc:
                desc += f"\n\nD-Tools Proposal: {dtool_proposal}"
            if total_price and "payment" in desc.lower():
                desc += f"\n\nProject total: {total_price}"

            issues.append(
                {
                    "title": issue["title"],
                    "description": f"**{phase['phase']}**\n\n{desc}",
                    "priority": issue["priority"],
                    "sort_order": sort_order,
                }
            )
            sort_order += 500.0

    return issues


def create_project_from_template(
    client_name: str,
    address: str,
    dtool_proposal: str = "",
    total_price: str = "",
    team_id: str = "b1ba685a-0eff-43fe-bec9-023e3c455672",  # SymphonySH
    linear_api_key: Optional[str] = None,
) -> dict:
    """
    Creates a Linear project with all 22 template issues.
    Returns project ID and issue identifiers.

    This is called by job_lifecycle.py when a job transitions to WON phase.
    """
    api_key = linear_api_key or os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise ValueError("LINEAR_API_KEY not set")

    import requests

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    gql_url = "https://api.linear.app/graphql"

    # 1. Create the project
    project_name = f"{client_name} — {address}"
    create_project_mutation = """
    mutation CreateProject($input: ProjectCreateInput!) {
        projectCreate(input: $input) {
            success
            project { id name }
        }
    }
    """
    proj_resp = requests.post(
        gql_url,
        headers=headers,
        json={
            "query": create_project_mutation,
            "variables": {
                "input": {
                    "name": project_name,
                    "teamIds": [team_id],
                }
            },
        },
    )
    proj_data = proj_resp.json()
    project_id = proj_data["data"]["projectCreate"]["project"]["id"]
    logger.info(f"Created Linear project: {project_name} ({project_id})")

    # 2. Create all 22 issues
    issues = build_issue_list(client_name, address, dtool_proposal, total_price)
    created_issues = []

    create_issue_mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue { id identifier title }
        }
    }
    """

    for issue in issues:
        issue_resp = requests.post(
            gql_url,
            headers=headers,
            json={
                "query": create_issue_mutation,
                "variables": {
                    "input": {
                        "teamId": team_id,
                        "projectId": project_id,
                        "title": issue["title"],
                        "description": issue["description"],
                        "priority": issue["priority"],
                        "sortOrder": issue["sort_order"],
                    }
                },
            },
        )
        issue_data = issue_resp.json()
        created = issue_data["data"]["issueCreate"]["issue"]
        created_issues.append(created)
        logger.info(f"  Created {created['identifier']}: {created['title']}")

    return {
        "project_id": project_id,
        "project_name": project_name,
        "issues": created_issues,
    }


if __name__ == "__main__":
    # Example usage / test
    print("Symphony Smart Homes — Project Template")
    print(f"Total phases: {len(PROJECT_PHASES)}")
    total_issues = sum(len(p['issues']) for p in PROJECT_PHASES)
    print(f"Total issues per project: {total_issues}")
    print()
    for phase in PROJECT_PHASES:
        print(f"\n{phase['phase']} ({len(phase['issues'])} issues)")
        for i, issue in enumerate(phase["issues"], 1):
            priority_map = {1: "URGENT", 2: "HIGH", 3: "MEDIUM", 4: "LOW"}
            print(f"  {i}. [{priority_map[issue['priority']]}] {issue['title']}")
    print(f"\n{WORKFLOW_RULES}")
