"""
Browser tests of the inputs of analyses: their validation, and restoring
the inputs of a saved run when running it again.
"""

from .helpers import (
    add_sites_and_satellite,
    analysis_error,
    open_analysis_tab,
    run_analysis,
    set_checked,
    set_value,
)


def test_invalid_inputs_show_their_errors_without_requests(page):
    requests = []
    page.on(
        "request", lambda r: requests.append(r.url) if "/analyze/" in r.url else None
    )
    add_sites_and_satellite(page)
    open_analysis_tab(page, "coverage")
    set_checked(page, "#sufficiency-enabled")
    set_value(page, "#sufficiency-decorrelation", 0)
    assert analysis_error(page) == "The decorrelation time must be positive."
    set_checked(page, "#sufficiency-enabled", False)
    set_checked(page, "#sample-size-enabled")
    set_value(page, "#sample-size-max", -1)
    assert (
        analysis_error(page) == "The maximum sample size must be positive (or blank)."
    )
    set_checked(page, "#sample-size-enabled", False)

    page.select_option("#analysis-type", "coincidence")
    set_value(page, "#coincidence-min", 1)
    assert (
        analysis_error(page)
        == "The number of platforms at once must be a whole number from 2 to 20."
    )

    page.select_option("#analysis-type", "swaths")
    set_value(page, "#swaths-step", 0)
    assert analysis_error(page) == "The step and segment must be positive."

    page.evaluate(
        "() => { tatc.design.stations.splice(0); tatc.design.targets.splice(0); }"
    )
    page.select_option("#analysis-type", "latency")
    assert analysis_error(page) == "Add at least one ground station."
    page.select_option("#analysis-type", "access")
    assert analysis_error(page) == "Add at least one target point."
    assert requests == []


def save_run(page) -> None:
    """
    Saves the results as a run (with its default name).
    """
    page.click("#run-save")
    page.wait_for_selector("#run-saved:visible")


def run_saved_run_again(page) -> None:
    """
    Runs the (first) saved run of the analysis type again.
    """
    page.click("#runs-open")
    page.wait_for_selector("#runs-dialog.show")
    page.locator("#runs-dialog button[aria-label$=' again']").first.click()
    page.wait_for_selector("#runs-dialog", state="hidden")
    assert run_analysis(page) == ""


def test_run_again_restores_coverage_inputs(page):
    open_analysis_tab(page, "coverage")
    set_checked(page, "#sufficiency-enabled")
    page.select_option("#sufficiency-decorrelation-unit", "86400")
    set_value(page, "#sufficiency-decorrelation", 2)
    set_value(page, "#sufficiency-sigma", 1.5)
    # (the default instrument has no pixels: sized, without a maximum)
    set_checked(page, "#sample-size-enabled")
    assert run_analysis(page) == ""
    save_run(page)
    # change the inputs, then run the saved run again
    set_checked(page, "#sufficiency-enabled", False)
    set_checked(page, "#sample-size-enabled", False)
    set_value(page, "#analysis-duration", 0.5)
    run_saved_run_again(page)
    assert page.is_checked("#sufficiency-enabled")
    assert page.input_value("#sufficiency-decorrelation-unit") == "86400"
    assert page.input_value("#sufficiency-decorrelation") == "2"
    assert page.input_value("#sufficiency-sigma") == "1.5"
    assert page.is_checked("#sample-size-enabled")
    assert page.input_value("#analysis-duration") == "0.25"


def test_run_again_restores_swath_inputs(page):
    add_sites_and_satellite(page)
    open_analysis_tab(page, "swaths")
    set_checked(page, "#swaths-region-enabled")
    set_checked(page, "#swaths-coincidence-enabled")
    set_value(page, "#swaths-coincidence-difference", 30)
    set_value(page, "#swaths-segment", 5)
    assert run_analysis(page) == ""
    save_run(page)
    set_checked(page, "#swaths-coincidence-enabled", False)
    set_value(page, "#swaths-segment", 9)
    run_saved_run_again(page)
    assert page.is_checked("#swaths-region-enabled")
    assert page.is_checked("#swaths-coincidence-enabled")
    assert page.input_value("#swaths-coincidence-difference") == "30"
    assert page.input_value("#swaths-segment") == "5"
