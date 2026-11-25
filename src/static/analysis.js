// Analysis tab: coverage and revisit, ground track swaths, data latency with
// ground stations, and point access (overflight) analyses, with animated
// results in the Cesium viewer.

let analysisResult = null; // {type, result, taskId, payload, design, duration}
let targetLayer = null;

// The analyses (in the order of the analysis select): whether each analyzes
// the points (and cells) of the region, and whether it shows its results with
// a layer of targets (points and cells colored by a metric, see
// `DISPLAY_MODES`).
const ANALYSES = {
  coverage: {
    label: "Coverage and Revisit",
    description: "Observations of a grid of points (and cells) by the checked instruments of the checked satellites. " +
      "Animates observations accumulating over the analysis period, or shows final revisit statistics.",
    region: true,
    targetLayer: true,
    endpoint: "/analyze/coverage"
  },
  coincidence: {
    label: "Coincident Observations",
    description: "Periods when several of the checked satellites (or satellites and constellations) observe a point of the grid at once, " +
      "as for cross-calibration or multi-sensor matchups. Animates coincidences accumulating, or shows final statistics.",
    region: true,
    targetLayer: true,
    endpoint: "/analyze/coincidence"
  },
  swaths: {
    label: "Ground Track Swaths",
    description: "Ground track swaths of the checked instruments, accumulating in segments as satellites orbit. " +
      "Best for periods of hours to a few days.",
    region: false,
    targetLayer: false,
    endpoint: "/analyze/swaths"
  },
  region: {
    label: "Swath Coverage of a Region",
    description: "Swaths of the checked instruments over the region, sampled every step: the share of its area observed over time, " +
      "its observations and revisit, and optionally the areas several satellites observe in common within a time difference.",
    region: true,
    targetLayer: false,
    endpoint: "/analyze/region"
  },
  latency: {
    label: "Data Latency (Ground Stations)",
    description: "Latency from the observation of each point to its downlink at a ground station. " +
      "Animates contacts with ground stations and observations awaiting downlink.",
    region: true,
    targetLayer: true,
    endpoint: "/analyze/latency"
  },
  access: {
    label: "Point Access (Overflight)",
    description: "Accesses of selected target points by each satellite, with lines of sight " +
      "animated during each access and a table of access windows.",
    region: false,
    targetLayer: false,
    endpoint: "/analyze/overflight"
  }
};

function hasTargetLayer(type) {
  return ANALYSES[type].targetLayer;
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

// Gets the options of sampling sufficiency of a coverage analysis: null if
// not assessed, or (showing an error) undefined if invalid.
function getSufficiencySpec() {
  if (!$("#sufficiency-enabled").is(":checked")) {
    return null;
  }
  const optional = function(selector) {
    const text = String($(selector).val()).trim();
    return text === "" ? null : Number(text);
  };
  const decorrelation = Number($("#sufficiency-decorrelation").val()) *
    Number($("#sufficiency-decorrelation-unit").val());
  const sigma = optional("#sufficiency-sigma");
  const target = optional("#sufficiency-target");
  const bins = Number($("#sufficiency-bins").val());
  let error = null;
  if (!(decorrelation > 0)) {
    error = "The decorrelation time must be positive.";
  } else if (sigma !== null && !(sigma > 0)) {
    error = "The field's standard deviation must be positive (or blank).";
  } else if (target !== null && !(target > 0)) {
    error = "The target error must be positive (or blank).";
  } else if (!(Number.isInteger(bins) && bins >= 1 && bins <= 24)) {
    error = "The number of local-time bins must be a whole number from 1 to 24.";
  }
  if (error) {
    $("#analysis-error").text(error).show();
    return undefined;
  }
  return {
    decorrelation_time: decorrelation,
    standard_deviation: sigma,
    target_relative_error: target === null ? null : target / 100,
    local_time_bins: bins
  };
}

// Sets the inputs of sampling sufficiency from the options of a coverage
// request (none to turn it off).
function setSufficiencyInputs(sufficiency) {
  $("#sufficiency-enabled").prop("checked", Boolean(sufficiency));
  $("#sufficiency-options").toggle(Boolean(sufficiency));
  if (!sufficiency) {
    return;
  }
  const seconds = Number(sufficiency.decorrelation_time);
  if (seconds > 0) {
    const unit = seconds >= 86400 && seconds % 86400 == 0 ? 86400 : 3600;
    $("#sufficiency-decorrelation-unit").val(String(unit));
    $("#sufficiency-decorrelation").val(Number((seconds / unit).toFixed(6)));
  }
  const sigma = sufficiency.standard_deviation;
  $("#sufficiency-sigma").val(sigma === null || sigma === undefined ? "" : sigma);
  const target = sufficiency.target_relative_error;
  $("#sufficiency-target").val(target === null || target === undefined ? "" : Number((100 * target).toFixed(6)));
  if (sufficiency.local_time_bins) {
    $("#sufficiency-bins").val(sufficiency.local_time_bins);
  }
}

// Gets the options of ground sample sizes of a coverage (or coincidence)
// analysis: null if not sized, or (showing an error) undefined if invalid.
function getSampleSizeSpec() {
  if (!$("#sample-size-enabled").is(":checked")) {
    return null;
  }
  const text = String($("#sample-size-max").val()).trim();
  const km = text === "" ? null : Number(text);
  if (km !== null && !(km > 0)) {
    $("#analysis-error").text("The maximum sample size must be positive (or blank).").show();
    return undefined;
  }
  return { max_sample_size: km === null ? null : km * 1000 };
}

// Sets the inputs of ground sample sizes from the options of a request (none
// to turn them off).
function setSampleSizeInputs(sampleSize) {
  $("#sample-size-enabled").prop("checked", Boolean(sampleSize));
  $("#sample-size-options").toggle(Boolean(sampleSize));
  const max = sampleSize && sampleSize.max_sample_size;
  $("#sample-size-max").val(max ? Number((max / 1000).toFixed(6)) : "");
}

// Gets the options of a coincidence analysis, or (showing an error)
// undefined if invalid.
function getCoincidenceSpec() {
  const minPlatforms = Number($("#coincidence-min").val());
  const minutes = Number($("#coincidence-difference").val());
  if (!(Number.isInteger(minPlatforms) && minPlatforms >= 2 && minPlatforms <= 20)) {
    $("#analysis-error").text("The number of platforms at once must be a whole number from 2 to 20.").show();
    return undefined;
  }
  if (!(minutes >= 0)) {
    $("#analysis-error").text("The maximum time difference must not be negative.").show();
    return undefined;
  }
  return {
    min_platforms: minPlatforms,
    max_time_difference: minutes * 60,
    instantaneous: $("#coincidence-instantaneous").is(":checked"),
    platforms: $("#coincidence-platforms").val()
  };
}

// Sets the inputs of a coincidence analysis from its request.
function setCoincidenceInputs(request) {
  $("#coincidence-min").val(request.min_platforms || 2);
  $("#coincidence-difference").val(Number(((request.max_time_difference || 0) / 60).toFixed(6)));
  $("#coincidence-instantaneous").prop("checked", Boolean(request.instantaneous));
  $("#coincidence-platforms").val(request.platforms || "members");
}

// Gets the request of an analysis type, or shows an error and returns null.
function getAnalysisPayload(type, base) {
  if (type == "coverage") {
    const sufficiency = getSufficiencySpec();
    const sampleSize = getSampleSizeSpec();
    if (sufficiency === undefined || sampleSize === undefined) {
      return null;
    }
    return _.assign(base, {
      points: getPointsSpec(),
      cells: getCellsSpec(),
      sufficiency: sufficiency,
      sample_size: sampleSize
    });
  } else if (type == "coincidence") {
    const sufficiency = getSufficiencySpec();
    const sampleSize = getSampleSizeSpec();
    const coincidence = getCoincidenceSpec();
    if (sufficiency === undefined || sampleSize === undefined || coincidence === undefined) {
      return null;
    }
    return _.assign(base, coincidence, {
      points: getPointsSpec(),
      cells: getCellsSpec(),
      sufficiency: sufficiency,
      sample_size: sampleSize
    });
  } else if (type == "region") {
    const step = Number($("#region-step").val());
    const segment = Number($("#region-segment").val());
    if (!(step > 0) || !(segment > 0)) {
      $("#analysis-error").text("The step and segment must be positive.").show();
      return null;
    }
    let coincidence = null;
    if ($("#region-coincidence-enabled").is(":checked")) {
      const minutes = Number($("#region-coincidence-difference").val());
      if (!(minutes >= 0)) {
        $("#analysis-error").text("The maximum time difference must not be negative.").show();
        return null;
      }
      coincidence = {
        max_time_difference: minutes * 60,
        platforms: $("#region-coincidence-platforms").val()
      };
    }
    // footprints are sampled every step over the analysis period
    return _.assign(_.omit(base, "display"), {
      region: getRegionMask(),
      instrument_index: null,
      step: step,
      segment: segment * 60,
      coincidence: coincidence
    });
  } else if (type == "swaths") {
    // swaths animate over the analysis period
    return _.assign(_.omit(base, "display"), {
      instrument_index: null,
      step: Number($("#swaths-step").val()),
      segment: Number($("#swaths-segment").val()) * 60
    });
  } else if (type == "latency") {
    if (design.stations.length == 0) {
      $("#analysis-error").text("Add at least one ground station.").show();
      return null;
    }
    return _.assign(base, {
      points: getPointsSpec(),
      cells: getCellsSpec(),
      stations: design.stations,
      during_contact: $("#latency-contact").val()
    });
  } else if (type == "access") {
    if (design.targets.length == 0) {
      $("#analysis-error").text("Add at least one target point.").show();
      return null;
    }
    return _.assign(base, {
      points: _.map(design.targets, function(target, i) {
        return { id: i, latitude: target.latitude, longitude: target.longitude };
      }),
      omit_solar: !$("#access-solar").is(":checked")
    });
  }
  throw new Error("Unknown analysis type: " + type);
}

function runSelectedAnalysis() {
  const type = getAnalysisType();
  if (getSatellites().length == 0) {
    $("#analysis-error").text("Add a satellite or constellation in the Design tab.").show();
    return;
  }
  const inputs = getFilteredInputs();
  if (inputs.satellites.length == 0) {
    $("#analysis-error").text("Check at least one satellite and instrument to analyze.").show();
    return;
  }
  const payload = getAnalysisPayload(type, getBasePayload(inputs));
  if (!payload) {
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
        $("#analysis-error").text("A satellite of this analysis was removed from the design. Run the analysis again.").show();
        return;
      }
      clearAnalysisLayers();
      showRegionGrid(false);
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
  const result = analysisResult.result;
  const type = analysisResult.type;
  const number2 = function(v) { return Number(v).toFixed(2); };
  // columns and values shared by the statistics of points
  const pointColumns = [
    { title: "Target", key: "target_hash" },
    { title: "Latitude (°)", key: "latitude_deg", format: number2 },
    { title: "Longitude (°)", key: "longitude_deg", format: number2 },
    { title: (COVERAGE_TERMS[type] || COVERAGE_TERMS.coverage).samples, key: "samples" }
  ];
  const hours = function(seconds) { return seconds === null ? null : seconds / 3600; };
  const pointRows = function(values) {
    return _.map(result.points.features, function(feature) {
      return _.assign({
        target_hash: feature.properties.target_hash,
        latitude_deg: feature.geometry.coordinates[1],
        longitude_deg: feature.geometry.coordinates[0],
        samples: feature.properties.samples
      }, values(feature.properties));
    });
  };
  if (type == "coverage" || type == "coincidence") {
    const terms = COVERAGE_TERMS[type];
    const coincidence = type == "coincidence";
    const sufficiency = result.summary && result.summary.sufficiency;
    const sampleSize = result.summary && result.summary.sample_size;
    const percent = function(share) { return share === null || share === undefined ? null : 100 * share; };
    const km = function(meters) { return meters === null || meters === undefined ? null : meters / 1000; };
    let columns = pointColumns.concat([
      { title: coincidence ? "Mean coincidence duration (s)" : "Mean access (s)", key: "access_s", format: number2 },
      { title: terms.revisitAxis + " (h)", key: "revisit_h", format: number2 }
    ]);
    if (sufficiency) {
      columns = columns.concat(
        [{ title: "Sampling error (% of σ)", key: "relative_error_pct", format: number2 }],
        sufficiency.standard_deviation ? [{ title: "Sampling error", key: "sampling_error", format: number2 }] : [],
        [
          { title: "Effective samples", key: "effective_samples", format: number2 },
          { title: "Median time between samples (h)", key: "revisit_p50_h", format: number2 },
          { title: "90th pct. time between samples (h)", key: "revisit_p90_h", format: number2 },
          { title: "Longest gap (h)", key: "max_gap_h", format: number2 },
          { title: "Local-time coverage (%)", key: "local_time_pct", format: number2 }
        ]
      );
    }
    if (sampleSize) {
      columns = columns.concat(
        [
          { title: "Median sample size (km)", key: "sample_size_median_km", format: number2 },
          { title: "Smallest sample size (km)", key: "sample_size_min_km", format: number2 },
          { title: "Observations sized", key: "observations_sized" }
        ],
        sampleSize.max_sample_size
          ? [{ title: "Observations at most " + formatValue(sampleSize.max_sample_size / 1000) + " km", key: "observations_meeting" }]
          : []
      );
    }
    showResultsTable({
      title: coincidence ? "Coincidence Statistics" : "Coverage Statistics",
      columns: columns,
      rows: pointRows(function(p) {
        return _.assign({ access_s: p.access, revisit_h: hours(p.revisit) }, sufficiency ? {
          relative_error_pct: percent(p.relative_error),
          sampling_error: p.sampling_error,
          effective_samples: p.effective_samples,
          revisit_p50_h: hours(p.revisit_p50),
          revisit_p90_h: hours(p.revisit_p90),
          max_gap_h: hours(p.max_gap),
          local_time_pct: percent(p.local_time_coverage)
        } : {}, sampleSize ? {
          sample_size_median_km: km(p.sample_size_median),
          sample_size_min_km: km(p.sample_size_min),
          observations_sized: p.observations_sized,
          observations_meeting: p.observations_meeting
        } : {});
      }),
      filename: type + "-points",
      note: (coincidence
        ? "Statistics of the coincident observations of each point over the analysis period: periods when enough platforms observe it at once."
        : "Statistics of each point over the analysis period. Overlapping observations by several satellites count once.") +
        (sufficiency ? " " + terms.revisitAxis + " runs from the end of one to the start of the next; times between samples run between their midpoints." : ""),
      summary: result.summary ? function(container) { renderCoverageSummary(container, result.summary, terms); } : null
    });
  } else if (type == "latency") {
    const contacts = result.contacts;
    const epoch = new Date(contacts.epoch).getTime();
    showResultsTable({
      title: "Data Latency Statistics",
      columns: pointColumns.concat([{ title: "Mean latency (h)", key: "latency_h", format: number2 }]),
      rows: pointRows(function(p) { return { latency_h: hours(p.latency) }; }),
      filename: "latency-points",
      note: "Statistics of each point over the analysis period.",
      summary: result.summary ? function(container) { renderLatencySummary(container, result.summary); } : null,
      extras: [{
        label: "Contacts CSV",
        filename: "latency-contacts.csv",
        columns: ["satellite", "ground_station", "start", "end", "duration_s"],
        rows: _.map(contacts.start, function(start, k) {
          const end = contacts.end[k];
          return [
            contacts.members[contacts.member[k]],
            contacts.targets[contacts.target[k]],
            new Date(epoch + start * 1000).toISOString(),
            end === null ? "" : new Date(epoch + end * 1000).toISOString(),
            end === null ? "" : (end - start).toFixed(1)
          ];
        })
      }]
    });
  } else if (type == "region") {
    const epoch = new Date(analysisResult.payload.start).getTime();
    const iso = function(seconds) { return new Date(epoch + seconds * 1000).toISOString(); };
    showResultsTable({
      title: "Observations of the Region",
      columns: [
        { title: "Satellites", key: "satellite" },
        { title: "Instruments", key: "instrument" },
        { title: "Start (UTC)", key: "start_utc" },
        { title: "End (UTC)", key: "end_utc" },
        { title: "Duration (min)", key: "duration_min", format: number2 }
      ],
      rows: _.map(result.observations, function(o) {
        return {
          satellite: o.satellite,
          instrument: o.instrument,
          start_utc: iso(o.start),
          end_utc: iso(o.end),
          duration_min: (o.end - o.start) / 60
        };
      }),
      filename: "region-observations",
      note: "Periods when any part of the region is observed (overlapping observations merged). Click a row to jump the animation to it.",
      summary: function(container) { renderRegionSummary(container, result.summary); },
      onRowClick: function(row) {
        viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(row.start_utc);
        viewer.clock.shouldAnimate = true;
        $("#results-dialog").modal("hide");
      }
    });
  } else if (type == "swaths") {
    showResultsTable({
      title: "Swath Segments",
      columns: [
        { title: "Satellite", key: "satellite" },
        { title: "Instrument", key: "instrument" },
        { title: "Start (UTC)", key: "start" },
        { title: "End (UTC)", key: "end" }
      ],
      rows: _.map(result.swaths.features, "properties"),
      filename: "swath-segments",
      note: "Each segment appears in the animation once it ends. Download the full geometry with the API."
    });
  } else {
    const ids = _.map(result.points.features, function(f) { return f.properties.id; });
    const hashes = _.map(result.points.features, function(f) { return f.properties.point_id; });
    const columns = [
      { title: "Target", key: "target" },
      { title: "Satellite", key: "satellite" },
      { title: "Instrument", key: "instrument" },
      { title: "Start (UTC)", key: "start" },
      { title: "End (UTC)", key: "end" },
      { title: "Duration (s)", key: "duration_s", format: number2 },
      { title: "Max. elevation (°)", key: "platform_alt", format: number2 }
    ];
    if (!analysisResult.payload.omit_solar) {
      columns.push({ title: "Solar elevation (°)", key: "solar_alt", format: number2 });
    }
    showResultsTable({
      title: "Point Accesses",
      columns: columns,
      rows: _.map(result.observations.features, function(feature) {
        const p = feature.properties;
        const index = _.indexOf(hashes, p.target_hash);
        return _.assign({}, p, {
          target: index >= 0 ? "Point " + ids[index] : p.target_hash,
          duration_s: (new Date(p.end) - new Date(p.start)) / 1000
        });
      }),
      filename: "point-accesses",
      note: "Click a row to jump the animation to that access.",
      onRowClick: function(row) {
        const start = Cesium.JulianDate.fromIso8601(row.start);
        viewer.clock.currentTime = Cesium.JulianDate.addSeconds(start, -60, new Cesium.JulianDate());
        viewer.clock.shouldAnimate = true;
        $("#results-dialog").modal("hide");
      }
    });
  }
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

// The swaths analysis suits short periods, so selecting it shortens a long
// duration; the duration it replaced returns on selecting another analysis
// (unless edited meanwhile).
const SWATHS_MAX_DAYS = 3;
const SWATHS_DEFAULT_DAYS = 0.25;
let durationBeforeSwaths = null; // days

function adjustDurationForType(type) {
  const input = $("#analysis-duration");
  if (type == "swaths") {
    if (Number(input.val()) > SWATHS_MAX_DAYS) {
      durationBeforeSwaths = input.val();
      input.val(SWATHS_DEFAULT_DAYS);
    }
  } else if (durationBeforeSwaths !== null) {
    input.val(durationBeforeSwaths);
    durationBeforeSwaths = null;
  }
}

function changeAnalysisType() {
  const type = getAnalysisType();
  $(".analysis-panel").removeClass("shown");
  $(".analysis-panel[data-analysis~='" + type + "']").addClass("shown");
  $(".region-panel").toggle(ANALYSES[type].region);
  $("#analysis-description").text(ANALYSES[type].description);
  $(".animate-control").toggle(type != "swaths" && type != "region");
  adjustDurationForType(type);
  limitAnimation();
  // picking (region vertices or target points) applies to one analysis type
  stopMapPick();
  const showResults = Boolean(analysisResult && analysisResult.type == type);
  // the region shows while editing it (not over its results)
  if (!ANALYSES[type].region) {
    showRegion(false);
  } else if (!showResults) {
    showRegion(true);
  }
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
  $("#analysis-duration").change(function() {
    // an edited duration stays on leaving the swaths analysis
    durationBeforeSwaths = null;
    limitAnimation();
  });
  $("#analysis-animate").change(function() {
    const value = Number($(this).val());
    if (value > 0) {
      requestedAnimate = value;
    }
    limitAnimation();
  });
  $("#region-coincidence-enabled").change(function() {
    $("#region-coincidence-options").toggle($(this).is(":checked"));
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
