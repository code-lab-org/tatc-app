"""
Helpers of browser tests: actions on the app's Design and Analysis tabs, and
waiting for the app's requests.
"""

import time

# time (milliseconds) to wait for an analysis to run
ANALYSIS_TIMEOUT = 240000


class _Requests:  # pylint: disable=too-few-public-methods
    """
    The requests of a page to the app that have not finished, and the time
    (`time.monotonic`) that one last started or finished.
    """

    def __init__(self):
        self.pending = set()
        self.changed = time.monotonic()


# requests of each page (see `track_requests`)
_REQUESTS = {}


def track_requests(page, url: str) -> None:
    """
    Tracks the requests of a page to the app at a URL (but not to CDNs), to
    wait for them (see `wait_for_requests`).
    """
    requests = _REQUESTS[page] = _Requests()

    def started(request):
        if request.url.startswith(url):
            requests.pending.add(request)
            requests.changed = time.monotonic()

    def ended(request):
        if request in requests.pending:
            requests.pending.discard(request)
            requests.changed = time.monotonic()

    page.on("request", started)
    page.on("requestfinished", ended)
    page.on("requestfailed", ended)
    page.on("close", lambda _: _REQUESTS.pop(page, None))


def wait_for_requests(page, quiet: float = 250, timeout: float = 60000) -> None:
    """
    Waits until the requests of a page to the app have finished, and it sends
    no more for a time (`quiet`, milliseconds, from now or the last request
    to finish): the app has handled what the test just did.
    """
    requests = _REQUESTS[page]
    now = time.monotonic()
    end = now + timeout / 1000
    while (
        requests.pending or time.monotonic() - max(now, requests.changed) < quiet / 1000
    ):
        if time.monotonic() > end:
            raise TimeoutError(f"{len(requests.pending)} requests did not finish")
        page.wait_for_timeout(50)


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
        tatc.design.stations.push({name: "GS", latitude: 40, longitude: -105,
                              min_elevation_angle: 5, min_access_time: 0});
        tatc.renderStations();
        tatc.addTarget(10, 20);
        tatc.addSatellites([_.assign(_.cloneDeep(tatc.design.satellites[0].system),
                                {name: "ISS 2"})]);
    }""")
    # the new satellite is validated by the server
    wait_for_requests(page)


def open_analysis_tab(page, analysis: str, days: float = 0.25) -> None:
    """
    Opens the Analysis tab, with an analysis type and period (days).
    """
    # (clicking the active tab collapses the drawer)
    if "active" not in (page.get_attribute("#nav-analysis-tab", "class") or ""):
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


def wait_for_animation(page) -> dict:
    """
    Waits until the animation of the analysis results (its CZML layer) has
    loaded.

    Returns:
        dict: Whether the layer is `shown`, and the identifiers of its
            satellite `entities` (`sat/<name>`).
    """
    # the module as the page imported it (same URL, same module), imported
    # once: polling stops at the first truthy value, and the promise of an
    # async predicate is truthy, so the predicate is synchronous
    layers = page.evaluate_handle(
        '() => import(new URL("layers.js", document.baseURI).href)'
    )
    return page.wait_for_function(
        """(layers) => {
            const source = layers.getCzmlLayer("analysis");
            return source && {
                shown: source.show,
                entities: source.entities.values
                    .map((entity) => entity.id)
                    .filter((id) => id.startsWith("sat/")),
            };
        }""",
        arg=layers,
    ).json_value()


def show_results(page) -> dict:
    """
    Opens the results dialog of the analysis results.

    Returns:
        dict: The number of `rows` of its table, and its `summary` text.
    """
    page.click("#analysis-data")
    wait_for_dialog(page, "#results-dialog")
    shown = {
        "rows": page.locator("#results-table tbody tr").count(),
        "summary": page.inner_text("#results-summary").strip(),
    }
    page.click("#results-dialog .modal-footer button[data-dismiss=modal]")
    page.wait_for_selector("#results-dialog", state="hidden")
    return shown


def wait_for_dialog(page, dialog: str) -> None:
    """
    Waits until a dialog shows, and its transition ends: until then,
    Bootstrap ignores clicks and keys (such as Escape) that would close it.
    """
    page.wait_for_selector(dialog + ".show")
    page.wait_for_function(
        "(dialog) => !$(dialog).data('bs.modal')._isTransitioning", arg=dialog
    )


def close_dialog(page, dialog: str) -> None:
    """
    Closes a dialog with the close button of its footer.
    """
    wait_for_dialog(page, dialog)
    page.click(dialog + " .modal-footer button[data-dismiss=modal]")
    page.wait_for_selector(dialog, state="hidden")
