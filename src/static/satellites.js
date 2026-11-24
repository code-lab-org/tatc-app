// Design state: satellites and constellations (and the ground stations and
// target points of analyses), with the satellite editor dialog, validation,
// and import/export of designs.

const DESIGN_STORAGE_KEY = "tatc-design-v2";
const COLORS = ["#e15759", "#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#ff9da7"];

const design = {
  // {system, color, instrumentColors, validation: {status, members, message}},
  // with the chosen color of each instrument (in order; null for the default)
  satellites: [],
  stations: [],
  targets: []
};
let selectedSatellite = -1;
const designListeners = [];

function onDesignChange(listener) {
  designListeners.push(listener);
}

function notifyDesignChange() {
  saveDesign();
  _.forEach(designListeners, function(listener) { listener(); });
}

function getSatellites() {
  return _.map(design.satellites, "system");
}

function getSatelliteColors() {
  return _.map(design.satellites, "color");
}

// Gets the chosen instrument colors of each satellite or constellation (null
// for one with only default colors), as analysis requests expect.
function getInstrumentColors() {
  return _.map(design.satellites, function(item) {
    const count = (item.system.instruments || []).length;
    const colors = _.take(item.instrumentColors || [], count);
    return _.some(colors) ? _.map(colors, function(c) { return c || null; }) : null;
  });
}

// Derives the default color of an instrument from the satellite color, as
// the server does (`tatc_app.czml.instrument_color`): the first instrument
// keeps the satellite color, and others rotate its hue evenly (with a
// minimum saturation, so variants of gray colors stay distinct).
function defaultInstrumentColor(color, index, count) {
  if (index <= 0 || count <= 1) {
    return color;
  }
  const rgb = _.map([1, 3, 5], function(i) { return parseInt(color.substr(i, 2), 16) / 255; });
  const max = _.max(rgb), min = _.min(rgb);
  const lightness = (max + min) / 2;
  let hue = 0, saturation = 0;
  if (max != min) {
    const range = max - min;
    saturation = lightness <= 0.5 ? range / (max + min) : range / (2 - max - min);
    const c = _.map(rgb, function(v) { return (max - v) / range; });
    hue = rgb[0] == max ? c[2] - c[1] : rgb[1] == max ? 2 + c[0] - c[2] : 4 + c[1] - c[0];
    hue = ((hue / 6) % 1 + 1) % 1;
  }
  hue = (hue + index / count) % 1;
  saturation = Math.max(saturation, 0.5);
  const m2 = lightness <= 0.5 ? lightness * (1 + saturation) : lightness + saturation - lightness * saturation;
  const m1 = 2 * lightness - m2;
  function channel(h) {
    h = ((h % 1) + 1) % 1;
    if (h < 1 / 6) { return m1 + (m2 - m1) * h * 6; }
    if (h < 0.5) { return m2; }
    if (h < 2 / 3) { return m1 + (m2 - m1) * (2 / 3 - h) * 6; }
    return m1;
  }
  return "#" + _.map([hue + 1 / 3, hue, hue - 1 / 3], function(h) {
    return _.padStart(Math.round(channel(h) * 255).toString(16), 2, "0");
  }).join("");
}

// Keeps valid colors (`#rrggbb`) of an imported list, and null otherwise.
function importInstrumentColors(colors) {
  return _.map(_.isArray(colors) ? colors : [], function(color) {
    return /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : null;
  });
}

// --- Persistence ---

function exportDesign() {
  return {
    version: 2,
    satellites: _.map(design.satellites, function(item) {
      const exported = { system: item.system, color: item.color };
      if (_.some(item.instrumentColors)) {
        exported.instrumentColors = item.instrumentColors;
      }
      return exported;
    }),
    stations: design.stations,
    targets: design.targets
  };
}

function saveDesign() {
  try {
    window.localStorage.setItem(DESIGN_STORAGE_KEY, JSON.stringify(exportDesign()));
  } catch (e) {
    // storage may be unavailable (for example, in a private window)
  }
}

// Loads a design (or a list of satellites, or a single satellite).
function importDesign(data) {
  let satellites;
  if (_.isArray(data)) {
    satellites = _.map(data, function(system) { return { system: system }; });
  } else if (data && data.satellites) {
    satellites = data.satellites;
  } else if (data && data.orbit) {
    satellites = [{ system: data }];
  } else {
    throw new Error("Unrecognized design file.");
  }
  design.satellites = _.map(satellites, function(item, i) {
    const system = item.system || item;
    if (!system.type) {
      system.type = "satellite";
    }
    return {
      system: system,
      color: item.color || COLORS[i % COLORS.length],
      instrumentColors: importInstrumentColors(item.system ? item.instrumentColors : null),
      validation: { status: "unknown" }
    };
  });
  if (data && data.stations) {
    design.stations = data.stations;
  }
  if (data && data.targets) {
    design.targets = data.targets;
  }
  selectedSatellite = design.satellites.length ? 0 : -1;
  renderSatelliteList();
  _.forEach(design.satellites, validateItem);
  if (typeof renderStations === "function") {
    renderStations();
    renderTargets();
  }
  notifyDesignChange();
}

function defaultDesign() {
  const iss = createSatellite("ISS");
  iss.orbit = { type: "tle", tle: DEFAULT_TLE.slice() };
  iss.instruments = [_.assign(createInstrument("Camera"), { field_of_regard: 100 })];
  return {
    satellites: [{ system: iss, color: COLORS[0] }],
    stations: [
      _.assign(createStation("Svalbard"), { latitude: 78.23, longitude: 15.39 }),
      _.assign(createStation("Wallops"), { latitude: 37.94, longitude: -75.46 }),
      _.assign(createStation("McMurdo"), { latitude: -77.84, longitude: 166.67 })
    ],
    targets: [{ id: 0, latitude: 33.42, longitude: -111.93 }]
  };
}

function loadInitialDesign() {
  let stored = null;
  try {
    stored = JSON.parse(window.localStorage.getItem(DESIGN_STORAGE_KEY));
  } catch (e) {
    stored = null;
  }
  try {
    importDesign(stored && stored.satellites ? stored : defaultDesign());
  } catch (e) {
    importDesign(defaultDesign());
  }
}

// --- Validation ---

// Validates a satellite or constellation with the server.
function validateSystem(system) {
  return $.ajax({
    url: "/validate/space-system",
    type: "POST",
    contentType: "application/json",
    dataType: "json",
    data: JSON.stringify(system)
  });
}

function validateItem(item) {
  item.validation = { status: "pending" };
  renderSatelliteList();
  validateSystem(item.system)
    .done(function(result) {
      item.validation = { status: "valid", members: result.members };
    })
    .fail(function(xhr) {
      item.validation = xhr.status == 401
        ? { status: "unknown" }
        : { status: "invalid", message: formatError(xhr) };
    })
    .always(function() {
      renderSatelliteList();
      // the filter lists the members of validated constellations
      if (typeof renderLayerFilter === "function") {
        renderLayerFilter();
      }
    });
}

// --- Satellite list ---

function describeSystem(system) {
  const platform = PLATFORM_SPECS[system.type || "satellite"];
  const orbit = system.orbit && ORBIT_SPECS[system.orbit.type];
  return (platform ? platform.label : system.type) + (orbit ? ", " + orbit.label : "");
}

function renderSatelliteList() {
  const list = $("#satellites").empty();
  _.forEach(design.satellites, function(item, i) {
    const badge = $("<span>").addClass("badge list-badge ml-1");
    if (item.validation.status == "valid") {
      const count = item.validation.members.length;
      badge.addClass("badge-light").text(count + (count == 1 ? " satellite" : " satellites"));
    } else if (item.validation.status == "invalid") {
      badge.addClass("badge-danger").text("invalid").attr("title", item.validation.message);
    } else if (item.validation.status == "pending") {
      badge.addClass("badge-light").text("…");
    }
    const entry = $("<a href='#'>")
      .addClass("list-group-item list-group-item-action py-1 px-2 small")
      .toggleClass("active", i == selectedSatellite)
      .append(
        $("<i>").addClass("fas fa-satellite mr-2").css("color", item.color),
        $("<span>").text(item.system.name),
        badge,
        $("<div>").addClass("small").css("opacity", 0.7).text(describeSystem(item.system))
      )
      .on("click", function(e) {
        e.preventDefault();
        selectedSatellite = i;
        renderSatelliteList();
      })
      .on("dblclick", function(e) {
        e.preventDefault();
        selectedSatellite = i;
        openSatelliteDialog();
      });
    list.append(entry);
  });
  const hasSelection = selectedSatellite >= 0 && selectedSatellite < design.satellites.length;
  $("#satellite-edit, #satellite-copy, #satellite-delete").prop("disabled", !hasSelection);
}

function uniqueName(name, names) {
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

// --- Satellite dialog ---

let editing = null; // {item, system, color, instrumentColors, instrument}

function openSatelliteDialog() {
  const item = design.satellites[selectedSatellite];
  if (!item) {
    return;
  }
  editing = {
    item: item,
    system: _.cloneDeep(item.system),
    color: item.color,
    instrumentColors: (item.instrumentColors || []).slice(),
    instrument: 0
  };
  $("#satellite-form-tab").tab("show");
  renderSatelliteForm();
  showValidation(item.validation);
  $("#satellite-dialog").modal("show");
}

function renderSatelliteForm() {
  const system = editing.system;
  system.type = system.type || "satellite";
  $("#satellite-name").val(system.name);
  $("#satellite-color").val(editing.color);
  $("#satellite-type").val(system.type);
  renderFields($("#platform-fields"), PLATFORM_SPECS[system.type].fields, system, function(key) {
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
  const known = ["type", "name", "orbit", "instruments"].concat(specKeys(PLATFORM_SPECS[system.type]));
  const extra = _.difference(_.keys(system), known);
  $("#satellite-extra").text(extra.length ? "Also set in JSON: " + extra.join(", ") + "." : "");
}

function renderOrbitForm() {
  const system = editing.system;
  const orbitType = system.orbit ? system.orbit.type : "circular";
  const allowed = PLATFORM_SPECS[system.type].orbits;
  const select = $("#orbit-type").empty();
  _.forEach(allowed, function(type) {
    if (type == "gp" && orbitType != "gp") {
      return; // GP orbits are edited in JSON
    }
    select.append($("<option>").val(type).text(ORBIT_SPECS[type].label));
  });
  select.val(orbitType);
  $("#query-celestrak").toggle(orbitType == "tle");
  renderFields($("#orbit-fields"), ORBIT_SPECS[orbitType].fields, system.orbit, formChanged);
}

function renderInstrumentForm() {
  const system = editing.system;
  if (!system.instruments || system.instruments.length == 0) {
    system.instruments = [createInstrument()];
  }
  editing.instrument = Math.min(editing.instrument, system.instruments.length - 1);
  const list = $("#instruments").empty();
  _.forEach(system.instruments, function(instrument, i) {
    list.append($("<option>").val(i).text(i + ": " + (instrument.name || "Default")));
  });
  list.val(editing.instrument);
  $("#instrument-delete").prop("disabled", system.instruments.length <= 1);
  const instrument = system.instruments[editing.instrument];
  instrument.type = instrument.type || "instrument";
  $("#instrument-type").val(instrument.type);
  const fields = [{ key: "name", label: "Name", type: "text", default: "Default" }]
    .concat(INSTRUMENT_SPECS[instrument.type].fields);
  renderFields($("#instrument-fields"), fields, instrument, function(key) {
    if (key == "name") {
      list.find("option").eq(editing.instrument).text(editing.instrument + ": " + instrument.name);
    }
    formChanged();
  });
  renderInstrumentColor();
}

// Shows the color of the selected instrument: its chosen color, or the
// default derived from the satellite color.
function renderInstrumentColor() {
  const chosen = editing.instrumentColors[editing.instrument];
  const count = editing.system.instruments.length;
  $("#instrument-color").val(chosen || defaultInstrumentColor(editing.color, editing.instrument, count));
  $("#instrument-color-default").prop("checked", !chosen);
}

// Removes, then inserts (a default) instrument colors at an index, to keep
// them aligned with the instruments.
function spliceInstrumentColors(index, removed, inserted) {
  const colors = editing.instrumentColors;
  while (colors.length < index) {
    colors.push(null);
  }
  colors.splice(index, removed);
  for (let i = 0; i < (inserted || 0); i++) {
    colors.splice(index, 0, null);
  }
}

function formChanged() {
  updateSatelliteJson();
  showValidation({ status: "unknown" });
}

function updateSatelliteJson() {
  $("#satellite-json-text").val(JSON.stringify(editing.system, null, 2));
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
    editing.system = system;
    // colors stay with instruments by index
    editing.instrumentColors = _.take(editing.instrumentColors, (system.instruments || []).length);
    renderSatelliteForm();
    return true;
  } catch (e) {
    showValidation({ status: "invalid", message: "JSON: " + e.message });
    return false;
  }
}

function validateEditing() {
  showValidation({ status: "pending" });
  validateSystem(editing.system)
    .done(function(result) {
      showValidation({ status: "valid", members: result.members });
    })
    .fail(function(xhr) {
      showValidation({ status: "invalid", message: formatError(xhr) });
    });
}

function commitSatelliteDialog() {
  if (!editing) {
    return;
  }
  if ($("#satellite-json-tab").hasClass("active")
      && $("#satellite-json-text").val() != JSON.stringify(editing.system, null, 2)
      && !applySatelliteJson()) {
    return;
  }
  const item = editing.item;
  const names = _.map(_.without(design.satellites, item), "system.name");
  editing.system.name = uniqueName(_.trim(editing.system.name) || "Satellite", names);
  const instrumentColors = _.map(
    _.take(editing.instrumentColors, (editing.system.instruments || []).length),
    function(color) { return color || null; }
  );
  const changed = !_.isEqual(item.system, editing.system) || item.color != editing.color
    || !_.isEqual(item.instrumentColors || [], instrumentColors);
  item.system = editing.system;
  item.color = editing.color;
  item.instrumentColors = instrumentColors;
  editing = null;
  renderSatelliteList();
  if (changed) {
    validateItem(item);
    notifyDesignChange();
  }
}

// --- CelesTrak ---

// The server searches a catalog it downloads from CelesTrak at most once
// every two hours (per CelesTrak's usage policy), so queries are not
// forwarded to CelesTrak. Objects with catalog numbers beyond the range of
// two line elements (Alpha-5, up to 339999) have general perturbations orbits.
let celestrakQuery = 0;

function celestrakElementsText(orbit) {
  if (orbit.type == "tle") {
    return orbit.tle.join("\n");
  }
  return JSON.stringify(orbit.elements, null, 2);
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
      $("#celestrak-status").text((xhr.responseJSON && xhr.responseJSON.detail) || "CelesTrak search failed.");
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

  $("#satellite-add").click(function() {
    const names = _.map(design.satellites, "system.name");
    const item = {
      system: createSatellite(uniqueName("New Satellite", names)),
      color: COLORS[design.satellites.length % COLORS.length],
      validation: { status: "unknown" }
    };
    design.satellites.push(item);
    selectedSatellite = design.satellites.length - 1;
    renderSatelliteList();
    openSatelliteDialog();
  });
  $("#satellite-edit").click(openSatelliteDialog);
  $("#satellite-copy").click(function() {
    const item = design.satellites[selectedSatellite];
    const copy = _.cloneDeep(item);
    copy.system.name = uniqueName(item.system.name, _.map(design.satellites, "system.name"));
    design.satellites.splice(selectedSatellite + 1, 0, copy);
    selectedSatellite += 1;
    renderSatelliteList();
    notifyDesignChange();
  });
  $("#satellite-delete").click(function() {
    design.satellites.splice(selectedSatellite, 1);
    selectedSatellite = Math.min(selectedSatellite, design.satellites.length - 1);
    renderSatelliteList();
    notifyDesignChange();
  });

  $("#satellite-name").on("input change", function() {
    editing.system.name = $(this).val();
    formChanged();
  });
  $("#satellite-color").on("change", function() {
    editing.color = $(this).val();
    renderInstrumentColor();
  });
  $("#instrument-color").on("input change", function() {
    editing.instrumentColors[editing.instrument] = $(this).val();
    $("#instrument-color-default").prop("checked", false);
  });
  $("#instrument-color-default").on("change", function() {
    if (this.checked) {
      editing.instrumentColors[editing.instrument] = null;
    } else {
      editing.instrumentColors[editing.instrument] = $("#instrument-color").val();
    }
    renderInstrumentColor();
  });
  $("#satellite-type").on("change", function() {
    const system = editing.system;
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
    editing.system.orbit = createDefault(ORBIT_SPECS[type], type);
    renderOrbitForm();
    formChanged();
  });
  $("#instruments").on("change", function() {
    editing.instrument = Number($(this).val());
    renderInstrumentForm();
  });
  $("#instrument-type").on("change", function() {
    const instruments = editing.system.instruments;
    instruments[editing.instrument] = changeInstrumentType(instruments[editing.instrument], $(this).val());
    renderInstrumentForm();
    formChanged();
  });
  $("#instrument-add").click(function() {
    const instruments = editing.system.instruments;
    instruments.push(createInstrument(uniqueName("Instrument", _.map(instruments, "name"))));
    editing.instrument = instruments.length - 1;
    spliceInstrumentColors(editing.instrument, 1, 1);
    renderInstrumentForm();
    formChanged();
  });
  $("#instrument-copy").click(function() {
    const instruments = editing.system.instruments;
    const copy = _.cloneDeep(instruments[editing.instrument]);
    copy.name = uniqueName(copy.name || "Instrument", _.map(instruments, "name"));
    instruments.splice(editing.instrument + 1, 0, copy);
    // the copy takes a default color, distinct from the original's
    spliceInstrumentColors(editing.instrument + 1, 0, 1);
    editing.instrument += 1;
    renderInstrumentForm();
    formChanged();
  });
  $("#instrument-delete").click(function() {
    const instruments = editing.system.instruments;
    if (instruments.length > 1) {
      instruments.splice(editing.instrument, 1);
      spliceInstrumentColors(editing.instrument, 1);
      renderInstrumentForm();
      formChanged();
    }
  });

  $("#satellite-json-tab").on("show.bs.tab", updateSatelliteJson);
  $("#satellite-form-tab").on("show.bs.tab", function(e) {
    if ($("#satellite-json-text").val() != JSON.stringify(editing.system, null, 2) && !applySatelliteJson()) {
      e.preventDefault();
    }
  });
  $("#satellite-json-apply").click(function() {
    if (applySatelliteJson()) {
      validateEditing();
    }
  });
  $("#satellite-validate").click(function() {
    if (!$("#satellite-json-tab").hasClass("active") || applySatelliteJson()) {
      validateEditing();
    }
  });
  $("#satellite-dialog").on("hide.bs.modal", commitSatelliteDialog);

  // CelesTrak
  $("#celestrak-name").on("input", _.debounce(queryCelestrak, 400));
  $("#celestrak-objects").on("change", function() {
    const option = $(this).find("option:selected");
    const orbit = option.length ? option.data("object").orbit : null;
    $("#celestrak-tle").val(orbit ? celestrakElementsText(orbit) : "").attr("rows", orbit && orbit.type != "tle" ? 8 : 2);
    $("#celestrak-tle-ok").prop("disabled", !option.length);
  });
  $("#celestrak-tle-ok").click(function() {
    const option = $("#celestrak-objects option:selected");
    if (option.length) {
      const object = option.data("object");
      editing.system.orbit = _.cloneDeep(object.orbit);
      if (/^New Satellite/.test(editing.system.name)) {
        editing.system.name = object.name;
        $("#satellite-name").val(editing.system.name);
      }
      renderOrbitForm();
      formChanged();
    }
  });

  // import/export
  $("#design-export").click(function() {
    downloadFile("tatc-design.json", JSON.stringify(exportDesign(), null, 2));
  });
  $("#design-import").on("change", function() {
    const file = this.files[0];
    const input = this;
    if (!file) {
      return;
    }
    file.text().then(function(text) {
      try {
        importDesign(JSON.parse(text));
      } catch (e) {
        alert("Could not import the design: " + e.message);
      }
      input.value = "";
    });
  });
  $("#design-reset").click(function() {
    if (confirm("Replace the current design with the default design?")) {
      importDesign(defaultDesign());
    }
  });

  loadInitialDesign();
  // revalidate once logged in (validation requires a session)
  $(document).ajaxSuccess(function(event, xhr, settings) {
    if (settings.url == "/auth/me") {
      _.forEach(design.satellites, function(item) {
        if (item.validation.status == "unknown") {
          validateItem(item);
        }
      });
    }
  });
});
