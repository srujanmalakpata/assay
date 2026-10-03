"""Accessibility scanning: inject axe-core into a Playwright page and run it.

The axe-core script (Deque, MPL-2.0) is the copy bundled with the
``axe-playwright-python`` package; we only use that file and drive axe ourselves,
so the scan options and the reporting format are under our control.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

# WCAG 2.0 / 2.1 level A and AA rules: the level most accessibility policies require.
WCAG_AA_TAGS = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa")


def axe_script_path() -> Path:
    override = os.environ.get("AXE_SCRIPT_PATH")
    if override:
        return Path(override)
    return Path(str(resources.files("axe_playwright_python").joinpath("axe.min.js")))


@dataclass(frozen=True)
class Violation:
    rule_id: str
    impact: str | None
    help: str
    help_url: str
    targets: tuple[str, ...]

    def describe(self) -> str:
        nodes = ", ".join(self.targets[:5])
        return f"[{self.impact}] {self.rule_id}: {self.help} -> {nodes} ({self.help_url})"


@dataclass(frozen=True)
class AxeResult:
    url: str
    axe_version: str
    violations: tuple[Violation, ...]
    passes: int
    # Checks axe could not decide automatically (often colour contrast over images or
    # gradients). They are not failures, but a human should review them.
    incomplete: tuple[Violation, ...] = ()

    def report(self) -> str:
        lines = [f"axe {self.axe_version} found {len(self.violations)} violation(s) on {self.url}"]
        lines += [f"  - {v.describe()}" for v in self.violations]
        if self.incomplete:
            lines.append(f"{len(self.incomplete)} check(s) need manual review (axe 'incomplete'):")
            lines += [f"  - {v.describe()}" for v in self.incomplete]
        return "\n".join(lines)


def _findings(raw: list[dict[str, Any]]) -> tuple[Violation, ...]:
    return tuple(
        Violation(
            rule_id=v["id"],
            impact=v.get("impact"),
            help=v["help"],
            help_url=v["helpUrl"],
            targets=tuple(" ".join(map(str, n["target"])) for n in v["nodes"]),
        )
        for v in raw
    )


def scan(page: Page, tags: tuple[str, ...] = WCAG_AA_TAGS) -> AxeResult:
    """Run axe-core against the page's current DOM."""
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        page.add_script_tag(path=str(axe_script_path()))
    raw = page.evaluate(
        "async (tags) => await axe.run(document, {runOnly: {type: 'tag', values: tags}})",
        list(tags),
    )
    return AxeResult(
        url=raw["url"],
        axe_version=raw["testEngine"]["version"],
        violations=_findings(raw["violations"]),
        passes=len(raw["passes"]),
        incomplete=_findings(raw["incomplete"]),
    )
