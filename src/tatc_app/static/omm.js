// Conversion between orbit mean-elements messages (OMM) and the general
// perturbations (GP) elements of the TAT-C library (`gp` orbits).
//
// Unlike two line elements (TLE), OMM is not limited to 5-character catalog
// numbers, so it specifies the orbits of objects with catalog numbers beyond
// the range of TLE. OMM text is accepted in the formats CelesTrak and
// Space-Track provide: JSON (an object or a list of objects), CSV (with a
// header row), XML, and KVN (keyword = value). Each element set (for example,
// each object of a JSON list) becomes one GP element.
//
// The conversion follows the `sgp4` library (`sgp4.omm.initialize` and
// `sgp4.exporter.export_omm`), which the TAT-C library uses: OMM gives mean
// motion and its derivatives in revolutions per day (per day squared, per day
// cubed), and TAT-C in degrees per second (per second squared, per second
// cubed). As SGP4 cannot initialize a satellite with a catalog number beyond
// the Alpha-5 range of TLE, which does not affect propagation, such elements
// use catalog number 0 instead (as for the CelesTrak catalog of the server).

const OMM_MAX_CATALOG_NUMBER = 339999;
const OMM_SECONDS_PER_DAY = 86400;

// OMM keywords of TAT-C GP element fields, in the order of `export_omm`, with
// for each number its scale (TAT-C value per OMM value) or for each text its
// conversion.
const OMM_REQUIRED = ["EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY"];
const OMM_NUMBERS = [
  { omm: "MEAN_MOTION", key: "mean_motion", scale: 360 / OMM_SECONDS_PER_DAY },
  { omm: "ECCENTRICITY", key: "eccentricity", scale: 1 },
  { omm: "INCLINATION", key: "inclination", scale: 1 },
  { omm: "RA_OF_ASC_NODE", key: "ra_of_asc_node", scale: 1 },
  { omm: "ARG_OF_PERICENTER", key: "arg_of_pericenter", scale: 1 },
  { omm: "MEAN_ANOMALY", key: "mean_anomaly", scale: 1 },
  { omm: "EPHEMERIS_TYPE", key: "ephemeris_type", integer: true },
  { omm: "NORAD_CAT_ID", key: "norad_cat_id", integer: true },
  { omm: "ELEMENT_SET_NO", key: "element_set_num", integer: true },
  { omm: "REV_AT_EPOCH", key: "revolution_num", integer: true },
  { omm: "BSTAR", key: "bstar", scale: 1 },
  { omm: "MEAN_MOTION_DOT", key: "mean_motion_dot", scale: 360 / Math.pow(OMM_SECONDS_PER_DAY, 2) },
  { omm: "MEAN_MOTION_DDOT", key: "mean_motion_ddot", scale: 360 / Math.pow(OMM_SECONDS_PER_DAY, 3) }
];

// Defaults of the TAT-C GP element fields that OMM may omit.
const OMM_ELEMENT_DEFAULTS = {
  norad_cat_id: 0, bstar: 0, mean_motion_dot: 0, mean_motion_ddot: 0, classification: "U",
  international_designator: "00000A", ephemeris_type: 0, element_set_num: 0, revolution_num: 0
};

// --- Parsing ---

// Parses CSV text (with quoted fields) into rows of fields.
function parseOmmCsvRows(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c == '"' && text[i + 1] == '"') {
        field += '"';
        i++;
      } else if (c == '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c == '"') {
      quoted = true;
    } else if (c == ",") {
      row.push(field);
      field = "";
    } else if (c == "\n" || c == "\r") {
      if (c == "\r" && text[i + 1] == "\n") {
        i++;
      }
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  row.push(field);
  rows.push(row);
  return rows.filter(function(r) { return r.length > 1 || r[0].trim() != ""; });
}

function parseOmmCsv(text) {
  const rows = parseOmmCsvRows(text);
  const header = rows[0].map(function(key) { return key.trim().toUpperCase(); });
  return rows.slice(1).map(function(row) {
    const record = {};
    header.forEach(function(key, i) {
      if (row[i] !== undefined && row[i].trim() !== "") {
        record[key] = row[i].trim();
      }
    });
    return record;
  });
}

// Parses OMM XML (the CCSDS format, with a segment per element set).
function parseOmmXml(text) {
  const segments = text.match(/<segment[\s>][\s\S]*?<\/segment>/g) || [text];
  return segments.map(function(segment) {
    const record = {};
    const pattern = /<(?:\w+:)?([A-Za-z_]+)(?:\s[^>]*)?>([^<]*)<\/(?:\w+:)?\1>/g;
    let match;
    while ((match = pattern.exec(segment)) !== null) {
      record[match[1].toUpperCase()] = match[2].trim();
    }
    return record;
  });
}

// Parses OMM KVN (the CCSDS keyword = value format, with a message per
// element set, each starting with its version).
function parseOmmKvn(text) {
  const records = [];
  let record = null;
  text.split(/\r?\n/).forEach(function(line) {
    const match = /^\s*([A-Za-z_0-9]+)\s*=\s*(.*?)\s*$/.exec(line);
    if (!match || match[1].toUpperCase() == "COMMENT") {
      return;
    }
    const key = match[1].toUpperCase();
    if (!record || key == "CCSDS_OMM_VERS" || key in record) {
      record = {};
      records.push(record);
    }
    // values may be followed by units, for example "15.5 [rev/day]"
    record[key] = match[2].replace(/\s*\[[^\]]*\]$/, "");
  });
  return records;
}

// Parses OMM text (JSON, CSV, XML, or KVN) into records of OMM keywords.
function parseOmmRecords(text) {
  const trimmed = String(text).trim();
  if (trimmed === "") {
    return [];
  }
  let records;
  if (trimmed[0] == "[" || trimmed[0] == "{") {
    let parsed;
    try {
      parsed = JSON.parse(trimmed);
    } catch (e) {
      throw new Error("Invalid OMM JSON: " + e.message);
    }
    records = Array.isArray(parsed) ? parsed : [parsed];
    records = records.map(function(record) {
      if (record === null || typeof record != "object" || Array.isArray(record)) {
        throw new Error("OMM JSON must be an object or a list of objects.");
      }
      const upper = {};
      Object.keys(record).forEach(function(key) { upper[key.toUpperCase()] = record[key]; });
      return upper;
    });
  } else if (trimmed[0] == "<") {
    records = parseOmmXml(trimmed);
  } else if (/^\s*[A-Za-z_0-9]+\s*=/m.test(trimmed)) {
    records = parseOmmKvn(trimmed);
  } else if (/,/.test(trimmed.split(/\r?\n/)[0])) {
    records = parseOmmCsv(trimmed);
  } else {
    throw new Error("Unrecognized OMM format: expected JSON, CSV, XML, or KVN.");
  }
  return records;
}

// Converts an OMM epoch (UTC, as a calendar or day-of-year date, with
// optional fraction of seconds) to an ISO 8601 time with a time zone.
function ommEpochToIso(epoch) {
  const text = String(epoch).trim();
  const match = /^(\d{4})-(?:(\d{2})-(\d{2})|(\d{3}))T(\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z?$/i.exec(text);
  if (!match) {
    throw new Error("Invalid EPOCH: " + text + ".");
  }
  let date = match[1] + "-" + match[2] + "-" + match[3];
  if (match[4] !== undefined) {
    const day = new Date(Date.UTC(Number(match[1]), 0, Number(match[4])));
    if (day.getUTCFullYear() != Number(match[1])) {
      throw new Error("Invalid EPOCH: " + text + ".");
    }
    date = day.toISOString().substring(0, 10);
  }
  return date + "T" + match[5] + "Z";
}

// Converts an OMM record to a TAT-C GP element.
function ommRecordToElement(record, index) {
  const prefix = "Element set " + (index + 1) + ": ";
  const missing = OMM_REQUIRED.filter(function(key) {
    return record[key] === undefined || record[key] === null || record[key] === "";
  });
  if (missing.length) {
    throw new Error(prefix + "missing " + missing.join(", ") + ".");
  }
  const theory = record.MEAN_ELEMENT_THEORY;
  if (theory && String(theory).trim().toUpperCase() != "SGP4") {
    throw new Error(prefix + "MEAN_ELEMENT_THEORY " + theory + " is not supported (SGP4 is required).");
  }
  const element = {};
  if (record.OBJECT_NAME) {
    element.object_name = String(record.OBJECT_NAME).trim();
  }
  try {
    element.epoch = ommEpochToIso(record.EPOCH);
  } catch (e) {
    throw new Error(prefix + e.message);
  }
  OMM_NUMBERS.forEach(function(field) {
    const value = record[field.omm];
    if (value === undefined || value === null || value === "") {
      return;
    }
    const number = Number(value);
    if (!isFinite(number) || (field.integer && !Number.isInteger(number))) {
      throw new Error(prefix + field.omm + " is not a" + (field.integer ? "n integer" : " number") + ": " + value + ".");
    }
    element[field.key] = field.integer ? number : number * field.scale;
  });
  if (element.norad_cat_id > OMM_MAX_CATALOG_NUMBER) {
    element.norad_cat_id = 0;
  }
  if (record.CLASSIFICATION_TYPE) {
    element.classification = String(record.CLASSIFICATION_TYPE).trim();
  }
  // the international designator as in TLE: "1998-067A" is "98067A"
  const objectId = /^\d{2}(\d{2})-(\d{3})([A-Z]{1,3})$/i.exec(String(record.OBJECT_ID || "").trim());
  if (objectId) {
    element.international_designator = (objectId[1] + objectId[2] + objectId[3]).toUpperCase();
  }
  return element;
}

// Converts OMM text (JSON, CSV, XML, or KVN) to TAT-C GP elements, throwing
// an error if it is not valid.
export function ommToElements(text) {
  const records = parseOmmRecords(text);
  if (records.length == 0) {
    throw new Error("No OMM element sets found.");
  }
  return records.map(ommRecordToElement);
}

// --- Formatting ---

// Rounds a converted value to remove floating point noise.
function ommNumber(value) {
  return Number(value.toPrecision(15));
}

// Converts a time (ISO 8601) to an OMM epoch (UTC, without a time zone).
function isoToOmmEpoch(time) {
  const text = String(time);
  const utc = /^(.*T[\d:.]+)(?:Z|[+-]00:?00)$/i.exec(text);
  if (utc) {
    return utc[1];
  }
  const date = new Date(text);
  return isNaN(date.getTime()) ? text : date.toISOString().replace(/Z$/, "");
}

// Converts a TAT-C GP element to an OMM record (as in CelesTrak's JSON).
function elementToOmmRecord(element) {
  const values = Object.assign({}, OMM_ELEMENT_DEFAULTS, element);
  const record = {};
  if (values.object_name) {
    record.OBJECT_NAME = values.object_name;
  }
  // the international designator as in TLE: "98067A" is "1998-067A"
  const designator = /^(\d{2})(\d{3})([A-Z]{1,3})$/i.exec(String(values.international_designator || ""));
  if (designator) {
    const year = Number(designator[1]) + (Number(designator[1]) < 57 ? 2000 : 1900);
    record.OBJECT_ID = year + "-" + designator[2] + designator[3];
  }
  record.EPOCH = isoToOmmEpoch(values.epoch);
  OMM_NUMBERS.forEach(function(field) {
    const value = values[field.key];
    record[field.omm] = typeof value != "number" || field.integer ? value : ommNumber(value / field.scale);
    if (field.omm == "EPHEMERIS_TYPE") {
      record.CLASSIFICATION_TYPE = values.classification;
    }
  });
  return record;
}

// Converts TAT-C GP elements to OMM text (JSON, as CelesTrak provides).
export function elementsToOmm(elements) {
  if (!Array.isArray(elements)) {
    return "";
  }
  return JSON.stringify(elements.map(elementToOmmRecord), null, 2);
}
