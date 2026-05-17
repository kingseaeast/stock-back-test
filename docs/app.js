(async function () {
  const status = document.getElementById("status");
  const table = document.getElementById("runs");
  const tbody = document.getElementById("runs-body");
  const filters = document.getElementById("filters");
  const strategySel = document.getElementById("filter-strategy");
  const tickerInput = document.getElementById("filter-ticker");
  const fromInput = document.getElementById("filter-from");
  const toInput = document.getElementById("filter-to");
  const clearBtn = document.getElementById("filter-clear");
  const count = document.getElementById("count");
  const headers = document.querySelectorAll("th[data-sort]");

  let allRuns = [];
  let sortKey = "timestamp";
  let sortDir = -1; // -1 desc, +1 asc

  const fmtMoney = (n) =>
    n == null || Number.isNaN(n) ? "—" : "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  const fmtPct = (n) =>
    n == null || Number.isNaN(n) ? "—" : (n * 100).toFixed(2) + "%";
  const fmtDate = (iso) => (iso ? iso.slice(0, 10) : "—");

  function getSortable(run, key) {
    const m = run.metrics || {};
    switch (key) {
      case "timestamp": return run.timestamp || "";
      case "strategy": return run.strategy || "";
      case "ticker": return run.ticker || "";
      case "period": return (run.start || "") + " " + (run.end || "");
      case "total_budget": return run.total_budget ?? -Infinity;
      case "final_value": return m.final_value ?? -Infinity;
      case "total_return": return m.total_return ?? -Infinity;
      case "cagr": return m.cagr ?? -Infinity;
      case "max_drawdown": return m.max_drawdown ?? -Infinity;
      default: return "";
    }
  }

  function row(entry) {
    const m = entry.metrics || {};
    const cells = [
      ["Date", fmtDate(entry.timestamp)],
      ["Strategy", entry.strategy],
      ["Ticker", entry.ticker],
      ["Period", `${entry.start} → ${entry.end}`],
      ["Budget", fmtMoney(entry.total_budget), "num"],
      ["Final value", fmtMoney(m.final_value), "num"],
      ["Total return", fmtPct(m.total_return), "num"],
      ["CAGR", fmtPct(m.cagr), "num"],
      ["Max DD", fmtPct(m.max_drawdown), "num"],
      ["Report", `<a href="${entry.html}">open ↗</a>`],
    ];
    return (
      "<tr>" +
      cells
        .map(
          ([label, val, cls]) =>
            `<td${cls ? ` class="${cls}"` : ""} data-label="${label}">${val}</td>`,
        )
        .join("") +
      "</tr>"
    );
  }

  function filtered() {
    const strategy = strategySel.value;
    const ticker = (tickerInput.value || "").trim().toUpperCase();
    const from = fromInput.value;
    const to = toInput.value;
    return allRuns.filter((r) => {
      if (strategy && r.strategy !== strategy) return false;
      if (ticker && !(r.ticker || "").includes(ticker)) return false;
      if (from && (r.end || "") < from) return false;
      if (to && (r.start || "") > to) return false;
      return true;
    });
  }

  function render() {
    const subset = filtered().slice().sort((a, b) => {
      const av = getSortable(a, sortKey);
      const bv = getSortable(b, sortKey);
      if (av < bv) return -1 * sortDir;
      if (av > bv) return 1 * sortDir;
      return 0;
    });
    tbody.innerHTML = subset.map(row).join("");
    count.textContent = `${subset.length} of ${allRuns.length}`;
    headers.forEach((th) => {
      const indicator = th.querySelector(".sort-indicator");
      if (!indicator) return;
      indicator.textContent = th.dataset.sort === sortKey ? (sortDir === 1 ? "▲" : "▼") : "";
    });
    if (subset.length === 0) {
      tbody.innerHTML = `<tr><td colspan="10" class="muted center">No runs match these filters.</td></tr>`;
    }
  }

  function populateStrategyOptions() {
    const set = new Set(allRuns.map((r) => r.strategy).filter(Boolean));
    [...set].sort().forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      strategySel.appendChild(opt);
    });
  }

  function wireEvents() {
    [strategySel, tickerInput, fromInput, toInput].forEach((el) =>
      el.addEventListener("input", render),
    );
    clearBtn.addEventListener("click", () => {
      strategySel.value = "";
      tickerInput.value = "";
      fromInput.value = "";
      toInput.value = "";
      render();
    });
    headers.forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (sortKey === key) sortDir = -sortDir;
        else { sortKey = key; sortDir = key === "timestamp" ? -1 : 1; }
        render();
      });
    });
  }

  try {
    const res = await fetch("runs.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`runs.json HTTP ${res.status}`);
    allRuns = await res.json();
    if (!Array.isArray(allRuns) || allRuns.length === 0) {
      status.textContent = "No runs yet. Use the CLI / agent to create one.";
      return;
    }
    populateStrategyOptions();
    wireEvents();
    render();
    status.hidden = true;
    filters.hidden = false;
    table.hidden = false;
  } catch (err) {
    status.textContent = "Failed to load runs.json: " + err.message;
  }
})();
