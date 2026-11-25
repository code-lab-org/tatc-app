// Designs and analysis runs saved to the user's account (the server's
// `/designs` and `/runs` endpoints): the saved designs dialog of the Design
// tab, and the saving, comparison, and running again of analysis runs of the
// Analysis tab.

// --- Requests ---

// Sends a request with an optional JSON body, expecting a JSON response (or
// none, for deletions).
function sendJson(method, url, data) {
  return $.ajax({
    url: url,
    type: method,
    contentType: data === undefined ? undefined : "application/json",
    data: data === undefined ? undefined : JSON.stringify(data),
    dataType: method == "DELETE" ? "text" : "json"
  });
}

function formatSavedTime(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// A small icon button of a row of a list (with an accessible name).
function actionButton(icon, label, onClick) {
  return $("<button type='button'>")
    .addClass("btn btn-link btn-sm text-secondary")
    .attr({ title: label, "aria-label": label })
    .append($("<i>").addClass(icon))
    .on("click", onClick);
}

// Shows a status message that fades after a while.
function flashStatus(element, text) {
  element.stop(true, true).text(text).show().delay(4000).fadeOut();
}

// --- Saved designs ---

const SAVED_DESIGN_KEY = "tatc-saved-design";
// the saved design ({id, name}) last opened or saved, which the current
// design updates; null for a design that is not saved
let savedDesignRef = null;

function setSavedDesignRef(ref) {
  savedDesignRef = ref;
  try {
    if (ref) {
      window.localStorage.setItem(SAVED_DESIGN_KEY, JSON.stringify(ref));
    } else {
      window.localStorage.removeItem(SAVED_DESIGN_KEY);
    }
  } catch (e) {
    // storage may be unavailable (for example, in a private window)
  }
}

function loadSavedDesignRef() {
  try {
    const ref = JSON.parse(window.localStorage.getItem(SAVED_DESIGN_KEY));
    savedDesignRef = ref && ref.id && ref.name ? ref : null;
  } catch (e) {
    savedDesignRef = null;
  }
}

// A default name of the current design, from its satellites.
function defaultDesignName() {
  const names = _.map(design.satellites, "system.name").join(", ");
  return _.truncate(names, { length: 60 }) || "Design";
}

function showDesignsError(xhr) {
  $("#designs-error").text(formatError(xhr)).show();
}

function renderDesignUpdate() {
  $("#design-update")
    .toggle(Boolean(savedDesignRef))
    .text(savedDesignRef ? "Update “" + savedDesignRef.name + "”" : "");
}

function loadDesigns() {
  $.getJSON("/designs").done(renderDesigns).fail(showDesignsError);
}

function renderDesigns(designs) {
  const list = $("#designs-list").empty();
  $("#designs-empty").toggle(designs.length == 0);
  _.forEach(designs, function(saved) {
    const current = savedDesignRef && savedDesignRef.id == saved.id;
    list.append($("<tr>").append(
      $("<td>").append(
        $("<span>").text(saved.name),
        current ? $("<span>").addClass("badge badge-secondary ml-2").text("open") : null
      ),
      $("<td>").text(saved.satellites),
      $("<td>").text(formatSavedTime(saved.updated)),
      $("<td>").addClass("library-actions").append(
        actionButton("fas fa-folder-open", "Open " + saved.name, function() { openDesign(saved); }),
        actionButton("fas fa-trash-alt", "Delete " + saved.name, function() { deleteDesign(saved); })
      )
    ));
  });
}

function openDesign(saved) {
  if (!confirm("Replace the current design with “" + saved.name + "”?")) {
    return;
  }
  $.getJSON("/designs/" + saved.id).done(function(result) {
    importDesign(result.design);
    setSavedDesignRef({ id: result.id, name: result.name });
    $("#designs-dialog").modal("hide");
  }).fail(showDesignsError);
}

function deleteDesign(saved) {
  if (!confirm("Delete the saved design “" + saved.name + "”?")) {
    return;
  }
  sendJson("DELETE", "/designs/" + saved.id).done(function() {
    if (savedDesignRef && savedDesignRef.id == saved.id) {
      setSavedDesignRef(null);
      renderDesignUpdate();
    }
    loadDesigns();
  }).fail(showDesignsError);
}

// Saves the current design (as new, or updating the saved design).
function saveCurrentDesign(update) {
  $("#designs-error").hide();
  const name = $("#design-save-name").val().trim();
  if (!name) {
    return;
  }
  const body = { name: name, design: exportDesign() };
  const request = update
    ? sendJson("PUT", "/designs/" + savedDesignRef.id, body)
    : sendJson("POST", "/designs", body);
  request.done(function(saved) {
    setSavedDesignRef({ id: saved.id, name: saved.name });
    renderDesignUpdate();
    flashStatus($("#designs-status"), "Saved “" + saved.name + "”.");
    loadDesigns();
  }).fail(function(xhr) {
    // the saved design may have been deleted (for example, in another tab)
    if (update && xhr.status == 404) {
      setSavedDesignRef(null);
      renderDesignUpdate();
    }
    showDesignsError(xhr);
  });
}

// --- Saved runs ---

// colors of runs compared (in the order they are checked; a run keeps its
// color while compared)
const RUN_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500"];
let savedRuns = [];
let comparedRuns = []; // [{id, slot}]

// The headline metric of runs of each analysis with a summary, and the rows
// of their comparison: {label, value(summary), kind} (a share, duration,
// number, length in meters, or count), and whether a row is `optional` (shown only if a run
// has a value).
// The metrics of runs of coverage-like analyses (see `COVERAGE_TERMS`).
function coverageRunMetrics(terms) {
  const twice = terms.twice.charAt(0).toUpperCase() + terms.twice.slice(1);
  const revisit = terms.revisit.replace(/^Mean /, "");
  return {
    headline: { label: terms.observed, value: function(s) { return s.observed; }, kind: "share" },
    rows: [
      { label: terms.observed, value: function(s) { return s.observed; }, kind: "share" },
      { label: twice, value: function(s) { return s.revisited; }, kind: "share" },
      { label: terms.revisit, value: function(s) { return s.revisit && s.revisit.mean; }, kind: "duration" },
      { label: "Median " + revisit, value: function(s) { return s.revisit && s.revisit.median; }, kind: "duration" },
      { label: "90th percentile " + revisit, value: function(s) { return s.revisit && s.revisit.p90; }, kind: "duration" },
      { label: terms.access, value: function(s) { return s.access && s.access.mean; }, kind: "duration" },
      // sampling sufficiency (of runs that assess it)
      { label: "Meets target sampling error", optional: true, value: function(s) { return s.sufficiency && s.sufficiency.sufficient; }, kind: "share" },
      { label: "Median sampling error (% of σ)", optional: true, value: function(s) { return s.sufficiency && s.sufficiency.relative_error && s.sufficiency.relative_error.median; }, kind: "share" },
      { label: "Median effective samples", optional: true, value: function(s) { return s.sufficiency && s.sufficiency.effective_samples && s.sufficiency.effective_samples.median; }, kind: "number" },
      { label: "90th percentile longest gap", optional: true, value: function(s) { return s.sufficiency && s.sufficiency.max_gap && s.sufficiency.max_gap.p90; }, kind: "duration" },
      { label: "Local time-of-day coverage", optional: true, value: function(s) { return s.sufficiency && s.sufficiency.local_time_coverage; }, kind: "share" },
      // ground sample sizes (of runs that size them)
      { label: "Median ground sample size", optional: true, value: function(s) { return s.sample_size && s.sample_size.median && s.sample_size.median.median; }, kind: "length" },
      { label: "Max. sample size required", optional: true, value: function(s) { return s.sample_size && s.sample_size.max_sample_size; }, kind: "length" },
      { label: "Analysis period", value: function(s) { return _.last(s.coverage.times); }, kind: "duration" },
      { label: "Points", value: function(s) { return s.points; }, kind: "count" }
    ]
  };
}

const RUN_METRICS = {
  coverage: coverageRunMetrics(COVERAGE_TERMS.coverage),
  coincidence: coverageRunMetrics(COVERAGE_TERMS.coincidence),
  latency: {
    headline: { label: "Region downlinked", value: function(s) { return s.downlinked; }, kind: "share" },
    rows: [
      { label: "Region downlinked", value: function(s) { return s.downlinked; }, kind: "share" },
      { label: "Mean latency", value: function(s) { return s.latency && s.latency.mean; }, kind: "duration" },
      { label: "Median latency", value: function(s) { return s.latency && s.latency.median; }, kind: "duration" },
      { label: "90th percentile latency", value: function(s) { return s.latency && s.latency.p90; }, kind: "duration" },
      { label: "Contacts", value: function(s) { return s.contacts; }, kind: "count" },
      { label: "Mean contact duration", value: function(s) { return s.contact_duration; }, kind: "duration" },
      { label: "Points", value: function(s) { return s.points; }, kind: "count" }
    ]
  }
};

function formatMetric(value, kind, unit) {
  if (value === null || value === undefined) {
    return "–";
  }
  if (kind == "share") {
    return formatShare(value);
  }
  if (kind == "duration") {
    return formatDuration(value, unit);
  }
  if (kind == "number") {
    return formatValue(value);
  }
  if (kind == "length") {
    return formatValue(value / 1000) + " km";
  }
  return Number(value).toLocaleString();
}

function showRunsError(xhr) {
  $("#runs-error").text(formatError(xhr)).show();
}

function runColor(id) {
  const compared = _.find(comparedRuns, { id: id });
  return compared ? RUN_COLORS[compared.slot] : null;
}

function openRunsDialog() {
  const type = getAnalysisType();
  $("#runs-title").text("Saved Runs: " + ANALYSES[type].label);
  $("#runs-error").hide();
  comparedRuns = [];
  savedRuns = [];
  renderRuns();
  loadRuns();
  $("#runs-dialog").modal("show");
}

function loadRuns() {
  $.getJSON("/runs", { analysis: getAnalysisType() }).done(function(runs) {
    savedRuns = runs;
    // forget compared runs since deleted
    comparedRuns = _.filter(comparedRuns, function(c) { return _.some(runs, { id: c.id }); });
    renderRuns();
  }).fail(showRunsError);
}

function renderRuns() {
  const type = getAnalysisType();
  const metrics = RUN_METRICS[type];
  $("#runs-metric").text(metrics ? metrics.headline.label : "");
  $("#runs-empty").toggle(savedRuns.length == 0);
  const list = $("#runs-list").empty();
  _.forEach(savedRuns, function(run) {
    const color = runColor(run.id);
    const checkbox = $("<input type='checkbox'>")
      .attr("aria-label", "Compare " + run.name)
      .prop("checked", Boolean(color))
      .prop("disabled", !run.summary || (!color && comparedRuns.length >= RUN_COLORS.length))
      .on("change", function() { toggleCompared(run.id, this.checked); });
    list.append($("<tr>").append(
      $("<td>").append(checkbox),
      $("<td>").append(
        color ? $("<span>").addClass("run-swatch").css("background", color) : null,
        $("<span>").text(run.name)
      ),
      $("<td>").text(formatSavedTime(run.created)),
      $("<td>").text(metrics && run.summary ? formatMetric(metrics.headline.value(run.summary), metrics.headline.kind) : ""),
      $("<td>").addClass("library-actions").append(
        actionButton("fas fa-pen", "Rename " + run.name, function() { renameRun(run); }),
        actionButton("fas fa-play", "Run " + run.name + " again", function() { runAgain(run); }),
        actionButton("fas fa-trash-alt", "Delete " + run.name, function() { deleteRun(run); })
      )
    ));
  });
  renderComparison();
}

function toggleCompared(id, compare) {
  if (compare) {
    const used = _.map(comparedRuns, "slot");
    const slot = _.find(_.range(RUN_COLORS.length), function(s) { return !_.includes(used, s); });
    if (slot !== undefined) {
      comparedRuns.push({ id: id, slot: slot });
    }
  } else {
    _.remove(comparedRuns, { id: id });
  }
  renderRuns();
}

// Renders the comparison of the checked runs: a table of their metrics and
// (for coverage) their shares of the region observed over time.
function renderComparison() {
  const container = $("#runs-compare").empty();
  const type = getAnalysisType();
  const metrics = RUN_METRICS[type];
  if (!metrics || savedRuns.length == 0) {
    return;
  }
  const runs = _.compact(_.map(comparedRuns, function(c) {
    const run = _.find(savedRuns, { id: c.id });
    return run ? _.assign({ color: RUN_COLORS[c.slot] }, run) : null;
  }));
  const root = $("<div>").addClass("summary").appendTo(container);
  if (runs.length == 0) {
    root.append($("<p>").addClass("small text-muted mb-0").text("Check up to four runs to compare them."));
    return;
  }
  const table = $("<table>").addClass("table table-sm small runs-metrics").appendTo(root);
  table.append($("<thead>").append($("<tr>").append(
    $("<th>").text("Metric"),
    _.map(runs, function(run) {
      return $("<th>").append($("<span>").addClass("run-swatch").css("background", run.color), $("<span>").text(run.name));
    })
  )));
  const body = $("<tbody>").appendTo(table);
  _.forEach(metrics.rows, function(row) {
    const values = _.map(runs, function(run) { return row.value(run.summary); });
    // rows of optional metrics show only if a run has them
    if (row.optional && _.every(values, function(value) { return value === null || value === undefined; })) {
      return;
    }
    // one unit per row of durations, so values compare at a glance
    const unit = row.kind == "duration"
      ? durationUnit(_.max(_.filter(values, _.isFinite)) || 0)
      : null;
    body.append($("<tr>").append(
      $("<td>").text(row.label),
      _.map(values, function(value) { return $("<td>").text(formatMetric(value, row.kind, unit)); })
    ));
  });
  if (COVERAGE_TERMS[type]) {
    $("<div>").addClass("summary-charts").appendTo(root).append(comparisonChart(_.map(runs, function(run) {
      return { name: run.name, color: run.color, curve: run.summary.coverage };
    }), COVERAGE_TERMS[type]));
  }
}

function renameRun(run) {
  const name = prompt("New name of the run:", run.name);
  if (name === null || !name.trim()) {
    return;
  }
  sendJson("PATCH", "/runs/" + run.id, { name: name.trim() }).done(loadRuns).fail(showRunsError);
}

function deleteRun(run) {
  if (!confirm("Delete the saved run “" + run.name + "”?")) {
    return;
  }
  sendJson("DELETE", "/runs/" + run.id).done(loadRuns).fail(showRunsError);
}

// Sets the inputs of the Analysis tab from the request of a saved run.
function setAnalysisInputs(type, request) {
  const start = new Date(request.start);
  const end = new Date(request.end);
  $("#analysis-start").val(toDateTimeInput(start));
  $("#analysis-duration").val(Number(((end - start) / 86400e3).toFixed(6))).trigger("change");
  if (request.display) {
    const hours = (new Date(request.display.end) - new Date(request.display.start)) / 3600e3;
    $("#analysis-animate").val(Number(hours.toFixed(6))).trigger("change");
  }
  if (type == "coverage") {
    setSufficiencyInputs(request.sufficiency);
    setSampleSizeInputs(request.sample_size);
  } else if (type == "coincidence") {
    setCoincidenceInputs(request);
    setSufficiencyInputs(request.sufficiency);
    setSampleSizeInputs(request.sample_size);
  } else if (type == "swaths") {
    $("#swaths-step").val(request.step);
    if (request.segment) {
      $("#swaths-segment").val(request.segment / 60);
    }
  } else if (type == "latency" && request.during_contact) {
    $("#latency-contact").val(request.during_contact);
  } else if (type == "access") {
    $("#access-solar").prop("checked", !request.omit_solar);
  }
}

// Runs a saved run again: loads its design, and analyzes its request as
// saved (its region and settings, which may differ from those of the tab).
function runAgain(run) {
  if (!confirm("Replace the current design with the design of “" + run.name +
      "” and run its analysis again?")) {
    return;
  }
  $.getJSON("/runs/" + run.id).done(function(saved) {
    $("#runs-dialog").modal("hide");
    importDesign(saved.design);
    setSavedDesignRef(null);
    // selecting the analysis type cancels any analysis running
    $("#analysis-type").val(saved.analysis).trigger("change");
    setAnalysisInputs(saved.analysis, saved.request);
    startAnalysis(saved.analysis, saved.request, saved.design);
  }).fail(showRunsError);
}

// A default name of the current analysis results.
function defaultRunName() {
  const names = _.map(analysisResult.payload.satellites, "name").join(", ");
  const days = analysisResult.duration / 86400;
  return _.truncate(names, { length: 50 }) + ", " +
    analysisResult.payload.start.substring(0, 10) + ", " + formatValue(days) + " d";
}

function saveRun() {
  if (!analysisResult) {
    return;
  }
  const name = prompt("Name of the saved run:", defaultRunName());
  if (name === null || !name.trim()) {
    return;
  }
  $("#analysis-error").hide();
  sendJson("POST", "/runs", {
    name: name.trim(),
    analysis: analysisResult.type,
    taskId: analysisResult.taskId,
    request: analysisResult.payload,
    design: analysisResult.design
  }).done(function(saved) {
    flashStatus($("#run-saved"), "Saved “" + saved.name + "”.");
  }).fail(function(xhr) {
    $("#analysis-error").text(formatError(xhr)).show();
  });
}

$(document).ready(function() {
  loadSavedDesignRef();
  $("#designs-open").click(function() {
    $("#designs-error").hide();
    renderDesignUpdate();
    $("#design-save-name").val(savedDesignRef ? savedDesignRef.name : defaultDesignName());
    $("#designs-list").empty();
    loadDesigns();
    $("#designs-dialog").modal("show");
  });
  $("#design-save-form").on("submit", function(event) {
    event.preventDefault();
    saveCurrentDesign(false);
  });
  $("#design-update").click(function() { saveCurrentDesign(true); });
  $("#run-save").click(saveRun);
  $("#runs-open").click(openRunsDialog);
});
