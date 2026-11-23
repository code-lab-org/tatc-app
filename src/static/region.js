// Region of interest and grids of points and cells for coverage and latency
// analyses.

let regionPoints = [];
let regionEntity = null;

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
  points.removeAll();
  cells.removeAll();
  cellOutlines.removeAll();
}

function showRegionGrid(show) {
  points.show = show;
  cells.show = show;
  cellOutlines.show = show;
}

// Adds cell polygons (GeoJSON features) as ground primitives with outlines.
function addCellPrimitives(features, collection, outlines, colorFunction) {
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
        arcType: getArcType()
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

let gridRequest = 0;
function generateRegionGrid() {
  const request = ++gridRequest;
  $("#region-generate").prop("disabled", true).find(".spinner-border").show();
  clearRegionGrid();
  showRegionGrid(true);
  function post(url, data) {
    return $.ajax({ url: url, type: "POST", contentType: "application/json", dataType: "json", data: JSON.stringify(data) });
  }
  $.when(post("/generate/points", getPointsSpec()), post("/generate/cells", getCellsSpec()))
    .done(function(pointsResponse, cellsResponse) {
      if (request != gridRequest) {
        return;
      }
      _.forEach(pointsResponse[0].features, function(feature) {
        points.add({
          position: Cesium.Cartesian3.fromDegrees(feature.geometry.coordinates[0], feature.geometry.coordinates[1]),
          color: Cesium.Color.DODGERBLUE,
          pixelSize: 4
        });
      });
      addCellPrimitives(cellsResponse[0].features, cells, cellOutlines, function() {
        return Cesium.Color.DODGERBLUE.withAlpha(0.15);
      });
    })
    .fail(function(xhr) {
      $("#analysis-error").text("Grid: " + formatError(xhr)).show();
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

  function pickListener(e) {
    const rect = viewer.canvas.getBoundingClientRect();
    const position = new Cesium.Cartesian2(e.clientX - rect.left, e.clientY - rect.top);
    const cartesian = viewer.camera.pickEllipsoid(position, viewer.scene.globe.ellipsoid);
    if (cartesian) {
      regionPoints.push(cartesian);
      regionEntity.polygon.hierarchy = new Cesium.PolygonHierarchy(regionPoints);
      updateCoordinatesText();
    }
  }
  let picking = false;
  $("#select-coordinates").click(function() {
    picking = !picking;
    $(this).toggleClass("btn-success", picking).toggleClass("btn-secondary", !picking);
    $(this).children("i").toggleClass("fa-check", picking).toggleClass("fa-map-marker", !picking);
    viewer.canvas.style.cursor = picking ? "crosshair" : "default";
    if (picking) {
      clearRegionGrid();
      regionPoints = [];
      regionEntity.polygon.hierarchy = new Cesium.PolygonHierarchy([]);
      viewer.canvas.addEventListener("click", pickListener);
    } else {
      viewer.canvas.removeEventListener("click", pickListener);
      updateCoordinatesText();
      generateRegionGrid();
    }
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
    changeRegionType();
    generateRegionGrid();
  });
  $("#region-generate").click(generateRegionGrid);
  $("#region-dialog").on("hidden.bs.modal", generateRegionGrid);
  changeRegionType();
});
