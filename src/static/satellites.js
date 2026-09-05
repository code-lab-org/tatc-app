// Design tab: satellite/instrument list CRUD and edit-form population.
// Uses EARTH_MEAN_RADIUS and getOrbit() from orbit.js.

function changeSatellite() {
  const satellite = $("#satellites option:selected").data("satellite");
  const features = $("#satellites option:selected").data("features");
  const color = $("#satellites option:selected").data("color");
  $("#satellite-edit").prop("disabled", satellite?false:true);
  $("#satellite-copy").prop("disabled", satellite?false:true);
  $("#satellite-delete").prop("disabled", satellite?false:true);
  $("#orbit-data-json").prop("disabled", features?false:true);
  $("#orbit-data-csv").prop("disabled", features?false:true);
  if(satellite) {
    $(".satellite-group").show();
    $("#satellite-name").val(satellite.name);
    if(!satellite.type) {
      $("#satellite-type").val("satellite");
    }
    if(satellite.type == "train") {
      $("#satellite-type").val("train");
      $(".constellation-train-group").show();
      $("#train-count").val(satellite.number_satellites);
      $("#train-interval").val(satellite.interval/60);
    } else {
      $(".constellation-train-group").hide();
    }
    if(satellite.type == "walker") {
      $("#satellite-type").val("walker");
      $(".constellation-walker-group").show();
      $("#walker-count").val(satellite.number_satellites);
      $("#walker-planes").val(satellite.number_planes);
      $("#walker-config").val(satellite.configuration);
      $("#walker-spacing").val(satellite.relative_spacing);
    } else {
      $(".constellation-walker-group").hide();
    }
    $("#satellite-orbit").val(satellite.orbit.type);
    $("#satellite-color").val(color);
    if(satellite.orbit.type == "tle") {
      $("#orbit-tle").val(satellite.orbit.tle.join("\n"));
    } else if(satellite.orbit.type == "circular") {
      var listener = $("#orbit-circular-epoch").off("change.datetimepicker");
      $("#orbit-circular-epoch").datetimepicker('date', satellite.orbit.epoch);
      $("#orbit-circular-epoch").on("change.datetimepicker", listener);
      $("#orbit-circular-altitude").val(satellite.orbit.mean_altitude/1000);
      $("#orbit-circular-inclination").val(satellite.orbit.inclination);
      $("#orbit-circular-raan").val(satellite.orbit.right_ascension_ascending_node);
      $("#orbit-circular-ta").val(satellite.orbit.true_anomaly);
    } else if(satellite.orbit.type == "sso") {
      var listener = $("#orbit-sso-epoch").off("change.datetimepicker");
      $("#orbit-sso-epoch").datetimepicker('date', satellite.orbit.epoch);
      $("#orbit-sso-epoch").on("change.datetimepicker", listener);
      $("#orbit-sso-ect").datetimepicker('date', satellite.orbit.equator_crossing_time);
      $("#orbit-sso-direction").val(satellite.orbit.equator_crossing_ascending?"asc":"desc");
      $("#orbit-sso-altitude").val(satellite.orbit.mean_altitude/1000);
      $("#orbit-sso-ta").val(satellite.orbit.true_anomaly);
    } else if(satellite.orbit.type == "keplerian") {
      var listener = $("#orbit-keplerian-epoch").off("change.datetimepicker");
      $("#orbit-keplerian-epoch").datetimepicker('date', satellite.orbit.epoch);
      $("#orbit-keplerian-epoch").on("change.datetimepicker", listener);
      $("#orbit-keplerian-altitude").val((satellite.orbit.semimajor_axis - EARTH_MEAN_RADIUS)/1000);
      $("#orbit-keplerian-inclination").val(satellite.orbit.inclination);
      $("#orbit-keplerian-eccentricity").val(satellite.orbit.eccentricity);
      $("#orbit-keplerian-pa").val(satellite.orbit.perigee_argument);
      $("#orbit-keplerian-raan").val(satellite.orbit.right_ascension_ascending_node);
      $("#orbit-keplerian-ta").val(satellite.orbit.true_anomaly);
    }
    $("#satellite-orbit").val()=="tle" ? $(".orbit-tle-group").show() : $(".orbit-tle-group").hide();
    $("#satellite-orbit").val()=="circular" ? $(".orbit-circular-group").show() : $(".orbit-circular-group").hide();
    $("#satellite-orbit").val()=="sso" ? $(".orbit-sso-group").show() : $(".orbit-sso-group").hide();
    $("#satellite-orbit").val()=="keplerian" ? $(".orbit-keplerian-group").show() : $(".orbit-keplerian-group").hide();
    $("#instruments").empty();
    satellite.instruments.forEach(function(instrument) {
      var option = $("<option></option>")
        .data("instrument", instrument)
        .text(instrument.name);
      if(instrument===$("#satellites option:selected").data("instrument")) {
        option.attr("selected", "selected");
      }
      $("#instruments").append(option);
      changeInstruments();
    });
  } else {
    $(".satellite-group").hide();
  }
}

function changeInstruments() {
  const instrument = $("#instruments option:selected").data("instrument");
  $("#instrument-copy").prop("disabled", instrument?false:true);
  $("#instrument-delete").prop("disabled", (instrument?false:true) || $("#instruments option").length <= 1);
  if(instrument) {
    $(".instrument-group").show();
    $("#instrument-name").val(instrument.name);
    $("#instrument-field").val(instrument.field_of_regard);
    $("#instrument-access").val(instrument.min_access_time);
    $("#instrument-target-sunlit").val(
      instrument.req_target_sunlit?"sunlit":
        (instrument.req_target_sunlit===false?"eclipse":"none")
    );
    $("#instrument-self-sunlit").val(
      instrument.req_self_sunlit?"sunlit":
        (instrument.req_self_sunlit===false?"eclipse":"none")
    );
    $("#satellites option:selected").data("instrument", instrument);
  } else {
    $(".instrument-group").hide();
  }
}

function getSunlitState(value) {
  if(value=="sunlit") {
    return true;
  } else if(value=="eclipse") {
    return false;
  } else {
    return null;
  }
}

$(document).ready(function() {
  $("#satellites").dblclick(function() {
    $("#satellite-dialog").modal('show');
  });
  $("#satellite-add").click(function() {
    const satellite = {
      name: "New Satellite",
      orbit: {
        type: "circular",
        mean_altitude: 400000,
        inclination: 0,
        true_anomaly: 0,
        right_ascension_ascending_node: 0,
        epoch: $("#display-start").datetimepicker("viewDate").toISOString()
      },
      instruments: [
        {
          name: "Default",
          field_of_regard: 180,
          min_access_time: 0,
          req_target_sunlit: null,
          req_self_sunlit: null
        }
      ]
    };
    $("#satellites").append(
      $("<option></option>")
        .data("satellite", satellite)
        .data("instrument", satellite.instruments[0])
        .data("color", "#ff0000")
        .text(satellite.name)
        .attr("selected", "selected")
    );
    changeSatellite();
  });
  $("#satellite-copy").click(function() {
    const selected = $("#satellites option:selected");
    const satellite = $.extend(true, {}, selected.data("satellite"));
    satellite.name += " (Copy)"
    $("#satellites").append(
      $("<option></option>")
        .data("satellite", satellite)
        .data("instrument", satellite.instruments[0])
        .data("color", selected.data("color"))
        .text(satellite.name)
        .attr("selected", "selected")
    );
    changeSatellite();
  });
  $("#satellite-delete").click(function() {
    if(confirm("Delete satellite " + $("#satellites :selected").data("satellite").name + "?")) {
      const index = $("#satellites").prop("selectedIndex");
      $("#satellites :selected").remove();
      if($("#satellites option").length > 0) {
        $("#satellites").prop("selectedIndex", Math.min(index, $("#satellites option").length - 1));
      }
      changeSatellite();
    }
  });

  $("#satellite-name").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.name = $("#satellite-name").val();
    $("#satellites option:selected").text($("#satellite-name").val());
    $("#orbit-data").prop("disabled", true);
  });
  $("#satellite-color").change(function() {
    $("#satellites option:selected").data("color", $("#satellite-color").val());
  });
  $("#satellite-type").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    if($("#satellite-type").val()=="train") {
      satellite.type = "train";
      satellite.number_satellites = +$("#train-count").val();
      satellite.interval = +$("#train-interval").val()*60;
      $(".constellation-train-group").show();
    } else {
      delete satellite.interval;
      $(".constellation-train-group").hide();
    }
    if($("#satellite-type").val()=="walker") {
      satellite.type = "walker";
      satellite.number_satellites = +$("#walker-count").val();
      satellite.number_planes = +$("#walker-planes").val();
      satellite.configuration = $("#walker-config").val();
      satellite.relative_spacing = +$("#walker-spacing").val();
      $(".constellation-walker-group").show();
    } else {
      delete satellite.number_planes;
      delete satellite.configuration;
      delete satellite.relative_spacing;
      $(".constellation-walker-group").hide();
    }
    if($("#satellite-type").val()=="satellite") {
      delete satellite.type;
      delete satellite.number_planes;
    }
    $("#orbit-data").prop("disabled", true);
  });
  $("#train-count").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.number_satellites = +$("#train-count").val();
    $("#orbit-data").prop("disabled", true);
  });
  $("#train-interval").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.interval = +$("#train-interval").val()*60;
    $("#orbit-data").prop("disabled", true);
  });
  $("#walker-count").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.number_satellites = +$("#walker-count").val();
    $("#orbit-data").prop("disabled", true);
  });
  $("#walker-planes").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.number_planes = +$("#walker-planes").val();
    $("#orbit-data").prop("disabled", true);
  });
  $("#walker-config").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.configuration = $("#walker-config").val();
    $("#orbit-data").prop("disabled", true);
  });
  $("#walker-spacing").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.relative_spacing = +$("#walker-spacing").val();
    $("#orbit-data").prop("disabled", true);
  });

  $("#instrument-add").click(function() {
    const satellite = $("#satellites option:selected").data("satellite");
    const instrument = {
      name: "New Instrument",
      field_of_regard: 180,
      min_access_time: 0,
      req_target_sunlit: null,
      req_self_sunlit: null
    };
    satellite.instruments.push(instrument);
    $("#satellites option:selected").data("instrument", instrument);
    $("#instruments").append(
      $("<option></option>")
        .data("instrument", instrument)
        .text(instrument.name)
        .attr("selected", "selected")
    );
    changeInstruments();
    $("#orbit-data").prop("disabled", true);
  });
  $("#instrument-copy").click(function() {
    const satellite = $("#satellites option:selected").data("satellite");
    const selected = $("#instruments option:selected");
    const instrument = $.extend({}, selected.data("instrument"));
    instrument.name += " (Copy)";
    satellite.instruments.push(instrument);
    $("#satellites option:selected").data("instrument", instrument);
    $("#instruments").append(
      $("<option></option>")
        .data("instrument", instrument)
        .text(instrument.name)
        .attr("selected", "selected")
    );
    changeInstruments();
    $("#orbit-data").prop("disabled", true);
  });
  $("#instrument-delete").click(function() {
    if(confirm("Delete instrument " + $("#instruments :selected").data("instrument").name + "?")) {
      const index = $("#instruments").prop("selectedIndex");
      $("#instruments :selected").remove();
      $("#instruments").prop("selectedIndex", Math.min(index, $("#instruments option").length - 1));
      changeInstruments();
      $("#orbit-data").prop("disabled", true);
    }
  });
  $("#instrument-name").change(function() {
    var instrument = $("#instruments option:selected").data("instrument");
    instrument.name = $("#instrument-name").val();
    $("#instruments option:selected").text($("#instrument-name").val());
    $("#orbit-data").prop("disabled", true);
  });
  $(".instrument-group").change(function() {
    var instrument = $("#instruments option:selected").data("instrument");
    instrument.field_of_regard = +$("#instrument-field").val();
    instrument.min_access_time = +$("#instrument-access").val();
    instrument.req_self_sunlit = getSunlitState($("#instrument-self-sunlit").val());
    instrument.req_target_sunlit = getSunlitState($("#instrument-target-sunlit").val());
    $("#orbit-data").prop("disabled", true);
  });

  $("#nav-design-tab").on("show.bs.tab", changeSatellite);

  // load initial data
  var satellites = [
    {
      name: "International Space Station",
      orbit: {
        type: "tle",
        tle: [
          "1 25544U 98067A   21156.30527927  .00003432  00000-0  70541-4 0  9993",
          "2 25544  51.6455  41.4969 0003508  68.0432  78.3395 15.48957534286754"
        ]
      },
      instruments: [
        {
          name: "Default",
          field_of_regard: 180,
          min_access_time: 0,
          req_target_sunlit: null,
          req_self_sunlit: null
        }
      ]
    }
  ];
  satellites.forEach(function(satellite) {
    $("#satellites").append(
      $("<option></option>")
        .data("satellite", satellite)
        .data("instrument", satellite.instruments[0])
        .data("color", "#ff0000")
        .text(satellite.name)
    );
  });
  $("#satellites").change(changeSatellite);
  $("#instruments").change(changeInstruments);
});
