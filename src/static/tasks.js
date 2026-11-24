// Submits analysis tasks to the server and polls them until complete.

const POLL_INTERVAL = 1000;

// Runs of each named analysis; starting a run cancels the previous run of the
// same name, so late results of a superseded run are dropped.
const activeRuns = {};

// Submits an analysis and polls its status (and progress) until complete.
//
// options:
//   name:       name of the analysis (one active run per name)
//   url:        endpoint to enqueue the analysis (POST)
//   payload:    request body (serialized to JSON)
//   resultUrl:  function(taskId) returning the endpoint of results (GET)
//   button:     jQuery button to disable (with a spinner) while running
//   progress:   jQuery progress element to show group progress
//   error:      jQuery element to show errors
//   onResult:   function(result, taskId) called with the results
//   onError:    optional function(message) called on failure
//
// Returns a run object with a `cancel()` method.
function runAnalysis(options) {
  if (activeRuns[options.name]) {
    activeRuns[options.name].cancel();
  }
  const run = {
    cancelled: false,
    task: null, // the enqueued task: {task_id, group_id}
    cancel: function() {
      if (this.cancelled) {
        return;
      }
      this.cancelled = true;
      revoke();
      finish();
    }
  };
  activeRuns[options.name] = run;

  // Revokes the enqueued task (if enqueued yet) so workers skip its pending
  // sub-tasks. Done tasks are unaffected, so this is safe to call any time.
  function revoke() {
    if (!run.task) {
      return;
    }
    $.ajax({
      url: "/tasks/" + run.task.task_id + "/revoke"
        + (run.task.group_id ? "?group_id=" + run.task.group_id : ""),
      type: "POST"
    });
  }

  function setBusy(busy) {
    if (options.button) {
      options.button.prop("disabled", busy);
      options.button.find(".spinner-border").toggle(busy);
    }
    if (options.progress) {
      options.progress.toggle(busy);
      options.progress.find(".progress-bar").css("width", "0%");
    }
  }
  function finish() {
    if (activeRuns[options.name] === run) {
      delete activeRuns[options.name];
    }
    setBusy(false);
  }
  function fail(message) {
    if (run.cancelled) {
      return;
    }
    finish();
    if (options.error) {
      options.error.text(message).show();
    }
    if (options.onError) {
      options.onError(message);
    }
  }

  if (options.error) {
    options.error.hide().text("");
  }
  setBusy(true);

  function pollProgress(groupId) {
    if (run.cancelled || activeRuns[options.name] !== run) {
      return;
    }
    $.get("/tasks/" + groupId + "/progress").done(function(progress) {
      if (run.cancelled || !options.progress) {
        return;
      }
      const percent = progress.task_count
        ? Math.round((100 * progress.completed_count) / progress.task_count)
        : 0;
      options.progress.find(".progress-bar").css("width", percent + "%");
      if (progress.completed_count < progress.task_count) {
        setTimeout(function() { pollProgress(groupId); }, POLL_INTERVAL);
      }
    });
  }

  function pollStatus(taskId) {
    if (run.cancelled) {
      return;
    }
    $.get("/tasks/" + taskId + "/status")
      .done(function(status) {
        if (run.cancelled) {
          return;
        }
        if (!status.ready) {
          setTimeout(function() { pollStatus(taskId); }, POLL_INTERVAL);
          return;
        }
        $.get(options.resultUrl(taskId))
          .done(function(result) {
            if (run.cancelled) {
              return;
            }
            finish();
            options.onResult(result, taskId);
          })
          .fail(function(xhr) { fail(formatError(xhr)); });
      })
      .fail(function(xhr) { fail(formatError(xhr)); });
  }

  $.ajax({
    url: options.url,
    type: "POST",
    contentType: "application/json",
    dataType: "json",
    data: JSON.stringify(options.payload)
  })
    .done(function(task) {
      run.task = task;
      if (run.cancelled) {
        // cancelled while enqueuing
        revoke();
        return;
      }
      if (task.group_id) {
        pollProgress(task.group_id);
      }
      pollStatus(task.task_id);
    })
    .fail(function(xhr) { fail(formatError(xhr)); });

  return run;
}

// Cancels the active run of a named analysis, if any: its results are dropped
// and its server task is revoked.
function cancelAnalysis(name) {
  if (activeRuns[name]) {
    activeRuns[name].cancel();
  }
}
