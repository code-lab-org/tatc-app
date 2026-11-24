// Design state: satellites and constellations (and the ground stations and
// target points of analyses), with their validation, the list of satellites,
// and persistence, import, and export of designs. The satellite dialog
// (satellite-dialog.js) edits satellites.

const DESIGN_STORAGE_KEY = "tatc-design-v2";
const COLORS = ["#e15759", "#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#76b7b2", "#edc948", "#ff9da7"];

const design = {
  // {system, color, instrumentColors, validation: {status, members, message}},
  // with the chosen color of each instrument (in order; null for the default)
  satellites: [],
  // {name, latitude, longitude, min_elevation_angle, min_access_time}
  stations: [],
  // {latitude, longitude}
  targets: []
};
let selectedSatellite = -1;

// --- Listeners ---

// Called after any change to the design (satellites, or a whole design
// imported); the design is saved first.
const designListeners = [];
// Called after the validation of a satellite or constellation completes.
const validationListeners = [];

function onDesignChange(listener) {
  designListeners.push(listener);
}

function notifyDesignChange() {
  saveDesign();
  _.forEach(designListeners, function(listener) { listener(); });
}

function onValidationChange(listener) {
  validationListeners.push(listener);
}

// --- Accessors ---

function getSatellites() {
  return _.map(design.satellites, "system");
}

function getSatelliteColors() {
  return _.map(design.satellites, "color");
}

// Gets the chosen colors of a number of instruments (null for the default).
function chosenInstrumentColors(colors, count) {
  return _.map(_.take(colors || [], count), function(color) { return color || null; });
}

// Gets the chosen instrument colors of a satellite or constellation, as
// analysis requests expect: null if all are default colors.
function requestInstrumentColors(item) {
  const colors = chosenInstrumentColors(item.instrumentColors, (item.system.instruments || []).length);
  return _.some(colors) ? colors : null;
}

function getInstrumentColors() {
  return _.map(design.satellites, requestInstrumentColors);
}

// Derives the default color of an instrument from the satellite color, as
// the server does (`instrument_color` of the server's CZML colors): the first
// instrument keeps the satellite color, and others rotate its hue evenly
// (with a minimum saturation, so variants of gray colors stay distinct).
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

// Gets the color of an instrument of a satellite or constellation: its
// chosen color, or the default derived from the satellite color.
function instrumentColor(item, index) {
  const chosen = (item.instrumentColors || [])[index];
  return chosen || defaultInstrumentColor(item.color, index, (item.system.instruments || []).length);
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
  notifyDesignChange();
}

function defaultDesign() {
  // a circular orbit like the ISS's (current elements are a CelesTrak
  // search away in the satellite dialog)
  const iss = createSatellite("ISS");
  _.assign(iss.orbit, { mean_altitude: 420e3, inclination: 51.64 });
  iss.instruments = [_.assign(createInstrument("Camera"), { field_of_regard: 100 })];
  return {
    satellites: [{ system: iss, color: COLORS[0] }],
    stations: [
      _.assign(createStation("Svalbard"), { latitude: 78.23, longitude: 15.39 }),
      _.assign(createStation("Wallops"), { latitude: 37.94, longitude: -75.46 }),
      _.assign(createStation("McMurdo"), { latitude: -77.84, longitude: 166.67 })
    ],
    targets: [{ latitude: 33.42, longitude: -111.93 }]
  };
}

// Loads the stored design (or the default design), once every module
// listens to design changes (see main.js).
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
  return postJson("/validate/space-system", system);
}

function validateItem(item) {
  // results of a superseded validation (of an earlier edit) are dropped
  const pending = item.validation = { status: "pending" };
  renderSatelliteList();
  function settle(validation) {
    if (item.validation !== pending) {
      return;
    }
    item.validation = validation;
    renderSatelliteList();
    _.forEach(validationListeners, function(listener) { listener(item); });
  }
  validateSystem(item.system)
    .done(function(result) {
      settle({ status: "valid", members: result.members });
    })
    .fail(function(xhr) {
      settle(xhr.status == 401 ? { status: "unknown" } : { status: "invalid", message: formatError(xhr) });
    });
}

// Validates the satellites not yet validated (validation requires a session).
function validateUnknownItems() {
  _.forEach(design.satellites, function(item) {
    if (item.validation.status == "unknown") {
      validateItem(item);
    }
  });
}

// --- Satellite list ---

function describeSystem(system) {
  const platform = PLATFORM_SPECS[system.type];
  const orbit = system.orbit && ORBIT_SPECS[system.orbit.type];
  return (platform ? platform.label : system.type) + (orbit ? ", " + orbit.label : "");
}

function validationBadge(validation) {
  const badge = $("<span>").addClass("badge list-badge ml-1");
  if (validation.status == "valid") {
    const count = validation.members.length;
    badge.addClass("badge-light").text(count + (count == 1 ? " satellite" : " satellites"));
  } else if (validation.status == "invalid") {
    badge.addClass("badge-danger").text("invalid").attr("title", validation.message);
  } else if (validation.status == "pending") {
    badge.addClass("badge-light").text("…");
  }
  return badge;
}

function renderSatelliteList() {
  renderSelectableList($("#satellites"), design.satellites, selectedSatellite, {
    buttons: "#satellite-edit, #satellite-copy, #satellite-delete",
    renderItem: function(item) {
      return [
        $("<i>").addClass("fas fa-satellite mr-2").css("color", item.color),
        $("<span>").text(item.system.name),
        validationBadge(item.validation),
        $("<div>").addClass("small").css("opacity", 0.7).text(describeSystem(item.system))
      ];
    },
    onSelect: function(i) {
      selectedSatellite = i;
      renderSatelliteList();
    },
    onOpen: function(i) {
      selectedSatellite = i;
      openSatelliteDialog();
    }
  });
}

// Adds satellites or constellations to the design (in one color: by default,
// the next of the palette) with unique names, selects the first, and
// validates them. Returns the added items.
function addSatellites(systems, color) {
  color = color || COLORS[design.satellites.length % COLORS.length];
  const names = _.map(design.satellites, "system.name");
  const items = _.map(systems, function(system) {
    system.name = uniqueName(system.name, names);
    names.push(system.name);
    return { system: system, color: color, validation: { status: "unknown" } };
  });
  selectedSatellite = design.satellites.length;
  design.satellites = design.satellites.concat(items);
  renderSatelliteList();
  _.forEach(items, validateItem);
  notifyDesignChange();
  return items;
}

$(document).ready(function() {
  $("#satellite-add").click(function() {
    addSatellites([createSatellite("New Satellite")]);
    openSatelliteDialog();
  });
  $("#satellite-edit").click(openSatelliteDialog);
  $("#satellite-copy").click(function() {
    const item = design.satellites[selectedSatellite];
    const copy = _.cloneDeep(item);
    copy.system.name = uniqueName(item.system.name, _.map(design.satellites, "system.name"));
    design.satellites.splice(selectedSatellite + 1, 0, copy);
    selectedSatellite += 1;
    // the copy's members have its new name (and the original may be validating)
    validateItem(copy);
    notifyDesignChange();
  });
  $("#satellite-delete").click(function() {
    selectedSatellite = removeSelected(design.satellites, selectedSatellite);
    renderSatelliteList();
    notifyDesignChange();
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
});
