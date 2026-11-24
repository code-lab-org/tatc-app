// Satellite and instrument filter, shared by the Design and Analysis tabs:
// unchecked satellites, constellation members, and instruments are hidden in
// the orbit preview and left out of analyses. The filter lists the design's
// satellites and constellations (with members once validated), so it does
// not depend on a preview.

// filtered (unchecked) items by key (see `layerKey`), kept across changes
// to the design
const layerHidden = {};
// names of constellations with an expanded member list
const layerExpanded = {};
// keys of instruments without a footprint (found by the orbit preview)
let layerNoFootprint = {};
const layerFilterListeners = [];
let layerToggleCount = 0;

function layerKey(kind, system, detail) {
  return kind + ":" + system + (detail === undefined ? "" : "/" + detail);
}

function isLayerShown(key) {
  return !layerHidden[key];
}

function onLayerFilterChange(listener) {
  layerFilterListeners.push(listener);
}

function notifyLayerFilterChange() {
  _.forEach(layerFilterListeners, function(listener) { listener(); });
}

// Marks the instruments (by key) without a footprint.
function setLayersWithoutFootprint(keys) {
  layerNoFootprint = _.zipObject(keys, _.map(keys, _.constant(true)));
  renderLayerFilter();
}

// Lists the satellites and constellations of the design: [{name, color,
// instruments: [{name, color}], members: [name] or null if not validated}].
function getFilterSystems() {
  return _.map(design.satellites, function(item) {
    const instruments = item.system.instruments || [];
    return {
      name: item.system.name,
      color: item.color,
      instruments: _.map(instruments, function(instrument, i) {
        return {
          name: instrument.name,
          color: (item.instrumentColors || [])[i] || defaultInstrumentColor(item.color, i, instruments.length)
        };
      }),
      members: item.validation.status == "valid" ? _.map(item.validation.members, "name") : null
    };
  });
}

function createLayerToggle(key, label, swatch, title, onChange) {
  const id = "layer-toggle-" + (layerToggleCount++);
  return $("<div>").addClass("form-check form-check-inline mr-2").attr("title", title || null).append(
    $("<input type='checkbox'>").addClass("form-check-input").attr("id", id)
      .prop("checked", isLayerShown(key))
      .on("change", function() {
        if (this.checked) {
          delete layerHidden[key];
        } else {
          layerHidden[key] = true;
        }
        if (onChange) { onChange(this.checked); }
        notifyLayerFilterChange();
      }),
    $("<label>").addClass("form-check-label").attr("for", id).append(swatch, $("<span>").text(label))
  );
}

function renderLayerFilter() {
  const list = $("#layer-filter-list").empty();
  const systems = getFilterSystems();
  $("#layer-filter").toggle(systems.length > 0);
  _.forEach(systems, function(system) {
    const details = $("<div>").addClass("preview-layer-details")
      .toggleClass("preview-layer-hidden", !isLayerShown(layerKey("sys", system.name)));
    const header = $("<div>").append(
      createLayerToggle(
        layerKey("sys", system.name),
        system.name,
        $("<i>").addClass("fas fa-satellite mr-1").css("color", system.color),
        null,
        function(shown) { details.toggleClass("preview-layer-hidden", !shown); }
      )
    );
    _.forEach(system.instruments, function(instrument, i) {
      const key = layerKey("ins", system.name, i);
      const swatch = $("<span>").addClass("preview-swatch");
      if (layerNoFootprint[key]) {
        swatch.addClass("preview-swatch-none");
      } else {
        swatch.css("background-color", instrument.color);
      }
      details.append(createLayerToggle(
        key,
        instrument.name || "Instrument " + i,
        swatch,
        "Instrument " + i + (layerNoFootprint[key] ? " (no footprint)" : "")
      ));
    });
    if (system.members && system.members.length > 1) {
      const members = $("<div>").addClass("preview-layer-members").toggle(!!layerExpanded[system.name]);
      _.forEach(system.members, function(member) {
        members.append(createLayerToggle(layerKey("sat", system.name, member), member));
      });
      const toggle = $("<a href='#'>").addClass("small ml-1")
        .text(system.members.length + " satellites")
        .prepend($("<i>").addClass("fas mr-1").toggleClass("fa-caret-down", !!layerExpanded[system.name])
          .toggleClass("fa-caret-right", !layerExpanded[system.name]))
        .on("click", function(e) {
          e.preventDefault();
          layerExpanded[system.name] = !layerExpanded[system.name];
          members.toggle(layerExpanded[system.name]);
          $(this).find("i").toggleClass("fa-caret-down fa-caret-right");
        });
      header.append(toggle);
      details.append(members);
    }
    list.append($("<div>").addClass("preview-layer").append(header, details));
  });
}

// Gets the inputs of an analysis, less unchecked items: {satellites, colors,
// instrumentColors, excludeMembers}. A satellite or constellation is left
// out if unchecked, or if all of its instruments or members are unchecked.
// Instruments keep their colors (default colors derive from their index
// among all instruments).
function getFilteredInputs() {
  const inputs = { satellites: [], colors: [], instrumentColors: [], excludeMembers: [] };
  _.forEach(design.satellites, function(item) {
    const system = item.system;
    if (!isLayerShown(layerKey("sys", system.name))) {
      return;
    }
    const instruments = system.instruments || [];
    const kept = _.filter(_.range(instruments.length), function(i) {
      return isLayerShown(layerKey("ins", system.name, i));
    });
    if (instruments.length > 0 && kept.length == 0) {
      return;
    }
    const members = item.validation.status == "valid" ? _.map(item.validation.members, "name") : [];
    const excluded = members.length > 1 ? _.filter(members, function(member) {
      return !isLayerShown(layerKey("sat", system.name, member));
    }) : [];
    if (excluded.length > 0 && excluded.length == members.length) {
      return;
    }
    const chosen = _.take(item.instrumentColors || [], instruments.length);
    let colors = _.some(chosen) ? _.map(chosen, function(c) { return c || null; }) : null;
    if (kept.length < instruments.length) {
      colors = _.map(kept, function(i) {
        return chosen[i] || defaultInstrumentColor(item.color, i, instruments.length);
      });
      inputs.satellites.push(_.assign({}, system, { instruments: _.at(instruments, kept) }));
    } else {
      inputs.satellites.push(system);
    }
    inputs.colors.push(item.color);
    inputs.instrumentColors.push(colors);
    inputs.excludeMembers = inputs.excludeMembers.concat(excluded);
  });
  return inputs;
}

// Moves the filter into the panel of the active tab, with a note on what
// it applies to.
function placeLayerFilter(tab) {
  const slot = $($(tab).attr("href")).find(".layer-filter-slot");
  if (slot.length) {
    $("#layer-filter").appendTo(slot);
  }
  $("#layer-filter-note").text($(tab).is("#nav-analysis-tab")
    ? "Unchecked satellites and instruments are left out of analyses."
    : "Unchecked satellites and instruments are hidden in the orbit preview.");
}

$(document).ready(function() {
  $("#layer-filter-all").click(function() {
    _.forEach(_.keys(layerHidden), function(key) { delete layerHidden[key]; });
    renderLayerFilter();
    notifyLayerFilterChange();
  });
  $("#nav-tab .rail-btn").on("show.bs.tab", function(e) { placeLayerFilter(e.target); });
  placeLayerFilter($("#nav-tab .rail-btn.active"));
  onDesignChange(renderLayerFilter);
  renderLayerFilter();
});
