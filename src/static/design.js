// Design tab: orbit preview of satellites and constellations (orbit tracks
// and footprints of all member satellites, animated from a CZML document).

function icrf(scene, time) {
  if (scene.mode !== Cesium.SceneMode.SCENE3D) {
    return;
  }
  const icrfToFixed = Cesium.Transforms.computeIcrfToFixedMatrix(time);
  if (Cesium.defined(icrfToFixed)) {
    const camera = viewer.camera;
    const offset = Cesium.Cartesian3.clone(camera.position);
    const transform = Cesium.Matrix4.fromRotationTranslation(icrfToFixed);
    camera.lookAtTransform(transform, offset);
  }
}

let previewResult = null;

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
  const path = $("#display-path").is(":checked");
  const footprint = $("#display-footprint").is(":checked");
  _.forEach(source.entities.values, function(entity) {
    if (entity.path) { entity.path.show = path; }
    if (entity.ellipse) { entity.ellipse.show = footprint; }
  });
}

function previewOrbits() {
  const satellites = getSatellites();
  if (satellites.length == 0) {
    clearCzmlLayer("design");
    return;
  }
  const period = getPreviewWindow();
  runAnalysis({
    name: "design",
    url: "/analyze/swaths",
    payload: {
      satellites: satellites,
      colors: getSatelliteColors(),
      start: period.start.toISOString(),
      end: period.end.toISOString(),
      step: period.step,
      segment: null
    },
    resultUrl: function(taskId) { return "/analyze/swaths/" + taskId; },
    button: $("#orbit-analyze"),
    progress: $("#orbit-progress"),
    error: $("#orbit-error"),
    onResult: function(result, taskId) {
      previewResult = result;
      $("#orbit-data").prop("disabled", false);
      loadCzmlLayer("design", "/analyze/swaths/" + taskId + "/czml").then(function(source) {
        source.show = $("#nav-design-tab").hasClass("active");
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
    for (let i = 0; i < track.positions.length; i += 4) {
      rows.push({
        time: new Date(epoch + track.positions[i] * 1000).toISOString(),
        satellite: track.name,
        longitude_deg: track.positions[i + 1],
        latitude_deg: track.positions[i + 2],
        altitude_km: track.positions[i + 3] / 1000,
        swath_width_km: track.swath_widths[(i / 4) * 2 + 1] / 1000
      });
    }
  });
  showResultsTable(
    "Orbit Tracks",
    [
      { title: "Time (UTC)", key: "time" },
      { title: "Satellite", key: "satellite" },
      { title: "Latitude (°)", key: "latitude_deg", format: function(v) { return v.toFixed(4); } },
      { title: "Longitude (°)", key: "longitude_deg", format: function(v) { return v.toFixed(4); } },
      { title: "Altitude (km)", key: "altitude_km", format: function(v) { return v.toFixed(2); } },
      { title: "Swath width (km)", key: "swath_width_km", format: function(v) { return v.toFixed(1); } }
    ],
    rows,
    "orbit-tracks",
    "Swath width spans the field of regard of each satellite's first instrument."
  );
}

$(document).ready(function() {
  const start = new Date();
  start.setUTCMinutes(0, 0, 0);
  $("#display-start").val(toDateTimeInput(start));

  $("#display-observer").change(function() {
    if ($(this).val() == "inertial") {
      viewer.scene.postUpdate.addEventListener(icrf);
    } else {
      viewer.scene.postUpdate.removeEventListener(icrf);
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    }
  });
  $("#display-path, #display-footprint").change(applyPreviewDisplayOptions);
  $("#display-lighting").change(function() {
    viewer.scene.globe.enableLighting = $(this).is(":checked");
  });
  $("#orbit-analyze").click(previewOrbits);
  $("#orbit-data").click(showPreviewData);
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
  $("#nav-design-tab").on("shown.bs.tab", function() {
    if (getCzmlLayer("design")) {
      showCzmlLayer("design", true);
      const source = getCzmlLayer("design");
      setClock(source.clock.startTime, source.clock.stopTime, source.clock.multiplier);
    } else {
      previewOrbits();
    }
  });
  $("#nav-design-tab").on("hide.bs.tab", function() {
    showCzmlLayer("design", false);
  });
});
