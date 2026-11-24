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
  const select = $("#catalog-systems").empty();
  _.forEach(SYSTEM_CLASS_LABELS, function(label, systemClass) {
    const group = $("<optgroup>").attr("label", label);
    _.forEach(_.filter(catalogSystems, { system_class: systemClass }), function(system) {
      const active = _.filter(system.spacecraft, isActive).length;
      group.append($("<option>").val(system.id).text(
        system.name + " (" + active + " of " + system.spacecraft.length + " active)"
      ));
    });
    if (group.children().length) {
      select.append(group);
    }
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
  details.append(
    $("<div>").text(
      system.operator + " · " + (system.role == "transmitting" ? "navigation (transmitting)" : "observing")
      + " · validation: " + system.tier
    ),
    $("<div>").text(system.selection)
  );
  if (system.limitations.length) {
    details.append($("<div>").text("Limitations: " + system.limitations.join(" ")));
  }
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

// Adds the satellites of a system to the design, in one color.
function addCatalogSatellites(result) {
  const color = COLORS[design.satellites.length % COLORS.length];
  const names = _.map(design.satellites, "system.name");
  const items = _.map(result.satellites, function(system) {
    system.name = uniqueName(system.name, names);
    names.push(system.name);
    return { system: system, color: color, validation: { status: "unknown" } };
  });
  selectedSatellite = design.satellites.length;
  design.satellites = design.satellites.concat(items);
  renderSatelliteList();
  _.forEach(items, validateItem);
  notifyDesignChange();
  return items.length;
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
  $.ajax({
    url: "/catalog/systems/" + encodeURIComponent(system.id) + "/build",
    type: "POST",
    contentType: "application/json",
    dataType: "json",
    data: JSON.stringify({
      members: _.map(members, "id"),
      instruments: getCatalogInstruments(),
      time_step: Number($("#catalog-time-step").val()),
      start: period.start.toISOString(),
      end: period.end.toISOString()
    })
  }).done(function(result) {
    showCatalogResult(result, addCatalogSatellites(result));
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
  const select = $("#instrument-catalog-entries").empty();
  _.forEach(INSTRUMENT_CLASS_LABELS, function(label, instrumentClass) {
    const group = $("<optgroup>").attr("label", label);
    _.forEach(_.sortBy(_.filter(catalogInstruments, { instrument_class: instrumentClass }), "name"), function(entry) {
      group.append($("<option>").val(entry.id).text(entry.name + " (" + entry.platforms.join(", ") + ")"));
    });
    if (group.children().length) {
      select.append(group);
    }
  });
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
  details.append(
    $("<div>").text("Carried by " + entry.platforms.join(", ") + " · validation: " + entry.tier),
    $("<div>").text(entry.selection)
  );
  if (entry.limitations.length) {
    details.append($("<div>").text("Limitations: " + entry.limitations.join(" ")));
  }
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
  if (!entry || !editing) {
    return;
  }
  const period = getAnalysisPeriod();
  const button = $("#instrument-catalog-add").prop("disabled", true);
  showInstrumentCatalogStatus("Adding " + entry.name + "…");
  $.ajax({
    url: "/catalog/instruments/" + encodeURIComponent(entry.id) + "/add",
    type: "POST",
    contentType: "application/json",
    dataType: "json",
    data: JSON.stringify({
      system: editing.system,
      configuration: $("#instrument-catalog-configurations").val(),
      time_step: Number($("#instrument-catalog-time-step").val()),
      start: period.start.toISOString(),
      end: period.end.toISOString(),
      replace: $("#instrument-catalog-replace").is(":checked")
    })
  }).done(function(result) {
    if (!editing) {
      return;
    }
    if (result.attitude_changed && !confirm(
      "Adding " + entry.name + " sets the satellite's attitude to the attitude it was validated with, "
      + "which also orients the satellite's other instruments. Add it?"
    )) {
      showInstrumentCatalogStatus(entry.name + " was not added.");
      return;
    }
    editing.system = result.system;
    editing.instrument = result.system.instruments.length - result.added.length;
    if (editing.instrument == 0) {
      // the added instruments replaced all others (and their colors)
      editing.instrumentColors = [];
    }
    renderSatelliteForm();
    formChanged();
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
    $("#instrument-catalog-replace").prop("checked", Boolean(editing) && hasDefaultInstruments(editing.system));
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
