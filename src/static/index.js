// Cesium viewer, login, and shared utilities.

// Offline base layer bundled with Cesium (no access token required).
function createOfflineBaseLayer() {
  return new Cesium.ImageryLayer(
    new Cesium.UrlTemplateImageryProvider({
      url: Cesium.buildModuleUrl("Assets/Textures/NaturalEarthII/") + "{z}/{x}/{reverseY}.jpg",
      tilingScheme: new Cesium.GeographicTilingScheme(),
      maximumLevel: 2,
      credit: "Natural Earth II"
    })
  );
}

// The viewer is created once; imagery and terrain are upgraded to Cesium ion
// assets once an access token is available (see `initializeCesium`).
const viewer = new Cesium.Viewer("cesiumContainer", {
  baseLayer: createOfflineBaseLayer(),
  baseLayerPicker: false,
  homeButton: false,
  infoBox: true,
  geocoder: false,
  selectionIndicator: true,
  navigationHelpButton: false,
  navigationInstructionsInitiallyVisible: false,
  sceneModePicker: true,
  timeline: true,
  animation: true
});
viewer.scene.globe.depthTestAgainstTerrain = false;

// primitive collections for generated points and cells
const points = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
const cells = viewer.scene.primitives.add(new Cesium.PrimitiveCollection());
const cellOutlines = viewer.scene.primitives.add(new Cesium.PolylineCollection());

let cesiumIonInitialized = false;
function initializeCesium() {
  if (cesiumIonInitialized) {
    return;
  }
  $.get("/cesium/token").done(function(token) {
    if (!token) {
      return;
    }
    cesiumIonInitialized = true;
    Cesium.Ion.defaultAccessToken = token;
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.add(
      Cesium.ImageryLayer.fromProviderAsync(Cesium.IonImageryProvider.fromAssetId(3845))
    );
    viewer.scene.setTerrain(Cesium.Terrain.fromWorldTerrain());
  });
}

// Removes the child entities of a parent entity.
function clearEntities(parent) {
  const entitiesToRemove = _.filter(viewer.entities.values, function(entity) {
    return entity.parent === parent;
  });
  _.forEach(entitiesToRemove, function(entity) {
    viewer.entities.remove(entity);
  });
}

function getArcType() {
  const type = $("#region-type").val();
  const latMin = Number($("#region-latitude-min").val());
  const latMax = Number($("#region-latitude-max").val());
  if (type == "global" || (type == "latitude" && (latMin <= -90 || latMax >= 90))) {
    return Cesium.ArcType.GEODESIC;
  }
  return Cesium.ArcType.RHUMB;
}

// --- Date time utilities (all times are UTC) ---

// Formats a Date for a datetime-local input (interpreted as UTC).
function toDateTimeInput(date) {
  return new Date(date).toISOString().substring(0, 19);
}

// Parses the value of a datetime-local input (interpreted as UTC).
function fromDateTimeInput(value) {
  return new Date(value + (value.length == 16 ? ":00Z" : "Z"));
}

// --- Download utilities ---

function downloadFile(filename, content, type) {
  const blob = new Blob([content], { type: type || "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}

function toCsv(columns, rows) {
  function escape(value) {
    if (value === null || value === undefined) {
      return "";
    }
    const text = String(value);
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }
  return [columns.map(escape).join(",")]
    .concat(_.map(rows, function(row) { return row.map(escape).join(","); }))
    .join("\n");
}

// Shows a table of results with JSON and CSV downloads.
// `columns` is a list of {title, key, format?}; `rows` a list of objects;
// `extras` a list of additional CSV downloads {label, filename, columns, rows};
// `onRowClick` an optional function(row) called when a row is clicked.
let resultsTable = null;
function showResultsTable(title, columns, rows, filename, note, extras, onRowClick) {
  $("#results-title").text(title);
  $("#results-note").text(note || "");
  if (resultsTable) {
    resultsTable.destroy();
    $("#results-table").empty().off("click");
  }
  $(".results-extra").remove();
  _.forEach(extras || [], function(extra) {
    $("<button type='button'>")
      .addClass("btn btn-secondary results-extra")
      .append($("<span>").addClass("fa fa-download"), " " + extra.label)
      .on("click", function() {
        downloadFile(extra.filename, toCsv(extra.columns, extra.rows), "text/csv");
      })
      .insertBefore("#results-json");
  });
  resultsTable = $("#results-table").DataTable({
    data: _.map(rows, function(row) {
      return _.map(columns, function(column) { return row[column.key]; });
    }),
    columns: _.map(columns, function(column) {
      return {
        title: column.title,
        render: column.format
          ? function(value) { return value === null || value === undefined ? "" : column.format(value); }
          : function(value) { return value === null || value === undefined ? "" : _.escape(String(value)); }
      };
    }),
    searching: false,
    deferRender: true,
    pageLength: 25
  });
  if (onRowClick) {
    $("#results-table").css("cursor", "pointer").on("click", "tbody tr", function() {
      const index = resultsTable.row(this).index();
      if (index !== undefined) {
        onRowClick(rows[index]);
      }
    });
  } else {
    $("#results-table").css("cursor", "default");
  }
  $("#results-json").off("click").on("click", function() {
    downloadFile(filename + ".json", JSON.stringify(rows, null, 2), "application/json");
  });
  $("#results-csv").off("click").on("click", function() {
    downloadFile(
      filename + ".csv",
      toCsv(
        _.map(columns, "key"),
        _.map(rows, function(row) { return _.map(columns, function(c) { return row[c.key]; }); })
      ),
      "text/csv"
    );
  });
  $("#results-dialog").modal("show");
}

// Formats an error response (including FastAPI validation errors).
function formatError(xhr) {
  if (xhr && xhr.responseJSON && xhr.responseJSON.detail) {
    const detail = xhr.responseJSON.detail;
    if (_.isArray(detail)) {
      return _.map(detail, function(error) {
        const location = _.filter(error.loc || [], function(part) { return part !== "body"; });
        return (location.length ? location.join(".") + ": " : "") + error.msg;
      }).join("\n");
    }
    return String(detail);
  }
  if (xhr && xhr.status) {
    return "Request failed (" + xhr.status + " " + xhr.statusText + ").";
  }
  return String(xhr || "Request failed.");
}

// --- Login ---

function initializePage(user) {
  $("#login-modal").modal("hide");
  $("#login-link").hide();
  $("#logout-link").show();
  $("#user-email").text(user.email);
  $("#nav-info-tab").off("hide.bs.tab");
  initializeCesium();
}

function getUserInformation() {
  $.get("/users/me")
    .done(initializePage)
    .fail(function() {
      $("#login-link").show();
      $("#logout-link").hide();
      $("#user-email").text("");
      // require login before leaving the information tab
      $("#nav-info-tab").off("hide.bs.tab").on("hide.bs.tab", function(e) {
        e.preventDefault();
        $("#login-modal").modal("show");
      });
    });
}

$(document).ready(function() {
  window.Split(["#editor", "#viewer"], { sizes: [30, 70], minSize: [320, 200] });
  $.get("/openapi.json").done(function(api) {
    $("#app-version").text(api.info.version);
  });
  $("#login-form").on("submit", function(e) {
    e.preventDefault();
    $("#login-message").text("");
    $.post("/login", $(this).serialize())
      .done(getUserInformation)
      .fail(function(xhr) {
        $("#login-message").text(
          xhr.status == 400 ? "Incorrect email or password." : formatError(xhr)
        );
      });
  });
  $("#logout-link").click(function(e) {
    e.preventDefault();
    $.post("/logout").done(function() {
      $("#nav-info-tab").tab("show");
      getUserInformation();
    });
  });
  $("#login-modal").modal({ backdrop: "static", keyboard: false, show: false });
  getUserInformation();
});
