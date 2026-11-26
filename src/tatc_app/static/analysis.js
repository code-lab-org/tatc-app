// Analysis tab: coverage and revisit, coincident observations, ground track
// swaths (optionally over a region), data latency with ground stations, and
// point access (overflight) analyses, with animated results in the Cesium
// viewer. Each type of analysis (its inputs and data) is in
// analysis-types.js; this file runs them and shows their results.

let analysisResult = null; // {type, result, taskId, payload, design, duration}
let targetLayer = null;

function hasTargetLayer(type) {
  return ANALYSES[type].targetLayer;
}

// Tests whether an analysis of a type uses the region (swaths, if limited to
// it).
function usesRegion(type) {
  const region = ANALYSES[type].region;
  return region === "optional" ? $("#swaths-region-enabled").is(":checked") : region;
}

function getAnalysisType() {
  return $("#analysis-type").val();
}

function getAnalysisPeriod() {
  const start = fromDateTimeInput($("#analysis-start").val());
  const end = new Date(start.getTime() + Number($("#analysis-duration").val()) * 86400e3);
  const animateEnd = new Date(Math.min(
    end.getTime(), start.getTime() + Number($("#analysis-animate").val()) * 3600e3
  ));
  return { start: start, end: end, animateEnd: animateEnd };
}

// The server's default and limit of the animation (display) time steps.
const DISPLAY_STEP = 60;
const MAX_DISPLAY_STEPS = 20000;

// Gets the inputs common to all analyses, with the satellites, members, and
// instruments checked in the filter.
function getBasePayload(inputs) {
  const period = getAnalysisPeriod();
  const duration = (period.animateEnd - period.start) / 1000;
  return {
    satellites: inputs.satellites,
    colors: inputs.colors,
    instrumentColors: inputs.instrumentColors,
    excludeMembers: inputs.excludeMembers.length ? inputs.excludeMembers : null,
    start: period.start.toISOString(),
    end: period.end.toISOString(),
    display: {
      start: period.start.toISOString(),
      end: period.animateEnd.toISOString(),
      delta: Math.max(DISPLAY_STEP, Math.ceil(duration / (MAX_DISPLAY_STEPS - 1)))
    }
  };
}

// Sets the inputs of the tab from a request of an analysis of a type (as of
// a saved run).
function setAnalysisInputs(type, request) {
  const start = new Date(request.start);
  const end = new Date(request.end);
  $("#analysis-start").val(toDateTimeInput(start));
  $("#analysis-duration").val(inputNumber((end - start) / 86400e3)).trigger("change");
  if (request.display) {
    const hours = (new Date(request.display.end) - new Date(request.display.start)) / 3600e3;
    $("#analysis-animate").val(inputNumber(hours)).trigger("change");
  }
  ANALYSES[type].writeInputs(request);
}

// --- Layers ---

function clearAnalysisLayers() {
  if (targetLayer) {
    targetLayer.destroy();
    targetLayer = null;
  }
  clearCzmlLayer("analysis");
  showLegend(false);
}

// Shows (or hides) the legend of the target layer in the display panel: the
// display mode, its color scale, and the settings of the scale.
function showLegend(show) {
  $("#legend-section").toggle(show);
}

// Shows the color scale of a display mode of results of a type in the
// legend.
function renderLegend(type, scale, unit) {
  $(".legend-mode").hide();
  $("#" + type + "-mode").show();
  renderColorbar($("#legend-colorbar"), scale);
  $("#legend-min").text(formatNumber(scale.min) + " " + unit);
  $("#legend-max").text(formatNumber(scale.max) + " " + unit);
  $(".colorbar-unit").text(unit);
  showLegend(true);
}

// Tests whether an analysis includes a satellite or constellation since
// removed from (or renamed in) the design.
function hasRemovedSatellites(payload) {
  const names = _.map(design.satellites, "system.name");
  return _.some(payload.satellites, function(system) { return !_.includes(names, system.name); });
}

// Drops the analysis results if they include a removed satellite, so it no
// longer shows in the viewer.
function dropStaleAnalysis() {
  if (!analysisResult || !hasRemovedSatellites(analysisResult.payload)) {
    return;
  }
  clearAnalysisLayers();
  analysisResult = null;
  enableResultButtons(false);
  if ($("#nav-analysis-tab").hasClass("active")) {
    changeAnalysisType();
  }
}

function showAnalysisLayers(show) {
  if (targetLayer) {
    targetLayer.show(show);
  }
  showCzmlLayer("analysis", show);
  // the target layer shows a legend
  showLegend(show && Boolean(targetLayer));
}

// Sets the clock to the results: the analysis period for results with a
// target layer, and the period of the animation otherwise.
function setAnalysisClock() {
  const source = getCzmlLayer("analysis");
  if (hasTargetLayer(analysisResult.type)) {
    setClock(analysisResult.payload.start, analysisResult.payload.end);
  } else if (source && source.clock) {
    setClock(source.clock.startTime, source.clock.stopTime, source.clock.multiplier);
  }
}

// --- Display modes ---

// Gets the color scale range: custom, or the default.
function getScaleRange(defaultRange) {
  if ($("#colorbar-custom").is(":checked")) {
    return [Number($("#colorbar-min").val()), Number($("#colorbar-max").val())];
  }
  $("#colorbar-min").val(Number(defaultRange[0].toPrecision(3)));
  $("#colorbar-max").val(Number(defaultRange[1].toPrecision(3)));
  return defaultRange;
}

function finiteValues(features, property, scale) {
  return _.filter(_.map(features, function(f) {
    const value = f.properties[property];
    return value === null || value === undefined ? NaN : value * (scale || 1);
  }), isFinite);
}

// Default ranges of a property of the points: from zero to the maximum, or
// from the minimum to the maximum.
function rangeFromZero(property) {
  return function(features) {
    return [0, _.max(finiteValues(features, property)) || 1];
  };
}
function rangeOfValues(property, scale) {
  return function(features) {
    const values = finiteValues(features, property, scale);
    return values.length ? [_.min(values), _.max(values)] : [0, 1];
  };
}

// The display modes of coverage-like results (see `COVERAGE_TERMS`), with
// the names of their events (such as "observations"): of their counts, the
// time since and between them, their sampling sufficiency, and their ground
// sample sizes (only of results that assess them).
function coverageDisplayModes(terms, event) {
  return [
    {
      value: "samples", label: terms.samples + " so far (animated)", unit: "",
      range: rangeFromZero("samples"),
      pointValue: function(i, t) { return targetLayer.countStarted(i, t); }
    },
    {
      value: "since", label: "Time since last " + event + " (animated)", unit: "h",
      reverse: true,
      range: function(features) {
        const revisits = finiteValues(features, "revisit", 1 / 3600);
        return [0, revisits.length ? Math.max(1, _.max(revisits)) : analysisResult.duration / 3600];
      },
      pointValue: function(i, t) { return targetLayer.timeSince(i, t) / 3600; }
    },
    {
      value: "revisit", label: terms.revisit + " (final)", unit: "h",
      reverse: true, property: "revisit", scale: 1 / 3600,
      range: rangeOfValues("revisit", 1 / 3600)
    },
    {
      value: "final-samples", label: "Number of " + terms.samples.toLowerCase() + " (final)", unit: "",
      property: "samples",
      range: rangeFromZero("samples")
    },
    {
      value: "relative-error", label: "Sampling error, % of σ (final)", unit: "%",
      sufficiency: true, reverse: true, property: "relative_error", scale: 100,
      range: rangeOfValues("relative_error", 100)
    },
    {
      value: "effective-samples", label: "Effective independent samples (final)", unit: "",
      sufficiency: true, property: "effective_samples",
      range: rangeFromZero("effective_samples")
    },
    {
      value: "max-gap", label: "Longest gap without a sample (final)", unit: "h",
      sufficiency: true, reverse: true, property: "max_gap", scale: 1 / 3600,
      range: rangeOfValues("max_gap", 1 / 3600)
    },
    {
      value: "local-time", label: "Local time-of-day coverage (final)", unit: "%",
      sufficiency: true, property: "local_time_coverage", scale: 100,
      range: function() { return [0, 100]; }
    },
    {
      value: "sample-size", label: "Median ground sample size (final)", unit: "km",
      sampleSize: true, reverse: true, property: "sample_size_median", scale: 1 / 1000,
      range: rangeOfValues("sample_size_median", 1 / 1000)
    },
    {
      value: "best-sample-size", label: "Smallest ground sample size (final)", unit: "km",
      sampleSize: true, reverse: true, property: "sample_size_min", scale: 1 / 1000,
      range: rangeOfValues("sample_size_min", 1 / 1000)
    }
  ];
}

// The display modes of coverage, coincidence, and latency results (in the
// order of their selects). An animated mode computes the value of each point
// at a time from the target layer, and a final mode shows a (scaled)
// property of each point and cell. `range(features)` gives the default color
// scale range, and `reverse` maps small values to the bright end (for
// example, short revisit times).
const DISPLAY_MODES = {
  coverage: coverageDisplayModes(COVERAGE_TERMS.coverage, "observation"),
  coincidence: coverageDisplayModes(COVERAGE_TERMS.coincidence, "coincidence"),
  latency: [
    {
      value: "pending", label: "Observations awaiting downlink (animated)", unit: "",
      reverse: true,
      range: function() { return [0, Math.max(1, targetLayer.maxPending())]; },
      pointValue: function(i, t) { return targetLayer.countPending(i, t); }
    },
    {
      value: "latency", label: "Mean data latency (final)", unit: "h",
      reverse: true, property: "latency", scale: 1 / 3600,
      range: rangeOfValues("latency", 1 / 3600)
    }
  ]
};

// Lists the display modes of results of a type: those of sampling
// sufficiency and of ground sample sizes only if the results assess them.
// Keeps the selected mode if it is listed.
function updateDisplayModes(type, result) {
  const select = $("#" + type + "-mode");
  const selected = select.val();
  const summary = (result && result.summary) || {};
  const modes = _.filter(DISPLAY_MODES[type], function(mode) {
    return (!mode.sufficiency || Boolean(summary.sufficiency)) &&
      (!mode.sampleSize || Boolean(summary.sample_size));
  });
  fillSelect(select, modes);
  if (_.some(modes, { value: selected })) {
    select.val(selected);
  }
}

// Applies the display mode of coverage or latency results.
function applyDisplayMode() {
  if (!analysisResult || !targetLayer) {
    return;
  }
  const type = analysisResult.type;
  const spec = _.find(DISPLAY_MODES[type], { value: $("#" + type + "-mode").val() }) ||
    DISPLAY_MODES[type][0];
  const range = getScaleRange(spec.range(analysisResult.result.points.features));
  let mode;
  if (spec.property) {
    const value = function(feature) {
      const v = feature.properties[spec.property];
      return v === null || v === undefined ? NaN : v * (spec.scale || 1);
    };
    mode = {
      animated: false,
      pointValue: function(i, t, feature) { return value(feature); },
      cellValue: function(c, feature) { return value(feature); }
    };
  } else {
    mode = { animated: true, pointValue: spec.pointValue };
  }
  mode.scale = createColorScale(range[0], range[1], spec.reverse);
  renderLegend(type, mode.scale, spec.unit);
  targetLayer.setMode(mode);
}

// --- Running analyses ---

function showAnalysisError(message) {
  $("#analysis-error").text(message).show();
}

// Gets the request of the selected analysis from the inputs of the tab, or
// throws an `InputError`.
function readAnalysisRequest(type) {
  if (getSatellites().length == 0) {
    throw new InputError("Add a satellite or constellation in the Design tab.");
  }
  const inputs = getFilteredInputs();
  if (inputs.satellites.length == 0) {
    throw new InputError("Check at least one satellite and instrument to analyze.");
  }
  return ANALYSES[type].readInputs(getBasePayload(inputs));
}

function runSelectedAnalysis() {
  const type = getAnalysisType();
  let payload;
  try {
    payload = readAnalysisRequest(type);
  } catch (error) {
    if (!(error instanceof InputError)) {
      throw error;
    }
    showAnalysisError(error.message);
    return;
  }
  startAnalysis(type, payload, exportDesign());
}

// Enables (or disables) the buttons that act on analysis results.
function enableResultButtons(enable) {
  $("#analysis-data, #run-save").prop("disabled", !enable);
  if (!enable) {
    $("#run-saved").hide();
  }
}

// Runs an analysis of a type with a request (`payload`), keeping the design
// it analyzes (as exported) with its results, to save the run.
function startAnalysis(type, payload, designSnapshot) {
  // cells of the results have the edges of the region requested
  const arcType = getArcType();
  const endpoint = ANALYSES[type].endpoint;
  runAnalysis({
    name: "analysis",
    url: endpoint,
    payload: payload,
    button: $("#analysis-run"),
    progress: $("#analysis-progress"),
    error: $("#analysis-error"),
    onResult: function(result, taskId) {
      // a satellite may be removed while the analysis runs
      if (hasRemovedSatellites(payload)) {
        showAnalysisError("A satellite of this analysis was removed from the design. Run the analysis again.");
        return;
      }
      clearAnalysisLayers();
      // the region (its grid or outline) shows while editing it, not over
      // results
      showRegion(false);
      analysisResult = {
        type: type,
        result: result,
        taskId: taskId,
        payload: payload,
        design: designSnapshot,
        duration: (new Date(payload.end) - new Date(payload.start)) / 1000
      };
      enableResultButtons(true);
      if (hasTargetLayer(type)) {
        targetLayer = new TargetLayer({
          points: result.points,
          cells: result.cells,
          timeline: result.timeline,
          cellTargets: result.cell_targets,
          arcType: arcType
        });
        updateDisplayModes(type, result);
        applyDisplayMode();
      }
      loadCzmlLayer("analysis", endpoint + "/" + taskId + "/czml", { clock: false }).then(function(source) {
        if (!source) {
          return;
        }
        applySatelliteDisplayOptions(source);
        // the analysis type may change while the CZML loads: then keep the
        // clock paused
        if (analysisResult && analysisResult.taskId === taskId && getAnalysisType() === type) {
          setAnalysisClock();
        }
      });
    }
  });
}

// --- Data tables ---

function showAnalysisData() {
  if (!analysisResult) {
    return;
  }
  // results with a summary compare with saved runs (library.js)
  const type = analysisResult.type;
  const compare = analysisResult.result.summary && canCompareRuns(type) ? openRunsDialog : null;
  ANALYSES[type].showData(analysisResult, compare);
}

// --- Panels ---

// Limits the animation (hours) to the analysis duration (days), so the input
// shows the length actually animated. The requested length is kept, so it
// returns when the duration grows again.
const MAX_ANIMATE_HOURS = 168;
let requestedAnimate = null; // hours, as last entered (or the default)

function limitAnimation() {
  const animate = $("#analysis-animate");
  if (requestedAnimate === null) {
    requestedAnimate = Number(animate.val());
  }
  const duration = Number($("#analysis-duration").val());
  if (!(duration > 0)) {
    return;
  }
  const limit = Math.round(Math.min(MAX_ANIMATE_HOURS, duration * 24) * 1000) / 1000;
  animate.attr("max", limit);
  animate.val(Math.min(requestedAnimate, limit));
}

// Shows the region panel if the selected analysis uses the region, and the
// region itself while editing it (not over results shown).
function updateRegionPanel(showResults) {
  const region = Boolean(usesRegion(getAnalysisType()));
  $(".region-panel").toggle(region);
  updateRegionControls();
  $("#swaths-region-options").toggle($("#swaths-region-enabled").is(":checked"));
  showRegion(region && !showResults);
}

function changeAnalysisType() {
  const type = getAnalysisType();
  $(".analysis-panel").removeClass("shown");
  $(".analysis-panel[data-analysis~='" + type + "']").addClass("shown");
  $("#analysis-description").text(ANALYSES[type].description);
  limitAnimation();
  // picking (region vertices or target points) applies to one analysis type
  stopMapPick();
  const showResults = Boolean(analysisResult && analysisResult.type == type);
  updateRegionPanel(showResults);
  showAnalysisLayers(showResults);
  enableResultButtons(showResults);
  renderSiteEntities();
}

// Fills a select with options ({value, label}).
function fillSelect(select, options) {
  select.empty().append(_.map(options, function(option) {
    return $("<option>").val(option.value).text(option.label);
  }));
}

$(document).ready(function() {
  fillSelect($("#analysis-type"), _.map(ANALYSES, function(analysis, value) {
    return { value: value, label: analysis.label };
  }));
  _.forEach(DISPLAY_MODES, function(modes, type) {
    fillSelect($("#" + type + "-mode"), modes);
  });

  const start = new Date();
  start.setUTCHours(0, 0, 0, 0);
  $("#analysis-start").val(toDateTimeInput(start));

  $("#analysis-type").change(function() {
    // drop any run of the previous analysis type, and rewind and pause the
    // animation until results of this analysis are ready (loading them
    // restarts the clock)
    cancelAnalysis("analysis");
    viewer.clock.shouldAnimate = false;
    viewer.clock.currentTime = viewer.clock.startTime.clone();
    changeAnalysisType();
  });
  $("#analysis-duration").change(limitAnimation);
  $("#analysis-animate").change(function() {
    const value = Number($(this).val());
    if (value > 0) {
      requestedAnimate = value;
    }
    limitAnimation();
  });
  $("#swaths-region-enabled").change(function() {
    // picking region vertices stops with the region
    stopMapPick();
    const type = getAnalysisType();
    updateRegionPanel(Boolean(analysisResult && analysisResult.type == type));
  });
  $("#swaths-coincidence-enabled").change(function() {
    $("#swaths-coincidence-options").toggle($(this).is(":checked"));
  });
  $("#sample-size-enabled").change(function() {
    $("#sample-size-options").toggle($(this).is(":checked"));
  });
  $("#sufficiency-enabled").change(function() {
    $("#sufficiency-options").toggle($(this).is(":checked"));
  });
  $("#analysis-run").click(runSelectedAnalysis);
  $("#analysis-data").click(showAnalysisData);
  $("#coverage-mode, #coincidence-mode, #latency-mode").change(function() {
    $("#colorbar-custom").prop("checked", false);
    $("#colorbar-range").hide();
    applyDisplayMode();
  });
  $("#colorbar-custom").change(function() {
    $("#colorbar-range").toggle($(this).is(":checked"));
    applyDisplayMode();
  });
  $("#colorbar-min, #colorbar-max").change(applyDisplayMode);

  $("#nav-analysis-tab").on("shown.bs.tab", function() {
    changeAnalysisType();
    if (analysisResult) {
      setAnalysisClock();
    }
    // pause any animation (such as the orbit preview) on entering this tab
    viewer.clock.shouldAnimate = false;
  });
  $("#nav-analysis-tab").on("hide.bs.tab", function() {
    stopMapPick();
    showAnalysisLayers(false);
    showRegion(false);
    siteSource.show = false;
  });

  onDesignChange(dropStaleAnalysis);

  changeAnalysisType();
  showRegion(false);
  siteSource.show = false;
});
