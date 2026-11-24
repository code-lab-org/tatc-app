// Analysis tab: coverage and revisit, ground track swaths, data latency with
// ground stations, and point access (overflight) analyses, with animated
// results in the Cesium viewer.

let analysisResult = null; // {type, result, taskId, payload, duration}
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
  swaths: {
    label: "Ground Track Swaths",
    description: "Ground track swaths of the checked instruments, accumulating in segments as satellites orbit. " +
      "Best for periods of hours to a few days.",
    region: false,
    targetLayer: false,
    endpoint: "/analyze/swaths"
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
  $("#analysis-data").prop("disabled", true);
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

// The display modes of coverage and latency results (in the order of their
// selects). An animated mode computes the value of each point at a time from
// the target layer, and a final mode shows a (scaled) property of each point
// and cell. `range(features)` gives the default color scale range, and
// `reverse` maps small values to the bright end (for example, short revisit
// times).
const DISPLAY_MODES = {
  coverage: [
    {
      value: "samples", label: "Observations so far (animated)", unit: "",
      range: rangeFromZero("samples"),
      pointValue: function(i, t) { return targetLayer.countStarted(i, t); }
    },
    {
      value: "since", label: "Time since last observation (animated)", unit: "h",
      reverse: true,
      range: function(features) {
        const revisits = finiteValues(features, "revisit", 1 / 3600);
        return [0, revisits.length ? Math.max(1, _.max(revisits)) : analysisResult.duration / 3600];
      },
      pointValue: function(i, t) { return targetLayer.timeSince(i, t) / 3600; }
    },
    {
      value: "revisit", label: "Mean revisit time (final)", unit: "h",
      reverse: true, property: "revisit", scale: 1 / 3600,
      range: rangeOfValues("revisit", 1 / 3600)
    },
    {
      value: "final-samples", label: "Number of observations (final)", unit: "",
      property: "samples",
      range: rangeFromZero("samples")
    }
  ],
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

// Applies the display mode of coverage or latency results.
function applyDisplayMode() {
  if (!analysisResult || !targetLayer) {
    return;
  }
  const type = analysisResult.type;
  const spec = _.find(DISPLAY_MODES[type], { value: $("#" + type + "-mode").val() });
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

// Gets the request of an analysis type, or shows an error and returns null.
function getAnalysisPayload(type, base) {
  if (type == "coverage") {
    return _.assign(base, { points: getPointsSpec(), cells: getCellsSpec() });
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
        duration: (new Date(payload.end) - new Date(payload.start)) / 1000
      };
      $("#analysis-data").prop("disabled", false);
      if (hasTargetLayer(type)) {
        targetLayer = new TargetLayer({
          points: result.points,
          cells: result.cells,
          timeline: result.timeline,
          cellTargets: result.cell_targets,
          arcType: arcType
        });
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
    { title: "Observations", key: "samples" }
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
  if (type == "coverage") {
    showResultsTable({
      title: "Coverage Statistics",
      columns: pointColumns.concat([
        { title: "Mean access (s)", key: "access_s", format: number2 },
        { title: "Mean revisit (h)", key: "revisit_h", format: number2 }
      ]),
      rows: pointRows(function(p) { return { access_s: p.access, revisit_h: hours(p.revisit) }; }),
      filename: "coverage-points",
      note: "Statistics of each point over the analysis period. Overlapping observations by several satellites count once."
    });
  } else if (type == "latency") {
    const contacts = result.contacts;
    const epoch = new Date(contacts.epoch).getTime();
    showResultsTable({
      title: "Data Latency Statistics",
      columns: pointColumns.concat([{ title: "Mean latency (h)", key: "latency_h", format: number2 }]),
      rows: pointRows(function(p) { return { latency_h: hours(p.latency) }; }),
      filename: "latency-points",
      note: contacts.start.length + " contacts with ground stations.",
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

function limitAnimation() {
  const animate = $("#analysis-animate");
  const duration = Number($("#analysis-duration").val());
  if (!(duration > 0)) {
    return;
  }
  const limit = Math.round(Math.min(MAX_ANIMATE_HOURS, duration * 24) * 1000) / 1000;
  const requested = Number(animate.data("requested") || animate.val());
  animate.attr("max", limit);
  animate.val(Math.min(requested, limit));
}

function changeAnalysisType() {
  const type = getAnalysisType();
  $(".analysis-panel").removeClass("shown");
  $(".analysis-panel[data-analysis='" + type + "']").addClass("shown");
  $(".region-panel").toggle(ANALYSES[type].region);
  $("#analysis-description").text(ANALYSES[type].description);
  $(".animate-control").toggle(type != "swaths");
  if (type == "swaths" && Number($("#analysis-duration").val()) > 3) {
    $("#analysis-duration").val(0.25);
  }
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
  $("#analysis-data").prop("disabled", !showResults);
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
    $(this).data("requested", Number($(this).val()) || null);
    limitAnimation();
  });
  $("#analysis-run").click(runSelectedAnalysis);
  $("#analysis-data").click(showAnalysisData);
  $("#coverage-mode, #latency-mode").change(function() {
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
