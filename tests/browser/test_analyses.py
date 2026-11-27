"""
Browser tests of running each type of analysis and showing its results.
"""

import pytest

from .helpers import (
    add_sites_and_satellite,
    open_analysis_tab,
    run_analysis,
    set_checked,
    show_results,
)

# analysis types, and whether their results have a summary
ANALYSES = [
    ("coverage", True),
    ("coincidence", True),
    ("swaths", False),
    ("latency", True),
    ("access", False),
]


@pytest.mark.parametrize("analysis, summary", ANALYSES)
def test_run_analysis(page, analysis, summary):
    add_sites_and_satellite(page)
    open_analysis_tab(page, analysis)
    assert run_analysis(page) == ""
    shown = show_results(page)
    assert shown["rows"] > 0
    assert bool(shown["summary"]) == summary


def test_swaths_over_region_with_coincidence(page):
    add_sites_and_satellite(page)
    open_analysis_tab(page, "swaths")
    set_checked(page, "#swaths-region-enabled")
    set_checked(page, "#swaths-coincidence-enabled")
    assert run_analysis(page) == ""
    shown = show_results(page)
    assert shown["rows"] > 0
    assert shown["summary"]


def test_coverage_with_sufficiency_and_sample_sizes(page):
    open_analysis_tab(page, "coverage")
    set_checked(page, "#sufficiency-enabled")
    set_checked(page, "#sample-size-enabled")
    assert run_analysis(page) == ""
    assert "Sampling" in show_results(page)["summary"]


def test_failed_polls_are_retried(page):
    failures = {"left": 2}

    def fail_twice(route):
        if failures["left"] > 0:
            failures["left"] -= 1
            route.fulfill(status=503, json={"detail": "Busy"})
        else:
            route.continue_()

    page.route("**/tasks/*/status", fail_twice)
    open_analysis_tab(page, "coverage")
    assert run_analysis(page) == ""
    assert failures["left"] == 0
    assert show_results(page)["rows"] > 0
