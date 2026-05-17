(async function () {
  const status = document.getElementById("status");
  const table = document.getElementById("runs");
  const tbody = document.getElementById("runs-body");

  function fmtMoney(n) {
    if (n == null || Number.isNaN(n)) return "—";
    return "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  function fmtPct(n) {
    if (n == null || Number.isNaN(n)) return "—";
    return (n * 100).toFixed(2) + "%";
  }
  function fmtDate(iso) {
    return iso ? iso.slice(0, 10) : "—";
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

  try {
    const res = await fetch("runs.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`runs.json HTTP ${res.status}`);
    const runs = await res.json();
    if (!Array.isArray(runs) || runs.length === 0) {
      status.textContent = "No runs yet. Use the CLI / agent to create one.";
      return;
    }
    runs.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
    tbody.innerHTML = runs.map(row).join("");
    status.hidden = true;
    table.hidden = false;
  } catch (err) {
    status.textContent = "Failed to load runs.json: " + err.message;
  }
})();
