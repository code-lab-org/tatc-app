// Design tab: orbit configuration form (orbit type fields, Celestrak TLE search).

// mean Earth radius (meters), matching tatc.constants.EARTH_MEAN_RADIUS;
// used to convert a user-facing altitude into a Keplerian orbit's
// semimajor_axis (semimajor_axis = EARTH_MEAN_RADIUS + altitude)
const EARTH_MEAN_RADIUS = 6371008.771415059;

function getOrbit() {
  if($("#satellite-orbit").val()=="tle") {
    return {
      type: "tle",
      tle: $("#orbit-tle").val().split("\n")
    }
  } else if($("#satellite-orbit").val()=="circular") {
    return {
      type: "circular",
      epoch: $("#orbit-circular-epoch").datetimepicker('viewDate').toISOString(),
      mean_altitude: $("#orbit-circular-altitude").val()*1000,
      inclination: $("#orbit-circular-inclination").val(),
      right_ascension_ascending_node: $("#orbit-circular-raan").val(),
      true_anomaly: $("#orbit-circular-ta").val()
    }
  } else if($("#satellite-orbit").val()=="sso") {
    return {
      type: "sso",
      epoch: $("#orbit-sso-epoch").datetimepicker('viewDate').toISOString(),
      equator_crossing_time: $("#orbit-sso-ect").datetimepicker('viewDate').format("HH:mm"),
      equator_crossing_ascending: $("#orbit-sso-direction").val()=="asc",
      mean_altitude: $("#orbit-sso-altitude").val()*1000,
      true_anomaly: $("#orbit-sso-ta").val()
    }
  } else if($("#satellite-orbit").val()=="keplerian") {
    return {
      type: "keplerian",
      epoch: $("#orbit-keplerian-epoch").datetimepicker('viewDate').toISOString(),
      semimajor_axis: $("#orbit-keplerian-altitude").val()*1000 + EARTH_MEAN_RADIUS,
      inclination: $("#orbit-keplerian-inclination").val(),
      eccentricity: $("#orbit-keplerian-eccentricity").val(),
      perigee_argument: $("#orbit-keplerian-pa").val(),
      right_ascension_ascending_node: $("#orbit-keplerian-raan").val(),
      true_anomaly: $("#orbit-keplerian-ta").val()
    }
  }
}

function queryCelestrak() {
  var query = $("#celestrak-name").val();
  if(query.length > 2) {
    $("#celestrak-objects").val([]);
    $("#celestrak-objects").change();
    $("#celestrak-tle").val("");
    $.ajax({
      url: "celestrak/tle?name=" + query,
      type: "GET",
      crossDomain: true,
      success: function(response) {
        var lines = response.split(/\r?\n/);
        if(lines.length >= 3) {
          $("#celestrak-objects").empty();
          for(var i = 0; i < lines.length - 2; i += 3) {
            $("#celestrak-objects").append(
              $('<option label="' + lines[i] + '" value="' + lines[i] + '">')
              .data("tle", lines[i+1] + "\n" + lines[i+2])
            );
          }
        }
      }
    });
  }
}

$(document).ready(function() {
  $('#orbit-circular-epoch').datetimepicker({
    timeZone: "UTC",
    defaultDate: moment.now(),
    icons: {
      time: 'far fa-clock'
    }
  });
  $('#orbit-sso-epoch').datetimepicker({
    timeZone: "UTC",
    defaultDate: moment.now(),
    icons: {
      time: 'far fa-clock'
    }
  });
  $('#orbit-sso-ect').datetimepicker({
    timeZone: "UTC",
    defaultDate: moment.now(),
    format: 'LT'
  });
  $('#orbit-keplerian-epoch').datetimepicker({
    timeZone: "UTC",
    defaultDate: moment.now(),
    icons: {
      time: 'far fa-clock'
    }
  });

  $("#satellite-orbit").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    $("#satellite-orbit").val()=="tle" ? $(".orbit-tle-group").show() : $(".orbit-tle-group").hide();
    $("#satellite-orbit").val()=="circular" ? $(".orbit-circular-group").show() : $(".orbit-circular-group").hide();
    $("#satellite-orbit").val()=="sso" ? $(".orbit-sso-group").show() : $(".orbit-sso-group").hide();
    $("#satellite-orbit").val()=="keplerian" ? $(".orbit-keplerian-group").show() : $(".orbit-keplerian-group").hide();
    satellite.orbit = getOrbit();
    $("#orbit-data").prop("disabled", true);
  });
  $("#celestrak-dialog").on("shown.bs.modal", queryCelestrak);
  $("#celestrak-name").change(queryCelestrak);
  $("#celestrak-objects").change(function() {
    if($("#celestrak-objects option:selected").length > 0) {
      $("#celestrak-tle").val($("#celestrak-objects option:selected").data("tle"));
      $("#celestrak-tle-ok").prop('disabled', false);
    } else {
      $("#celestrak-tle-ok").prop('disabled', true);
    }
  });
  $("#celestrak-tle-ok").click(function() {
    $("#orbit-tle").val($("#celestrak-tle").val());
    $("#orbit-tle").change();
  })
  $("#orbit-tle").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.tle = $("#orbit-tle").val().split("\n");
    $("#orbit-data").prop("disabled", true);
  });
  $("#orbit-circular-epoch").on("change.datetimepicker", function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.epoch = $("#orbit-circular-epoch").datetimepicker("viewDate").toISOString();
    $("#orbit-data").prop("disabled", true);
  });
  $(".orbit-circular-group").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.mean_altitude = +$("#orbit-circular-altitude").val()*1000;
    satellite.orbit.inclination = +$("#orbit-circular-inclination").val();
    satellite.orbit.right_ascension_ascending_node = +$("#orbit-circular-raan").val();
    satellite.orbit.true_anomaly = +$("#orbit-circular-ta").val();
    $("#orbit-data").prop("disabled", true);
  });
  $("#orbit-sso-epoch").on("change.datetimepicker", function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.epoch = $("#orbit-sso-epoch").datetimepicker("viewDate").toISOString();
    $("#orbit-data").prop("disabled", true);
  });
  $("#orbit-sso-ect").on("change.datetimepicker", function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.equator_crossing_time = $("#orbit-sso-ect").datetimepicker("viewDate").format("HH:mm");
    $("#orbit-data").prop("disabled", true);
  });
  $(".orbit-sso-group").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.equator_crossing_ascending = $("#orbit-sso-direction").val()=="asc";
    satellite.orbit.mean_altitude = +$("#orbit-sso-altitude").val()*1000;
    satellite.orbit.true_anomaly = +$("#orbit-sso-ta").val();
    $("#orbit-data").prop("disabled", true);
  });
  $("#orbit-keplerian-epoch").on("change.datetimepicker", function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.epoch = $("#orbit-keplerian-epoch").datetimepicker("viewDate").toISOString();
    $("#orbit-data").prop("disabled", true);
  });
  $(".orbit-keplerian-group").change(function() {
    var satellite = $("#satellites option:selected").data("satellite");
    satellite.orbit.semimajor_axis = +$("#orbit-keplerian-altitude").val()*1000 + EARTH_MEAN_RADIUS;
    satellite.orbit.inclination = +$("#orbit-keplerian-inclination").val();
    satellite.orbit.eccentricity = +$("#orbit-keplerian-eccentricity").val();
    satellite.orbit.perigee_argument = +$("#orbit-keplerian-pa").val();
    satellite.orbit.right_ascension_ascending_node = +$("#orbit-keplerian-raan").val();
    satellite.orbit.true_anomaly = +$("#orbit-keplerian-ta").val();
    $("#orbit-data").prop("disabled", true);
  });
});
