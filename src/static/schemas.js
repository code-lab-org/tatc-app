// Declarative specifications of the space-domain schemas of the TAT-C library
// (version 3.7): satellites and constellations, orbits, and instruments, with
// the units of form fields and their conversion to the library's SI units.
//
// Field properties:
//   key:      property path in the schema object (e.g. "ascending_node.time")
//   label:    form label
//   type:     number | integer | text | select | checkbox | datetime | time |
//             duration | tle | omm | note
//   unit:     unit displayed in the form
//   scale:    SI value per form unit (default 1), e.g. 1000 for km -> m
//   min, max, step: input constraints (form units)
//   default:  default value (SI units), or a function returning it
//   optional: if true, a blank input removes the property (library default)
//   options:  for selects, a list of {value, label} (values may be any JSON)
//   showIf:   optional function(object) to show the field conditionally
//   help:     optional tooltip
//
// Specs with `jsonOnly` have no form: their objects are edited in the JSON
// tab of the satellite dialog.

// placeholder elements (of the ISS in 2021) for a new TLE orbit, to replace
// with current elements (for example, from CelesTrak)
const DEFAULT_TLE = [
  "1 25544U 98067A   21156.30527927  .00003432  00000-0  70541-4 0  9993",
  "2 25544  51.6455  41.4969 0003508  68.0432  78.3395 15.48957534286754"
];

// the same placeholder elements as an orbit mean-elements message (OMM), for
// a new general perturbations orbit
const DEFAULT_OMM = {
  OBJECT_NAME: "ISS (ZARYA)", OBJECT_ID: "1998-067A", EPOCH: "2021-06-05T07:19:36.128928",
  MEAN_MOTION: 15.48957534, ECCENTRICITY: 0.0003508, INCLINATION: 51.6455, RA_OF_ASC_NODE: 41.4969,
  ARG_OF_PERICENTER: 68.0432, MEAN_ANOMALY: 78.3395, EPHEMERIS_TYPE: 0, CLASSIFICATION_TYPE: "U",
  NORAD_CAT_ID: 25544, ELEMENT_SET_NO: 999, REV_AT_EPOCH: 28675, BSTAR: 7.0541e-5,
  MEAN_MOTION_DOT: 3.432e-5, MEAN_MOTION_DDOT: 0
};

function defaultEpoch() {
  const date = new Date();
  date.setUTCHours(0, 0, 0, 0);
  return date.toISOString();
}

const ANGLE = { unit: "°", step: "any" };
const SUNLIT_OPTIONS = [
  { value: null, label: "(Any)" },
  { value: true, label: "Sunlit" },
  { value: false, label: "Eclipse" }
];

const EPOCH_FIELD = { key: "epoch", label: "Epoch (UTC)", type: "datetime", default: defaultEpoch };
const RAAN_FIELD = _.assign({ key: "right_ascension_ascending_node", label: "RAAN", type: "number", min: 0, max: 360, default: 0, help: "Right ascension of the ascending node" }, ANGLE);
const TA_FIELD = _.assign({ key: "true_anomaly", label: "True anomaly", type: "number", min: 0, max: 360, default: 0 }, ANGLE);
const INCLINATION_FIELD = _.assign({ key: "inclination", label: "Inclination", type: "number", min: 0, max: 180, default: 0 }, ANGLE);

const ORBIT_SPECS = {
  tle: {
    label: "Two Line Elements (TLE)",
    fields: [{ key: "tle", label: "Two line elements", type: "tle", default: function() { return DEFAULT_TLE.slice(); } }]
  },
  // general perturbations orbits, edited as orbit mean-elements messages,
  // which (unlike TLE) support catalog numbers beyond 5 characters
  gp: {
    label: "Orbit Mean-Elements Message (OMM)",
    fields: [
      {
        key: "elements", label: "Orbit mean-elements message", type: "omm",
        default: function() { return ommToElements(JSON.stringify(DEFAULT_OMM)); },
        help: "OMM in JSON, CSV, XML, or KVN format (as from CelesTrak or Space-Track), with one or more element sets. "
          + "Catalog numbers beyond 339999, which SGP4 does not support, are replaced by 0."
      },
      { type: "note", label: "Other settings of general perturbations (GP) orbits, such as removing drag, are edited in the JSON tab." }
    ]
  },
  circular: {
    label: "Circular",
    fields: [
      EPOCH_FIELD,
      { key: "mean_altitude", label: "Altitude", type: "number", unit: "km", scale: 1000, min: 0, step: "any", default: 500e3 },
      INCLINATION_FIELD,
      RAAN_FIELD,
      TA_FIELD
    ]
  },
  sso: {
    label: "Sun Synchronous",
    fields: [
      EPOCH_FIELD,
      { key: "mean_altitude", label: "Altitude", type: "number", unit: "km", scale: 1000, min: 0, max: 5980, step: "any", default: 705e3 },
      { key: "equator_crossing_time", label: "Equator crossing", type: "time", default: "10:30:00", help: "Local solar time of the equator crossing" },
      { key: "equator_crossing_ascending", label: "Direction", type: "select", default: false, options: [{ value: true, label: "Ascending" }, { value: false, label: "Descending" }] },
      TA_FIELD
    ]
  },
  keplerian: {
    label: "Keplerian",
    fields: [
      EPOCH_FIELD,
      { key: "semimajor_axis", label: "Semimajor axis", type: "number", unit: "km", scale: 1000, min: 6378, step: "any", default: 7000e3 },
      { key: "eccentricity", label: "Eccentricity", type: "number", min: 0, max: 0.999999, step: "any", default: 0 },
      INCLINATION_FIELD,
      _.assign({ key: "perigee_argument", label: "Perigee argument", type: "number", min: 0, max: 360, default: 0 }, ANGLE),
      RAAN_FIELD,
      TA_FIELD
    ]
  },
  geosynchronous: {
    label: "Geosynchronous",
    fields: [
      EPOCH_FIELD,
      _.assign({ key: "longitude", label: "Longitude", type: "number", min: -180, max: 180, default: -75 }, ANGLE),
      INCLINATION_FIELD
    ]
  },
  molniya: {
    label: "Molniya",
    fields: [
      EPOCH_FIELD,
      { key: "perigee_altitude", label: "Perigee altitude", type: "number", unit: "km", scale: 1000, min: 0, step: "any", default: 600e3 },
      { key: "northern_coverage", label: "Northern coverage", type: "checkbox", default: true },
      _.assign({ key: "inclination", label: "Inclination", type: "number", min: 0, max: 180, optional: true, help: "Blank for the critical inclination" }, ANGLE),
      RAAN_FIELD,
      TA_FIELD
    ]
  },
  tundra: {
    label: "Tundra",
    fields: [
      EPOCH_FIELD,
      { key: "perigee_altitude", label: "Perigee altitude", type: "number", unit: "km", scale: 1000, min: 0, step: "any", default: 25000e3 },
      { key: "northern_coverage", label: "Northern coverage", type: "checkbox", default: true },
      _.assign({ key: "inclination", label: "Inclination", type: "number", min: 0, max: 180, optional: true, help: "Blank for the critical inclination" }, ANGLE),
      RAAN_FIELD,
      TA_FIELD
    ]
  },
  repeat: {
    label: "Repeat Ground Track",
    fields: [
      { key: "revolutions", label: "Revolutions", type: "integer", min: 1, default: 233, help: "Orbital revolutions per repeat cycle" },
      { key: "days", label: "Days", type: "integer", min: 1, default: 16, help: "Days per repeat cycle" },
      _.assign({ key: "inclination", label: "Inclination", type: "number", min: 0, max: 180, optional: true, help: "Blank for a sun-synchronous orbit" }, ANGLE),
      { key: "ascending_node.time", label: "Node time (UTC)", type: "datetime", default: defaultEpoch, help: "Time of an ascending node" },
      _.assign({ key: "ascending_node.longitude", label: "Node longitude", type: "number", min: -180, max: 180, default: 0 }, ANGLE)
    ]
  }
};
const ALL_ORBITS = _.keys(ORBIT_SPECS);

const PLATFORM_SPECS = {
  satellite: { label: "Satellite", orbits: ALL_ORBITS, fields: [] },
  walker: {
    label: "Walker Constellation",
    orbits: ALL_ORBITS,
    fields: [
      { key: "configuration", label: "Configuration", type: "select", default: "delta", options: [{ value: "delta", label: "Delta" }, { value: "star", label: "Star" }] },
      { key: "number_satellites", label: "Satellites", type: "integer", min: 1, default: 4 },
      { key: "number_planes", label: "Planes", type: "integer", min: 1, default: 2 },
      { key: "relative_spacing", label: "Relative spacing", type: "integer", min: 0, default: 0, help: "Walker phasing parameter (less than the number of planes)" },
      _.assign({ key: "seam_spacing", label: "Seam spacing", type: "number", min: 0, max: 180, optional: true, showIf: function(o) { return o.configuration == "star"; }, help: "Blank for uniform spacing" }, ANGLE)
    ]
  },
  train: {
    label: "Train Constellation",
    orbits: ALL_ORBITS,
    fields: [
      { key: "number_satellites", label: "Satellites", type: "integer", min: 1, default: 2 },
      { key: "interval", label: "Interval", type: "duration", unit: "min", scale: 60, min: 0, step: "any", default: 600 },
      { key: "repeat_ground_track", label: "Repeat ground track", type: "checkbox", default: true }
    ]
  },
  mog: {
    label: "MOG Constellation",
    orbits: ["circular"],
    fields: [
      { key: "number_satellites", label: "Satellites", type: "integer", min: 1, default: 2 },
      { key: "parallel_axis", label: "Parallel axis", type: "number", unit: "km", scale: 1000, min: 0, step: "any", default: 50e3 },
      { key: "transverse_axis", label: "Transverse axis", type: "number", unit: "km", scale: 1000, min: 0, step: "any", default: 25e3 },
      { key: "clockwise", label: "Clockwise", type: "checkbox", default: true }
    ]
  },
  soc: {
    label: "Streets of Coverage (SOC) Constellation",
    orbits: ["circular"],
    fields: [
      { key: "swath_width", label: "Swath width", type: "number", unit: "km", scale: 1000, min: 0, step: "any", default: 2000e3 },
      { key: "packing_distance", label: "Packing distance", type: "number", min: 0.01, max: 1, step: "any", default: 1, help: "Fraction of the footprint diameter between satellites" },
      { key: "polar", label: "Pattern", type: "select", default: null, options: [{ value: null, label: "Automatic" }, { value: true, label: "Polar" }, { value: false, label: "Inclined" }] }
    ]
  }
};

// (the lighting constraints share a row)
const COMMON_INSTRUMENT_FIELDS = [
  { key: "min_access_time", label: "Min. access", type: "duration", unit: "s", min: 0, step: "any", default: 0 },
  { key: "req_target_sunlit", label: "Target", type: "select", default: null, options: SUNLIT_OPTIONS, group: "lighting" },
  { key: "req_self_sunlit", label: "Satellite", type: "select", default: null, options: SUNLIT_OPTIONS, group: "lighting" },
  _.assign({ key: "min_target_solar_elevation", label: "Min. solar elev.", type: "number", min: -90, max: 90, optional: true, group: "lighting" }, ANGLE),
  _.assign({ key: "max_target_solar_elevation", label: "Max. solar elev.", type: "number", min: -90, max: 90, optional: true, group: "lighting" }, ANGLE)
];

const INSTRUMENT_SPECS = {
  instrument: {
    label: "Simple (field of regard)",
    fields: [
      _.assign({ key: "field_of_regard", label: "Field of regard", type: "number", min: 0, max: 360, default: 180 }, ANGLE)
    ].concat(COMMON_INSTRUMENT_FIELDS)
  },
  pointed: {
    label: "Pointed (field of view)",
    fields: [
      _.assign({ key: "cross_track_field_of_view", label: "Cross-track FOV", type: "number", min: 0, max: 180, default: 30, group: "fov" }, ANGLE),
      _.assign({ key: "along_track_field_of_view", label: "Along-track FOV", type: "number", min: 0, max: 180, default: 1, group: "fov" }, ANGLE),
      _.assign({ key: "roll_angle", label: "Roll", type: "number", min: -180, max: 180, default: 0, group: "pointing" }, ANGLE),
      _.assign({ key: "pitch_angle", label: "Pitch", type: "number", min: -180, max: 180, default: 0, group: "pointing" }, ANGLE),
      { key: "is_rectangular", label: "Rectangular", type: "checkbox", default: false },
      _.assign({ key: "field_of_regard", label: "Field of regard", type: "number", min: 0, max: 360, optional: true, help: "Blank for the default" }, ANGLE),
      // pixels, which size the ground samples (blank for one pixel across
      // the field of view)
      { key: "cross_track_pixels", label: "Cross-track pixels", type: "integer", min: 1, optional: true, group: "pixels", help: "Pixels across the cross-track field of view, which size ground samples (blank for 1)" },
      { key: "along_track_pixels", label: "Along-track pixels", type: "integer", min: 1, optional: true, group: "pixels", help: "Pixels across the along-track field of view (blank for 1)" },
      { key: "cross_track_oversampling", label: "Cross-track overlap", type: "number", unit: "%", scale: 0.01, max: 99, step: "any", optional: true, group: "oversampling", help: "Share of a pixel overlapping its neighbor across track (negative for a gap; blank for 0)" },
      { key: "along_track_oversampling", label: "Along-track overlap", type: "number", unit: "%", scale: 0.01, max: 99, step: "any", optional: true, group: "oversampling", help: "Share of a pixel overlapping its neighbor along track (negative for a gap; blank for 0)" },
      { key: "scan_period", label: "Scan period", type: "number", unit: "s", min: 0, step: "any", optional: true, help: "Seconds between scans of a scanning instrument, which space its samples along track (blank if not modeled)" }
    ].concat(COMMON_INSTRUMENT_FIELDS)
  },
  conical: {
    label: "Conical scan",
    fields: [
      _.assign({ key: "cone_angle", label: "Cone angle", type: "number", min: 0, max: 90, default: 45 }, ANGLE),
      _.assign({ key: "along_track_field_of_view", label: "Along-track FOV", type: "number", min: 0, max: 180, default: 1 }, ANGLE),
      _.assign({ key: "scan_center_azimuth", label: "Scan center", type: "number", min: -180, max: 180, default: 0, group: "scan" }, ANGLE),
      _.assign({ key: "scan_half_width", label: "Scan half-width", type: "number", min: 0, max: 180, default: 180, group: "scan" }, ANGLE),
      _.assign({ key: "field_of_regard", label: "Field of regard", type: "number", min: 0, max: 360, optional: true, help: "Blank for the default" }, ANGLE),
      // samples, which size the ground samples (if both are given)
      _.assign({ key: "beam_width", label: "Beam width", type: "number", min: 0, max: 90, optional: true, group: "samples", help: "Angular width of the beam (such as its half-power width), which sizes ground samples (blank if not modeled)" }, ANGLE),
      _.assign({ key: "scan_sample_spacing", label: "Sample spacing", type: "number", min: 0, max: 180, optional: true, group: "samples", help: "Scan azimuth between neighboring samples along the scanned arc (blank if not modeled)" }, ANGLE)
    ].concat(COMMON_INSTRUMENT_FIELDS)
  }
};

// Fields (other than `type`) whose presence implies the type of an instrument
// without one (as the library infers it, written before the field existed).
const POINTED_KEYS = [
  "along_track_field_of_view", "along_track_oversampling", "along_track_pixels",
  "cross_track_field_of_view", "cross_track_oversampling", "cross_track_pixels",
  "is_rectangular", "is_swept", "pitch_angle", "pitch_angle_profile", "roll_angle",
  "roll_angle_profile", "scan_period", "velocity_frame", "view_geometry", "yaw_angle"
];
const CONICAL_KEYS = ["beam_width", "cone_angle", "scan_center_azimuth", "scan_half_width", "scan_sample_spacing"];
const IN_SITU_KEYS = ["radius"];

// Gets the type of an instrument: its `type` or, if omitted, the type its
// fields imply (as the library does).
function instrumentType(instrument) {
  if (_.isString(instrument.type)) {
    return instrument.type;
  }
  function has(keys) {
    return _.some(keys, function(key) { return _.has(instrument, key); });
  }
  return has(IN_SITU_KEYS) ? "in_situ" : has(CONICAL_KEYS) ? "conical" : has(POINTED_KEYS) ? "pointed" : "instrument";
}

// Gets the spec of a type, or for a type without a form (such as an in-situ
// instrument, which only surface platforms carry), a spec to edit it in JSON.
function specOf(specs, type) {
  return specs[type] || {
    label: String(type) + " (JSON only)",
    jsonOnly: true,
    orbits: ALL_ORBITS,
    fields: [{ type: "note", label: "This type has no form: edit it in the JSON tab." }]
  };
}

const STATION_FIELDS = [
  { key: "name", label: "Name", type: "text", default: "Station" },
  _.assign({ key: "latitude", label: "Latitude", type: "number", min: -90, max: 90, default: 0 }, ANGLE),
  _.assign({ key: "longitude", label: "Longitude", type: "number", min: -180, max: 180, default: 0 }, ANGLE),
  _.assign({ key: "min_elevation_angle", label: "Min. elevation", type: "number", min: 0, max: 90, default: 5 }, ANGLE),
  { key: "min_access_time", label: "Min. access", type: "duration", unit: "s", min: 0, step: "any", default: 0 }
];

// --- Values ---

// Parses a duration (seconds, or an ISO 8601 duration such as "PT1H30M").
function parseDuration(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "number") {
    return value;
  }
  const match = /^(-)?P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$/.exec(value);
  if (!match) {
    return Number(value);
  }
  const seconds = 86400 * Number(match[2] || 0) + 3600 * Number(match[3] || 0)
    + 60 * Number(match[4] || 0) + Number(match[5] || 0);
  return match[1] ? -seconds : seconds;
}

function resolveDefault(field) {
  return _.isFunction(field.default) ? field.default() : _.cloneDeep(field.default);
}

// Creates an object of a type with default values.
function createDefault(spec, type) {
  const object = type === undefined ? {} : { type: type };
  _.forEach(spec.fields, function(field) {
    if (field.key && field.default !== undefined) {
      _.set(object, field.key, resolveDefault(field));
    }
  });
  return object;
}

// Converts a schema (SI) value to a form value.
function toFormValue(field, value) {
  if (value === null || value === undefined) {
    return "";
  }
  const scale = field.scale || 1;
  switch (field.type) {
    case "number":
    case "integer":
      return Number((value / scale).toPrecision(12));
    case "duration":
      return Number((parseDuration(value) / scale).toPrecision(12));
    case "datetime":
      return toDateTimeInput(value);
    case "time":
      return String(value).substring(0, 8);
    case "tle":
      return _.isArray(value) ? value.join("\n") : String(value);
    case "omm":
      return elementsToOmm(value);
    default:
      return value;
  }
}

// Converts a form value to a schema (SI) value (`undefined` for blank),
// throwing an error if the value cannot be converted.
function fromFormValue(field, value) {
  const scale = field.scale || 1;
  switch (field.type) {
    case "number":
    case "integer":
    case "duration":
      if (value === "" || value === null) {
        return undefined;
      }
      return field.type == "integer" ? Math.round(Number(value)) : Number(value) * scale;
    case "datetime":
      return value ? fromDateTimeInput(value).toISOString() : undefined;
    case "time":
      return value ? (value.length == 5 ? value + ":00" : value) : undefined;
    case "tle":
      return _.filter(_.map(String(value).split(/\r?\n/), _.trim), function(line) { return line.length > 0; });
    case "omm":
      return ommToElements(value);
    default:
      return value;
  }
}

// --- Rendering ---

// Renders form fields for an object into a container, in rows of a number of
// columns (by default, two). Text fields and elements span a row, date-times
// two columns of rows of four or more (they need about twice the width of a
// number), and other fields one column, unless they set `span` (a number of
// columns). Consecutive fields of a `group` (such as a minimum and maximum)
// share a row: a group that does not fit in the rest of a row starts the next.
// Calls `onChange(key)` after each change is written to the object.
function renderFields(container, fields, object, onChange, columns) {
  columns = columns || 2;
  function spanOf(field) {
    const wide = field.type == "tle" || field.type == "omm" || field.type == "text";
    return Math.min(field.span || (wide ? columns : field.type == "datetime" && columns >= 4 ? 2 : 1), columns);
  }
  const shown = _.filter(fields, function(field) {
    return !field.showIf || field.showIf(object);
  });
  container.empty();
  let row = null;
  let count = 0;
  _.forEach(shown, function(field, i) {
    if (field.type == "note") {
      container.append($("<p>").addClass("small text-muted").text(field.label));
      return;
    }
    const id = "field-" + _.uniqueId();
    const span = spanOf(field);
    // the span of the group the field starts (if any)
    let groupSpan = span;
    if (field.group && (i == 0 || shown[i - 1].group != field.group)) {
      groupSpan = _.sumBy(_.takeWhile(shown.slice(i), { group: field.group }), spanOf);
    }
    if (!row || count + Math.min(groupSpan, columns) > columns) {
      row = $("<div>").addClass("form-row");
      container.append(row);
      count = 0;
    }
    const group = $("<div>").addClass("form-group mb-2").addClass("col-sm-" + 12 / columns * span);
    const label = $("<label>").attr("for", id).addClass("small mb-0").text(field.label);
    if (field.help) {
      label.attr("title", field.help).append(" ", $("<i>").addClass("far fa-question-circle text-muted"));
    }
    let input;
    const value = _.get(object, field.key);
    if (field.type == "select") {
      input = $("<select>").addClass("form-control form-control-sm");
      _.forEach(field.options, function(option) {
        input.append($("<option>").val(JSON.stringify(option.value)).text(option.label));
      });
      input.val(JSON.stringify(value === undefined ? null : value));
      input.on("change", function() {
        _.set(object, field.key, JSON.parse(input.val()));
        onChange(field.key);
      });
    } else if (field.type == "checkbox") {
      input = $("<input type='checkbox'>").addClass("form-check-input");
      input.prop("checked", !!value);
      input.on("change", function() {
        _.set(object, field.key, input.is(":checked"));
        onChange(field.key);
      });
      group.addClass("pt-3");
      group.append($("<div>").addClass("form-check").append(input.attr("id", id), label.addClass("form-check-label")));
      row.append(group);
      count += span;
      return;
    } else if (field.type == "tle" || field.type == "omm") {
      input = $("<textarea spellcheck='false'>").attr("rows", field.type == "omm" ? 12 : 2)
        .addClass("form-control form-control-sm mono");
      input.val(toFormValue(field, value));
    } else {
      const types = { number: "number", integer: "number", duration: "number", datetime: "datetime-local", time: "time", text: "text" };
      input = $("<input>").attr("type", types[field.type] || "text").addClass("form-control form-control-sm");
      if (field.type == "integer") {
        input.attr("step", 1);
      } else if (field.step !== undefined) {
        input.attr("step", field.step);
      }
      if (field.type == "datetime" || field.type == "time") {
        input.attr("step", 1);
      }
      if (field.min !== undefined) { input.attr("min", field.min); }
      if (field.max !== undefined) { input.attr("max", field.max); }
      if (field.optional) { input.attr("placeholder", "(default)"); }
      input.val(toFormValue(field, value));
    }
    // an error converting the value is shown (keeping the input) until fixed
    const feedback = $("<div>").addClass("invalid-feedback");
    if (field.type != "select") {
      input.on("change", function() {
        let converted;
        try {
          converted = fromFormValue(field, input.val());
        } catch (e) {
          input.addClass("is-invalid");
          feedback.text(e.message).show();
          return;
        }
        input.removeClass("is-invalid");
        feedback.hide();
        if (converted === undefined) {
          if (field.optional) {
            _.unset(object, field.key);
          } else {
            input.val(toFormValue(field, _.get(object, field.key)));
            return;
          }
        } else {
          _.set(object, field.key, converted);
        }
        onChange(field.key);
      });
    }
    input.attr("id", id);
    if (field.unit) {
      group.append(label, $("<div>").addClass("input-group input-group-sm").append(
        input,
        $("<div>").addClass("input-group-append").append($("<span>").addClass("input-group-text").text(field.unit))
      ));
    } else {
      group.append(label, input);
    }
    group.append(feedback);
    row.append(group);
    count += span;
  });
}

// Keys of an object type (to remove when the type changes).
function specKeys(spec) {
  return _.uniq(_.compact(_.map(spec.fields, function(field) {
    return field.key ? field.key.split(".")[0] : null;
  })));
}

// Changes the type of an object in place, removing the properties of the
// former type and adding defaults of the new type, while keeping shared
// properties (such as `name`) and properties edited in JSON.
function changeType(object, specs, type) {
  const former = specs[object.type || "satellite"];
  const next = specs[type];
  const keep = specKeys(next);
  if (former) {
    _.forEach(specKeys(former), function(key) {
      if (!_.includes(keep, key)) {
        delete object[key];
      }
    });
  }
  const defaults = createDefault(next, type);
  _.forEach(defaults, function(value, key) {
    if (object[key] === undefined || key == "type") {
      object[key] = value;
    }
  });
  return object;
}

// Creates an instrument of a type, keeping the name and shared settings.
function changeInstrumentType(instrument, type) {
  const spec = specOf(INSTRUMENT_SPECS, type);
  const next = createDefault(spec, type);
  next.name = instrument.name || "Default";
  _.forEach(specKeys(spec), function(key) {
    if (instrument[key] !== undefined && _.find(COMMON_INSTRUMENT_FIELDS, { key: key })) {
      next[key] = instrument[key];
    }
  });
  return next;
}

function createInstrument(name) {
  return _.assign({ name: name || "Default" }, createDefault(INSTRUMENT_SPECS.instrument, "instrument"));
}

function createSatellite(name) {
  return {
    type: "satellite",
    name: name || "New Satellite",
    orbit: createDefault(ORBIT_SPECS.circular, "circular"),
    instruments: [createInstrument()]
  };
}

function createStation(name) {
  return _.assign(createDefault({ fields: STATION_FIELDS }), { name: name || "Station" });
}
