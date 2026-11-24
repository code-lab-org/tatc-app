// TAT-C catalog: loads the satellites of past and present programs from the
// system catalog, and adds instruments of the instrument catalog to
// satellites. The server replaces the cataloged (idealized) orbits of
// satellites with current general perturbations (GP) elements from CelesTrak,
// so that satellites are coordinated across systems; it takes them from its
// cached CelesTrak group or narrow queries for each other satellite, each
// cached for two hours (per CelesTrak's usage policy).

const SYSTEM_CLASS_LABELS = {
  sun_synchronous: "Sun-Synchronous",
  inclined: "Inclined",
  geostationary: "Geostationary"
};

let catalogSystems = null;
let catalogUnchecked = {}; // instruments the user unchecked, by identifier

function showStatus(container, text, className) {
  container.empty().append($("<div>").addClass(className || "text-muted").text(text));
}

function appendNotes(container, notes) {
  if (notes.length) {
    const list = $("<ul>").addClass("mb-0 pl-3");
    _.forEach(notes, function(note) {
      list.append($("<li>").text(note));
    });
    container.append($("<div>").addClass("mt-1").text("Notes:"), list);
  }
}

// Renders options of items (by `id`) grouped by class: `labels` maps the
// classes (values of `classKey`) to group labels, and empty groups are left out.
function renderGroupedOptions(select, labels, items, classKey, optionText) {
  select.empty();
  _.forEach(labels, function(label, itemClass) {
    const members = _.filter(items, function(item) { return item[classKey] == itemClass; });
    if (members.length) {
      select.append($("<optgroup>").attr("label", label).append(_.map(members, function(item) {
        return $("<option>").val(item.id).text(optionText(item));
      })));
    }
  });
}

// Renders the details of a catalog entry: a summary (with its validation
// tier), how it was selected, and its limitations.
function renderCatalogDetails(container, summary, entry) {
  container.empty().append(
    $("<div>").text(summary + " · validation: " + entry.tier),
    $("<div>").text(entry.selection)
  );
  if (entry.limitations.length) {
    container.append($("<div>").text("Limitations: " + entry.limitations.join(" ")));
  }
}

function showCatalogStatus(text, className) {
  showStatus($("#catalog-status"), text, className);
}

function loadCatalogSystems() {
  if (catalogSystems) {
    return;
  }
  showCatalogStatus("Loading the catalog…");
  $.getJSON("/catalog/systems").done(function(systems) {
    catalogSystems = systems;
    renderCatalogSystems();
    $("#catalog-status").empty();
  }).fail(function(xhr) {
    showCatalogStatus(formatError(xhr), "text-danger");
  });
}

function isActive(spacecraft) {
  return spacecraft.status != "retired";
}

function renderCatalogSystems() {
  renderGroupedOptions($("#catalog-systems"), SYSTEM_CLASS_LABELS, catalogSystems, "system_class", function(system) {
    const active = _.filter(system.spacecraft, isActive).length;
    return system.name + " (" + active + " of " + system.spacecraft.length + " active)";
  });
  renderCatalogSystem();
}

function getCatalogSystem() {
  return _.find(catalogSystems, { id: $("#catalog-systems").val() });
}

function getCatalogMembers(system) {
  const checked = $("#catalog-members input:checked").map(function() {
    return $(this).val();
  }).get();
  return _.filter(system.spacecraft, function(spacecraft) {
    return _.includes(checked, spacecraft.id);
  });
}

function renderCatalogSystem() {
  const system = getCatalogSystem();
  const details = $("#catalog-details").empty();
  const members = $("#catalog-members").empty();
  catalogUnchecked = {};
  if (!system) {
    renderCatalogInstruments();
    return;
  }
  renderCatalogDetails(details, system.operator + " · "
    + (system.role == "transmitting" ? "navigation (transmitting)" : "observing"), system);
  _.forEach(system.spacecraft, function(spacecraft) {
    const id = "catalog-member-" + spacecraft.id;
    const label = $("<label>").addClass("form-check-label").attr("for", id).text(
      spacecraft.name + " (NORAD " + spacecraft.norad_id + ")"
    );
    if (spacecraft.status != "operational") {
      label.append($("<span>").addClass("badge badge-light ml-1").text(spacecraft.status)
        .attr("title", "Status as of " + spacecraft.as_of));
    }
    members.append($("<div>").addClass("form-check").append(
      $("<input type='checkbox'>").addClass("form-check-input").attr("id", id)
        .val(spacecraft.id).prop("checked", isActive(spacecraft)),
      label
    ));
  });
  renderCatalogInstruments();
}

// Lists the instruments of the selected satellites.
function renderCatalogInstruments() {
  const system = getCatalogSystem();
  const container = $("#catalog-instruments").empty();
  const members = system ? getCatalogMembers(system) : [];
  const instruments = _.uniqBy(_.flatMap(members, "instruments"), "id");
  _.forEach(instruments, function(instrument) {
    const id = "catalog-instrument-" + instrument.id;
    const carriers = _.filter(members, function(member) {
      return _.some(member.instruments, { id: instrument.id });
    });
    const label = $("<label>").addClass("form-check-label").attr("for", id).text(instrument.name);
    if (members.length > 1) {
      label.append($("<span>").addClass("text-muted").text(" (" + _.map(carriers, "name").join(", ") + ")"));
    }
    container.append($("<div>").addClass("form-check").append(
      $("<input type='checkbox'>").addClass("form-check-input").attr("id", id)
        .val(instrument.id).prop("checked", !catalogUnchecked[instrument.id]),
      label
    ));
  });
  if (!instruments.length) {
    container.append($("<span>").addClass("text-muted").text(
      members.length ? "None cataloged (other than sounders)." : "Select satellites."
    ));
  }
  $("#catalog-load").prop("disabled", members.length == 0);
}

// Gets the instruments to carry: true for all, false for none, or a list.
function getCatalogInstruments() {
  const inputs = $("#catalog-instruments input");
  const checked = inputs.filter(":checked").map(function() { return $(this).val(); }).get();
  if (checked.length == inputs.length) {
    return true;
  }
  return checked.length ? checked : false;
}

function formatEpoch(epoch) {
  return epoch.substring(0, 16).replace("T", " ");
}

function showCatalogResult(result, count) {
  const status = $("#catalog-status").empty();
  status.append($("<div>").addClass("text-success").text(
    "Added " + count + (count == 1 ? " satellite" : " satellites") + " of " + result.name + " to the design."
  ));
  const epochs = _.sortBy(_.compact(_.map(result.members, "epoch")));
  if (epochs.length) {
    const range = epochs.length > 1 && formatEpoch(epochs[0]) != formatEpoch(_.last(epochs))
      ? "epochs " + formatEpoch(epochs[0]) + " to " + formatEpoch(_.last(epochs))
      : "epoch " + formatEpoch(epochs[0]);
    status.append($("<div>").addClass("text-muted").text(
      "GP elements from CelesTrak (" + range + " UTC)."
    ));
  }
  appendNotes(status, result.warnings);
}

function loadCatalogSystem() {
  const system = getCatalogSystem();
  const members = system ? getCatalogMembers(system) : [];
  if (!members.length) {
    return;
  }
  const period = getAnalysisPeriod();
  const button = $("#catalog-load").prop("disabled", true);
  showCatalogStatus("Loading " + system.name + " with GP elements from CelesTrak…");
  postJson("/catalog/systems/" + encodeURIComponent(system.id) + "/build", {
    members: _.map(members, "id"),
    instruments: getCatalogInstruments(),
    time_step: Number($("#catalog-time-step").val()),
    start: period.start.toISOString(),
    end: period.end.toISOString()
  }).done(function(result) {
    // the satellites of a system share one color
    showCatalogResult(result, addSatellites(result.satellites).length);
  }).fail(function(xhr) {
    showCatalogStatus(formatError(xhr), "text-danger");
  }).always(function() {
    button.prop("disabled", false);
  });
}

// --- Instrument catalog ---

const INSTRUMENT_CLASS_LABELS = {
  cross_track: "Cross-Track Scanners",
  pushbroom: "Pushbroom Imagers",
  conical: "Conical Scanners",
  sar: "Synthetic Aperture Radars",
  scatterometer: "Scatterometers",
  altimeter: "Altimeters",
  lidar: "Lidars",
  profiler: "Profilers",
  geostationary: "Geostationary Imagers",
  geostationary_regional: "Geostationary Regional Imagers"
};

let catalogInstruments = null;

function showInstrumentCatalogStatus(text, className) {
  showStatus($("#instrument-catalog-status"), text, className);
}

function loadCatalogInstruments() {
  if (catalogInstruments) {
    return;
  }
  showInstrumentCatalogStatus("Loading the catalog…");
  $.getJSON("/catalog/instruments").done(function(entries) {
    catalogInstruments = entries;
    renderCatalogInstrumentEntries();
    $("#instrument-catalog-status").empty();
  }).fail(function(xhr) {
    showInstrumentCatalogStatus(formatError(xhr), "text-danger");
  });
}

function renderCatalogInstrumentEntries() {
  renderGroupedOptions(
    $("#instrument-catalog-entries"), INSTRUMENT_CLASS_LABELS, _.sortBy(catalogInstruments, "name"),
    "instrument_class", function(entry) { return entry.name + " (" + entry.platforms.join(", ") + ")"; }
  );
  renderCatalogInstrumentEntry();
}

function getCatalogInstrumentEntry() {
  return _.find(catalogInstruments, { id: $("#instrument-catalog-entries").val() });
}

function renderCatalogInstrumentEntry() {
  const entry = getCatalogInstrumentEntry();
  const details = $("#instrument-catalog-details").empty();
  const select = $("#instrument-catalog-configurations").empty();
  $("#instrument-catalog-add").prop("disabled", !entry);
  if (!entry) {
    renderCatalogConfiguration();
    return;
  }
  renderCatalogDetails(details, "Carried by " + entry.platforms.join(", "), entry);
  _.forEach(entry.configurations, function(configuration) {
    select.append($("<option>").val(configuration.id).text(
      configuration.id + " (" + configuration.grade.replace("_", " ") + ", " + configuration.tier
      + (configuration.id == entry.default_configuration ? ", default" : "") + ")"
    ));
  });
  select.val(entry.default_configuration);
  renderCatalogConfiguration();
}

function renderCatalogConfiguration() {
  const entry = getCatalogInstrumentEntry();
  const configuration = entry && _.find(entry.configurations, { id: $("#instrument-catalog-configurations").val() });
  const container = $("#instrument-catalog-configuration").empty();
  if (configuration) {
    container.text(configuration.description + (configuration.instruments > 1
      ? " (" + configuration.instruments + " instruments: " + (configuration.grouping == "union"
        ? "parts of one view)" : "alternative views)")
      : ""));
  }
}

// Whether the satellite carries only the design's default instrument.
function hasDefaultInstruments(system) {
  return !system.instruments || system.instruments.length == 0
    || _.isEqual(system.instruments, [createInstrument()]);
}

function addCatalogInstrument() {
  const entry = getCatalogInstrumentEntry();
  if (!entry || !getEditedSystem()) {
    return;
  }
  const period = getAnalysisPeriod();
  const button = $("#instrument-catalog-add").prop("disabled", true);
  showInstrumentCatalogStatus("Adding " + entry.name + "…");
  postJson("/catalog/instruments/" + encodeURIComponent(entry.id) + "/add", {
    system: getEditedSystem(),
    configuration: $("#instrument-catalog-configurations").val(),
    time_step: Number($("#instrument-catalog-time-step").val()),
    start: period.start.toISOString(),
    end: period.end.toISOString(),
    replace: $("#instrument-catalog-replace").is(":checked")
  }).done(function(result) {
    // the satellite dialog may close meanwhile
    if (!getEditedSystem()) {
      return;
    }
    if (result.attitude_changed && !confirm(
      "Adding " + entry.name + " sets the satellite's attitude to the attitude it was validated with, "
      + "which also orients the satellite's other instruments. Add it?"
    )) {
      showInstrumentCatalogStatus(entry.name + " was not added.");
      return;
    }
    replaceEditedSystem(result.system, result.system.instruments.length - result.added.length);
    $("#instrument-catalog-replace").prop("checked", false);
    const status = $("#instrument-catalog-status").empty().append($("<div>").addClass("text-success").text(
      "Added " + result.added.join(", ") + " (" + result.configuration + ") to " + result.system.name + "."
    ));
    appendNotes(status, result.notes);
  }).fail(function(xhr) {
    showInstrumentCatalogStatus(formatError(xhr), "text-danger");
  }).always(function() {
    button.prop("disabled", false);
  });
}

$(document).ready(function() {
  $("#catalog-dialog").on("show.bs.modal", loadCatalogSystems);
  $("#instrument-catalog-dialog").on("show.bs.modal", function() {
    $("#instrument-catalog-status").empty();
    const system = getEditedSystem();
    $("#instrument-catalog-replace").prop("checked", Boolean(system) && hasDefaultInstruments(system));
    loadCatalogInstruments();
  });
  $("#instrument-catalog-entries").on("change", function() {
    $("#instrument-catalog-status").empty();
    renderCatalogInstrumentEntry();
  });
  $("#instrument-catalog-configurations").on("change", renderCatalogConfiguration);
  $("#instrument-catalog-add").click(addCatalogInstrument);
  $("#catalog-systems").on("change", function() {
    $("#catalog-status").empty();
    renderCatalogSystem();
  });
  $("#catalog-members").on("change", "input", renderCatalogInstruments);
  $("#catalog-instruments").on("change", "input", function() {
    catalogUnchecked[$(this).val()] = !$(this).is(":checked");
  });
  $("#catalog-load").click(loadCatalogSystem);
});
