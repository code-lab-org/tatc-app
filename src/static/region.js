// Region of interest and grids of points and cells for coverage and latency
// analyses.

// vertices (Cartesian3) of a custom region, and its polygon on the map
let regionPoints = [];
let regionEntity = null;

// primitive collections of the generated grid of points and cells
const gridPoints = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
const gridCells = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
const gridCellOutlines = viewer.scene.primitives.add(new Cesium.PolylineCollection());

// Gets the type of the edges of cells in the region: geodesic for global
// regions (rhumb lines cannot reach the poles), and rhumb lines otherwise.
function getArcType() {
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

function boxPolygon(lonMin, latMin, lonMax, latMax) {
  return {
    type: "Polygon",
    coordinates: [[
      [lonMin, latMin], [lonMax, latMin], [lonMax, latMax], [lonMin, latMax], [lonMin, latMin]
    ]]
  };
}

// Gets the mask of the region (a GeoJSON polygon, known shape, country code,
// or null for global).
function getRegionMask() {
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

function getPointsSpec() {
  return {
    method: $("#point-method").val(),
    distance: Number($("#point-distance").val()) * 1000,
    mask: getRegionMask()
  };
}

function getCellsSpec() {
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

// Shows (generating the grid if needed) or hides the region and its grid.
function showRegion(show) {
  regionEntity.show = show && $("#region-type").val() == "custom";
  if (show && gridPoints.length == 0) {
    generateRegionGrid();
  } else {
    showRegionGrid(show);
  }
}

// Adds cell polygons (GeoJSON features) as ground primitives (with edges of
// an arc type) and outlines (if a collection is given).
function addCellPrimitives(features, collection, outlines, arcType, colorFunction) {
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

const GRID_ERROR_PREFIX = "Grid: ";

// Hides a grid error (but not other analysis errors sharing the alert).
function clearGridError() {
  const error = $("#analysis-error");
  if (_.startsWith(error.text(), GRID_ERROR_PREFIX)) {
    error.hide().text("");
  }
}

let gridRequest = 0;
function generateRegionGrid() {
  const request = ++gridRequest;
  clearGridError();
  $("#region-generate").prop("disabled", true).find(".spinner-border").show();
  clearRegionGrid();
  showRegionGrid(true);
  const arcType = getArcType();
  $.when(postJson("/generate/points", getPointsSpec()), postJson("/generate/cells", getCellsSpec()))
    .done(function(pointsResponse, cellsResponse) {
      if (request != gridRequest) {
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
      if (request == gridRequest) {
        $("#analysis-error").text(GRID_ERROR_PREFIX + formatError(xhr)).show();
      }
    })
    .always(function() {
      if (request == gridRequest) {
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

function setRegionCoordinates(coordinates) {
  regionPoints = Cesium.Cartesian3.fromDegreesArray(_.flatten(coordinates));
  regionEntity.polygon.hierarchy = new Cesium.PolygonHierarchy(regionPoints);
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
}

function regionPanelVisible() {
  return $("#nav-analysis-tab").hasClass("active") && $(".region-panel").is(":visible");
}

$(document).ready(function() {
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
  updateCoordinatesText();

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
        generateRegionGrid();
      } catch (e) {
        alert("Invalid coordinates: " + e.message);
      }
      updateCoordinatesText();
    }
  });

  // picks the vertices of a custom region: the grid is generated once
  // picking is done (picking stopped otherwise, such as by leaving the tab,
  // leaves the grid to generate when the region shows again)
  const selectButton = $("#select-coordinates");
  let formerPoints = [];
  function setRegionPoints(points) {
    regionPoints = points;
    regionEntity.polygon.hierarchy = new Cesium.PolygonHierarchy(regionPoints);
    updateCoordinatesText();
  }
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
      generateRegionGrid();
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
    generateRegionGrid();
  });
  $("#region-generate").click(generateRegionGrid);
  $("#region-dialog").on("hidden.bs.modal", generateRegionGrid);
  changeRegionType();
});
