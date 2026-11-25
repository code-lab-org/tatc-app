// Cesium viewer, sign in, and utilities shared by the tabs: requests, map
// picking, selectable lists, and tables of results.

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

// Shows a status over the map while Cesium prepares the graphics of data
// sources: large footprints, for example, take seconds to tessellate (in web
// workers). Meanwhile, the viewer pauses the animation (its default
// `allowDataSourcesToSuspendAnimation`), which `canAnimate` reflects. The
// status shows after a delay, so it does not flash for brief preparations.
const MAP_BUSY_DELAY = 300; // milliseconds
let mapBusySince = null;
let mapBusyShown = false;
viewer.scene.postRender.addEventListener(function() {
  const now = performance.now();
  mapBusySince = viewer.clockViewModel.canAnimate ? null : (mapBusySince === null ? now : mapBusySince);
  const shown = mapBusySince !== null && now - mapBusySince >= MAP_BUSY_DELAY;
  if (shown !== mapBusyShown) {
    mapBusyShown = shown;
    $("#map-busy").toggleClass("shown", shown);
  }
});

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

// --- Map picking ---

// The active pick mode: {button, onPick, onStop}. One mode is active at a
// time: starting one stops the other.
let mapPick = null;

function mapPickListener(e) {
  const rect = viewer.canvas.getBoundingClientRect();
  const position = new Cesium.Cartesian2(e.clientX - rect.left, e.clientY - rect.top);
  const cartesian = viewer.camera.pickEllipsoid(position, viewer.scene.globe.ellipsoid);
  if (cartesian && mapPick) {
    mapPick.onPick(cartesian);
  }
}

// Starts picking points on the map with a toggle button: calls
// `onPick(cartesian)` for each click on the globe, and `onStop()` (if any)
// once picking stops.
function startMapPick(button, onPick, onStop) {
  stopMapPick();
  mapPick = { button: button, onPick: onPick, onStop: onStop };
  button.addClass("btn-success").removeClass("btn-secondary");
  viewer.canvas.style.cursor = "crosshair";
  viewer.canvas.addEventListener("click", mapPickListener);
}

// Stops picking points on the map (only with a button, if given).
function stopMapPick(button) {
  if (!mapPick || (button && !isMapPicking(button))) {
    return;
  }
  const stopped = mapPick;
  mapPick = null;
  stopped.button.addClass("btn-secondary").removeClass("btn-success");
  viewer.canvas.style.cursor = "default";
  viewer.canvas.removeEventListener("click", mapPickListener);
  if (stopped.onStop) {
    stopped.onStop();
  }
}

function isMapPicking(button) {
  return Boolean(mapPick) && mapPick.button[0] === button[0];
}

// --- Selectable lists ---

// Renders a list of items into a list group: `options.renderItem(item, i)`
// returns the content of an item, clicking an item calls
// `options.onSelect(i)`, double clicking it calls `options.onOpen(i)` (if
// any), and `options.buttons` (a selector) are enabled with a selection.
function renderSelectableList(container, items, selected, options) {
  container.empty();
  _.forEach(items, function(item, i) {
    const entry = $("<a href='#'>")
      .addClass("list-group-item list-group-item-action py-1 px-2 small")
      .toggleClass("active", i == selected)
      .append(options.renderItem(item, i))
      .on("click", function(e) {
        e.preventDefault();
        options.onSelect(i);
      });
    if (options.onOpen) {
      entry.on("dblclick", function(e) {
        e.preventDefault();
        options.onOpen(i);
      });
    }
    container.append(entry);
  });
  $(options.buttons).prop("disabled", !(selected >= 0 && selected < items.length));
}

// Removes the selected item of a list, returning the index to select next.
function removeSelected(items, selected) {
  items.splice(selected, 1);
  return Math.min(selected, items.length - 1);
}

// A name not among others: the (trimmed) name or, if blank, the fallback,
// with a number appended if taken (for example, "Station (2)").
function uniqueName(name, names, fallback) {
  name = _.trim(name) || fallback || name;
  if (!_.includes(names, name)) {
    return name;
  }
  const base = name.replace(/ \(\d+\)$/, "");
  let i = 2;
  while (_.includes(names, base + " (" + i + ")")) {
    i++;
  }
  return base + " (" + i + ")";
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
//
// options:
//   title:      dialog title
//   columns:    list of {title, key, format?}
//   rows:       list of objects
//   filename:   name (without extension) of the JSON and CSV downloads
//   note:       optional note shown above the table
//   extras:     optional additional CSV downloads {label, filename, columns, rows}
//   onRowClick: optional function(row) called when a row is clicked
let resultsTable = null;
function showResultsTable(options) {
  const columns = options.columns;
  const rows = options.rows;
  const filename = options.filename;
  const onRowClick = options.onRowClick;
  $("#results-title").text(options.title);
  $("#results-note").text(options.note || "");
  if (resultsTable) {
    resultsTable.destroy();
    $("#results-table").empty().off("click");
  }
  $(".results-extra").remove();
  _.forEach(options.extras || [], function(extra) {
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

// Posts JSON data, expecting a JSON response.
function postJson(url, data) {
  return $.ajax({
    url: url,
    type: "POST",
    contentType: "application/json",
    dataType: "json",
    data: JSON.stringify(data)
  });
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

// --- Authentication ---

const signedInListeners = [];

// Adds a listener called each time the user information shows the user is
// signed in (or authentication is disabled).
function onSignedIn(listener) {
  signedInListeners.push(listener);
}

function signedIn(info) {
  $("#login-link").hide();
  $("#nav-info-tab").off("hide.bs.tab");
  if (info.mode == "oidc") {
    $("#user-email").text(info.user.email || info.user.name || info.user.id);
    $("#user-menu").show();
  } else {
    // authentication is disabled (local development)
    $("#user-menu").hide();
  }
  initializeCesium();
  _.forEach(signedInListeners, function(listener) { listener(info); });
}

function signedOut() {
  $("#user-menu").hide();
  $("#user-email").text("");
  $("#login-link").show();
  // require sign in before leaving the information tab
  $("#nav-info-tab").off("hide.bs.tab").on("hide.bs.tab", function(e) {
    e.preventDefault();
    window.location.href = "/auth/login";
  });
}

function getUserInformation(onArrival) {
  $.get("/auth/me").done(signedIn).fail(function(xhr) {
    signedOut();
    // prompt to sign in on arrival (not after signing out or on other errors)
    if (onArrival && xhr.status == 401) {
      $("#login-dialog").modal("show");
    }
  });
}

// --- Drawer ---

// Collapsing the drawer hides only the panel: the active tab stays active, so
// its layers stay visible on the globe.
function setDrawerCollapsed(collapsed) {
  $("#drawer").toggleClass("collapsed", collapsed);
  $("#drawer-collapse").attr("aria-expanded", String(!collapsed));
}

function initializeDrawer() {
  // Bound directly on the rail buttons, so this runs before Bootstrap's
  // delegated tab handler: clicking the active tab toggles the drawer and
  // clicking another tab opens it (Bootstrap then switches tabs).
  $("#nav-tab .rail-btn").on("click", function() {
    if ($(this).hasClass("active")) {
      setDrawerCollapsed(!$("#drawer").hasClass("collapsed"));
    } else {
      setDrawerCollapsed(false);
    }
  });
  $("#nav-tab .rail-btn").on("shown.bs.tab", function(e) {
    $("#drawer-title").text($(e.target).attr("title"));
  });
  $("#drawer-collapse").on("click", function() {
    setDrawerCollapsed(true);
  });
  $(document).on("keydown", function(e) {
    // Esc in a dialog or menu closes that instead (handled by Bootstrap)
    if (e.key === "Escape" && !$(".modal.show").length && !$(e.target).closest(".dropright").length) {
      setDrawerCollapsed(true);
    }
  });
}

$(document).ready(function() {
  initializeDrawer();
  $.get("/openapi.json").done(function(api) {
    $("#app-version").text(api.info.version);
  });
  $("#logout-link").click(function(e) {
    e.preventDefault();
    $.post("/auth/logout").always(function() {
      $("#nav-info-tab").tab("show");
      getUserInformation();
    });
  });
  $("#token-link").click(function(e) {
    e.preventDefault();
    $.get("/auth/token")
      .done(function(token) {
        navigator.clipboard.writeText(token).then(
          function() { alert("API token copied. Send it in the header 'Authorization: Bearer <token>' until it expires."); },
          function() { window.prompt("API token (send as 'Authorization: Bearer <token>'):", token); }
        );
      })
      .fail(function(xhr) { alert(formatError(xhr)); });
  });
  $("#login-dialog").on("shown.bs.modal", function() {
    $("#login-dialog-link").trigger("focus");
  });
  getUserInformation(true);
});
