"""
Fixtures of browser tests, which drive the web app in a browser with
Playwright.

Browser tests are skipped unless `TATC_BROWSER_TESTS=1`: they need the
`browser` optional dependencies, a browser (`playwright install chromium`),
and internet access (the app loads Cesium and other libraries from CDNs).
Set `TATC_BROWSER_CHANNEL` to use an installed browser instead (for example,
`chrome` or `msedge`).

Each test process runs its own server (`serve.py`), with an empty database,
so the tests may run in parallel (`pytest -n 4`), and each test opens the app
in a new browser context. A test fails if the page logs a script error.
"""

import os
import socket
import subprocess
import sys
import time

import pytest

from .helpers import track_requests, wait_for_requests

ENABLED = os.getenv("TATC_BROWSER_TESTS", "0") == "1"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Animation frames come every 500 ms rather than with the display (60 times a
# second). Cesium draws the globe in every frame, which without a GPU (as in
# CI) the browser does in software, at a cost of seconds of CPU per frame:
# drawing as many frames as it can keeps every CPU busy, so the app and the
# server (which runs the analyses) wait their turn. Nothing else in the app
# animates with frames but jQuery's fades, which last as long at any rate.
SLOW_ANIMATION_FRAMES = """(() => {
    const interval = 500;
    window.requestAnimationFrame = (callback) =>
        window.setTimeout(() => callback(performance.now()), interval);
    window.cancelAnimationFrame = (id) => window.clearTimeout(id);
})();"""


def pytest_collection_modifyitems(config, items):  # pylint: disable=unused-argument
    """
    Skips browser tests unless enabled.
    """
    if ENABLED:
        return
    skip = pytest.mark.skip(reason="browser tests run with TATC_BROWSER_TESTS=1")
    browser_dir = os.path.dirname(os.path.abspath(__file__))
    for item in items:
        if str(item.fspath).startswith(browser_dir):
            item.add_marker(skip)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for(port: int, server: subprocess.Popen, timeout: float = 120) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if server.poll() is not None:
            raise RuntimeError("The app server exited.")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"The app server did not start on port {port}.")


@pytest.fixture(scope="session")
def app_url():
    """
    Runs the app (with an empty database) for the tests of a process.
    """
    port = _free_port()
    with subprocess.Popen(
        [sys.executable, "-m", "tests.browser.serve", str(port)], cwd=ROOT
    ) as server:
        try:
            _wait_for(port, server)
            yield f"http://127.0.0.1:{port}/"
        finally:
            server.terminate()
            server.wait()


@pytest.fixture(scope="session")
def browser():
    """
    Launches the browser for all tests.
    """
    # pylint: disable=import-outside-toplevel
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(
            channel=os.getenv("TATC_BROWSER_CHANNEL") or None
        )
        yield launched
        launched.close()


@pytest.fixture
def page(browser, app_url):  # pylint: disable=redefined-outer-name
    """
    Opens the app in a new browser context, with slow animation frames (see
    `SLOW_ANIMATION_FRAMES`), and checks that it logs no script errors.
    """
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    context.add_init_script(SLOW_ANIMATION_FRAMES)
    opened = context.new_page()
    errors = []
    opened.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    opened.on("pageerror", lambda error: errors.append(str(error)))
    # accept confirmations, and prompts with their default
    opened.on("dialog", lambda dialog: dialog.accept(dialog.default_value))
    track_requests(opened, app_url)
    opened.goto(app_url, wait_until="load", timeout=90000)
    # the app has loaded its design and validated its satellites (rather than
    # wait for the network to be idle, as the globe loads imagery from CDNs)
    wait_for_requests(opened)
    yield opened
    context.close()
    # failed requests (such as those refused on purpose) are logged too
    assert [e for e in errors if "Failed to load resource" not in e] == []
