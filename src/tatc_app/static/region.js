// Region of interest: grids of points and cells for the analyses that sample
// one (coverage, coincidence, and latency), or else its outline (swaths over
// a region).

import { ANALYSES } from "./analysis-types.js";
import { getAnalysisType } from "./analysis.js";
import { formatError, isMapPicking, latestRequests, postJson, startMapPick, stopMapPick } from "./index.js";
import { viewer } from "./viewer.js";

// vertices (Cartesian3) of a custom region, and its polygon on the map
let regionPoints = [];
let regionEntity = null;

// primitive collections of the generated grid of points and cells
export const gridPoints = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
const gridCells = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
const gridCellOutlines = viewer.scene.primitives.add(new Cesium.PolylineCollection());

// the outline of the region (other than a custom one, drawn as its polygon)
// for analyses without a grid
export const regionOutline = new Cesium.CustomDataSource("region-outline");
viewer.dataSources.add(regionOutline);
let outlineDrawn = false;
const outlineRequests = latestRequests();

// Gets the type of the edges of cells in the region: geodesic for global
// regions (rhumb lines cannot reach the poles), and rhumb lines otherwise.
export function getArcType() {
  const type = $("#region-type").val();
  const latMin = Number($("#region-latitude-min").val());
  const latMax = Number($("#region-latitude-max").val());
  if (type == "global" || (type == "latitude" && (latMin <= -90 || latMax >= 90))) {
    return Cesium.ArcType.GEODESIC;
  }
  return Cesium.ArcType.RHUMB;
}

function getRegionCoordinates() {
  const ellipsoid = viewer.scene.globe.ellipsoid;
  const coordinates = _.map(regionPoints, function(point) {
    const cartographic = Cesium.Cartographic.fromCartesian(point, ellipsoid);
    return [
      Cesium.Math.toDegrees(cartographic.longitude),
      Cesium.Math.toDegrees(cartographic.latitude)
    ];
  });
  // close the polygon
  return coordinates.length ? coordinates.concat([coordinates[0]]) : coordinates;
}

export function boxPolygon(lonMin, latMin, lonMax, latMax) {
  return {
    type: "Polygon",
    coordinates: [[
      [lonMin, latMin], [lonMax, latMin], [lonMax, latMax], [lonMin, latMax], [lonMin, latMin]
    ]]
  };
}

// Gets the mask of the region (a GeoJSON polygon, known shape, country code,
// or null for global).
export function getRegionMask() {
  const type = $("#region-type").val();
  const latMin = Number($("#region-latitude-min").val());
  const latMax = Number($("#region-latitude-max").val());
  if (type == "custom") {
    return { type: "Polygon", coordinates: [getRegionCoordinates()] };
  } else if (type == "latitude") {
    return boxPolygon(-180, latMin, 180, latMax);
  } else if (type == "latlon") {
    return boxPolygon(
      Number($("#region-longitude-min").val()), latMin,
      Number($("#region-longitude-max").val()), latMax
    );
  } else if (type == "global") {
    return null;
  }
  return type;
}

export function getPointsSpec() {
  return {
    method: $("#point-method").val(),
    distance: Number($("#point-distance").val()) * 1000,
    mask: getRegionMask()
  };
}

export function getCellsSpec() {
  const strips = $("#cell-strips").val();
  return {
    method: "equally_spaced",
    distance: Number($("#cell-distance").val()) * 1000,
    mask: getRegionMask(),
    strips: strips == "none" ? null : strips
  };
}

function clearRegionGrid() {
  gridPoints.removeAll();
  gridCells.removeAll();
  gridCellOutlines.removeAll();
}

function showRegionGrid(show) {
  gridPoints.show = show;
  gridCells.show = show;
  gridCellOutlines.show = show;
}

// Tests whether the selected analysis samples a grid of the region (see
// `ANALYSES`).
function regionUsesGrid() {
  return _.get(ANALYSES, [getAnalysisType(), "grid"], true);
}

// Shows (generating them if needed) or hides the region and its grid, or its
// outline for analyses without a grid.
export function showRegion(show) {
  const grid = regionUsesGrid();
  regionEntity.show = show && $("#region-type").val() == "custom";
  regionOutline.show = show && !grid;
  if (show && !grid && !outlineDrawn) {
    drawRegionOutline();
  }
  if (show && grid && gridPoints.length == 0) {
    generateRegionGrid();
  } else {
    showRegionGrid(show && grid);
  }
}

// Shows the controls of the grid only for analyses that sample one, and
// enables editing the region only if it has settings to edit.
export function updateRegionControls() {
  const grid = regionUsesGrid();
  const type = $("#region-type").val();
  $("#region-generate-group, #region-grid-settings").toggle(grid);
  $("#region-edit")
    .prop("disabled", !grid && type != "latitude" && type != "latlon")
    .attr("title", grid ? "Edit region and grid" : "Edit region");
  $("#region-dialog-title").text(grid ? "Edit Region and Grid" : "Edit Region");
}

// Updates the display of the changed region: its grid, or its outline
// (the other is redone when it next shows).
function refreshRegion() {
  if (regionUsesGrid()) {
    clearRegionOutline();
    generateRegionGrid();
  } else {
    cancelRegionGrid();
    drawRegionOutline();
  }
}

function clearRegionOutline() {
  outlineRequests.cancel();
  outlineDrawn = false;
  regionOutline.entities.removeAll();
}

// Splits the rings of a (multi)polygon into runs of [longitude, latitude]
// vertices, leaving out the edges along the antimeridian (such as the sides
// of a band of latitude), which are not edges on the globe.
function outlineRuns(geometry) {
  const polygons = geometry.type == "MultiPolygon" ? geometry.coordinates : [geometry.coordinates];
  const runs = [];
  _.forEach(polygons, function(rings) {
    _.forEach(rings, function(ring) {
      let run = [];
      _.forEach(ring, function(vertex, i) {
        const previous = ring[i - 1];
        if (previous && Math.abs(vertex[0]) == 180 && previous[0] == vertex[0]) {
          if (run.length > 1) {
            runs.push(run);
          }
          run = [];
        }
        run.push([vertex[0], vertex[1]]);
      });
      if (run.length > 1) {
        runs.push(run);
      }
    });
  });
  return runs;
}

// Draws the outline of the region (none for a custom region, drawn as its
// polygon, or for the globe).
function drawRegionOutline() {
  clearRegionOutline();
  const isLatest = outlineRequests.start();
  outlineDrawn = true;
  $("#grid-error").hide().text("");
  const type = $("#region-type").val();
  if (type == "custom" || type == "global") {
    return;
  }
  postJson("/generate/region", { mask: getRegionMask() })
    .done(function(collection) {
      if (!isLatest()) {
        return;
      }
      _.forEach(collection.features, function(feature) {
        _.forEach(outlineRuns(feature.geometry), function(run) {
          regionOutline.entities.add({
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(_.flatten(run)),
              arcType: Cesium.ArcType.RHUMB,
              width: 2,
              material: Cesium.Color.DODGERBLUE
            }
          });
        });
      });
    })
    .fail(function(xhr) {
      if (isLatest()) {
        outlineDrawn = false;
        $("#grid-error").text(formatError(xhr)).show();
      }
    });
}

// Adds cell polygons (GeoJSON features) as ground primitives (with edges of
// an arc type) and outlines (if a collection is given).
export function addCellPrimitives(features, collection, outlines, arcType, colorFunction) {
  const instances = _.map(features, function(feature, i) {
    const vertices = Cesium.Cartesian3.fromDegreesArray(_.flatten(
      _.map(feature.geometry.coordinates[0], function(c) { return [c[0], c[1]]; })
    ));
    if (outlines) {
      outlines.add({
        positions: vertices,
        width: 1.0,
        loop: true,
        material: Cesium.Material.fromType("Color", { color: Cesium.Color.BLACK.withAlpha(0.5) })
      });
    }
    return new Cesium.GeometryInstance({
      id: feature.properties.cell_id || i,
      geometry: new Cesium.PolygonGeometry({
        polygonHierarchy: new Cesium.PolygonHierarchy(vertices),
        arcType: arcType
      }),
      attributes: {
        color: Cesium.ColorGeometryInstanceAttribute.fromColor(colorFunction(feature, i))
      }
    });
  });
  if (instances.length == 0) {
    return null;
  }
  return collection.add(new Cesium.GroundPrimitive({
    geometryInstances: instances,
    appearance: new Cesium.PerInstanceColorAppearance({ flat: true, translucent: true }),
    releaseGeometryInstances: false
  }));
}

// Cancels generating the grid, and clears it (to generate when it next
// shows).
export function cancelRegionGrid() {
  gridRequests.cancel();
  $("#region-generate").prop("disabled", false).find(".spinner-border").hide();
  clearRegionGrid();
}

const gridRequests = latestRequests();
export function generateRegionGrid() {
  const isLatest = gridRequests.start();
  $("#grid-error").hide().text("");
  $("#region-generate").prop("disabled", true).find(".spinner-border").show();
  clearRegionGrid();
  showRegionGrid(true);
  const arcType = getArcType();
  $.when(postJson("/generate/points", getPointsSpec()), postJson("/generate/cells", getCellsSpec()))
    .done(function(pointsResponse, cellsResponse) {
      if (!isLatest()) {
        return;
      }
      _.forEach(pointsResponse[0].features, function(feature) {
        gridPoints.add({
          position: Cesium.Cartesian3.fromDegrees(feature.geometry.coordinates[0], feature.geometry.coordinates[1]),
          color: Cesium.Color.DODGERBLUE,
          pixelSize: 4
        });
      });
      addCellPrimitives(cellsResponse[0].features, gridCells, gridCellOutlines, arcType, function() {
        return Cesium.Color.DODGERBLUE.withAlpha(0.15);
      });
    })
    .fail(function(xhr) {
      // ignore failures of superseded requests
      if (isLatest()) {
        $("#grid-error").text(formatError(xhr)).show();
      }
    })
    .always(function() {
      if (isLatest()) {
        $("#region-generate").prop("disabled", false).find(".spinner-border").hide();
      }
    });
}

function updateCoordinatesText() {
  const coordinates = _.dropRight(getRegionCoordinates());
  $("#region-coordinates").val(JSON.stringify(_.map(coordinates, function(c) {
    return [Number(c[0].toFixed(4)), Number(c[1].toFixed(4))];
  })));
}

// Sets the vertices (Cartesian3) of the custom region, updating its polygon
// and coordinates.
function setRegionPoints(points) {
  regionPoints = points;
  regionEntity.polygon.hierarchy = new Cesium.PolygonHierarchy(regionPoints);
  updateCoordinatesText();
}

// Sets the vertices of the custom region from [longitude, latitude] pairs.
function setRegionCoordinates(coordinates) {
  setRegionPoints(Cesium.Cartesian3.fromDegreesArray(_.flatten(coordinates)));
}

function changeRegionType() {
  const type = $("#region-type").val();
  regionEntity.show = type == "custom" && regionPanelVisible();
  $("#region-latitude-group").toggle(type == "latitude" || type == "latlon");
  $("#region-longitude-group").toggle(type == "latlon");
  $("#region-coordinates-group").toggle(type == "custom");
  $("#select-coordinates, #edit-coordinates").prop("disabled", type != "custom");
  $("#cell-strips").prop("disabled", type != "custom");
  if (type != "custom") {
    $("#cell-strips").val("none");
  }
  updateRegionControls();
}

function regionPanelVisible() {
  return $("#nav-analysis-tab").hasClass("active") && $(".region-panel").is(":visible");
}

// Sets up this module once the page has loaded (see main.js).
export function setupRegion() {
  regionEntity = viewer.entities.add({
    polygon: {
      hierarchy: new Cesium.PolygonHierarchy([]),
      arcType: Cesium.ArcType.RHUMB,
      material: Cesium.Color.WHITE.withAlpha(0.1),
      outline: true,
      outlineColor: Cesium.Color.BLACK,
      height: 0
    },
    show: false
  });
  setRegionCoordinates([[-130, 20], [-130, 50], [-60, 50], [-60, 20]]);

  let editingCoordinates = false;
  $("#edit-coordinates").click(function() {
    editingCoordinates = !editingCoordinates;
    $("#region-coordinates").prop("disabled", !editingCoordinates);
    $(this).toggleClass("btn-success", editingCoordinates).toggleClass("btn-secondary", !editingCoordinates);
    $(this).children("i").toggleClass("fa-check", editingCoordinates).toggleClass("fa-edit", !editingCoordinates);
    if (!editingCoordinates) {
      try {
        let coordinates = JSON.parse($("#region-coordinates").val());
        if (!_.isArray(coordinates[0])) {
          coordinates = _.chunk(coordinates, 2); // flat list of longitude, latitude
        }
        if (coordinates.length < 3) {
          throw new Error("A region requires at least three points.");
        }
        setRegionCoordinates(coordinates);
        refreshRegion();
      } catch (e) {
        alert("Invalid coordinates: " + e.message);
        updateCoordinatesText();
      }
    }
  });

  // picks the vertices of a custom region: the grid is generated once
  // picking is done (picking stopped otherwise, such as by leaving the tab,
  // leaves the grid to generate when the region shows again)
  const selectButton = $("#select-coordinates");
  let formerPoints = [];
  function addRegionPoint(cartesian) {
    setRegionPoints(regionPoints.concat([cartesian]));
  }
  function stoppedPicking() {
    selectButton.children("i").addClass("fa-map-marker").removeClass("fa-check");
    // too few vertices for a region: keep the former region
    setRegionPoints(regionPoints.length < 3 ? formerPoints : regionPoints);
  }
  selectButton.click(function() {
    if (isMapPicking(selectButton)) {
      stopMapPick();
      refreshRegion();
      return;
    }
    startMapPick(selectButton, addRegionPoint, stoppedPicking);
    selectButton.children("i").addClass("fa-check").removeClass("fa-map-marker");
    clearRegionGrid();
    formerPoints = regionPoints;
    setRegionPoints([]);
  });

  $("#region-latitude-min, #region-latitude-max").change(function() {
    $("#region-latitude-min").attr("max", $("#region-latitude-max").val());
    $("#region-latitude-max").attr("min", $("#region-latitude-min").val());
  });
  $("#region-longitude-min, #region-longitude-max").change(function() {
    $("#region-longitude-min").attr("max", $("#region-longitude-max").val());
    $("#region-longitude-max").attr("min", $("#region-longitude-min").val());
  });
  $("#region-type").change(function() {
    stopMapPick(selectButton);
    changeRegionType();
    refreshRegion();
  });
  $("#region-generate").click(generateRegionGrid);
  $("#region-dialog").on("hidden.bs.modal", refreshRegion);
  changeRegionType();
}
