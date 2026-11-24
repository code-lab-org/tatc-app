// Satellite dialog: edits a satellite or constellation of the design with
// forms (schemas.js) or JSON, validates it, and searches CelesTrak for
// orbital elements.

// The satellite being edited (null when the dialog is closed): {item,
// system, color, instrumentColors, instrument, revision}, with a copy of the
// item's system and colors (committed when the dialog closes), the index of
// the selected instrument, and a count of changes to the system.
let satelliteEditor = null;

// Gets the system being edited, or null if the dialog is closed.
function getEditedSystem() {
  return satelliteEditor ? satelliteEditor.system : null;
}

// Gets a token of the current edit, to check that the response of a request
// about the edited system still applies (see `isCurrentEdit`).
function currentEdit() {
  return satelliteEditor && { editor: satelliteEditor, revision: satelliteEditor.revision };
}

// Whether the dialog still edits the same system as when a token was taken:
// the same satellite, without changes since.
function isCurrentEdit(edit) {
  return Boolean(edit) && edit.editor === satelliteEditor && edit.revision == satelliteEditor.revision;
}

// Replaces the system being edited (for example, with added catalog
// instruments), selecting an instrument: the first added one.
function replaceEditedSystem(system, selectedInstrument) {
  satelliteEditor.system = system;
  satelliteEditor.instrument = selectedInstrument;
  if (selectedInstrument == 0) {
    // the added instruments replaced all others (and their colors)
    satelliteEditor.instrumentColors = [];
  }
  renderSatelliteForm();
  formChanged();
}

function openSatelliteDialog() {
  const item = design.satellites[selectedSatellite];
  if (!item) {
    return;
  }
  satelliteEditor = {
    item: item,
    system: _.cloneDeep(item.system),
    color: item.color,
    instrumentColors: (item.instrumentColors || []).slice(),
    instrument: 0,
    revision: 0
  };
  $("#satellite-form-tab").tab("show");
  renderSatelliteForm();
  showValidation(item.validation);
  $("#satellite-dialog").modal("show");
}

// Selects a type in a type select, with an option for a type without a form.
function selectType(select, type, specs) {
  select.find("option.json-only").remove();
  if (!specs[type]) {
    select.append($("<option>").addClass("json-only").val(type).text(specOf(specs, type).label));
  }
  select.val(type);
}

function renderSatelliteForm() {
  const system = satelliteEditor.system;
  const spec = specOf(PLATFORM_SPECS, system.type);
  $("#satellite-name").val(system.name);
  $("#satellite-color").val(satelliteEditor.color);
  selectType($("#satellite-type"), system.type, PLATFORM_SPECS);
  renderFields($("#platform-fields"), spec.fields, system, function(key) {
    if (key == "configuration") {
      if (system.configuration != "star") {
        delete system.seam_spacing;
      }
      renderSatelliteForm();
    }
    formChanged();
  });
  renderOrbitForm();
  renderInstrumentForm();
  updateSatelliteJson();
  const known = ["type", "name", "orbit", "instruments"].concat(specKeys(spec));
  const extra = _.difference(_.keys(system), known);
  $("#satellite-extra").text(extra.length ? "Also set in JSON: " + extra.join(", ") + "." : "");
}

function renderOrbitForm() {
  const system = satelliteEditor.system;
  const orbitType = system.orbit ? system.orbit.type : "circular";
  // orbits without a form are only listed if the orbit has one
  const types = _.filter(specOf(PLATFORM_SPECS, system.type).orbits, function(type) {
    return !ORBIT_SPECS[type].jsonOnly || type == orbitType;
  });
  if (!_.includes(types, orbitType)) {
    types.push(orbitType);
  }
  const select = $("#orbit-type").empty();
  _.forEach(types, function(type) {
    select.append($("<option>").val(type).text(specOf(ORBIT_SPECS, type).label));
  });
  select.val(orbitType);
  $("#query-celestrak").toggle(orbitType == "tle" || orbitType == "gp");
  renderFields($("#orbit-fields"), specOf(ORBIT_SPECS, orbitType).fields, system.orbit, formChanged);
}

function renderInstrumentForm() {
  const system = satelliteEditor.system;
  if (!system.instruments || system.instruments.length == 0) {
    system.instruments = [createInstrument()];
  }
  satelliteEditor.instrument = Math.min(satelliteEditor.instrument, system.instruments.length - 1);
  const list = $("#instruments").empty();
  _.forEach(system.instruments, function(instrument, i) {
    list.append($("<option>").val(i).text(i + ": " + (instrument.name || "Default")));
  });
  list.val(satelliteEditor.instrument);
  $("#instrument-delete").prop("disabled", system.instruments.length <= 1);
  const instrument = system.instruments[satelliteEditor.instrument];
  // an instrument without a type keeps it implicit (as the library infers it)
  const type = instrumentType(instrument);
  selectType($("#instrument-type"), type, INSTRUMENT_SPECS);
  const fields = [{ key: "name", label: "Name", type: "text", default: "Default" }]
    .concat(specOf(INSTRUMENT_SPECS, type).fields);
  renderFields($("#instrument-fields"), fields, instrument, function(key) {
    if (key == "name") {
      list.find("option").eq(satelliteEditor.instrument).text(satelliteEditor.instrument + ": " + instrument.name);
    }
    formChanged();
  });
  renderInstrumentColor();
}

// Shows the color of the selected instrument: its chosen color, or the
// default derived from the satellite color.
function renderInstrumentColor() {
  const chosen = satelliteEditor.instrumentColors[satelliteEditor.instrument];
  const count = satelliteEditor.system.instruments.length;
  $("#instrument-color").val(chosen || defaultInstrumentColor(satelliteEditor.color, satelliteEditor.instrument, count));
  $("#instrument-color-default").prop("checked", !chosen);
}

// Removes, then inserts (a default) instrument colors at an index, to keep
// them aligned with the instruments.
function spliceInstrumentColors(index, removed, inserted) {
  const colors = satelliteEditor.instrumentColors;
  while (colors.length < index) {
    colors.push(null);
  }
  colors.splice(index, removed);
  for (let i = 0; i < (inserted || 0); i++) {
    colors.splice(index, 0, null);
  }
}

function formChanged() {
  satelliteEditor.revision += 1;
  updateSatelliteJson();
  showValidation({ status: "unknown" });
}

function updateSatelliteJson() {
  $("#satellite-json-text").val(JSON.stringify(satelliteEditor.system, null, 2));
}

function showValidation(validation) {
  const container = $("#satellite-validation").empty();
  if (!validation || validation.status == "unknown") {
    container.append($("<span>").addClass("text-muted").text("Not yet validated."));
  } else if (validation.status == "pending") {
    container.append($("<span>").addClass("text-muted").text("Validating…"));
  } else if (validation.status == "invalid") {
    container.append(
      $("<div>").addClass("text-danger").text("Invalid:"),
      $("<pre>").addClass("text-danger small mb-0").text(validation.message)
    );
  } else {
    const members = validation.members;
    container.append($("<div>").addClass("text-success").text(
      "Valid: " + members.length + (members.length == 1 ? " satellite." : " member satellites.")
    ));
    const table = $("<table>").addClass("table table-sm small mb-0").append(
      $("<thead>").append($("<tr>").append(
        $("<th>").text("Name"), $("<th>").text("Altitude (km)"),
        $("<th>").text("Inclination (°)"), $("<th>").text("Period (min)")
      ))
    );
    const body = $("<tbody>");
    _.forEach(_.take(members, 8), function(member) {
      body.append($("<tr>").append(
        $("<td>").text(member.name),
        $("<td>").text(member.altitude === null ? "" : formatNumber(member.altitude / 1000, 1)),
        $("<td>").text(member.inclination === null ? "" : formatNumber(member.inclination, 2)),
        $("<td>").text(member.period === null ? "" : formatNumber(member.period / 60, 1))
      ));
    });
    if (members.length > 8) {
      body.append($("<tr>").append($("<td colspan='4'>").text("… and " + (members.length - 8) + " more")));
    }
    container.append(table.append(body));
  }
}

// Applies the JSON editor's text, returning false if it is not valid JSON.
function applySatelliteJson() {
  try {
    const system = JSON.parse($("#satellite-json-text").val());
    if (!_.isPlainObject(system)) {
      throw new Error("The JSON must be an object.");
    }
    system.type = system.type || "satellite";
    if (!PLATFORM_SPECS[system.type]) {
      throw new Error("Unknown type: " + system.type);
    }
    const changed = !_.isEqual(system, satelliteEditor.system);
    satelliteEditor.system = system;
    // colors stay with instruments by index
    satelliteEditor.instrumentColors = _.take(satelliteEditor.instrumentColors, (system.instruments || []).length);
    renderSatelliteForm();
    if (changed) {
      formChanged();
    }
    return true;
  } catch (e) {
    showValidation({ status: "invalid", message: "JSON: " + e.message });
    return false;
  }
}

function validateEditedSystem() {
  // results of an earlier edit (or satellite) are ignored
  const edit = currentEdit();
  showValidation({ status: "pending" });
  validateSystem(satelliteEditor.system)
    .done(function(result) {
      if (isCurrentEdit(edit)) {
        showValidation({ status: "valid", members: result.members });
      }
    })
    .fail(function(xhr) {
      if (isCurrentEdit(edit)) {
        showValidation({ status: "invalid", message: formatError(xhr) });
      }
    });
}

// Whether the JSON tab shows changes not yet applied to the edited system.
function hasUnappliedJson() {
  return $("#satellite-json-text").val() != JSON.stringify(satelliteEditor.system, null, 2);
}

function commitSatelliteDialog() {
  if (!satelliteEditor) {
    return;
  }
  if ($("#satellite-json-tab").hasClass("active") && hasUnappliedJson() && !applySatelliteJson()) {
    return;
  }
  const item = satelliteEditor.item;
  const system = satelliteEditor.system;
  system.name = uniqueName(system.name, _.map(_.without(design.satellites, item), "system.name"), "Satellite");
  const instrumentColors = chosenInstrumentColors(satelliteEditor.instrumentColors, (system.instruments || []).length);
  const changed = !_.isEqual(item.system, system) || item.color != satelliteEditor.color
    || !_.isEqual(item.instrumentColors || [], instrumentColors);
  item.system = system;
  item.color = satelliteEditor.color;
  item.instrumentColors = instrumentColors;
  satelliteEditor = null;
  renderSatelliteList();
  if (changed) {
    validateItem(item);
    notifyDesignChange();
  }
}

// --- CelesTrak ---

// The server searches a catalog it downloads from CelesTrak at most once
// every two hours (per CelesTrak's usage policy), so queries are not
// forwarded to CelesTrak. Objects have general perturbations orbits (from
// orbit mean-elements messages) and, if their catalog numbers are within the
// range of two line elements (Alpha-5, up to 339999), also TLE.
let celestrakQuery = 0;

// Gets the orbit of a CelesTrak object in the format of the edited orbit:
// OMM (a general perturbations orbit), or TLE if the object has them.
function celestrakOrbit(object) {
  const orbit = satelliteEditor.system.orbit;
  return orbit && orbit.type == "gp" ? object.gp_orbit : object.orbit;
}

function celestrakElementsText(orbit) {
  if (orbit.type == "tle") {
    return orbit.tle.join("\n");
  }
  return elementsToOmm(orbit.elements);
}

function queryCelestrak() {
  const query = _.trim($("#celestrak-name").val());
  const queryId = ++celestrakQuery;
  $("#celestrak-objects").empty();
  $("#celestrak-tle").val("").attr("rows", 2);
  $("#celestrak-tle-ok").prop("disabled", true);
  if (query.length < 3 && !/^\d+$/.test(query)) {
    $("#celestrak-status").text("");
    return;
  }
  $("#celestrak-status").text("Searching...");
  $.get("/celestrak/search", { query: query }).done(function(response) {
    if (queryId != celestrakQuery) {
      return;
    }
    _.forEach(response.objects, function(object) {
      const label = object.name + " (" + object.norad_cat_id + (object.object_id ? ", " + object.object_id : "") + ")";
      $("#celestrak-objects").append($("<option>").text(label).data("object", object));
    });
    let status = response.total == response.objects.length
      ? response.total + (response.total == 1 ? " object" : " objects") + " found"
      : "Showing " + response.objects.length + " of " + response.total + " objects found";
    if (response.downloaded) {
      status += " in the CelesTrak " + response.group + " group, downloaded "
        + response.downloaded.substring(0, 16).replace("T", " ") + " UTC (refreshed at most every 2 hours)";
    }
    $("#celestrak-status").text(status + ".");
  }).fail(function(xhr) {
    if (queryId == celestrakQuery) {
      $("#celestrak-status").text(formatError(xhr));
    }
  });
}

$(document).ready(function() {
  _.forEach(PLATFORM_SPECS, function(spec, type) {
    $("#satellite-type").append($("<option>").val(type).text(spec.label));
  });
  _.forEach(INSTRUMENT_SPECS, function(spec, type) {
    $("#instrument-type").append($("<option>").val(type).text(spec.label));
  });

  $("#satellite-name").on("input change", function() {
    satelliteEditor.system.name = $(this).val();
    formChanged();
  });
  $("#satellite-color").on("change", function() {
    satelliteEditor.color = $(this).val();
    renderInstrumentColor();
  });
  $("#instrument-color").on("input change", function() {
    satelliteEditor.instrumentColors[satelliteEditor.instrument] = $(this).val();
    $("#instrument-color-default").prop("checked", false);
  });
  $("#instrument-color-default").on("change", function() {
    satelliteEditor.instrumentColors[satelliteEditor.instrument] = this.checked ? null : $("#instrument-color").val();
    renderInstrumentColor();
  });
  $("#satellite-type").on("change", function() {
    const system = satelliteEditor.system;
    changeType(system, PLATFORM_SPECS, $(this).val());
    const allowed = PLATFORM_SPECS[system.type].orbits;
    if (!system.orbit || !_.includes(allowed, system.orbit.type)) {
      system.orbit = createDefault(ORBIT_SPECS[allowed[0]], allowed[0]);
    }
    renderSatelliteForm();
    formChanged();
  });
  $("#orbit-type").on("change", function() {
    const type = $(this).val();
    satelliteEditor.system.orbit = createDefault(specOf(ORBIT_SPECS, type), type);
    renderOrbitForm();
    formChanged();
  });
  $("#instruments").on("change", function() {
    satelliteEditor.instrument = Number($(this).val());
    renderInstrumentForm();
  });
  $("#instrument-type").on("change", function() {
    const instruments = satelliteEditor.system.instruments;
    instruments[satelliteEditor.instrument] = changeInstrumentType(instruments[satelliteEditor.instrument], $(this).val());
    renderInstrumentForm();
    formChanged();
  });
  $("#instrument-add").click(function() {
    const instruments = satelliteEditor.system.instruments;
    instruments.push(createInstrument(uniqueName("Instrument", _.map(instruments, "name"))));
    satelliteEditor.instrument = instruments.length - 1;
    spliceInstrumentColors(satelliteEditor.instrument, 1, 1);
    renderInstrumentForm();
    formChanged();
  });
  $("#instrument-copy").click(function() {
    const instruments = satelliteEditor.system.instruments;
    const copy = _.cloneDeep(instruments[satelliteEditor.instrument]);
    copy.name = uniqueName(copy.name, _.map(instruments, "name"), "Instrument");
    instruments.splice(satelliteEditor.instrument + 1, 0, copy);
    // the copy takes a default color, distinct from the original's
    spliceInstrumentColors(satelliteEditor.instrument + 1, 0, 1);
    satelliteEditor.instrument += 1;
    renderInstrumentForm();
    formChanged();
  });
  $("#instrument-delete").click(function() {
    const instruments = satelliteEditor.system.instruments;
    if (instruments.length > 1) {
      instruments.splice(satelliteEditor.instrument, 1);
      spliceInstrumentColors(satelliteEditor.instrument, 1);
      renderInstrumentForm();
      formChanged();
    }
  });

  $("#satellite-json-tab").on("show.bs.tab", updateSatelliteJson);
  $("#satellite-form-tab").on("show.bs.tab", function(e) {
    if (hasUnappliedJson() && !applySatelliteJson()) {
      e.preventDefault();
    }
  });
  $("#satellite-json-apply").click(function() {
    if (applySatelliteJson()) {
      validateEditedSystem();
    }
  });
  $("#satellite-validate").click(function() {
    if (!$("#satellite-json-tab").hasClass("active") || applySatelliteJson()) {
      validateEditedSystem();
    }
  });
  $("#satellite-dialog").on("hide.bs.modal", commitSatelliteDialog);

  // CelesTrak
  $("#celestrak-name").on("input", _.debounce(queryCelestrak, 400));
  // the elements of a selected object are shown in the edited orbit's format
  $("#celestrak-dialog").on("show.bs.modal", function() {
    $("#celestrak-objects").trigger("change");
  });
  $("#celestrak-objects").on("change", function() {
    const option = $(this).find("option:selected");
    const orbit = option.length ? celestrakOrbit(option.data("object")) : null;
    $("#celestrak-tle").val(orbit ? celestrakElementsText(orbit) : "").attr("rows", orbit && orbit.type != "tle" ? 8 : 2);
    $("#celestrak-tle-ok").prop("disabled", !option.length);
  });
  $("#celestrak-tle-ok").click(function() {
    const option = $("#celestrak-objects option:selected");
    if (option.length) {
      const object = option.data("object");
      satelliteEditor.system.orbit = _.cloneDeep(celestrakOrbit(object));
      if (/^New Satellite/.test(satelliteEditor.system.name)) {
        satelliteEditor.system.name = object.name;
        $("#satellite-name").val(satelliteEditor.system.name);
      }
      renderOrbitForm();
      formChanged();
    }
  });
});
