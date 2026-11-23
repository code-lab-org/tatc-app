// Design tab: orbit preview of satellites and constellations (orbit tracks
// and instrument footprints of all member satellites, animated from a CZML
// document), with a list to filter the displayed satellites and instruments.

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
// satellites and constellations of the preview: [{name, color, instruments:
// [{name, color}], members: [{name, instruments}]}]
let previewLayers = null;
// layers hidden by the user (by key, see `layerKey`), kept across previews
const previewHidden = {};
// names of constellations with an expanded member list
const previewExpanded = {};
let previewLayerCount = 0;

function layerKey(kind, system, detail) {
  return kind + ":" + system + (detail === undefined ? "" : "/" + detail);
}

function isLayerShown(key) {
  return !previewHidden[key];
}

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
  _.forEach(previewLayers, function(system) {
    const systemShown = isLayerShown(layerKey("sys", system.name));
    _.forEach(system.members, function(member) {
      const shown = systemShown && isLayerShown(layerKey("sat", system.name, member.name));
      const satellite = source.entities.getById("sat/" + member.name);
      if (satellite) {
        satellite.show = shown;
        if (satellite.path) { satellite.path.show = path; }
      }
      for (let i = 0; i < member.instruments; i++) {
        const entity = source.entities.getById("fp/" + member.name + "/" + i);
        if (entity) {
          entity.show = shown && footprint && isLayerShown(layerKey("ins", system.name, i));
        }
      }
    });
  });
}

// Gets the (opaque) CSS color of an entity's footprint, if any: a circle
// (ellipse) or, for footprints computed by TAT-C, the polygon of its first
// part (a child entity, `<id>/0`).
function getFootprintColor(source, id) {
  const entity = source.entities.getById(id);
  const part = source.entities.getById(id + "/0");
  const graphics = (entity && entity.ellipse) || (part && part.polygon);
  if (!graphics || !graphics.material) {
    return null;
  }
  const color = graphics.material.color.getValue(viewer.clock.currentTime);
  return color ? color.withAlpha(1).toCssColorString() : null;
}

// Groups the member tracks of a preview result by satellite or constellation
// (`systems` lists the names of the requested satellites and constellations).
function buildPreviewLayers(result, systems, source) {
  const groups = [];
  _.forEach(result.tracks.tracks, function(track) {
    const index = result.systems ? result.systems[track.name] : undefined;
    const key = index === undefined ? "member:" + track.name : index;
    let group = _.find(groups, { key: key });
    if (!group) {
      group = {
        key: key,
        name: index === undefined || !systems[index] ? track.name : systems[index],
        color: result.colors[track.name],
        instruments: _.map(track.instruments, function(instrument) {
          return { name: instrument.name, color: null };
        }),
        members: []
      };
      groups.push(group);
    }
    group.members.push({ name: track.name, instruments: track.instruments.length });
    _.forEach(group.instruments, function(instrument, i) {
      instrument.color = instrument.color || getFootprintColor(source, "fp/" + track.name + "/" + i);
    });
  });
  return groups;
}

function createLayerToggle(key, label, swatch, title, onChange) {
  const id = "preview-layer-" + (previewLayerCount++);
  return $("<div>").addClass("form-check form-check-inline mr-2").attr("title", title || null).append(
    $("<input type='checkbox'>").addClass("form-check-input").attr("id", id)
      .prop("checked", isLayerShown(key))
      .on("change", function() {
        if (this.checked) {
          delete previewHidden[key];
        } else {
          previewHidden[key] = true;
        }
        if (onChange) { onChange(this.checked); }
        applyPreviewDisplayOptions();
      }),
    $("<label>").addClass("form-check-label").attr("for", id).append(swatch, $("<span>").text(label))
  );
}

function renderPreviewLayers() {
  const list = $("#preview-layers-list").empty();
  if (!previewLayers || previewLayers.length == 0) {
    $("#preview-layers").hide();
    return;
  }
  _.forEach(previewLayers, function(system) {
    const details = $("<div>").addClass("preview-layer-details")
      .toggleClass("preview-layer-hidden", !isLayerShown(layerKey("sys", system.name)));
    const header = $("<div>").append(
      createLayerToggle(
        layerKey("sys", system.name),
        system.name,
        $("<i>").addClass("fas fa-satellite mr-1").css("color", system.color),
        null,
        function(shown) { details.toggleClass("preview-layer-hidden", !shown); }
      )
    );
    _.forEach(system.instruments, function(instrument, i) {
      const swatch = $("<span>").addClass("preview-swatch");
      if (instrument.color) {
        swatch.css("background-color", instrument.color);
      } else {
        swatch.addClass("preview-swatch-none");
      }
      details.append(createLayerToggle(
        layerKey("ins", system.name, i),
        instrument.name || "Instrument " + i,
        swatch,
        instrument.color ? "Instrument " + i : "Instrument " + i + " (no footprint)"
      ));
    });
    if (system.members.length > 1) {
      const members = $("<div>").addClass("preview-layer-members").toggle(!!previewExpanded[system.name]);
      _.forEach(system.members, function(member) {
        members.append(createLayerToggle(layerKey("sat", system.name, member.name), member.name));
      });
      const toggle = $("<a href='#'>").addClass("small ml-1")
        .text(system.members.length + " satellites")
        .prepend($("<i>").addClass("fas mr-1").toggleClass("fa-caret-down", !!previewExpanded[system.name])
          .toggleClass("fa-caret-right", !previewExpanded[system.name]))
        .on("click", function(e) {
          e.preventDefault();
          previewExpanded[system.name] = !previewExpanded[system.name];
          members.toggle(previewExpanded[system.name]);
          $(this).find("i").toggleClass("fa-caret-down fa-caret-right");
        });
      header.append(toggle);
      details.append(members);
    }
    list.append($("<div>").addClass("preview-layer").append(header, details));
  });
  $("#preview-layers").show();
}

function previewOrbits() {
  const satellites = getSatellites();
  if (satellites.length == 0) {
    clearCzmlLayer("design");
    previewLayers = null;
    renderPreviewLayers();
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
        previewLayers = buildPreviewLayers(result, systems, source);
        renderPreviewLayers();
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
  showResultsTable(
    "Orbit Tracks",
    [
      { title: "Time (UTC)", key: "time" },
      { title: "Satellite", key: "satellite" },
      { title: "Instrument", key: "instrument" },
      { title: "Latitude (°)", key: "latitude_deg", format: function(v) { return v.toFixed(4); } },
      { title: "Longitude (°)", key: "longitude_deg", format: function(v) { return v.toFixed(4); } },
      { title: "Altitude (km)", key: "altitude_km", format: function(v) { return v.toFixed(2); } },
      { title: "Swath width (km)", key: "swath_width_km", format: function(v) { return v.toFixed(1); } }
    ],
    rows,
    "orbit-tracks",
    "Swath width spans the field of regard of each instrument."
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
  $("#preview-layers-all").click(function() {
    _.forEach(_.keys(previewHidden), function(key) { delete previewHidden[key]; });
    renderPreviewLayers();
    applyPreviewDisplayOptions();
  });
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
