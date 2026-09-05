// Design tab: orbit-track computation and Cesium visualization.

function icrf(scene, time) {
  if (scene.mode !== Cesium.SceneMode.SCENE3D) {
    return;
  }
  var icrfToFixed = Cesium.Transforms.computeIcrfToFixedMatrix(time);
  if (Cesium.defined(icrfToFixed)) {
    var camera = viewer.camera;
    var offset = Cesium.Cartesian3.clone(camera.position);
    var transform = Cesium.Matrix4.fromRotationTranslation(icrfToFixed);
    camera.lookAtTransform(transform, offset);
  }
}

function collectOrbitTrack() {
  clearOrbitTrack();
  $("#orbit-analyze").prop("disabled", true);
  $("#orbit-analyze .spinner-border").show();
  $("#satellites > option").each(function() {
    const option = $(this);
    $.ajax({
      url: "/analyze/orbit-track",
      type: "POST",
      contentType: "application/json",
      dataType: "json",
      data: JSON.stringify({
        satellite: option.data("satellite"),
        instrument: option.data("instrument"),
        times: {
          start: $('#display-start').datetimepicker('viewDate').toISOString(),
          end: $('#display-start').datetimepicker('viewDate').clone().add(
            $("#display-duration").val(), "minutes").toISOString(),
          delta: parseInt($("#display-step").val())
        }
      }),
      success: function(response) {
        checkOrbitTrack(response.task_id, option);
        if(response.group_id) {
          checkProgress(response.group_id, option);
        }
      }
    });
  });
};

function checkProgress(groupId, option) {
  $.get(
    "/tasks/"+groupId+"/progress",
    function(progress) {
      if(progress.task_count == progress.completed_count) {
        $("#orbit-progress").hide();
        $("#orbit-progress .progress-bar").css('width', "0%");
        $("#orbit-progress .progress-bar").prop('aria-valuenow', 0);
      } else {
        $("#orbit-progress").show();
        var percent = Math.round(100*(progress.completed_count/progress.task_count));
        $("#orbit-progress .progress-bar").css('width', percent + "%");
        $("#orbit-progress .progress-bar").prop('aria-valuenow', percent);
        setTimeout(
          function() {
            checkProgress(groupId);
          }, 1000
        );
      }
    }
  );
};
function checkOrbitTrack(taskId, option) {
  $.get(
    "/tasks/"+taskId+"/status",
    function(status) {
      if(status.ready) {
        $.get(
          "/analyze/orbit-track/"+taskId,
          function(results) {
            option.data("features", results.features);
            $("#orbit-analyze .spinner-border").hide();
            $("#orbit-analyze").prop("disabled", false);
            $("#orbit-data").prop("disabled", false);
            $("#orbit-data-json").prop("disabled", false);
            $("#orbit-data-csv").prop("disabled", false);
            processOrbitTrack(option);
          }
        );
      } else {
        setTimeout(
          function() {
            checkOrbitTrack(taskId, option);
          }, 1000
        );
      }
    }
  );
};

// entity group holding the drawn orbit tracks; assigned once the Cesium
// viewer (from index.js) is ready, so processOrbitTrack/clearOrbitTrack
// (declared here at top level) can both reference it
var orbitTrack;
function processOrbitTrack(option) {
  var start = $('#display-start').datetimepicker('viewDate').toISOString();
  var end = $('#display-start').datetimepicker('viewDate').clone().add($("#display-duration").val(), "minutes").toISOString();
  var satellites = {};
  _.forEach(option.data("features"), function(feature) {
    var satellite = feature.properties.satellite;
    if(!satellites.hasOwnProperty(satellite)) {
      satellites[satellite] = {
        position: new Cesium.SampledPositionProperty(),
        radius: new Cesium.SampledProperty(Number),
        visibility: new Cesium.SampledProperty(Cesium.Color)
      };
      satellites[satellite].position.setInterpolationOptions({
        interpolationDegree: 2,
        interpolationAlgorithm: Cesium.LagrangePolynomialApproximation
      });
    }
    satellites[satellite].position.addSample(
      Cesium.JulianDate.fromIso8601(feature.properties.time),
      Cesium.Cartesian3.fromDegrees(
        feature.geometry.coordinates[0],
        feature.geometry.coordinates[1],
        feature.geometry.coordinates[2]
      )
    );
    satellites[satellite].radius.addSample(
      Cesium.JulianDate.fromIso8601(feature.properties.time),
      feature.properties.swath_width/2
    );
    satellites[satellite].visibility.addSample(
      Cesium.JulianDate.fromIso8601(feature.properties.time),
      Cesium.Color.fromCssColorString(option.data("color")).withAlpha(feature.properties.valid_obs*0.5)
    );
  });
  for(var satellite in satellites) {
    viewer.entities.add({
      parent: orbitTrack,
      availability: new Cesium.TimeIntervalCollection([
        new Cesium.TimeInterval({
          start: Cesium.JulianDate.fromIso8601(start),
          stop: Cesium.JulianDate.fromIso8601(end)
        })
      ]),
      position: satellites[satellite].position,
      orientation: new Cesium.VelocityOrientationProperty(satellites[satellite].position),
      point: {
        pixelSize: 8,
        color: Cesium.Color.fromCssColorString(option.data("color"))
      },
      path: {
        leadTime: $("#display-path").is(":checked") ? $("#display-duration").val()*60 : 0,
        trailTime: $("#display-path").is(":checked") ? $("#display-duration").val()*60 : 0,
        material: new Cesium.ColorMaterialProperty(Cesium.Color.fromCssColorString(option.data("color")))
      },
      ellipse: {
        semiMajorAxis: satellites[satellite].radius,
        semiMinorAxis: satellites[satellite].radius,
        height: 0,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        material: new Cesium.ColorMaterialProperty(satellites[satellite].visibility),
        outline: true,
        outlineColor: Cesium.Color.BLACK
      }
    });
  }
  viewer.clock.startTime = Cesium.JulianDate.fromIso8601(start);
  viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(start);
  viewer.clock.stopTime = Cesium.JulianDate.fromIso8601(end);
  viewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP;
  viewer.timeline.zoomTo(
    Cesium.JulianDate.fromIso8601(start),
    Cesium.JulianDate.fromIso8601(end)
  );
}
function clearOrbitTrack() {
  clearEntities(orbitTrack);
}

$(document).ready(function() {
  orbitTrack = viewer.entities.add(new Cesium.Entity());

  $("#display-observer").change(function() {
    if($(this).val() == "inertial") {
      viewer.scene.postUpdate.addEventListener(icrf);
    } else {
      viewer.scene.postUpdate.removeEventListener(icrf);
    }
  });

  $('#display-start').datetimepicker({
    timeZone: "UTC",
    defaultDate: moment.now(),
    icons: {
      time: 'far fa-clock'
    }
  });
  $("#display-duration").val(60);
  $("#display-step").val(30);

  $("#display-path").change(function() {
    _.forEach(viewer.entities.values, function(entity) {
      if(entity.parent === orbitTrack) {
        entity.path.leadTime = $("#display-path").is(":checked") ? $("#display-duration").val()*60 : 0;
        entity.path.trailTime = $("#display-path").is(":checked") ? $("#display-duration").val()*60 : 0;
      }
    });
  });
  $("#display-lighting").change(function() {
    viewer.scene.globe.enableLighting = $("#display-lighting").is(":checked");
  });

  var orbitTable;
  $("#orbit-dialog").on("show.bs.modal", function() {
    $("#orbit-dialog").find("tbody").empty();
    var features = [];
    $("#satellites option").each(function(index) {
      _.forEach($(this).data("features"), function(feature) {
          features.push({
            date: feature.properties.time,
            satellite: feature.properties.satellite,
            instrument: feature.properties.instrument,
            latitude: feature.geometry.coordinates[1],
            longitude: feature.geometry.coordinates[0],
            altitude: feature.geometry.coordinates[2]/1000,
            obsRadius: feature.properties.swath_width/2000,
            obsValid: feature.properties.valid_obs
          });
      });
    });

    if(orbitTable) {
      orbitTable.destroy();
    }
    orbitTable = $('#orbit-table').DataTable({
      'data': _.map(features, function(feature) {
        return [
          feature.date,
          feature.satellite,
          feature.instrument,
          feature.latitude,
          feature.longitude,
          feature.altitude,
          feature.obsRadius,
          feature.obsValid
        ];
      }),
      'columns': [
        { title: 'Date' },
        { title: 'Satellite' },
        { title: 'Instrument' },
        {
          title: 'Latitude (deg)',
          render: $.fn.dataTable.render.number(',', '.', 6)
        },
        {
          title: 'Longitude (deg)',
          render: $.fn.dataTable.render.number(',', '.', 6)
        },
        {
          title: 'Altitude (km)',
          render: $.fn.dataTable.render.number(',', '.', 2)
        },
        { title: 'Obs. Radius (km)',
          render: $.fn.dataTable.render.number(',', '.', 2)
        },
        { title: 'Obs. Valid' }
      ],
      'order': [[ 0, 'asc'], [ 1, 'asc' ], [2, 'asc']],
      'searching': false
    });
    $("#orbit-data-json").attr(
      "href",
      "data:text/json;charset=utf-8,"
      + encodeURIComponent(
        JSON.stringify(
          _.map(features, function(feature) {
            return {
              date: feature.date,
              satellite: feature.satellite,
              instrument: feature.instrument,
              latitude_deg: feature.latitude,
              longitude_deg: feature.longitude,
              altitude_km: feature.altitude,
              obsRadius_km: feature.obsRadius,
              obsValid: feature.obsValid
            }
          })
        )
      )
    );
    $("#orbit-data-json").attr("download", "orbit.json");
    $("#orbit-data-csv").attr(
      "href",
      "data:text/csv;charset=utf-8,"
      + encodeURIComponent(
        [
          [
            "date",
            "satellite",
            "instrument",
            "latitude_deg",
            "longitude_deg",
            "altitude_km",
            "obsRadius_km",
            "obsValid"
          ].join()
        ].concat(
          _.map(features, function(feature) {
            return [
              feature.date,
              feature.satellite,
              feature.instrument,
              feature.latitude,
              feature.longitude,
              feature.altitude,
              feature.obsRadius,
              feature.obsValid
            ].join();
          })
        ).join("\n")
      )
    );
    $("#orbit-data-csv").attr("download", "orbit.csv");
  });

  $("#orbit-analyze").click(collectOrbitTrack);
  $("#satellite-dialog").on('hidden.bs.modal', collectOrbitTrack);
  $("#nav-design-tab").on("show.bs.tab", collectOrbitTrack);
  $("#nav-design-tab").on("hide.bs.tab", clearOrbitTrack);
});
