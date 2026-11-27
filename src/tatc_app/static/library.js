// Designs and analysis runs saved to the user's account (the server's
// `/designs` and `/runs` endpoints): the saved designs dialog of the Design
// tab, and the saving (under the saved design of the current design),
// comparison (with the current results), and running again of analysis runs
// of the Analysis tab.

import { ANALYSES } from "./analysis-types.js";
import { analysisResult, getAnalysisType, setAnalysisInputs, startAnalysis } from "./analysis.js";
import { design, exportDesign, importDesign } from "./design-state.js";
import { durationUnit, formatDuration, formatError, formatKilometers, formatShare, formatValue, sendJson } from "./index.js";
import { comparisonChart } from "./summary.js";
import { COVERAGE_TERMS } from "./terms.js";

// --- Helpers ---

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
// design updates (and runs save under); null for a design that is not saved
let savedDesignRef = null;

export function setSavedDesignRef(ref) {
  savedDesignRef = ref;
  renderRunDesign();
  renderDesignUpdate();
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
      $("<td>").text(saved.runs),
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
  const runs = saved.runs == 1 ? "the run" : "the " + saved.runs + " runs";
  if (!confirm("Delete the saved design “" + saved.name + "”" +
      (saved.runs ? " and " + runs + " saved under it?" : "?"))) {
    return;
  }
  sendJson("DELETE", "/designs/" + saved.id).done(function() {
    if (savedDesignRef && savedDesignRef.id == saved.id) {
      setSavedDesignRef(null);
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
    flashStatus($("#designs-status"), "Saved “" + saved.name + "”.");
    loadDesigns();
  }).fail(function(xhr) {
    // the saved design may have been deleted (for example, in another tab)
    if (update && xhr.status == 404) {
      setSavedDesignRef(null);
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
// the id of the current results (before they are saved) among runs compared
const CURRENT_RUN = "current";
// the saved designs (that runs save under), and the groups of runs under
// them collapsed (by design id, "" for none), of the runs dialog
let savedDesigns = [];
let collapsedGroups = {};

// The rows of the comparison of runs of each analysis with a summary (the
// first is the headline metric, shown in the list of runs): {label,
// value(summary), kind} (a share, duration, number, length in meters, or
// count), and whether a row is `optional` (shown only if a run has a value).
// The metrics of runs of coverage-like analyses (see `COVERAGE_TERMS`).
function coverageRunMetrics(terms) {
  const twice = terms.twice.charAt(0).toUpperCase() + terms.twice.slice(1);
  const revisit = terms.revisit.replace(/^Mean /, "");
  return {
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
  // (swaths over a region)
  swaths: {
    curveTerms: COVERAGE_TERMS.region,
    rows: [
      { label: "Area observed", value: function(s) { return s.covered; }, kind: "share" },
      { label: "Observations of the region", value: function(s) { return s.observations; }, kind: "count" },
      { label: "Mean revisit time", value: function(s) { return s.revisit && s.revisit.mean; }, kind: "duration" },
      { label: "90th percentile revisit time", value: function(s) { return s.revisit && s.revisit.p90; }, kind: "duration" },
      { label: "Longest gap", value: function(s) { return s.max_gap; }, kind: "duration" },
      { label: "Area in common", optional: true, value: function(s) { return s.coincidence && s.coincidence.common; }, kind: "share" },
      { label: "Coincident footprints", optional: true, value: function(s) { return s.coincidence && s.coincidence.pairs; }, kind: "count" },
      { label: "Region area (km²)", value: function(s) { return s.area; }, kind: "number" },
      { label: "Analysis period", value: function(s) { return _.last(s.coverage.times); }, kind: "duration" }
    ]
  },
  latency: {
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
    return formatKilometers(value);
  }
  return Number(value).toLocaleString();
}

function showRunsError(xhr) {
  $("#runs-error").text(formatError(xhr)).show();
}

// Shows (on the Analysis tab) the saved design that runs save under: the
// saved design last opened or saved, if any.
function renderRunDesign() {
  const note = $("#run-design").empty();
  if (savedDesignRef) {
    note.append(
      $("<i>").addClass("fas fa-folder mr-1").attr("aria-hidden", "true"),
      "Runs save under ",
      $("<strong>").text(savedDesignRef.name)
    );
  } else {
    note.text("Runs save under no design: save the design (Design tab, Saved) to save runs under it.");
  }
}

// Tests whether the comparison of runs of an analysis is available.
export function canCompareRuns(type) {
  return Boolean(RUN_METRICS[type]);
}

function runColor(id) {
  const compared = _.find(comparedRuns, { id: id });
  return compared ? RUN_COLORS[compared.slot] : null;
}

// The current results of the selected analysis as a run to compare (with
// the saved runs), unless saved (their saved run is then marked current).
function currentRun() {
  if (!analysisResult || analysisResult.type != getAnalysisType()) {
    return null;
  }
  if (analysisResult.savedRunId && _.some(savedRuns, { id: analysisResult.savedRunId })) {
    return null;
  }
  return {
    id: CURRENT_RUN,
    name: "Current results",
    summary: analysisResult.result.summary || null,
    current: true
  };
}

function isCurrentRun(run) {
  return Boolean(run.current || (analysisResult && run.id === analysisResult.savedRunId));
}

// The runs to compare: the current results (if not saved) and the saved runs.
function comparableRuns() {
  return _.compact([currentRun()]).concat(savedRuns);
}

export function openRunsDialog() {
  const type = getAnalysisType();
  $("#runs-title").text("Compare Runs: " + ANALYSES[type].label);
  $("#runs-error").hide();
  savedRuns = [];
  savedDesigns = [];
  // the current results compare from the start
  comparedRuns = [];
  if (analysisResult && analysisResult.type == type && analysisResult.result.summary) {
    comparedRuns.push({ id: analysisResult.savedRunId || CURRENT_RUN, slot: 0 });
  }
  renderRuns();
  loadRuns();
  $("#runs-dialog").modal("show");
}

function loadRuns() {
  $.when(
    $.getJSON("/runs", { analysis: getAnalysisType() }),
    $.getJSON("/designs")
  ).done(function(runs, designs) {
    savedRuns = runs[0];
    savedDesigns = designs[0];
    // the saved run of the current results may since be deleted (they then
    // compare as not saved)
    const savedRunId = analysisResult && analysisResult.savedRunId;
    if (savedRunId && !_.some(savedRuns, { id: savedRunId })) {
      delete analysisResult.savedRunId;
      _.forEach(comparedRuns, function(c) {
        if (c.id === savedRunId) {
          c.id = CURRENT_RUN;
        }
      });
    }
    // and so may the saved design of the current design
    if (savedDesignRef && !_.some(savedDesigns, { id: savedDesignRef.id })) {
      setSavedDesignRef(null);
    }
    // forget compared runs since deleted
    const ids = _.map(comparableRuns(), "id");
    comparedRuns = _.filter(comparedRuns, function(c) { return _.includes(ids, c.id); });
    renderRuns();
  }).fail(showRunsError);
}

// Groups the saved runs by the saved design they save under: the open
// design first, then the other designs (latest saved first), then runs
// under no design.
function runGroups() {
  const byDesign = _.groupBy(savedRuns, function(run) { return run.design_id || ""; });
  const designs = _.sortBy(savedDesigns, function(d) {
    return savedDesignRef && d.id == savedDesignRef.id ? 0 : 1;
  });
  const groups = _.map(designs, function(d) {
    return {
      id: d.id,
      name: d.name,
      current: Boolean(savedDesignRef && d.id == savedDesignRef.id),
      runs: byDesign[d.id] || []
    };
  });
  const known = _.map(savedDesigns, "id");
  groups.push({
    id: "",
    name: "No design",
    runs: _.filter(savedRuns, function(run) { return !run.design_id || !_.includes(known, run.design_id); })
  });
  return _.filter(groups, function(group) { return group.current || group.runs.length; });
}

// A header row of a group of runs (that toggles it, if collapsible).
function groupHeader(label, icon, extras, collapsed, onToggle) {
  const content = _.compact([
    $("<i>").addClass(icon + " mr-2").attr("aria-hidden", "true"),
    $("<span>").text(label)
  ].concat(extras || []));
  const cell = $("<td colspan='5'>");
  if (onToggle) {
    cell.append($("<button type='button'>")
      .addClass("btn btn-link btn-sm runs-group-toggle")
      .attr("aria-expanded", String(!collapsed))
      .append(
        $("<i>").addClass("fas fa-fw mr-1 " + (collapsed ? "fa-caret-right" : "fa-caret-down")).attr("aria-hidden", "true"),
        content
      )
      .on("click", onToggle));
  } else {
    cell.append(content);
  }
  return $("<tr>").addClass("runs-group").append(cell);
}

function compareCheckbox(run) {
  const color = runColor(run.id);
  return $("<input type='checkbox'>")
    .attr("aria-label", "Compare " + run.name)
    .prop("checked", Boolean(color))
    .prop("disabled", !run.summary || (!color && comparedRuns.length >= RUN_COLORS.length))
    .on("change", function() { toggleCompared(run.id, this.checked); });
}

function runNameCell(run) {
  const color = runColor(run.id);
  return $("<td>").append(
    color ? $("<span>").addClass("run-swatch").css("background", color) : null,
    $("<span>").text(run.name),
    // (the saved run of the current results)
    isCurrentRun(run) && !run.current ? $("<span>").addClass("badge badge-info ml-2").text("current") : null
  );
}

function runMetricCell(run, metrics) {
  return $("<td>").text(metrics && run.summary
    ? formatMetric(metrics.rows[0].value(run.summary), metrics.rows[0].kind)
    : "");
}

function renderRuns() {
  const type = getAnalysisType();
  const metrics = RUN_METRICS[type];
  $("#runs-metric").text(metrics ? metrics.rows[0].label : "");
  const current = currentRun();
  $("#runs-empty").toggle(savedRuns.length == 0 && !current);
  const list = $("#runs-list").empty();
  if (current) {
    list.append(
      groupHeader("Current results", "fas fa-chart-bar", null, false, null),
      $("<tr>").addClass("runs-current").append(
        $("<td>").addClass("runs-indent").append(compareCheckbox(current)),
        runNameCell(current),
        $("<td>").addClass("text-muted").text("Not saved"),
        runMetricCell(current, metrics),
        $("<td>").addClass("library-actions").append(
          actionButton("fas fa-save", "Save the current results", function() { saveRun($("#runs-error")); })
        )
      )
    );
  }
  _.forEach(runGroups(), function(group) {
    const collapsed = Boolean(collapsedGroups[group.id]);
    const extras = [
      group.current ? $("<span>").addClass("badge badge-secondary ml-2").text("open design") : null,
      $("<span>").addClass("text-muted ml-2").text("(" + group.runs.length + ")")
    ];
    list.append(groupHeader(group.name, group.id ? "fas fa-folder" : "far fa-folder", extras, collapsed, function() {
      collapsedGroups[group.id] = !collapsed;
      renderRuns();
    }));
    if (collapsed) {
      return;
    }
    if (group.runs.length == 0) {
      list.append($("<tr>").append($("<td colspan='5'>").addClass("text-muted runs-indent")
        .text("No saved runs of this analysis under this design yet.")));
    }
    _.forEach(group.runs, function(run) {
      const actions = $("<td>").addClass("library-actions");
      actions.append(
        actionButton("fas fa-pen", "Rename " + run.name, function() { renameRun(run); }),
        actionButton("fas fa-folder", "Save " + run.name + " under another design", function() { moveRun(run, actions); }),
        actionButton("fas fa-play", "Run " + run.name + " again", function() { runAgain(run); }),
        actionButton("fas fa-trash-alt", "Delete " + run.name, function() { deleteRun(run); })
      );
      list.append($("<tr>").toggleClass("runs-current", isCurrentRun(run)).append(
        $("<td>").addClass("runs-indent").append(compareCheckbox(run)),
        runNameCell(run),
        $("<td>").text(formatSavedTime(run.created)),
        runMetricCell(run, metrics),
        actions
      ));
    });
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
  const all = comparableRuns();
  if (!metrics || all.length == 0) {
    return;
  }
  const runs = _.compact(_.map(comparedRuns, function(c) {
    const run = _.find(all, { id: c.id });
    return run ? _.assign({ color: RUN_COLORS[c.slot] }, run) : null;
  }));
  const root = $("<div>").addClass("summary").appendTo(container);
  if (runs.length == 0) {
    root.append($("<p>").addClass("small text-muted mb-0").text(
      "Check up to four runs to compare them" + (currentRun() ? ", including the current results." : ".")
    ));
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
  const curveTerms = metrics.curveTerms || COVERAGE_TERMS[type];
  if (curveTerms) {
    $("<div>").addClass("summary-charts").appendTo(root).append(comparisonChart(_.map(runs, function(run) {
      return { name: run.name, color: run.color, curve: run.summary.coverage };
    }), curveTerms));
  }
}

function renameRun(run) {
  const name = prompt("New name of the run:", run.name);
  if (name === null || !name.trim()) {
    return;
  }
  sendJson("PATCH", "/runs/" + run.id, { name: name.trim() }).done(loadRuns).fail(showRunsError);
}

// Replaces the actions of a run with a select of the design to save it under.
function moveRun(run, cell) {
  const select = $("<select>")
    .addClass("custom-select custom-select-sm runs-move")
    .attr("aria-label", "Design to save " + run.name + " under")
    .append(
      _.map(savedDesigns, function(d) { return $("<option>").val(d.id).text(d.name); }),
      $("<option>").val("").text("No design")
    )
    .val(_.some(savedDesigns, { id: run.design_id }) ? run.design_id : "")
    .on("change", function() {
      sendJson("PATCH", "/runs/" + run.id, { designId: this.value || null })
        .done(loadRuns)
        .fail(showRunsError);
    })
    // leaving the select without a change restores the actions
    .on("blur", function() {
      if (this.value == (run.design_id || "")) {
        renderRuns();
      }
    });
  cell.empty().append(select);
  select.trigger("focus");
}

function deleteRun(run) {
  if (!confirm("Delete the saved run “" + run.name + "”?")) {
    return;
  }
  sendJson("DELETE", "/runs/" + run.id).done(loadRuns).fail(showRunsError);
}

// Runs a saved run again: loads its design, and analyzes its request as
// saved (its region and settings, which may differ from those of the tab).
// Runs then save under the same saved design.
function runAgain(run) {
  if (!confirm("Replace the current design with the design of “" + run.name +
      "” and run its analysis again?")) {
    return;
  }
  $.getJSON("/runs/" + run.id).done(function(saved) {
    $("#runs-dialog").modal("hide");
    importDesign(saved.design);
    const parent = _.find(savedDesigns, { id: saved.design_id });
    setSavedDesignRef(parent ? { id: parent.id, name: parent.name } : null);
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

// Saves the current results (under the saved design of the current design,
// if any), showing any error in an element.
function saveRun(errorElement) {
  const result = analysisResult;
  if (!result) {
    return;
  }
  const parent = savedDesignRef;
  const name = prompt(
    parent
      ? "Name of the run (saved under the design “" + parent.name + "”):"
      : "Name of the run (saved under no design: save the design first to save runs under it):",
    defaultRunName()
  );
  if (name === null || !name.trim()) {
    return;
  }
  errorElement.hide();
  sendJson("POST", "/runs", {
    name: name.trim(),
    analysis: result.type,
    designId: parent ? parent.id : null,
    taskId: result.taskId,
    request: result.payload,
    design: result.design
  }).done(function(saved) {
    result.savedRunId = saved.id;
    flashStatus($("#run-saved"), "Saved “" + saved.name + "”" + (parent ? " under “" + parent.name + "”." : "."));
    // the current results compare as their saved run
    if (analysisResult === result) {
      _.forEach(comparedRuns, function(c) {
        if (c.id === CURRENT_RUN) {
          c.id = saved.id;
        }
      });
    }
    if ($("#runs-dialog").hasClass("show")) {
      loadRuns();
    }
  }).fail(function(xhr) {
    // the saved design may have been deleted (for example, in another tab)
    if (parent && xhr.status == 404) {
      setSavedDesignRef(null);
      errorElement.text("The saved design “" + parent.name + "” was deleted. Save the run again to save it under no design.").show();
      return;
    }
    errorElement.text(formatError(xhr)).show();
  });
}

// Sets up this module once the page has loaded (see main.js).
export function setupLibrary() {
  loadSavedDesignRef();
  renderRunDesign();
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
  $("#run-save").click(function() { saveRun($("#analysis-error")); });
  $("#runs-open").click(openRunsDialog);
}
