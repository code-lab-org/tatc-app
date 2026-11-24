// Sites of analyses: the ground stations of data latency analyses and the
// target points of point access analyses, listed in the Analysis tab and
// shown on the map while editing them.
//
// Stations and targets are part of the design: edits save the design
// (saveDesign) without notifying design listeners, which react to changes of
// the satellites (see design-state.js).

// data source of the sites shown on the map
let siteSource = null;

// --- Ground stations ---

let selectedStation = -1;

function renderStations() {
  renderSelectableList($("#stations"), design.stations, selectedStation, {
    buttons: "#station-edit, #station-delete",
    renderItem: function(station) {
      return [
        $("<i>").addClass("fas fa-broadcast-tower mr-2"),
        $("<span>").text(station.name),
        $("<span>").addClass("ml-2 text-muted").text(
          "(" + Number(station.latitude).toFixed(2) + "°, " + Number(station.longitude).toFixed(2) + "°)"
        )
      ];
    },
    onSelect: function(i) {
      selectedStation = i;
      renderStations();
    },
    onOpen: function(i) {
      selectedStation = i;
      openStationDialog();
    }
  });
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

function renderTargets() {
  renderSelectableList($("#targets"), design.targets, selectedTarget, {
    buttons: "#target-delete",
    renderItem: function(target, i) {
      return [
        $("<i>").addClass("fas fa-map-marker-alt mr-2"),
        $("<span>").text("Point " + i + " (" + Number(target.latitude).toFixed(3) + "°, " + Number(target.longitude).toFixed(3) + "°)")
      ];
    },
    onSelect: function(i) {
      selectedTarget = i;
      renderTargets();
    }
  });
  renderSiteEntities();
}

function addTarget(latitude, longitude) {
  design.targets.push({ latitude: latitude, longitude: longitude });
  selectedTarget = design.targets.length - 1;
  renderTargets();
  saveDesign();
}

function addPickedTarget(cartesian) {
  const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
  addTarget(
    Number(Cesium.Math.toDegrees(cartographic.latitude).toFixed(4)),
    Number(Cesium.Math.toDegrees(cartographic.longitude).toFixed(4))
  );
}

// Shows the stations (latency) or targets (access) being edited on the map.
function renderSiteEntities() {
  if (!siteSource) {
    return;
  }
  siteSource.entities.removeAll();
  const type = getAnalysisType();
  const visible = $("#nav-analysis-tab").hasClass("active")
    && !(analysisResult && analysisResult.type == type);
  siteSource.show = visible;
  function addSite(latitude, longitude, name, point) {
    siteSource.entities.add({
      position: Cesium.Cartesian3.fromDegrees(longitude, latitude),
      point: _.assign({ outlineColor: Cesium.Color.BLACK, outlineWidth: 1, disableDepthTestDistance: 1e12 }, point),
      label: { text: name, font: "11px sans-serif", pixelOffset: new Cesium.Cartesian2(8, 0), horizontalOrigin: Cesium.HorizontalOrigin.LEFT, style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineWidth: 2, disableDepthTestDistance: 1e12 }
    });
  }
  if (type == "latency") {
    _.forEach(design.stations, function(station) {
      addSite(station.latitude, station.longitude, station.name, { pixelSize: 9, color: Cesium.Color.fromCssColorString("#ffd166") });
    });
  } else if (type == "access") {
    _.forEach(design.targets, function(target, i) {
      addSite(target.latitude, target.longitude, "Point " + i, { pixelSize: 8, color: Cesium.Color.WHITE });
    });
  }
}

$(document).ready(function() {
  siteSource = new Cesium.CustomDataSource("sites");
  viewer.dataSources.add(siteSource);

  // stations
  $("#station-add").click(function() {
    design.stations.push(createStation(uniqueName("Station", _.map(design.stations, "name"))));
    selectedStation = design.stations.length - 1;
    renderStations();
    openStationDialog();
  });
  $("#station-edit").click(openStationDialog);
  $("#station-delete").click(function() {
    selectedStation = removeSelected(design.stations, selectedStation);
    renderStations();
    saveDesign();
  });
  $("#station-dialog").on("hidden.bs.modal", function() {
    const station = design.stations[selectedStation];
    if (station) {
      station.name = uniqueName(station.name, _.map(_.without(design.stations, station), "name"), "Station");
    }
    renderStations();
    saveDesign();
  });

  // targets
  $("#target-pick").click(function() {
    if (isMapPicking($(this))) {
      stopMapPick();
    } else {
      startMapPick($(this), addPickedTarget);
    }
  });
  $("#target-add").click(function() { $("#target-dialog").modal("show"); });
  $("#target-ok").click(function() {
    addTarget(Number($("#target-latitude").val()), Number($("#target-longitude").val()));
  });
  $("#target-delete").click(function() {
    selectedTarget = removeSelected(design.targets, selectedTarget);
    renderTargets();
    saveDesign();
  });

  // an imported design replaces the stations and targets
  onDesignChange(function() {
    renderStations();
    renderTargets();
  });
});
