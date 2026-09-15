/*
 * References page.
 *
 * Rows are selected with checkboxes rather than by clicking, so the operator
 * can build up a set across several searches without losing what they already
 * ticked. Selection is held by Event ID, not by row position, which is why it
 * survives re-searching and paging.
 */
(function () {
  var cfg = JSON.parse(document.getElementById("ref-config").textContent);
  var snack = window.COBRA.snack;

  var columns = cfg.columns.slice();
  var selected = {};           // Event ID -> true
  var pageNo = 0;
  var lastMode = "prefill";    // or "search"

  var headRow = document.getElementById("head-row");
  var bodyRows = document.getElementById("body-rows");
  var resultNote = document.getElementById("result-note");

  function filters() {
    function val(id) {
      var el = document.getElementById(id);
      return el && el.value.trim() ? el.value.trim() : "";
    }
    return {
      start_date: val("f-start"),
      end_date: val("f-end"),
      number: val("f-number"),
      calling_party: val("f-clgpty"),
      called_party: val("f-cldpty"),
      category: val("f-category"),
      language: val("f-language"),
      filter_value: val("f-filter"),
      key_word: val("f-keyword")
    };
  }

  function post(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); });
  }

  function render(data) {
    headRow.innerHTML = "";
    var th = document.createElement("th");
    th.className = "col-check";
    headRow.appendChild(th);
    data.columns.forEach(function (c) {
      var el = document.createElement("th");
      el.textContent = c.label;
      headRow.appendChild(el);
    });

    bodyRows.innerHTML = "";
    if (!data.rows.length) {
      var tr = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = data.columns.length + 1;
      td.className = "empty-cell";
      td.textContent = "No matching messages.";
      tr.appendChild(td);
      bodyRows.appendChild(tr);
      return;
    }

    data.rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.dataset.id = row._id;
      if (selected[row._id]) tr.classList.add("is-selected");

      var tdc = document.createElement("td");
      tdc.className = "col-check";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !!selected[row._id];
      cb.addEventListener("change", function () {
        if (cb.checked) selected[row._id] = true;
        else delete selected[row._id];
        tr.classList.toggle("is-selected", cb.checked);
        updateCount();
      });
      tdc.appendChild(cb);
      tr.appendChild(tdc);

      data.columns.forEach(function (c) {
        var td = document.createElement("td");
        td.textContent = row[c.key] || "";
        tr.appendChild(td);
      });

      // Clicking anywhere on the row toggles it, which is quicker than
      // aiming for the checkbox.
      tr.addEventListener("click", function (e) {
        if (e.target.tagName === "INPUT") return;
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event("change"));
      });

      bodyRows.appendChild(tr);
    });
    updateCount();
  }

  function updateCount() {
    var n = Object.keys(selected).length;
    resultNote.textContent = n ? n + " selected" : "";
  }

  function load(mode) {
    lastMode = mode;
    var payload = { page_no: pageNo, offset: 25 };
    if (mode === "prefill") {
      payload.prefill = true;
      payload.numbers = cfg.numbers;
      payload.parties = cfg.parties;
    } else {
      payload.filters = filters();
    }
    post("/message/api/references/" + cfg.msgType, payload)
      .then(function (b) {
        if (!b.ok) { snack.error(b.error || "Search failed."); return; }
        render(b);
      })
      .catch(function (e) { snack.error("Could not reach the server.", String(e)); });
  }

  document.getElementById("btn-search").addEventListener("click", function () {
    pageNo = 0;
    load("search");
  });
  document.getElementById("btn-prefill").addEventListener("click", function () {
    pageNo = 0;
    ["f-start","f-end","f-number","f-clgpty","f-cldpty","f-category",
     "f-language","f-filter","f-keyword"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = "";
    });
    load("prefill");
  });
  document.getElementById("btn-next").addEventListener("click", function () {
    pageNo += 1;
    load(lastMode);
  });
  document.getElementById("btn-prev").addEventListener("click", function () {
    if (pageNo === 0) return;
    pageNo -= 1;
    load(lastMode);
  });

  document.getElementById("btn-apply").addEventListener("click", function () {
    var ids = Object.keys(selected);
    if (!ids.length) { snack.error("Tick at least one message first."); return; }
    post("/message/api/references/" + cfg.msgType + "/apply", { event_ids: ids })
      .then(function (b) {
        if (!b.ok) { snack.error(b.error || "Could not add references."); return; }
        document.getElementById("ref-preview").value = b.Msg_Ref;
        document.getElementById("apply-note").textContent =
          b.added + " reference(s) added to the message.";
        selected = {};
        bodyRows.querySelectorAll("tr").forEach(function (tr) {
          tr.classList.remove("is-selected");
          var cb = tr.querySelector("input[type=checkbox]");
          if (cb) cb.checked = false;
        });
        updateCount();
        snack.success("Reference text updated.");
      })
      .catch(function (e) { snack.error("Could not reach the server.", String(e)); });
  });

  // --- column chooser ----------------------------------------------------
  var modal = document.getElementById("columns-modal");
  var list = document.getElementById("column-list");

  document.getElementById("btn-columns").addEventListener("click", function () {
    list.innerHTML = "";
    cfg.available.forEach(function (c) {
      var row = document.createElement("label");
      row.className = "checkbox-row";
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = c.key;
      cb.checked = columns.indexOf(c.key) !== -1;
      var span = document.createElement("span");
      span.textContent = c.label;
      row.appendChild(cb);
      row.appendChild(span);
      list.appendChild(row);
    });
    modal.hidden = false;
  });

  document.getElementById("columns-cancel").addEventListener("click", function () {
    modal.hidden = true;
  });
  modal.addEventListener("click", function (e) {
    if (e.target === modal) modal.hidden = true;
  });

  document.getElementById("columns-save").addEventListener("click", function () {
    var chosen = [];
    list.querySelectorAll("input[type=checkbox]").forEach(function (cb) {
      if (cb.checked) chosen.push(cb.value);
    });
    if (!chosen.length) { snack.error("Keep at least one column."); return; }
    post("/message/api/references/" + cfg.msgType + "/columns", { columns: chosen })
      .then(function (b) {
        if (!b.ok) { snack.error(b.error || "Could not save columns."); return; }
        columns = b.columns;
        modal.hidden = true;
        snack.success("Column layout saved to your profile.");
        load(lastMode);
      })
      .catch(function (e) { snack.error("Could not reach the server.", String(e)); });
  });

  load("prefill");
})();
