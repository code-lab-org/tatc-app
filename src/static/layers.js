// Manages result layers in the Cesium viewer: CZML data sources (animated
// satellites, links, and swaths) and the legend overlay.

const czmlSources = {};

// Loads a CZML document as the named layer, replacing any previous one.
// Returns a promise resolving to the data source.
function loadCzmlLayer(name, url, options) {
  options = options || {};
  clearCzmlLayer(name);
  return Cesium.CzmlDataSource.load(url).then(function(source) {
    czmlSources[name] = source;
    return viewer.dataSources.add(source).then(function() {
      if (options.clock !== false && source.clock) {
        setClock(source.clock.startTime, source.clock.stopTime, source.clock.multiplier);
      }
      return source;
    });
  });
}

function getCzmlLayer(name) {
  return czmlSources[name];
}

function clearCzmlLayer(name) {
  if (czmlSources[name]) {
    viewer.dataSources.remove(czmlSources[name], true);
    delete czmlSources[name];
  }
}

function showCzmlLayer(name, show) {
  if (czmlSources[name]) {
    czmlSources[name].show = show;
  }
}

// Sets the clock and timeline to an interval (JulianDate or ISO 8601 strings),
// animating at a multiplier (default: the interval in about one minute).
function setClock(start, stop, multiplier) {
  start = start instanceof Cesium.JulianDate ? start : Cesium.JulianDate.fromIso8601(start);
  stop = stop instanceof Cesium.JulianDate ? stop : Cesium.JulianDate.fromIso8601(stop);
  const duration = Cesium.JulianDate.secondsDifference(stop, start);
  viewer.clock.startTime = start.clone();
  viewer.clock.stopTime = stop.clone();
  viewer.clock.currentTime = start.clone();
  viewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP;
  viewer.clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
  viewer.clock.multiplier = multiplier || Math.max(1, Math.round(duration / 60));
  viewer.clock.shouldAnimate = true;
  viewer.timeline.zoomTo(start, stop);
}

// --- Color scales and legend ---

// Stops (position, RGB) of the viridis colormap.
const VIRIDIS_STOPS = [
  [0, [68, 1, 84]], [0.13, [71, 44, 122]], [0.25, [59, 81, 139]],
  [0.38, [44, 113, 142]], [0.5, [33, 144, 141]], [0.63, [39, 173, 129]],
  [0.75, [92, 200, 99]], [0.88, [170, 220, 50]], [1, [253, 231, 37]]
];

// Interpolates a number of hex colors (`#rrggbb`) linearly between stops.
function interpolateColors(stops, count) {
  function hex(rgb) {
    return "#" + _.map(rgb, function(v) { return _.padStart(Math.round(v).toString(16), 2, "0"); }).join("");
  }
  const colors = [];
  for (let s = 0; s < stops.length - 1; s++) {
    const from = stops[s], to = stops[s + 1];
    const steps = Math.round(to[0] * (count - 1)) - Math.round(from[0] * (count - 1));
    for (let j = 0; j < steps; j++) {
      colors.push(hex(_.map(from[1], function(v, k) { return v + (to[1][k] - v) * j / steps; })));
    }
  }
  colors.push(hex(_.last(stops)[1]));
  return colors;
}

const VIRIDIS = interpolateColors(VIRIDIS_STOPS, 64);

// A linear color scale over [min, max]; `reverse` maps small values to the
// bright end (for example, short revisit times).
function createColorScale(min, max, reverse) {
  const colors = reverse ? VIRIDIS.slice().reverse() : VIRIDIS;
  const cesiumColors = _.map(colors, function(c) { return Cesium.Color.fromCssColorString(c); });
  return {
    min: min,
    max: max,
    colors: colors,
    // returns a Cesium.Color, or `undefined` for a missing value
    color: function(value) {
      if (value === null || value === undefined || isNaN(value)) {
        return undefined;
      }
      const t = max > min ? (value - min) / (max - min) : 0;
      const index = Math.min(colors.length - 1, Math.max(0, Math.floor(t * colors.length)));
      return cesiumColors[index];
    }
  };
}

function renderColorbar(container, scale) {
  container.empty();
  _.forEach(scale.colors, function(color) {
    container.append($("<span>").css("background-color", color));
  });
}

function formatNumber(value, digits) {
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 1 : digits });
}

// Shows the legend overlay (and the colorbar settings of the Analysis tab).
function showLegend(title, scale, unit) {
  $("#legend-title").text(title);
  renderColorbar($("#legend-colorbar"), scale);
  $("#legend-min").text(formatNumber(scale.min) + " " + unit);
  $("#legend-max").text(formatNumber(scale.max) + " " + unit);
  $("#legend-overlay").show();
  $("#colorbar-title").text(title);
  $(".colorbar-unit").text(unit);
  $("#colorbar-group").show();
}

function hideLegend() {
  $("#legend-overlay").hide();
  $("#colorbar-group").hide();
}
