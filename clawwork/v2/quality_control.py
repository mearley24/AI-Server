#!/usr/bin/env python3
"""
quality_control.py
==================
Pre-submission quality assurance engine for Bob's ClawWork deliverables.

Runs a multi-layer quality check on every deliverable before submission:
  1. Structure check — required sections, headers, length
  2. Language check  — grammar indicators, readability, tone
  3. Content check   — relevance, completeness, citation presence
  4. Format check    — markdown consistency, code block validity, table structure
  5. Sector check    — sector-specific requirements (e.g. financial disclaimers)

Each check produces a score (0–1.0). The aggregate is weighted to a final
quality score. If below threshold, the deliverable is flagged for revision.

Usage:
    from quality_control import QualityChecker, Deliverable
    qc = QualityChecker()
    report = qc.check(deliverable)
    if not report.passed:
        # revise and recheck
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("clawwork.qc")

# ── Thresholds ──────────────────────────────────────────────────────────────────────────

SCORE_PASS           = 0.85   # Submit as-is
SCORE_REVISE         = 0.75   # Auto-revise before submit
SCORE_REJECT         = 0.65   # Do not submit; regenerate from scratch

CHECK_WEIGHTS = {
    "structure":  0.25,
    "language":   0.30,
    "content":    0.25,
    "format":     0.10,
    "sector":     0.10,
}

# Readability: target Flesch-Kincaid grade level
FK_TARGET_MIN = 8
FK_TARGET_MAX = 14


# ── Data classes ────────────────────────────────────────────────────────────────────────

@dataclass
class Deliverable:
    """
    A completed task deliverable ready for QC review.
    """
    task_id:       str
    sector:        str          # 'research_reports', 'content_writing', etc.
    content:       str          # The actual deliverable text
    brief:         str = ""     # Original task brief (for relevance check)
    word_count_req: Optional[int] = None   # Required word count from brief
    required_sections: list = field(default_factory=list)  # e.g. ['Executive Summary', 'Methodology']
    platform:      str = "generic"


@dataclass
class QualityIssue:
    """
    A single quality problem identified during checking.
    """
    check:     str     # Which check found it: 'structure', 'language', etc.
    severity:  str     # 'critical' | 'major' | 'minor'
    message:   str
    suggestion: str = ""


@dataclass
class QualityReport:
    """
    Full output of a QC run.
    """
    deliverable:      Deliverable
    overall_score:    float
    structure_score:  float
    language_score:   float
    content_score:    float
    format_score:     float
    sector_score:     float
    passed:           bool
    action:           str        # 'submit' | 'revise' | 'reject'
    issues:           list       = field(default_factory=list)  # list of QualityIssue
    summary:          str        = ""


# ── Sector-specific requirements ───────────────────────────────────────────────────────

SECTOR_REQUIREMENTS = {
    "research_reports": {
        "min_words":         800,
        "max_words":         5000,
        "required_sections": ["Executive Summary", "Methodology", "Findings"],
        "requires_citations": True,
        "requires_tables":    True,
        "disclaimer":         None,
    },
    "financial_analysis": {
        "min_words":         600,
        "max_words":         3000,
        "required_sections": ["Summary", "Analysis", "Recommendation"],
        "requires_citations": True,
        "requires_tables":    True,
        "disclaimer":         "This report is for informational purposes only and does not constitute financial advice.",
    },
    "technical_writing": {
        "min_words":         300,
        "max_words":         10000,
        "required_sections": [],
        "requires_citations": False,
        "requires_tables":    False,
        "disclaimer":         None,
    },
    "content_writing": {
        "min_words":         300,
        "max_words":         3000,
        "required_sections": [],
        "requires_citations": False,
        "requires_tables":    False,
        "disclaimer":         None,
    },
    "real_estate": {
        "min_words":         100,
        "max_words":         2000,
        "required_sections": [],
        "requires_citations": False,
        "requires_tables":    False,
        "disclaimer":         None,
    },
    "bookkeeping": {
        "min_words":         50,
        "max_words":         5000,
        "required_sections": [],
        "requires_citations": False,
        "requires_tables":    True,
        "disclaimer":         "Prepared for informational purposes. Consult a CPA for tax or compliance decisions.",
    },
    "code_review": {
        "min_words":         200,
        "max_words":         5000,
        "required_sections": ["Summary", "Issues"],
        "requires_citations": False,
        "requires_tables":    False,
        "disclaimer":         None,
    },
    "customer_support": {
        "min_words":         50,
        "max_words":         500,
        "required_sections": [],
        "requires_citations": False,
        "requires_tables":    False,
        "disclaimer":         None,
    },
    "data_entry": {
        "min_words":         0,
        "max_words":         999999,
        "required_sections": [],
        "requires_citations": False,
        "requires_tables":    False,
        "disclaimer":         None,
    },
}

DEFAULT_REQUIREMENTS = {
    "min_words": 100,
    "max_words": 10000,
    "required_sections": [],
    "requires_citations": False,
    "requires_tables": False,
    "disclaimer": None,
}


# ── QualityChecker ───────────────────────────────────────────────────────────────────────

class QualityChecker:
    """
    Multi-layer quality assurance for ClawWork deliverables.

    Each check is independent and returns a score in [0, 1.0].
    Final score is a weighted average per CHECK_WEIGHTS.
    """

    def check(self, deliverable: Deliverable) -> QualityReport:
        """
        Run all quality checks on a deliverable.

        Returns a QualityReport with pass/fail decision and actionable issues.
        """
        reqs = {**DEFAULT_REQUIREMENTS,
                **SECTOR_REQUIREMENTS.get(deliverable.sector, {})}

        issues = []

        structure_score = self._check_structure(deliverable, reqs, issues)
        language_score  = self._check_language(deliverable, reqs, issues)
        content_score   = self._check_content(deliverable, reqs, issues)
        format_score    = self._check_format(deliverable, reqs, issues)
        sector_score    = self._check_sector(deliverable, reqs, issues)

        overall = (
            structure_score * CHECK_WEIGHTS["structure"] +
            language_score  * CHECK_WEIGHTS["language"]  +
            content_score   * CHECK_WEIGHTS["content"]   +
            format_score    * CHECK_WEIGHTS["format"]    +
            sector_score    * CHECK_WEIGHTS["sector"]
        )

        if overall >= SCORE_PASS:
            action = "submit"
        elif overall >= SCORE_REVISE:
            action = "revise"
        else:
            action = "reject"

        passed  = overall >= SCORE_REVISE
        summary = self._generate_summary(overall, action, issues)

        report = QualityReport(
            deliverable     = deliverable,
            overall_score   = round(overall, 4),
            structure_score = round(structure_score, 4),
            language_score  = round(language_score, 4),
            content_score   = round(content_score, 4),
            format_score    = round(format_score, 4),
            sector_score    = round(sector_score, 4),
            passed          = passed,
            action          = action,
            issues          = issues,
            summary         = summary,
        )
        log.info("QC %s | overall=%.4f | action=%s | issues=%d",
                 deliverable.task_id, overall, action, len(issues))
        return report

    # ── Check 1: Structure ─────────────────────────────────────────────────────────────

    def _check_structure(self, d: Deliverable, reqs: dict, issues: list) -> float:
        """
        Checks: word count, required sections, minimum length.
        """
        score      = 1.0
        word_count = len(d.content.split())

        # Word count check
        min_w = d.word_count_req or reqs["min_words"]
        max_w = reqs["max_words"]

        if word_count < min_w * 0.80:
            pct = word_count / min_w * 100
            issues.append(QualityIssue(
                check="structure", severity="major",
                message=f"Word count {word_count} is below minimum {min_w} ({pct:.0f}%)",
                suggestion=f"Add approximately {min_w - word_count} more words to meet the brief.",
            ))
            score -= 0.30
        elif word_count < min_w:
            issues.append(QualityIssue(
                check="structure", severity="minor",
                message=f"Word count {word_count} slightly below minimum {min_w}",
                suggestion="Expand slightly to meet the specification.",
            ))
            score -= 0.10

        if word_count > max_w * 1.20:
            issues.append(QualityIssue(
                check="structure", severity="minor",
                message=f"Word count {word_count} exceeds maximum {max_w}",
                suggestion="Trim content to stay within spec.",
            ))
            score -= 0.10

        # Required sections check
        all_required = list(reqs.get("required_sections", [])) + list(d.required_sections)
        for section in all_required:
            if section.lower() not in d.content.lower():
                issues.append(QualityIssue(
                    check="structure", severity="critical",
                    message=f"Required section missing: '{section}'",
                    suggestion=f"Add a '{section}' section to the deliverable.",
                ))
                score -= 0.20

        return max(0.0, score)

    # ── Check 2: Language ───────────────────────────────────────────────────────────────

    def _check_language(self, d: Deliverable, reqs: dict, issues: list) -> float:
        """
        Checks: filler phrases, passive voice overuse, readability proxies,
        repetitive sentence starters, AI tell-tale patterns.
        """
        score   = 1.0
        content = d.content
        lower   = content.lower()
        words   = content.split()

        # AI filler phrase detection
        ai_fillers = [
            "certainly!", "absolutely!", "of course!", "great question",
            "as an ai", "as a language model", "i cannot", "i'm unable to",
            "in conclusion,", "in summary,", "it is important to note",
            "it is worth noting", "it should be noted", "needless to say",
            "the bottom line is", "at the end of the day",
        ]
        filler_count = sum(1 for f in ai_fillers if f in lower)
        if filler_count >= 3:
            issues.append(QualityIssue(
                check="language", severity="major",
                message=f"Detected {filler_count} AI-typical filler phrases",
                suggestion="Rewrite to sound more direct and professional. Remove hedging and AI disclaimers.",
            ))
            score -= 0.25
        elif filler_count >= 1:
            issues.append(QualityIssue(
                check="language", severity="minor",
                message=f"Detected {filler_count} potential filler phrase(s)",
                suggestion="Review for overly formulaic language.",
            ))
            score -= 0.10

        # Passive voice proxy ("was [verb]ed", "is [verb]ed", "were [verb]ed")
        passive_matches = len(re.findall(
            r'\b(was|is|were|are|been|being)\s+\w+ed\b', lower
        ))
        sentence_count  = max(1, len(re.split(r'[.!?]+', content)))
        passive_rate    = passive_matches / sentence_count
        if passive_rate > 0.40:
            issues.append(QualityIssue(
                check="language", severity="minor",
                message=f"High passive voice rate ({passive_rate:.0%})",
                suggestion="Convert passive constructions to active voice for stronger, cleaner writing.",
            ))
            score -= 0.15

        # Repetitive sentence starter check
        sentences     = [s.strip() for s in re.split(r'[.!?]+', content) if s.strip()]
        starters      = [s.split()[0].lower() for s in sentences if s.split()]
        if starters:
            most_common   = max(set(starters), key=starters.count)
            starter_freq  = starters.count(most_common) / len(starters)
            if starter_freq > 0.30 and len(starters) > 5:
                issues.append(QualityIssue(
                    check="language", severity="minor",
                    message=f"Repetitive sentence starter: '{most_common}' ({starter_freq:.0%} of sentences)",
                    suggestion="Vary sentence structure to improve readability.",
                ))
                score -= 0.10

        # Rough Flesch-Kincaid grade level proxy
        syllable_count  = sum(self._estimate_syllables(w) for w in words)
        avg_syllables   = syllable_count / max(1, len(words))
        avg_sent_len    = len(words) / max(1, sentence_count)
        fk_grade        = 0.39 * avg_sent_len + 11.8 * avg_syllables - 15.59

        if fk_grade < FK_TARGET_MIN:
            issues.append(QualityIssue(
                check="language", severity="minor",
                message=f"Readability too simple (FK grade ~{fk_grade:.1f}, target {FK_TARGET_MIN}–{FK_TARGET_MAX})",
                suggestion="Use more precise, domain-specific vocabulary.",
            ))
            score -= 0.05
        elif fk_grade > FK_TARGET_MAX:
            issues.append(QualityIssue(
                check="language", severity="minor",
                message=f"Readability too complex (FK grade ~{fk_grade:.1f}, target {FK_TARGET_MIN}–{FK_TARGET_MAX})",
                suggestion="Simplify sentence structure for the target audience.",
            ))
            score -= 0.05

        return max(0.0, score)

    def _estimate_syllables(self, word: str) -> int:
        """Rough syllable count for FK calculation."""
        word = word.lower().strip(".,!?;:")
        if len(word) <= 3:
            return 1
        vowels = "aeiouy"
        count  = 0
        prev_v = False
        for ch in word:
            is_v = ch in vowels
            if is_v and not prev_v:
                count += 1
            prev_v = is_v
        if word.endswith("e") and count > 1:
            count -= 1
        return max(1, count)

    # ── Check 3: Content ────────────────────────────────────────────────────────────────

    def _check_content(self, d: Deliverable, reqs: dict, issues: list) -> float:
        """
        Checks: citations if required, keyword coverage from brief,
        tables if required, basic relevance.
        """
        score = 1.0
        lower = d.content.lower()

        # Citations check
        has_citations = bool(
            re.search(r'\[\d+\]|\(\d{4}\)|https?://|www\.|\bsource:\b|\.gov|\betal\.\b',
                      d.content, re.IGNORECASE)
        )
        if reqs.get("requires_citations") and not has_citations:
            issues.append(QualityIssue(
                check="content", severity="major",
                message="No citations or sources found",
                suggestion="Add at least 2–3 cited sources (URLs, author (year), or [1] style).",
            ))
            score -= 0.25

        # Tables check
        has_table = bool(re.search(r'\|.+\|', d.content))
        if reqs.get("requires_tables") and not has_table:
            issues.append(QualityIssue(
                check="content", severity="minor",
                message="No tables found",
                suggestion="Add a summary or comparison table to improve scannability.",
            ))
            score -= 0.15

        # Brief keyword coverage (basic relevance)
        if d.brief:
            brief_words  = set(re.findall(r'\b\w{4,}\b', d.brief.lower()))
            common_words = {"that", "this", "with", "from", "have", "will",
                            "they", "them", "your", "also", "then", "than",
                            "when", "what", "where", "which", "there"}
            brief_words -= common_words
            if brief_words:
                covered = sum(1 for w in brief_words if w in lower)
                coverage = covered / len(brief_words)
                if coverage < 0.40:
                    issues.append(QualityIssue(
                        check="content", severity="major",
                        message=f"Low brief keyword coverage ({coverage:.0%})",
                        suggestion="Ensure the deliverable directly addresses the brief’s key topics.",
                    ))
                    score -= 0.20
                elif coverage < 0.60:
                    issues.append(QualityIssue(
                        check="content", severity="minor",
                        message=f"Moderate brief keyword coverage ({coverage:.0%})",
                        suggestion="Review the brief and ensure all requested topics are covered.",
                    ))
                    score -= 0.10

        return max(0.0, score)

    # ── Check 4: Format ────────────────────────────────────────────────────────────────

    def _check_format(self, d: Deliverable, reqs: dict, issues: list) -> float:
        """
        Checks: markdown consistency, unmatched formatting markers,
        code blocks (if sector is code_review or technical_writing).
        """
        score   = 1.0
        content = d.content

        # Unmatched bold/italic markers (odd number of ** or *)
        bold_markers   = content.count("**")
        italic_markers = len(re.findall(r'(?<!\*)\*(?!\*)', content))
        if bold_markers % 2 != 0:
            issues.append(QualityIssue(
                check="format", severity="minor",
                message="Unmatched bold markers (**) detected",
                suggestion="Check all **bold** markdown pairs are properly closed.",
            ))
            score -= 0.10
        if italic_markers % 2 != 0:
            issues.append(QualityIssue(
                check="format", severity="minor",
                message="Unmatched italic markers (*) detected",
                suggestion="Check all *italic* markdown pairs are properly closed.",
            ))
            score -= 0.05

        # Code blocks for technical sectors
        if d.sector in ("code_review", "technical_writing"):
            has_code_block = "```" in content or "    " in content  # indented code also OK
            if not has_code_block:
                issues.append(QualityIssue(
                    check="format", severity="minor",
                    message="No code blocks found in technical deliverable",
                    suggestion="Wrap code samples in ``` code blocks.",
                ))
                score -= 0.15

        # Orphaned list markers (dash at start with no following text)
        orphaned = len(re.findall(r'^\s*-\s*$', content, re.MULTILINE))
        if orphaned > 0:
            issues.append(QualityIssue(
                check="format", severity="minor",
                message=f"{orphaned} empty list item(s) found",
                suggestion="Remove empty list items or complete them.",
            ))
            score -= 0.05

        # Consecutive blank lines (>2)
        excessive_blanks = len(re.findall(r'\n{4,}', content))
        if excessive_blanks > 0:
            issues.append(QualityIssue(
                check="format", severity="minor",
                message="Excessive blank lines detected",
                suggestion="Remove extra blank lines for cleaner presentation.",
            ))
            score -= 0.05

        return max(0.0, score)

    # ── Check 5: Sector ────────────────────────────────────────────────────────────────

    def _check_sector(self, d: Deliverable, reqs: dict, issues: list) -> float:
        """
        Sector-specific checks: disclaimer presence, sector keyword density,
        and platform-specific requirements.
        """
        score = 1.0
        lower = d.content.lower()

        # Disclaimer check
        disclaimer = reqs.get("disclaimer")
        if disclaimer:
            disclaimer_lower = disclaimer.lower()[:40]  # Check first 40 chars
            if disclaimer_lower not in lower:
                issues.append(QualityIssue(
                    check="sector", severity="major",
                    message=f"Required disclaimer missing for sector '{d.sector}'",
                    suggestion=f"Append disclaimer: '{disclaimer}'",
                ))
                score -= 0.30

        # Sector keyword density (basic relevance to sector)
        sector_keywords = {
            "research_reports":   ["analysis", "data", "findings", "research", "study"],
            "content_writing":    ["you", "your", "we", "tips", "guide"],
            "bookkeeping":        ["account", "debit", "credit", "balance", "reconcil"],
            "real_estate":        ["property", "market", "bedroom", "sqft", "listing"],
            "code_review":        ["function", "class", "error", "bug", "refactor", "variable"],
            "technical_writing":  ["install", "config", "step", "example", "note"],
            "customer_support":   ["sorry", "thank", "help", "resolve", "issue"],
            "data_entry":         [],  # No specific keyword requirement
        }
        kws = sector_keywords.get(d.sector, [])
        if kws:
            present  = sum(1 for kw in kws if kw in lower)
            coverage = present / len(kws)
            if coverage < 0.40:
                issues.append(QualityIssue(
                    check="sector", severity="minor",
                    message=f"Low sector keyword coverage ({coverage:.0%}) for '{d.sector}'",
                    suggestion=f"Ensure content uses terminology appropriate for {d.sector}.",
                ))
                score -= 0.20

        return max(0.0, score)

    # ── Summary generation ───────────────────────────────────────────────────────────────

    def _generate_summary(self, score: float, action: str, issues: list) -> str:
        critical = [i for i in issues if i.severity == "critical"]
        major    = [i for i in issues if i.severity == "major"]
        minor    = [i for i in issues if i.severity == "minor"]

        parts = [f"QC score: {score:.3f} — Action: {action.upper()}"]
        if critical:
            parts.append(f"{len(critical)} CRITICAL issue(s): " +
                         "; ".join(i.message for i in critical))
        if major:
            parts.append(f"{len(major)} major issue(s): " +
                         "; ".join(i.message for i in major))
        if minor:
            parts.append(f"{len(minor)} minor issue(s)")
        if not issues:
            parts.append("No issues found.")
        return " | ".join(parts)


# ── Revision helpers ────────────────────────────────────────────────────────────────────────

def build_revision_prompt(deliverable: Deliverable, report: QualityReport) -> str:
    """
    Build a revision instruction string to pass back to the generating LLM.

    Transforms QualityReport issues into actionable revision directives.
    """
    if not report.issues:
        return ""  # Nothing to revise

    lines = [
        f"Revise the following {deliverable.sector} deliverable to address these quality issues:",
        "",
    ]

    for issue in sorted(report.issues, key=lambda i: {"critical": 0, "major": 1, "minor": 2}[i.severity]):
        prefix = {"critical": "❌ CRITICAL", "major": "⚠️ MAJOR", "minor": "ℹ️ MINOR"}[issue.severity]
        lines.append(f"{prefix} [{issue.check.upper()}]: {issue.message}")
        if issue.suggestion:
            lines.append(f"   → {issue.suggestion}")
        lines.append("")

    lines += [
        f"Target quality score: ≥ {SCORE_PASS} (current: {report.overall_score:.3f})",
        "Maintain all original factual content. Only fix the issues listed above.",
    ]
    return "\n".join(lines)


# ── CLI demo ──────────────────────────────────────────────────────────────────────────────────

def main():
    qc = QualityChecker()

    # Test 1: Good research report
    good_report = Deliverable(
        task_id = "TEST-001",
        sector  = "research_reports",
        content = """## Executive Summary
This analysis examines the competitive landscape of the SaaS market.
Based on research from multiple sources [1][2][3], we identify three key trends.

## Methodology
Data was gathered from public filings, industry reports, and company websites.
A structured analysis framework was applied across 50 companies.

## Findings
Our analysis reveals significant market concentration in the top quartile.

| Segment | Market Share | Growth Rate |
|---------|-------------|-------------|
| Enterprise | 45% | 12% |
| SMB | 35% | 18% |
| Consumer | 20% | 8% |

The enterprise segment holds the largest share at 45%, while SMB shows
the highest growth rate at 18% annually. Consumer adoption lags at 8%.
Further analysis of competitive dynamics suggests consolidation pressure
will intensify over the next 24 months as capital costs rise.

## Recommendations
Based on the data, three strategic recommendations emerge for market participants.
First, double down on enterprise retention to protect the high-value base.
Second, accelerate SMB acquisition before the growth window closes.
Third, deprioritize consumer spend until margins stabilize.

Sources: [1] Gartner Q3 2025, [2] IDC Annual Report 2025, [3] S&P Global
""",
        brief = "Analyze the SaaS competitive landscape and provide market segmentation data.",
        word_count_req = 400,
    )

    report1 = qc.check(good_report)
    print("Test 1 (Good research report):")
    print(f"  Score: {report1.overall_score:.4f} | Action: {report1.action}")
    print(f"  Summary: {report1.summary}")
    print()

    # Test 2: Weak content piece with issues
    weak_content = Deliverable(
        task_id = "TEST-002",
        sector  = "content_writing",
        content = """Great question! As an AI, I can certainly help with this.
In conclusion, smart home technology is important. It is important to note that
smart homes are getting popular. Certainly, they are useful. Absolutely, the
market is growing. Of course, more people are buying them.
In summary, smart homes are good and people like them very much.
""",
        brief   = "Write an engaging blog post about smart home technology trends.",
    )

    report2 = qc.check(weak_content)
    print("Test 2 (Weak content with AI patterns):")
    print(f"  Score: {report2.overall_score:.4f} | Action: {report2.action}")
    print(f"  Issues: {len(report2.issues)}")
    for issue in report2.issues:
        print(f"    [{issue.severity.upper()}] {issue.message}")
    print()
    print("  Revision prompt (excerpt):")
    prompt = build_revision_prompt(weak_content, report2)
    print("  " + "\n  ".join(prompt.split("\n")[:10]))


if __name__ == "__main__":
    main()
