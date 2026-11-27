"""
Browser tests of dialogs, scripts from CDNs, and the lists of saved designs
and runs.
"""

from .helpers import close_dialog, open_analysis_tab, run_analysis


def test_datatables_loaded_with_integrity_hash(page):
    assert page.evaluate("() => typeof $.fn.DataTable === 'function'")


def test_dialog_closes_with_escape_and_is_labelled(page):
    open_analysis_tab(page, "access")
    page.click("#target-add")
    page.wait_for_selector("#target-dialog.show")
    # Bootstrap ignores keys until the dialog's transition ends
    page.wait_for_timeout(600)
    page.keyboard.press("Escape")
    page.wait_for_selector("#target-dialog", state="hidden", timeout=5000)
    label = page.evaluate("""() => document.getElementById(
        document.getElementById("target-dialog").getAttribute("aria-labelledby")
    ).textContent""")
    assert label == "Add Target Point"


def test_saved_design_shows_update_button(page):
    page.click("#nav-design-tab")
    page.click("#designs-open")
    page.wait_for_selector("#designs-dialog.show")
    page.fill("#design-save-name", "Updated design")
    page.click("#design-save-form button[type=submit]")
    page.wait_for_selector("#design-update:visible")
    assert "Updated design" in page.inner_text("#design-update")
    close_dialog(page, "#designs-dialog")


def test_saved_run_shows_headline_metric(page):
    open_analysis_tab(page, "coverage", days=0.1)
    assert run_analysis(page) == ""
    page.click("#run-save")
    page.wait_for_selector("#run-saved:visible")
    page.click("#runs-open")
    page.wait_for_selector("#runs-dialog.show")
    page.wait_for_selector("#runs-dialog tbody tr")
    assert page.inner_text("#runs-metric") == "Region observed"
    assert "%" in page.inner_text("#runs-dialog tbody")
