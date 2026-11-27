"""
Browser tests of requests: saved designs, and expired sessions.
"""

from .helpers import close_dialog


def test_no_sign_in_prompt_when_signed_in(page):
    assert not page.is_visible("#login-dialog")


def test_save_update_and_delete_design(page):
    page.click("#nav-design-tab")
    page.click("#designs-open")
    page.wait_for_selector("#designs-dialog.show")
    page.fill("#design-save-name", "Saved design")
    page.click("#design-save-form button[type=submit]")
    row = page.locator("#designs-list tr", has_text="Saved design")
    row.wait_for()
    page.click("#design-update")
    page.wait_for_selector("#designs-status:visible")
    assert "Saved" in page.inner_text("#designs-status")
    row.locator("button[aria-label^=Delete]").click()
    row.wait_for(state="detached")
    assert not page.is_visible("#designs-error")
    close_dialog(page, "#designs-dialog")


def test_prompt_to_sign_in_when_session_expires(page):
    page.route(
        "**/designs",
        lambda route: route.fulfill(status=401, json={"detail": "Not authenticated"}),
    )
    page.click("#nav-design-tab")
    page.click("#designs-open")
    page.wait_for_selector("#login-dialog.show")
    assert "session expired" in page.inner_text("#login-dialog-message")
    assert page.is_visible("#login-link")
