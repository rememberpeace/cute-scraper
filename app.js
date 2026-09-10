(function () {
  const $ = (id) => document.getElementById(id);

  let socket = null;
  let running = false;

  function setStatus(text, kind) {
    const box = $("status");
    box.hidden = false;
    $("statusText").textContent = text;
    const spinner = $("spinner");
    spinner.classList.toggle("hidden", kind !== "running");
  }

  function log(line, kind) {
    const el = document.createElement("span");
    el.className = "line" + (kind ? " " + kind : "");
    el.textContent = line;
    $("log").appendChild(el);
    $("log").scrollTop = $("log").scrollHeight;
  }

  function resetLog() {
    $("log").innerHTML = "";
  }

  function renderPreview(rows) {
    const wrap = $("preview");
    if (!rows || !rows.length) {
      wrap.innerHTML = '<div class="empty">No preview available.</div>';
      return;
    }

    const keys = [];
    rows.slice(0, 50).forEach((r) => {
      Object.keys(r).forEach((k) => {
        if (!keys.includes(k) && keys.length < 8) keys.push(k);
      });
    });

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    keys.forEach((k) => {
      const th = document.createElement("th");
      th.textContent = k;
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rows.slice(0, 50).forEach((r) => {
      const row = document.createElement("tr");
      keys.forEach((k) => {
        const td = document.createElement("td");
        let v = r[k];
        if (v === undefined || v === null) v = "";
        if (typeof v === "object") v = JSON.stringify(v);
        v = String(v);
        if (v.length > 120) v = v.slice(0, 120) + "…";
        td.textContent = v;
        row.appendChild(td);
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);

    wrap.innerHTML = "";
    wrap.appendChild(table);
  }

  async function fetchPreview(jobId) {
    try {
      const r = await fetch("/api/download/" + jobId + "/json");
      if (!r.ok) return;
      const data = await r.json();
      renderPreview(data.slice(0, 50));
    } catch (e) {
      console.warn("preview failed", e);
    }
  }

  function onDone(msg) {
    setStatus("Done — " + msg.rows + " rows", "done");
    log("✓ finished: " + msg.rows + " rows (" + msg.mode + ")", "ok");
    $("result").hidden = false;
    $("resultRows").textContent = msg.rows;
    $("resultMode").textContent = msg.mode || "auto";
    $("dlCsv").href = "/api/download/" + msg.job_id + "/csv";
    $("dlJson").href = "/api/download/" + msg.job_id + "/json";
    fetchPreview(msg.job_id);
    running = false;
    $("scrapeBtn").disabled = false;
  }

  function onError(message) {
    setStatus("Error: " + message, "error");
    log("✗ " + message, "err");
    running = false;
    $("scrapeBtn").disabled = false;
  }

  function openSocket() {
    return new Promise((resolve, reject) => {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(proto + "//" + location.host + "/ws/scrape");

      ws.onopen = () => {
        socket = ws;
        resolve(ws);
      };

      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "start") {
          setStatus("Scraping " + msg.url, "running");
          log("→ " + msg.url);
        } else if (msg.type === "progress") {
          log(msg.message);
        } else if (msg.type === "done") {
          onDone(msg);
        } else if (msg.type === "error") {
          onError(msg.message);
        }
      };

      ws.onclose = () => {
        running = false;
        $("scrapeBtn").disabled = false;
        socket = null;
      };

      ws.onerror = () => {
        reject(new Error("WebSocket failed"));
      };
    });
  }

  $("scrapeForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (running) return;

    const url = $("url").value.trim();
    if (!url) return;

    const mode = $("mode").value;
    const maxPages = parseInt($("maxPages").value, 10) || 5;

    resetLog();
    $("result").hidden = true;
    setStatus("Connecting…", "running");
    $("scrapeBtn").disabled = true;
    running = true;

    try {
      let ws = socket;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        ws = await openSocket();
      }
      ws.send(JSON.stringify({ url, mode, max_pages: maxPages }));
    } catch (err) {
      onError(err.message || "Could not connect");
    }
  });

  $("copyJson").addEventListener("click", async () => {
    const dl = $("dlJson").href;
    if (!dl || dl.endsWith("#")) return;
    try {
      const r = await fetch(dl);
      const text = await r.text();
      await navigator.clipboard.writeText(text);
      const btn = $("copyJson");
      const prev = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = prev; }, 1400);
    } catch (e) {
      console.warn(e);
    }
  });

  $("historyBtn").addEventListener("click", async () => {
    const modal = $("historyModal");
    modal.hidden = false;
    const list = $("historyList");
    list.innerHTML = '<div class="empty">Loading…</div>';
    try {
      const r = await fetch("/api/jobs");
      const jobs = await r.json();
      if (!jobs.length) {
        list.innerHTML = '<div class="empty">No jobs yet.</div>';
        return;
      }
      list.innerHTML = "";
      jobs.forEach((j) => {
        const row = document.createElement("div");
        row.className = "history-row";

        const left = document.createElement("div");
        left.className = "history-left";
        const u = document.createElement("div");
        u.className = "history-url";
        u.textContent = j.url;
        const m = document.createElement("div");
        m.className = "history-meta";
        const when = j.finished ? new Date(j.finished * 1000).toLocaleString() : "running";
        m.textContent = j.status + " · " + j.rows + " rows · " + when;
        left.appendChild(u);
        left.appendChild(m);

        const right = document.createElement("div");
        right.className = "history-right";
        if (j.status === "done") {
          const csv = document.createElement("a");
          csv.className = "ghost-btn";
          csv.href = "/api/download/" + j.id + "/csv";
          csv.textContent = "CSV";
          const js = document.createElement("a");
          js.className = "ghost-btn";
          js.href = "/api/download/" + j.id + "/json";
          js.textContent = "JSON";
          right.appendChild(csv);
          right.appendChild(js);
        }

        row.appendChild(left);
        row.appendChild(right);
        list.appendChild(row);
      });
    } catch (e) {
      list.innerHTML = '<div class="empty">Failed to load.</div>';
    }
  });

  $("closeHistory").addEventListener("click", () => {
    $("historyModal").hidden = true;
  });

  $("historyModal").addEventListener("click", (e) => {
    if (e.target === $("historyModal")) $("historyModal").hidden = true;
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("historyModal").hidden) {
      $("historyModal").hidden = true;
    }
  });
})();