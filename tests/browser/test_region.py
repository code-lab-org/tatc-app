"""
Browser tests of the region's grid and outline when their requests overlap.
"""

from .helpers import open_analysis_tab, set_checked

GENERATED = "!document.querySelector('#region-generate').disabled"


def test_only_latest_grid_is_drawn(page):
    open_analysis_tab(page, "coverage")
    page.evaluate("() => { tatc.generateRegionGrid(); tatc.generateRegionGrid(); }")
    page.wait_for_function(GENERATED)
    count = page.evaluate("() => tatc.gridPoints.length")
    assert count > 0
    page.evaluate("() => tatc.generateRegionGrid()")
    page.wait_for_function(GENERATED)
    assert page.evaluate("() => tatc.gridPoints.length") == count


def test_cancelled_grid_is_not_drawn(page):
    open_analysis_tab(page, "coverage")
    page.evaluate("() => { tatc.generateRegionGrid(); tatc.cancelRegionGrid(); }")
    page.wait_for_timeout(3000)
    assert page.evaluate("() => tatc.gridPoints.length") == 0
    assert not page.is_visible("#grid-error")


def test_only_latest_region_outline_is_drawn(page):
    open_analysis_tab(page, "swaths")
    set_checked(page, "#swaths-region-enabled")
    outline = "() => tatc.regionOutline.entities.values.length"
    page.evaluate('() => $("#region-type").val("conus").trigger("change")')
    page.wait_for_timeout(4000)
    expected = page.evaluate(outline)
    assert expected > 0
    page.evaluate("""() => {
        $("#region-type").val("USA").trigger("change");
        $("#region-type").val("conus").trigger("change");
    }""")
    page.wait_for_timeout(4000)
    assert page.evaluate(outline) == expected
