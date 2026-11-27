// Display panel, shared by all tabs: options of the view (the frame of the
// observer, lighting, and the paths and footprints of satellites), and the
// legends of satellites and instruments (see filter.js) and of analysis
// results (see analysis.js).

import { getCzmlLayer } from "./layers.js";
import { viewer } from "./viewer.js";

// Keeps the camera in the inertial (ICRF) frame, after each update of the
// scene.
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

export function isPathShown() {
  return $("#display-path").is(":checked");
}

export function isFootprintShown() {
  return $("#display-footprint").is(":checked");
}

// Shows or hides the orbit paths and instrument footprints of the satellites
// of a CZML layer (entities `sat/<satellite>` and `fp/<satellite>/<index>`,
// whose polygons are child entities). The orbit preview also hides the
// satellites and instruments unchecked in the filter (see preview.js).
export function applySatelliteDisplayOptions(source) {
  if (!source) {
    return;
  }
  const path = isPathShown();
  const footprint = isFootprintShown();
  _.forEach(source.entities.values, function(entity) {
    if (_.startsWith(entity.id, "sat/") && entity.path) {
      entity.path.show = path;
    } else if (_.startsWith(entity.id, "fp/") && !entity.parent) {
      entity.show = footprint;
    }
  });
}

// Collapses the panel into its button of Cesium's toolbar (or expands it).
function setDisplayCollapsed(collapsed) {
  $("#display-panel").toggleClass("collapsed", collapsed);
  $("#display-toggle").toggleClass("active", !collapsed).attr("aria-expanded", String(!collapsed));
}

// Adds the button that shows or hides the panel to Cesium's toolbar, beside
// the scene mode picker (to its right, clear of the picker's options, which
// open to its left).
function createDisplayToggle() {
  $("<button type='button'>")
    .addClass("cesium-button cesium-toolbar-button display-toggle active")
    .attr({
      id: "display-toggle",
      title: "Display",
      "aria-label": "Display",
      "aria-controls": "display-panel",
      "aria-expanded": "true"
    })
    .append($("<i>").addClass("fas fa-layer-group"))
    .on("click", function() {
      setDisplayCollapsed(!$("#display-panel").hasClass("collapsed"));
    })
    .appendTo($(viewer.container).find(".cesium-viewer-toolbar"));
}

// Sets up this module once the page has loaded (see main.js).
export function setupDisplay() {
  $("#display-observer").change(function() {
    if ($(this).val() == "inertial") {
      viewer.scene.postUpdate.addEventListener(icrf);
    } else {
      viewer.scene.postUpdate.removeEventListener(icrf);
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    }
  });
  $("#display-lighting").change(function() {
    viewer.scene.globe.enableLighting = $(this).is(":checked");
  });
  // the orbit preview applies these options with the filter (see preview.js)
  $("#display-path, #display-footprint").change(function() {
    applySatelliteDisplayOptions(getCzmlLayer("analysis"));
  });
  createDisplayToggle();
  $("#display-collapse").click(function() {
    setDisplayCollapsed(true);
  });
}
