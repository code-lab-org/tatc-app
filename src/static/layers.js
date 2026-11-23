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

const VIRIDIS = createColormap({ colormap: "viridis", nshades: 64, format: "hex" });

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
