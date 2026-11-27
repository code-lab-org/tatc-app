"""
Browser tests of the summary charts: rendered with fixed data, and driven
with the pointer and keys.
"""

import pytest

# a day sampled every 432 seconds: A observes the square root of the share
# of the day elapsed, and B, over 18 hours, a share growing to 15/16
CHARTS = """() => {
    const box = $("<div id='chart-test'>").css({position: "fixed", left: 0, top: 0,
        width: 600, background: "white", "z-index": 100000}).appendTo("body");
    const times = _.range(0, 201).map((i) => i * 432);
    const a = {times: times, shares: times.map((t, i) => Math.sqrt(i / 200))};
    const b = {times: times.slice(0, 151), shares: _.range(0, 151).map((i) => i / 160)};
    box.append(tatc.coverageChart(a, tatc.COVERAGE_TERMS.coverage));
    box.append(tatc.histogramChart({edges: _.range(0, 21).map((i) => i * 3600),
        shares: _.range(0, 20).map((i) => (i % 5) / 40)}, "Histogram", "", "Revisit"));
    box.append(tatc.comparisonChart([{name: "A", color: "#3987e5", curve: a},
        {name: "B", color: "#d95926", curve: b}], tatc.COVERAGE_TERMS.coverage));
}"""


@pytest.fixture
def charts(page):
    page.evaluate(CHARTS)
    return page.locator("#chart-test svg")


def tooltip(chart) -> str:
    return chart.locator("xpath=..").locator(".summary-tooltip").inner_text()


def point_at(page, chart, fraction: float) -> None:
    """
    Moves the pointer over a fraction of the width of a chart's plot.
    """
    box = chart.locator("rect[tabindex]").last.bounding_box()
    page.mouse.move(box["x"] + box["width"] * fraction, box["y"] + box["height"] / 2)


def test_coverage_chart_tracks_the_pointer(page, charts):
    chart = charts.nth(0)
    point_at(page, chart, 0)
    assert tooltip(chart) == "0%\nobserved by 0 h"
    point_at(page, chart, 0.5)
    assert tooltip(chart) == "70.7%\nobserved by 12 h"
    assert chart.locator(".summary-crosshair").get_attribute("x1") == "263"
    point_at(page, chart, 1)
    assert tooltip(chart) == "100%\nobserved by 24 h"


def test_coverage_chart_steps_by_samples_with_keys(page, charts):
    chart = charts.nth(0)
    chart.locator("rect[tabindex]").focus()
    assert tooltip(chart) == "100%\nobserved by 24 h"
    page.keyboard.press("ArrowLeft")
    assert tooltip(chart) == "99.7%\nobserved by 23.9 h"
    page.keyboard.press("Shift+ArrowLeft")
    assert tooltip(chart) == "97.2%\nobserved by 22.7 h"
    page.keyboard.press("ArrowRight")
    assert tooltip(chart) == "97.5%\nobserved by 22.8 h"


def test_comparison_chart_lists_every_run(page, charts):
    chart = charts.nth(2)
    point_at(page, chart, 0.5)
    assert tooltip(chart) == "12 h since start\n70.4%\nA\n61.9%\nB"
    # past the end of B's analysis period
    point_at(page, chart, 0.9)
    assert tooltip(chart) == "21.6 h since start\n94.6%\nA\n–\nB"
    assert (
        chart.locator(".summary-marker").nth(1).get_attribute("visibility") == "hidden"
    )


def test_histogram_columns_show_their_shares(page, charts):
    columns = charts.nth(1).locator("rect[tabindex]")
    assert columns.count() == 20
    columns.nth(4).focus()
    assert tooltip(charts.nth(1)) == "10%\nof points, 4–5 h"
