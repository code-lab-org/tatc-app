// Analysis tab: coverage and revisit, ground track swaths, data latency with
// ground stations, and point access (overflight) analyses, with animated
// results in the Cesium viewer.

let analysisResult = null; // {type, result, taskId, payload}
let targetLayer = null;

const ANALYSES = {
  coverage: {
    description: "Observations of a grid of points (and cells) by all instruments of all satellites. " +
      "Animates observations accumulating over the analysis period, or shows final revisit statistics.",
    region: true,
    endpoint: "/analyze/coverage"
  },
  swaths: {
    description: "Ground track swaths of an instrument, accumulating in segments as satellites orbit. " +
      "Best for periods of hours to a few days.",
    region: false,
    endpoint: "/analyze/swaths"
  },
  latency: {
    description: "Latency from the observation of each point to its downlink at a ground station. " +
      "Animates contacts with ground stations and observations awaiting downlink.",
    region: true,
    endpoint: "/analyze/latency"
  },
  access: {
    description: "Accesses of selected target points by each satellite, with lines of sight " +
      "animated during each access and a table of access windows.",
    region: false,
    endpoint: "/analyze/overflight"
  }
};

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

function getBasePayload() {
  const period = getAnalysisPeriod();
  const duration = (period.animateEnd - period.start) / 1000;
  return {
    satellites: getSatellites(),
    colors: getSatelliteColors(),
    start: period.start.toISOString(),
    end: period.end.toISOString(),
    display: {
      start: period.start.toISOString(),
      end: period.animateEnd.toISOString(),
      // at least 60 second steps, at most 20000 steps
      delta: Math.max(60, Math.ceil(duration / 19999))
    }
  };
}

function parseOptionalInteger(value) {
  return value === "" || value === null || value === undefined ? null : Math.round(Number(value));
}

// --- Layers ---

function clearAnalysisLayers() {
  if (targetLayer) {
    targetLayer.destroy();
    targetLayer = null;
  }
  clearCzmlLayer("analysis");
  hideLegend();
}

function showAnalysisLayers(show) {
  if (targetLayer) {
    targetLayer.show(show);
  }
  showCzmlLayer("analysis", show);
  $("#legend-overlay").toggle(show && !!(analysisResult && analysisResult.legend));
}

// Gets the color scale range: custom, or the default.
function getScaleRange(defaultMin, defaultMax) {
  if ($("#colorbar-custom").is(":checked")) {
    return [Number($("#colorbar-min").val()), Number($("#colorbar-max").val())];
  }
  $("#colorbar-min").val(Number(defaultMin.toPrecision(3)));
  $("#colorbar-max").val(Number(defaultMax.toPrecision(3)));
  return [defaultMin, defaultMax];
}

function finiteValues(features, property, scale) {
  return _.filter(_.map(features, function(f) {
    const value = f.properties[property];
    return value === null || value === undefined ? NaN : value * (scale || 1);
  }), isFinite);
}

// Applies the display mode of coverage or latency results.
function applyDisplayMode() {
  if (!analysisResult || !targetLayer) {
    return;
  }
  const result = analysisResult.result;
  const points = result.points.features;
  let mode, title, unit, range, reverse;
  if (analysisResult.type == "coverage") {
    const name = $("#coverage-mode").val();
    if (name == "samples") {
      const max = _.max(finiteValues(points, "samples")) || 1;
      range = getScaleRange(0, max);
      title = "Observations so far";
      unit = "";
      mode = { animated: true, pointValue: function(i, t) { return targetLayer.countStarted(i, t); } };
    } else if (name == "since") {
      const revisits = finiteValues(points, "revisit", 1 / 3600);
      range = getScaleRange(0, revisits.length ? Math.max(1, _.max(revisits)) : analysisResult.duration / 3600);
      title = "Time since last observation";
      unit = "h";
      reverse = true;
      mode = { animated: true, pointValue: function(i, t) { return targetLayer.timeSince(i, t) / 3600; } };
    } else if (name == "revisit") {
      const values = finiteValues(points, "revisit", 1 / 3600);
      range = getScaleRange(values.length ? _.min(values) : 0, values.length ? _.max(values) : 1);
      title = "Mean revisit time";
      unit = "h";
      reverse = true;
      mode = {
        animated: false,
        pointValue: function(i, t, feature) { return feature.properties.revisit === null ? NaN : feature.properties.revisit / 3600; },
        cellValue: function(c, feature) { return feature.properties.revisit === null ? NaN : feature.properties.revisit / 3600; }
      };
    } else {
      const max = _.max(finiteValues(points, "samples")) || 1;
      range = getScaleRange(0, max);
      title = "Number of observations";
      unit = "";
      mode = {
        animated: false,
        pointValue: function(i, t, feature) { return feature.properties.samples; },
        cellValue: function(c, feature) { return feature.properties.samples; }
      };
    }
  } else {
    const name = $("#latency-mode").val();
    if (name == "pending") {
      range = getScaleRange(0, Math.max(1, targetLayer.maxPending()));
      title = "Observations awaiting downlink";
      unit = "";
      reverse = true;
      mode = { animated: true, pointValue: function(i, t) { return targetLayer.countPending(i, t); } };
    } else {
      const values = finiteValues(points, "latency", 1 / 3600);
      range = getScaleRange(values.length ? _.min(values) : 0, values.length ? _.max(values) : 1);
      title = "Mean data latency";
      unit = "h";
      reverse = true;
      mode = {
        animated: false,
        pointValue: function(i, t, feature) { return feature.properties.latency === null ? NaN : feature.properties.latency / 3600; },
        cellValue: function(c, feature) { return feature.properties.latency === null ? NaN : feature.properties.latency / 3600; }
      };
    }
  }
  mode.scale = createColorScale(range[0], range[1], reverse);
  analysisResult.legend = true;
  showLegend(title, mode.scale, unit);
  targetLayer.setMode(mode);
}

// --- Running analyses ---

function runSelectedAnalysis() {
  const type = getAnalysisType();
  if (getSatellites().length == 0) {
    $("#analysis-error").text("Add a satellite or constellation in the Design tab.").show();
    return;
  }
  const base = getBasePayload();
  let payload;
  if (type == "coverage") {
    payload = _.assign(base, { points: getPointsSpec(), cells: getCellsSpec() });
  } else if (type == "swaths") {
    payload = {
      satellites: base.satellites,
      colors: base.colors,
      start: base.start,
      end: base.end,
      instrument_index: parseOptionalInteger($("#swaths-instrument").val()),
      step: Number($("#swaths-step").val()),
      segment: Number($("#swaths-segment").val()) * 60
    };
  } else if (type == "latency") {
    if (design.stations.length == 0) {
      $("#analysis-error").text("Add at least one ground station.").show();
      return;
    }
    payload = _.assign(base, {
      points: getPointsSpec(),
      cells: getCellsSpec(),
      stations: design.stations,
      during_contact: $("#latency-contact").val()
    });
  } else {
    if (design.targets.length == 0) {
      $("#analysis-error").text("Add at least one target point.").show();
      return;
    }
    payload = _.assign(base, {
      points: _.map(design.targets, function(target, i) {
        return { id: i, latitude: target.latitude, longitude: target.longitude };
      }),
      instrument_index: parseOptionalInteger($("#access-instrument").val()),
      omit_solar: !$("#access-solar").is(":checked")
    });
  }
  const endpoint = ANALYSES[type].endpoint;
  runAnalysis({
    name: "analysis",
    url: endpoint,
    payload: payload,
    resultUrl: function(taskId) { return endpoint + "/" + taskId; },
    button: $("#analysis-run"),
    progress: $("#analysis-progress"),
    error: $("#analysis-error"),
    onResult: function(result, taskId) {
      clearAnalysisLayers();
      showRegionGrid(false);
      const period = getAnalysisPeriod();
      analysisResult = {
        type: type,
        result: result,
        taskId: taskId,
        payload: payload,
        duration: (period.end - period.start) / 1000
      };
      $("#analysis-data").prop("disabled", false);
      if (type == "coverage" || type == "latency") {
        targetLayer = new TargetLayer({
          points: result.points,
          cells: result.cells,
          timeline: result.timeline,
          cellTargets: result.cell_targets
        });
        loadCzmlLayer("analysis", endpoint + "/" + taskId + "/czml", { clock: false }).then(function() {
          setClock(payload.start, payload.end);
          applyDisplayMode();
        });
        applyDisplayMode();
      } else {
        loadCzmlLayer("analysis", endpoint + "/" + taskId + "/czml");
      }
    }
  });
}

// --- Data tables ---

function formatHours(seconds) {
  return seconds === null || seconds === undefined ? "" : (seconds / 3600).toFixed(2);
}

function showAnalysisData() {
  if (!analysisResult) {
    return;
  }
  const result = analysisResult.result;
  const type = analysisResult.type;
  const number2 = function(v) { return Number(v).toFixed(2); };
  const coordinates = function(feature) {
    return {
      latitude_deg: feature.geometry.coordinates[1],
      longitude_deg: feature.geometry.coordinates[0]
    };
  };
  if (type == "coverage") {
    showResultsTable(
      "Coverage Statistics",
      [
        { title: "Target", key: "target_hash" },
        { title: "Latitude (°)", key: "latitude_deg", format: number2 },
        { title: "Longitude (°)", key: "longitude_deg", format: number2 },
        { title: "Observations", key: "samples" },
        { title: "Mean access (s)", key: "access_s", format: number2 },
        { title: "Mean revisit (h)", key: "revisit_h", format: number2 }
      ],
      _.map(result.points.features, function(feature) {
        return _.assign(coordinates(feature), {
          target_hash: feature.properties.target_hash,
          samples: feature.properties.samples,
          access_s: feature.properties.access,
          revisit_h: feature.properties.revisit === null ? null : feature.properties.revisit / 3600
        });
      }),
      "coverage-points",
      "Statistics of each point over the analysis period. Overlapping observations by several satellites count once."
    );
  } else if (type == "latency") {
    const epoch = new Date(result.contacts.epoch).getTime();
    showResultsTable(
      "Data Latency Statistics",
      [
        { title: "Target", key: "target_hash" },
        { title: "Latitude (°)", key: "latitude_deg", format: number2 },
        { title: "Longitude (°)", key: "longitude_deg", format: number2 },
        { title: "Observations", key: "samples" },
        { title: "Mean latency (h)", key: "latency_h", format: number2 }
      ],
      _.map(result.points.features, function(feature) {
        return _.assign(coordinates(feature), {
          target_hash: feature.properties.target_hash,
          samples: feature.properties.samples,
          latency_h: feature.properties.latency === null ? null : feature.properties.latency / 3600
        });
      }),
      "latency-points",
      result.contacts.start.length + " contacts with ground stations.",
      [{
        label: "Contacts CSV",
        filename: "latency-contacts.csv",
        columns: ["satellite", "ground_station", "start", "end", "duration_s"],
        rows: _.map(result.contacts.start, function(start, k) {
          const end = result.contacts.end[k];
          return [
            result.contacts.members[result.contacts.member[k]],
            result.contacts.targets[result.contacts.target[k]],
            new Date(epoch + start * 1000).toISOString(),
            end === null ? "" : new Date(epoch + end * 1000).toISOString(),
            end === null ? "" : (end - start).toFixed(1)
          ];
        })
      }]
    );
  } else if (type == "swaths") {
    showResultsTable(
      "Swath Segments",
      [
        { title: "Satellite", key: "satellite" },
        { title: "Instrument", key: "instrument" },
        { title: "Start (UTC)", key: "start" },
        { title: "End (UTC)", key: "end" }
      ],
      _.map(result.swaths.features, "properties"),
      "swath-segments",
      "Each segment appears in the animation once it ends. Download the full geometry with the API."
    );
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
    showResultsTable(
      "Point Accesses",
      columns,
      _.map(result.observations.features, function(feature) {
        const p = feature.properties;
        const index = _.indexOf(hashes, p.target_hash);
        return _.assign({}, p, {
          target: index >= 0 ? "Point " + ids[index] : p.target_hash,
          duration_s: (new Date(p.end) - new Date(p.start)) / 1000
        });
      }),
      "point-accesses",
      "Click a row to jump the animation to that access.",
      [],
      function(row) {
        const start = Cesium.JulianDate.fromIso8601(row.start);
        viewer.clock.currentTime = Cesium.JulianDate.addSeconds(start, -60, new Cesium.JulianDate());
        viewer.clock.shouldAnimate = true;
        $("#results-dialog").modal("hide");
      }
    );
  }
}

// --- Ground stations ---

let selectedStation = -1;
let stationSource = null;

function renderStations() {
  const list = $("#stations").empty();
  _.forEach(design.stations, function(station, i) {
    list.append(
      $("<a href='#'>")
        .addClass("list-group-item list-group-item-action py-1 px-2 small")
        .toggleClass("active", i == selectedStation)
        .append(
          $("<i>").addClass("fas fa-broadcast-tower mr-2"),
          $("<span>").text(station.name),
          $("<span>").addClass("ml-2 text-muted").text(
            "(" + Number(station.latitude).toFixed(2) + "°, " + Number(station.longitude).toFixed(2) + "°)"
          )
        )
        .on("click", function(e) { e.preventDefault(); selectedStation = i; renderStations(); })
        .on("dblclick", function(e) { e.preventDefault(); selectedStation = i; openStationDialog(); })
    );
  });
  $("#station-edit, #station-delete").prop("disabled", selectedStation < 0 || selectedStation >= design.stations.length);
  renderSiteEntities();
}

function openStationDialog() {
  const station = design.stations[selectedStation];
  if (!station) {
    return;
  }
  renderFields($("#station-fields"), STATION_FIELDS, station, function() {
    renderStations();
    saveDesign();
  });
  $("#station-dialog").modal("show");
}

// --- Target points ---

let selectedTarget = -1;
let pickingTargets = false;

function renderTargets() {
  const list = $("#targets").empty();
  _.forEach(design.targets, function(target, i) {
    list.append(
      $("<a href='#'>")
        .addClass("list-group-item list-group-item-action py-1 px-2 small")
        .toggleClass("active", i == selectedTarget)
        .append(
          $("<i>").addClass("fas fa-map-marker-alt mr-2"),
          $("<span>").text("Point " + i + " (" + Number(target.latitude).toFixed(3) + "°, " + Number(target.longitude).toFixed(3) + "°)")
        )
        .on("click", function(e) { e.preventDefault(); selectedTarget = i; renderTargets(); })
    );
  });
  $("#target-delete").prop("disabled", selectedTarget < 0 || selectedTarget >= design.targets.length);
  renderSiteEntities();
}

function addTarget(latitude, longitude) {
  design.targets.push({ id: design.targets.length, latitude: latitude, longitude: longitude });
  selectedTarget = design.targets.length - 1;
  renderTargets();
  saveDesign();
}

function pickTargetListener(e) {
  const rect = viewer.canvas.getBoundingClientRect();
  const position = new Cesium.Cartesian2(e.clientX - rect.left, e.clientY - rect.top);
  const cartesian = viewer.camera.pickEllipsoid(position, viewer.scene.globe.ellipsoid);
  if (cartesian) {
    const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
    addTarget(
      Number(Cesium.Math.toDegrees(cartographic.latitude).toFixed(4)),
      Number(Cesium.Math.toDegrees(cartographic.longitude).toFixed(4))
    );
  }
}

function setPickingTargets(picking) {
  pickingTargets = picking;
  $("#target-pick").toggleClass("btn-success", picking).toggleClass("btn-secondary", !picking);
  viewer.canvas.style.cursor = picking ? "crosshair" : "default";
  if (picking) {
    viewer.canvas.addEventListener("click", pickTargetListener);
  } else {
    viewer.canvas.removeEventListener("click", pickTargetListener);
  }
}

// Shows the stations (latency) or targets (access) being edited on the map.
function renderSiteEntities() {
  if (!stationSource) {
    return;
  }
  stationSource.entities.removeAll();
  const type = getAnalysisType();
  const visible = $("#nav-analysis-tab").hasClass("active")
    && !(analysisResult && analysisResult.type == type);
  stationSource.show = visible;
  if (type == "latency") {
    _.forEach(design.stations, function(station) {
      stationSource.entities.add({
        position: Cesium.Cartesian3.fromDegrees(station.longitude, station.latitude),
        point: { pixelSize: 9, color: Cesium.Color.fromCssColorString("#ffd166"), outlineColor: Cesium.Color.BLACK, outlineWidth: 1, disableDepthTestDistance: 1e12 },
        label: { text: station.name, font: "11px sans-serif", pixelOffset: new Cesium.Cartesian2(8, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT, style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineWidth: 2, disableDepthTestDistance: 1e12 }
      });
    });
  } else if (type == "access") {
    _.forEach(design.targets, function(target, i) {
      stationSource.entities.add({
        position: Cesium.Cartesian3.fromDegrees(target.longitude, target.latitude),
        point: { pixelSize: 8, color: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 1, disableDepthTestDistance: 1e12 },
        label: { text: "Point " + i, font: "11px sans-serif", pixelOffset: new Cesium.Cartesian2(8, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT, style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineWidth: 2, disableDepthTestDistance: 1e12 }
      });
    });
  }
}

// --- Panels ---

function changeAnalysisType() {
  const type = getAnalysisType();
  $(".analysis-panel").hide();
  $(".analysis-panel[data-analysis='" + type + "']").show();
  $(".region-panel").toggle(ANALYSES[type].region);
  $("#analysis-description").text(ANALYSES[type].description);
  $(".animate-control").toggle(type != "swaths");
  if (type == "swaths" && Number($("#analysis-duration").val()) > 3) {
    $("#analysis-duration").val(0.25);
  }
  if (!ANALYSES[type].region) {
    showRegionGrid(false);
    regionEntity.show = false;
  } else if (!(analysisResult && analysisResult.type == type)) {
    changeRegionType();
    if (points.length == 0) {
      generateRegionGrid();
    } else {
      showRegionGrid(true);
    }
  }
  setPickingTargets(false);
  const showResults = analysisResult && analysisResult.type == type;
  showAnalysisLayers(!!showResults);
  $("#analysis-data").prop("disabled", !showResults);
  renderSiteEntities();
}

$(document).ready(function() {
  stationSource = new Cesium.CustomDataSource("sites");
  viewer.dataSources.add(stationSource);

  const start = new Date();
  start.setUTCHours(0, 0, 0, 0);
  $("#analysis-start").val(toDateTimeInput(start));

  $("#analysis-type").change(changeAnalysisType);
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

  // stations
  $("#station-add").click(function() {
    const names = _.map(design.stations, "name");
    design.stations.push(createStation(uniqueName("Station", names)));
    selectedStation = design.stations.length - 1;
    renderStations();
    openStationDialog();
  });
  $("#station-edit").click(openStationDialog);
  $("#station-delete").click(function() {
    design.stations.splice(selectedStation, 1);
    selectedStation = Math.min(selectedStation, design.stations.length - 1);
    renderStations();
    saveDesign();
  });
  $("#station-dialog").on("hidden.bs.modal", function() {
    const station = design.stations[selectedStation];
    if (station) {
      const others = _.map(_.without(design.stations, station), "name");
      station.name = uniqueName(_.trim(station.name) || "Station", others);
    }
    renderStations();
    saveDesign();
  });

  // targets
  $("#target-pick").click(function() { setPickingTargets(!pickingTargets); });
  $("#target-add").click(function() { $("#target-dialog").modal("show"); });
  $("#target-ok").click(function() {
    addTarget(Number($("#target-latitude").val()), Number($("#target-longitude").val()));
  });
  $("#target-delete").click(function() {
    design.targets.splice(selectedTarget, 1);
    selectedTarget = Math.min(selectedTarget, design.targets.length - 1);
    renderTargets();
    saveDesign();
  });

  $("#nav-analysis-tab").on("shown.bs.tab", function() {
    changeAnalysisType();
    if (analysisResult) {
      const payload = analysisResult.payload;
      const source = getCzmlLayer("analysis");
      if (analysisResult.type == "coverage" || analysisResult.type == "latency") {
        setClock(payload.start, payload.end);
      } else if (source) {
        setClock(source.clock.startTime, source.clock.stopTime, source.clock.multiplier);
      }
    }
    // pause any animation (such as the orbit preview) on entering this tab
    viewer.clock.shouldAnimate = false;
  });
  $("#nav-analysis-tab").on("hide.bs.tab", function() {
    showAnalysisLayers(false);
    showRegionGrid(false);
    regionEntity.show = false;
    setPickingTargets(false);
    stationSource.show = false;
  });

  renderStations();
  renderTargets();
  changeAnalysisType();
  showRegionGrid(false);
  regionEntity.show = false;
  stationSource.show = false;
});
