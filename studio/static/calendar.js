(function () {
  var scroller = document.getElementById("year-scroll");
  if (!scroller) return;

  var yearKey = function () {
    var bar = scroller.querySelector(".type-track .bar[data-year]");
    return "studio-year-scroll:" + (bar ? bar.dataset.year : "current");
  };

  var restoreKey = yearKey();
  var saved = sessionStorage.getItem(restoreKey);
  if (saved !== null) {
    scroller.scrollLeft = Number(saved) || 0;
    sessionStorage.removeItem(restoreKey);
  } else {
    var today = scroller.querySelector(".day-num.is-today");
    if (today) {
      var left = today.getBoundingClientRect().left - scroller.getBoundingClientRect().left;
      scroller.scrollLeft += left - 220;
    }
  }

  var dayWidth = function () {
    var sample = scroller.querySelector(".day-num");
    return sample ? sample.getBoundingClientRect().width : 24;
  };

  var addDays = function (iso, days) {
    var parts = iso.split("-").map(Number);
    var value = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    value.setUTCDate(value.getUTCDate() + days);
    return value.toISOString().slice(0, 10);
  };

  var yearStart = function (year) {
    return year + "-01-01";
  };

  var clamp = function (value, min, max) {
    return Math.max(min, Math.min(max, value));
  };

  var applyGeometry = function (bar, start, span) {
    bar.dataset.start = String(start);
    bar.dataset.span = String(span);
    bar.style.left = "calc(" + start + " * var(--day) + 2px)";
    bar.style.width = "calc(" + span + " * var(--day) - 4px)";
  };

  var reloadKeepingScroll = function () {
    sessionStorage.setItem(yearKey(), String(scroller.scrollLeft));
    window.location.reload();
  };

  var saveDates = function (bar, startIndex, span) {
    var year = Number(bar.dataset.year);
    var start = addDays(yearStart(year), startIndex);
    var end = addDays(start, span - 1);
    var body = new FormData();
    body.append("start_date", start);
    body.append("end_date", end);
    return fetch("/activities/" + bar.dataset.activityId + "/schedule", {
      method: "POST",
      body: body,
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          if (!response.ok || !payload.ok) {
            throw new Error((payload && payload.error) || "Could not save the dates.");
          }
          return payload;
        });
      })
      .then(function () {
        reloadKeepingScroll();
      })
      .catch(function () {
        reloadKeepingScroll();
      });
  };

  var drag = null;

  scroller.addEventListener("pointerdown", function (event) {
    var handle = event.target.closest(".bar-handle");
    var bar = event.target.closest(".type-track .bar");
    if (!bar || event.button !== 0) return;
    if (event.target.closest("a") && event.metaKey) return;

    var mode = handle ? handle.dataset.edge : "move";
    var startIndex = Number(bar.dataset.start);
    var span = Number(bar.dataset.span);
    drag = {
      bar: bar,
      mode: mode,
      pointerId: event.pointerId,
      originX: event.clientX,
      originStart: startIndex,
      originSpan: span,
      moved: false,
      width: dayWidth(),
    };
    bar.classList.add("is-dragging");
    bar.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  scroller.addEventListener("pointermove", function (event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    var delta = Math.round((event.clientX - drag.originX) / drag.width);
    if (delta !== 0) drag.moved = true;
    var maxIndex = (Number(scroller.style.getPropertyValue("--days")) || 365) - 1;
    var start = drag.originStart;
    var span = drag.originSpan;

    if (drag.mode === "move") {
      start = clamp(drag.originStart + delta, 0, maxIndex - span + 1);
    } else if (drag.mode === "start") {
      var endExclusive = drag.originStart + drag.originSpan;
      start = clamp(drag.originStart + delta, 0, endExclusive - 1);
      span = endExclusive - start;
    } else if (drag.mode === "end") {
      var nextEnd = clamp(drag.originStart + drag.originSpan - 1 + delta, drag.originStart, maxIndex);
      span = nextEnd - drag.originStart + 1;
    }

    applyGeometry(drag.bar, start, span);
  });

  var finish = function (event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    var bar = drag.bar;
    var moved = drag.moved;
    var start = Number(bar.dataset.start);
    var span = Number(bar.dataset.span);
    bar.classList.remove("is-dragging");
    try {
      bar.releasePointerCapture(drag.pointerId);
    } catch (error) {
      /* ignore */
    }
    drag = null;
    if (!moved) return;
    bar.dataset.suppressClick = "1";
    saveDates(bar, start, span);
  };

  scroller.addEventListener("pointerup", finish);
  scroller.addEventListener("pointercancel", finish);

  scroller.addEventListener(
    "click",
    function (event) {
      var bar = event.target.closest(".type-track .bar");
      if (!bar) return;
      if (bar.dataset.suppressClick === "1") {
        event.preventDefault();
        delete bar.dataset.suppressClick;
      }
    },
    true
  );
})();
