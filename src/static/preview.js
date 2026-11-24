// Design tab: orbit preview of satellites and constellations (orbit tracks
// and instrument footprints of all member satellites, animated from a CZML
// document). The preview computes all satellites and instruments, and shows
// those checked in the shared filter (see filter.js) with the paths and
// footprints chosen in the display panel (see display.js).

let previewResult = null;
// satellites and constellations of the preview: [{name, members: [{name,
// instruments}]}]
let previewLayers = null;

function getPreviewWindow() {
  const start = fromDateTimeInput($("#display-start").val());
  const end = new Date(start.getTime() + Number($("#display-duration").val()) * 60e3);
  return { start: start, end: end, step: Number($("#display-step").val()) };
}

function applyPreviewDisplayOptions() {
  const source = getCzmlLayer("design");
  if (!source) {
    return;
  }
  const path = isPathShown();
  const footprint = isFootprintShown();
  _.forEach(previewLayers, function(system) {
    const systemShown = isFilterChecked(filterKey("sys", system.name));
    _.forEach(system.members, function(member) {
      const shown = systemShown && isFilterChecked(filterKey("sat", system.name, member.name));
      const satellite = source.entities.getById("sat/" + member.name);
      if (satellite) {
        satellite.show = shown;
        if (satellite.path) { satellite.path.show = path; }
      }
      for (let i = 0; i < member.instruments; i++) {
        const entity = source.entities.getById("fp/" + member.name + "/" + i);
        if (entity) {
          entity.show = shown && footprint && isFilterChecked(filterKey("ins", system.name, i));
        }
      }
    });
  });
}

// Whether an instrument has a footprint in a preview: a circle (ellipse)
// or, for footprints computed by TAT-C, polygons (child entities, `<id>/0`).
function hasFootprint(source, id) {
  const entity = source.entities.getById(id);
  const part = source.entities.getById(id + "/0");
  return Boolean((entity && entity.ellipse) || (part && part.polygon));
}

// Groups the member tracks of a preview result by satellite or constellation
// (`systems` lists the names of the requested satellites and constellations,
// and `result.systems` the index of each member's), and marks instruments
// without a footprint in the filter.
function buildPreviewLayers(result, systems, source) {
  const groups = _.map(systems, function(name) { return { name: name, members: [] }; });
  const withFootprint = {};
  _.forEach(result.tracks.tracks, function(track) {
    const group = groups[result.systems[track.name]];
    group.members.push({ name: track.name, instruments: track.instruments.length });
    _.forEach(track.instruments, function(instrument, i) {
      const insKey = filterKey("ins", group.name, i);
      withFootprint[insKey] = withFootprint[insKey] || hasFootprint(source, "fp/" + track.name + "/" + i);
    });
  });
  setFilterWithoutFootprint(_.filter(_.keys(withFootprint), function(k) { return !withFootprint[k]; }));
  return _.filter(groups, function(group) { return group.members.length > 0; });
}

function previewOrbits() {
  const satellites = getSatellites();
  if (satellites.length == 0) {
    // drop any run in progress, so its results do not show
    cancelAnalysis("design");
    clearCzmlLayer("design");
    previewResult = null;
    previewLayers = null;
    $("#orbit-data").prop("disabled", true);
    return;
  }
  const systems = _.map(satellites, "name");
  const period = getPreviewWindow();
  runAnalysis({
    name: "design",
    url: "/analyze/swaths",
    payload: {
      satellites: satellites,
      colors: getSatelliteColors(),
      instrumentColors: getInstrumentColors(),
      start: period.start.toISOString(),
      end: period.end.toISOString(),
      step: period.step,
      segment: null
    },
    button: $("#orbit-analyze"),
    progress: $("#orbit-progress"),
    error: $("#orbit-error"),
    onResult: function(result, taskId) {
      previewResult = result;
      $("#orbit-data").prop("disabled", false);
      loadCzmlLayer("design", "/analyze/swaths/" + taskId + "/czml").then(function(source) {
        source.show = $("#nav-design-tab").hasClass("active");
        previewLayers = buildPreviewLayers(result, systems, source);
        applyPreviewDisplayOptions();
      });
    }
  });
}

function showPreviewData() {
  if (!previewResult) {
    return;
  }
  const tracks = previewResult.tracks;
  const epoch = new Date(tracks.epoch).getTime();
  const rows = [];
  _.forEach(tracks.tracks, function(track) {
    // positions are [t, longitude, latitude, altitude] samples, and swath
    // widths [t, width] samples at the same times
    for (let i = 0; i < track.positions.length; i += 4) {
      _.forEach(track.instruments, function(instrument) {
        rows.push({
          time: new Date(epoch + track.positions[i] * 1000).toISOString(),
          satellite: track.name,
          instrument: instrument.name,
          longitude_deg: track.positions[i + 1],
          latitude_deg: track.positions[i + 2],
          altitude_km: track.positions[i + 3] / 1000,
          swath_width_km: instrument.swath_widths[(i / 4) * 2 + 1] / 1000
        });
      });
    }
  });
  showResultsTable({
    title: "Orbit Tracks",
    columns: [
      { title: "Time (UTC)", key: "time" },
      { title: "Satellite", key: "satellite" },
      { title: "Instrument", key: "instrument" },
      { title: "Latitude (°)", key: "latitude_deg", format: function(v) { return v.toFixed(4); } },
      { title: "Longitude (°)", key: "longitude_deg", format: function(v) { return v.toFixed(4); } },
      { title: "Altitude (km)", key: "altitude_km", format: function(v) { return v.toFixed(2); } },
      { title: "Swath width (km)", key: "swath_width_km", format: function(v) { return v.toFixed(1); } }
    ],
    rows: rows,
    filename: "orbit-tracks",
    note: "Swath width spans the field of regard of each instrument."
  });
}

$(document).ready(function() {
  const start = new Date();
  start.setUTCMinutes(0, 0, 0);
  $("#display-start").val(toDateTimeInput(start));

  $("#display-path, #display-footprint").change(applyPreviewDisplayOptions);
  $("#orbit-analyze").click(previewOrbits);
  $("#orbit-data").click(showPreviewData);
  onLayerFilterChange(applyPreviewDisplayOptions);
  $("#display-start, #display-duration, #display-step").on("change", function() {
    if ($("#nav-design-tab").hasClass("active")) {
      previewOrbits();
    }
  });
  onDesignChange(_.debounce(function() {
    if ($("#nav-design-tab").hasClass("active")) {
      previewOrbits();
    }
  }, 300));
  // clock time of the orbit preview when leaving this tab, to resume from it
  let pausedPreview = null;
  $("#nav-design-tab").on("shown.bs.tab", function() {
    const source = getCzmlLayer("design");
    if (source) {
      showCzmlLayer("design", true);
      setClock(source.clock.startTime, source.clock.stopTime, source.clock.multiplier);
      if (pausedPreview && pausedPreview.source === source) {
        viewer.clock.currentTime = pausedPreview.time;
      }
    } else {
      previewOrbits();
    }
    pausedPreview = null;
  });
  $("#nav-design-tab").on("hide.bs.tab", function() {
    const source = getCzmlLayer("design");
    pausedPreview = source ? { source: source, time: viewer.clock.currentTime.clone() } : null;
    showCzmlLayer("design", false);
  });
});
