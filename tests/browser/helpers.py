"""
Helpers of browser tests: actions on the app's Design and Analysis tabs.
"""

# time (milliseconds) to wait for an analysis to run
ANALYSIS_TIMEOUT = 240000


def set_value(page, selector: str, value) -> None:
    """
    Sets the value of an input, as typed (with its change event).
    """
    page.fill(selector, str(value))
    page.dispatch_event(selector, "change")


def set_checked(page, selector: str, checked: bool = True) -> None:
    """
    Checks (or unchecks) a checkbox, with its change event.
    """
    page.set_checked(selector, checked)
    page.dispatch_event(selector, "change")


def add_sites_and_satellite(page) -> None:
    """
    Adds a ground station and a target point (for latency and access
    analyses), and a second satellite (for coincidences) to the design.
    """
    page.evaluate("""() => {
        design.stations.push({name: "GS", latitude: 40, longitude: -105,
                              min_elevation_angle: 5, min_access_time: 0});
        renderStations();
        addTarget(10, 20);
        addSatellites([_.assign(_.cloneDeep(design.satellites[0].system),
                                {name: "ISS 2"})]);
    }""")
    # the new satellite is validated by the server
    page.wait_for_timeout(2000)


def open_analysis_tab(page, analysis: str, days: float = 0.25) -> None:
    """
    Opens the Analysis tab, with an analysis type and period (days).
    """
    page.click("#nav-analysis-tab")
    page.select_option("#analysis-type", analysis)
    set_value(page, "#analysis-duration", days)


def run_analysis(page) -> str:
    """
    Runs the selected analysis, and waits for it to complete.

    Returns:
        str: The error shown, or an empty string.
    """
    page.click("#analysis-run")
    page.wait_for_function(
        "!document.querySelector('#analysis-run').disabled",
        timeout=ANALYSIS_TIMEOUT,
    )
    if page.is_visible("#analysis-error"):
        return page.inner_text("#analysis-error")
    return ""


def analysis_error(page) -> str:
    """
    Clicks run, and gets the error shown at once (of invalid inputs).
    """
    page.click("#analysis-run")
    page.wait_for_timeout(300)
    return (
        page.inner_text("#analysis-error") if page.is_visible("#analysis-error") else ""
    )


def show_results(page) -> dict:
    """
    Opens the results dialog of the analysis results.

    Returns:
        dict: The number of `rows` of its table, and its `summary` text.
    """
    page.click("#analysis-data")
    page.wait_for_selector("#results-dialog.show")
    page.wait_for_timeout(500)
    shown = {
        "rows": page.locator("#results-table tbody tr").count(),
        "summary": page.inner_text("#results-summary").strip(),
    }
    page.click("#results-dialog .modal-footer button[data-dismiss=modal]")
    page.wait_for_selector("#results-dialog", state="hidden")
    return shown


def close_dialog(page, dialog: str) -> None:
    """
    Closes a dialog with the close button of its footer.
    """
    page.click(dialog + " .modal-footer button[data-dismiss=modal]")
    page.wait_for_selector(dialog, state="hidden")
