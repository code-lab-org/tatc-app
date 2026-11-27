"""
Browser tests that open each dialog and panel of the app, so that every
module's handlers run at least once (the `page` fixture fails a test on any
script error, such as a missing import).
"""

from .helpers import (
    close_dialog,
    open_analysis_tab,
    set_checked,
    wait_for_dialog,
    wait_for_requests,
)


def open_dialog(page, opener: str, dialog: str) -> None:
    page.click(opener)
    wait_for_dialog(page, dialog)


def test_satellite_editor_and_catalogs(page):
    page.click("#nav-design-tab")
    page.locator("#satellites .list-group-item").first.click()
    open_dialog(page, "#satellite-edit", "#satellite-dialog")
    for tab in ("orbit", "json", "instruments"):
        page.click(f"#satellite-{tab}-tab")
        page.wait_for_selector(f"#satellite-{tab}.show")
    page.click("#instrument-add")
    page.click("#satellite-validate")
    wait_for_requests(page)
    open_dialog(page, "#instrument-catalog-open", "#instrument-catalog-dialog")
    page.wait_for_selector("#instrument-catalog-dialog :is(li, option, tr)")
    close_dialog(page, "#instrument-catalog-dialog")
    # (searching CelesTrak is left out: the server would query celestrak.org)
    page.click("#satellite-orbit-tab")
    page.wait_for_selector("#satellite-orbit.show")
    # (CelesTrak elements are TLE or OMM)
    page.select_option("#orbit-type", "tle")
    open_dialog(page, "#query-celestrak", "#celestrak-dialog")
    close_dialog(page, "#celestrak-dialog")
    close_dialog(page, "#satellite-dialog")
    open_dialog(page, "#catalog-open", "#catalog-dialog")
    page.wait_for_selector("#catalog-dialog :is(li, option, tr)")
    close_dialog(page, "#catalog-dialog")


def test_copy_and_delete_satellite(page):
    page.click("#nav-design-tab")
    count = page.locator("#satellites .list-group-item").count()
    page.locator("#satellites .list-group-item").first.click()
    page.click("#satellite-copy")
    page.wait_for_function(
        f"document.querySelectorAll('#satellites .list-group-item').length == {count + 1}"
    )
    page.click("#satellite-delete")
    page.wait_for_function(
        f"document.querySelectorAll('#satellites .list-group-item').length == {count}"
    )


def test_orbit_preview_and_design_export(page):
    page.click("#nav-design-tab")
    page.wait_for_function("!document.querySelector('#orbit-data').disabled")
    page.click("#orbit-data")
    page.wait_for_selector("#results-dialog.show")
    page.wait_for_selector("#results-table tbody tr")
    close_dialog(page, "#results-dialog")
    with page.expect_download() as download:
        page.click("#design-export")
    assert download.value.suggested_filename.endswith(".json")


def test_display_options(page):
    page.click("#nav-design-tab")
    for checkbox in ("#display-path", "#display-footprint", "#display-lighting"):
        set_checked(page, checkbox, not page.is_checked(checkbox))
    page.select_option("#display-observer", "inertial")
    page.select_option("#display-observer", "fixed")
    page.click("#layer-filter-all")
    page.click("#display-collapse")


def test_station_and_region_dialogs(page):
    open_analysis_tab(page, "latency")
    page.click("#station-add")
    close_dialog(page, "#station-dialog")
    page.locator("#stations .list-group-item").first.click()
    page.click("#station-delete")
    open_analysis_tab(page, "coverage")
    page.wait_for_timeout(600)
    open_dialog(page, "#region-edit", "#region-dialog")
    page.select_option("#region-type", "latitude")
    close_dialog(page, "#region-dialog")
    set_checked(page, "#sufficiency-enabled")
