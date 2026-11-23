// System catalog: loads the satellites of past and present programs from the
// TAT-C system catalog. The server replaces their cataloged (idealized)
// orbits with current general perturbations (GP) elements from CelesTrak, so
// that satellites are coordinated across systems; it takes them from its
// cached CelesTrak group or narrow queries for each other satellite, each
// cached for two hours (per CelesTrak's usage policy).

const SYSTEM_CLASS_LABELS = {
  sun_synchronous: "Sun-Synchronous",
  inclined: "Inclined",
  geostationary: "Geostationary"
};

let catalogSystems = null;
let catalogUnchecked = {}; // instruments the user unchecked, by identifier

function showCatalogStatus(text, className) {
  $("#catalog-status").empty().append($("<div>").addClass(className || "text-muted").text(text));
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
  if (result.warnings.length) {
    const list = $("<ul>").addClass("mb-0 pl-3");
    _.forEach(result.warnings, function(warning) {
      list.append($("<li>").text(warning));
    });
    status.append($("<div>").addClass("mt-1").text("Notes:"), list);
  }
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

$(document).ready(function() {
  $("#catalog-dialog").on("show.bs.modal", loadCatalogSystems);
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
