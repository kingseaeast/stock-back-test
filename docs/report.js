/* Interactive report bootstrap.
 *
 * Reads the embedded #report-data JSON, renders parameter controls based on
 * the strategy's param schema + common controls (window/budget/costs), and
 * re-runs the backtest in the browser on every input change via Backtest.run.
 *
 * Updates: chart (Plotly.react), summary table, trade log, header summary.
 */
(function () {
  "use strict";

  const PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"];

  // ---------------------------------------------------------- formatters ---

  const fmtMoney = (n) =>
    Number.isFinite(n)
      ? "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : "—";
  const fmtPct = (n) => (Number.isFinite(n) ? (n * 100).toFixed(2) + "%" : "—");

  // ---------------------------------------------------------- controls ----

  function buildCommonControls(state) {
    const minDate = state.data.prices[0].date;
    const maxDate = state.data.prices[state.data.prices.length - 1].date;
    return [
      {
        name: "start", type: "date", label: "Window start",
        min: minDate, max: maxDate, default: state.defaults.start,
      },
      {
        name: "end", type: "date", label: "Window end",
        min: minDate, max: maxDate, default: state.defaults.end,
      },
      {
        name: "total_budget", type: "number", label: "Budget ($)",
        min: 100, max: 1000000, step: 100, default: state.defaults.total_budget,
      },
      {
        name: "commission_bps", type: "number", label: "Commission (bps)",
        min: 0, max: 100, step: 1, default: state.defaults.commission_bps,
      },
      {
        name: "slippage_bps", type: "number", label: "Slippage (bps)",
        min: 0, max: 100, step: 1, default: state.defaults.slippage_bps,
      },
    ];
  }

  function renderControlsInto(container, schema, currentValues, group) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "control-group";
    const legend = document.createElement("legend");
    legend.textContent = group;
    fieldset.appendChild(legend);
    for (const entry of schema) {
      fieldset.appendChild(renderControl(entry, currentValues[entry.name]));
    }
    container.appendChild(fieldset);
  }

  function renderControl(entry, currentValue) {
    const wrap = document.createElement("label");
    wrap.className = "control";
    const labelText = document.createElement("span");
    labelText.className = "control-label";
    labelText.textContent = entry.label || entry.name;
    wrap.appendChild(labelText);

    let input;
    if (entry.type === "number") {
      input = document.createElement("input");
      input.type = "number";
      if (entry.min != null) input.min = entry.min;
      if (entry.max != null) input.max = entry.max;
      if (entry.step != null) input.step = entry.step;
      input.value = currentValue ?? entry.default;
    } else if (entry.type === "date") {
      input = document.createElement("input");
      input.type = "date";
      if (entry.min) input.min = entry.min;
      if (entry.max) input.max = entry.max;
      input.value = currentValue ?? entry.default;
    } else if (entry.type === "boolean") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = currentValue ?? entry.default;
    } else if (entry.type === "select") {
      input = document.createElement("select");
      for (const opt of entry.options) {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        input.appendChild(o);
      }
      input.value = currentValue ?? entry.default;
    } else {
      throw new Error("Unknown control type: " + entry.type);
    }
    input.dataset.controlName = entry.name;
    input.dataset.controlType = entry.type;
    wrap.appendChild(input);
    if (entry.help) {
      const help = document.createElement("span");
      help.className = "control-help";
      help.textContent = entry.help;
      wrap.appendChild(help);
    }
    return wrap;
  }

  function readValueFromInput(input) {
    if (input.dataset.controlType === "boolean") return input.checked;
    if (input.dataset.controlType === "number") return Number(input.value);
    return input.value;
  }

  function snapshotCurrentValues(panel) {
    const out = {};
    for (const input of panel.querySelectorAll("[data-control-name]")) {
      out[input.dataset.controlName] = readValueFromInput(input);
    }
    return out;
  }

  // ------------------------------------------------------- chart figure ---

  function buildFigure(result, state) {
    const runs = [result.strategy, ...result.benchmarks];
    const showFg = state.strategy === "fear_greed";
    const rows = showFg ? 5 : 4;
    const titles = [
      "Equity curves (same total budget)",
      "Drawdown",
      `${state.ticker} price + strategy trades`,
      "Cumulative cash deployed",
    ];
    if (showFg) titles.push(`CNN ${(state.currentParams.index_type || "fear_greed").replace(/_/g, " ")}`);

    const heights = showFg ? [0.30, 0.15, 0.20, 0.10, 0.25] : [0.32, 0.18, 0.25, 0.25];
    const layout = buildSubplotLayout(rows, heights, titles, result.strategy.dates);

    const data = [];

    // Row 1: equity
    runs.forEach((run, i) => {
      data.push({
        x: run.dates, y: run.equity, name: run.name, type: "scatter", mode: "lines",
        line: { color: PALETTE[i % PALETTE.length] },
        xaxis: "x", yaxis: "y",
      });
    });

    // Row 2: drawdown (%)
    runs.forEach((run, i) => {
      data.push({
        x: run.dates, y: run.drawdown.map((d) => d * 100),
        name: `${run.name} dd`, type: "scatter", mode: "lines",
        line: { color: PALETTE[i % PALETTE.length] },
        xaxis: "x", yaxis: "y2", showlegend: false,
      });
    });

    // Row 3: price + trade markers
    const priceWindow = state.data.prices.filter(
      (p) => p.date >= state.currentConfig.start && p.date <= state.currentConfig.end,
    );
    data.push({
      x: priceWindow.map((p) => p.date), y: priceWindow.map((p) => p.adj_close),
      name: `${state.ticker} adj close`, type: "scatter", mode: "lines",
      line: { color: "#555" }, showlegend: false,
      xaxis: "x", yaxis: "y3",
    });
    const priceMap = new Map(priceWindow.map((p) => [p.date, p.adj_close]));
    const buys = result.strategy.trades.filter((t) => t.side === "buy");
    const sells = result.strategy.trades.filter((t) => t.side === "sell");
    if (buys.length) {
      data.push({
        x: buys.map((t) => t.date), y: buys.map((t) => priceMap.get(t.date)),
        name: "buy", mode: "markers", type: "scatter",
        marker: { symbol: "triangle-up", size: 10, color: "#2ca02c" },
        xaxis: "x", yaxis: "y3",
      });
    }
    if (sells.length) {
      data.push({
        x: sells.map((t) => t.date), y: sells.map((t) => priceMap.get(t.date)),
        name: "sell", mode: "markers", type: "scatter",
        marker: { symbol: "triangle-down", size: 10, color: "#d62728" },
        xaxis: "x", yaxis: "y3",
      });
    }

    // Row 4: cash deployed
    runs.forEach((run, i) => {
      data.push({
        x: run.dates, y: run.cash_deployed,
        name: `${run.name} deployed`, type: "scatter", mode: "lines",
        line: { color: PALETTE[i % PALETTE.length], dash: "dot" },
        showlegend: false,
        xaxis: "x", yaxis: "y4",
      });
    });

    // Row 5: F&G with thresholds
    if (showFg) {
      const fgWindow = state.data.fear_greed.filter(
        (f) => f.date >= state.currentConfig.start && f.date <= state.currentConfig.end,
      );
      const indexCol = state.currentParams.index_type || "fear_greed";
      data.push({
        x: fgWindow.map((f) => f.date), y: fgWindow.map((f) => f[indexCol]),
        name: indexCol, type: "scatter", mode: "lines",
        line: { color: "#8e44ad" }, showlegend: false,
        xaxis: "x", yaxis: "y5",
      });
      const buyBelow = state.currentParams.buy_below ?? 25;
      const exitAbove = state.currentParams.exit_above ?? 75;
      layout.shapes = [
        {
          type: "line", xref: "x", yref: "y5",
          x0: state.currentConfig.start, x1: state.currentConfig.end,
          y0: buyBelow, y1: buyBelow,
          line: { color: "#2ca02c", dash: "dash", width: 1 },
        },
        {
          type: "line", xref: "x", yref: "y5",
          x0: state.currentConfig.start, x1: state.currentConfig.end,
          y0: exitAbove, y1: exitAbove,
          line: { color: "#d62728", dash: "dash", width: 1 },
        },
      ];
      layout.annotations.push(
        { xref: "x", yref: "y5", x: state.currentConfig.start, y: buyBelow, text: `buy < ${buyBelow}`, showarrow: false, xanchor: "left", yanchor: "bottom", font: { color: "#2ca02c", size: 11 } },
        { xref: "x", yref: "y5", x: state.currentConfig.start, y: exitAbove, text: `exit > ${exitAbove}`, showarrow: false, xanchor: "left", yanchor: "top", font: { color: "#d62728", size: 11 } },
      );
    }

    return { data, layout };
  }

  function buildSubplotLayout(rows, heights, titles, _dates) {
    const yAxes = {};
    const yTitles = ["Value ($)", "Drawdown (%)", "Price ($)", "Deployed ($)"];
    if (rows === 5) yTitles.push("F&G score");
    const verticalSpacing = 0.06;
    const annotations = [];
    let yTop = 1.0;
    const cumHeights = heights;
    const totalSpacing = verticalSpacing * (rows - 1);
    const totalHeight = 1 - totalSpacing;
    let pos = 1.0;
    for (let i = 0; i < rows; i++) {
      const frac = cumHeights[i] / cumHeights.reduce((a, b) => a + b, 0);
      const h = frac * totalHeight;
      const yBottom = pos - h;
      const axisKey = i === 0 ? "yaxis" : `yaxis${i + 1}`;
      yAxes[axisKey] = {
        domain: [yBottom, pos],
        anchor: i === 0 ? "x" : "x",
        title: { text: yTitles[i] || "", standoff: 5 },
        automargin: true,
      };
      if (i === rows - 1) {
        yAxes[axisKey].range = rows === 5 && i === 4 ? [0, 100] : undefined;
      }
      // Subplot title as an annotation above each subplot
      annotations.push({
        text: `<b>${titles[i] || ""}</b>`,
        showarrow: false,
        xref: "paper", yref: "paper",
        x: 0.5, y: pos + 0.005,
        xanchor: "center", yanchor: "bottom",
        font: { size: 12 },
      });
      pos = yBottom - verticalSpacing;
    }
    return {
      ...yAxes,
      xaxis: { anchor: rows === 1 ? "y" : `y${rows}` },
      height: 240 * rows,
      hovermode: "x unified",
      legend: { orientation: "h", y: -0.10 },
      margin: { l: 60, r: 30, t: 60, b: 60 },
      annotations,
    };
  }

  // ----------------------------------------------------------- summary ---

  function renderSummary(result, container) {
    const runs = [result.strategy, ...result.benchmarks];
    const rows = runs.map((run, i) => {
      const m = run.metrics;
      const cls = i === 0 ? " class='strategy-row'" : "";
      return `<tr${cls}><th>${run.name}</th>` +
        `<td>${fmtMoney(m.final_value)}</td>` +
        `<td>${fmtMoney(m.cash_deployed)}</td>` +
        `<td>${fmtPct(m.total_return)}</td>` +
        `<td>${fmtPct(m.cagr)}</td>` +
        `<td>${fmtPct(m.max_drawdown)}</td>` +
        `<td>${m.n_buys}</td>` +
        `<td>${m.n_sells}</td></tr>`;
    }).join("");
    container.innerHTML = (
      "<table class='stats'><thead><tr><th></th>" +
      "<th>Final value</th><th>Cash deployed</th>" +
      "<th>Total return</th><th>CAGR (approx)</th><th>Max drawdown</th>" +
      "<th>Buys</th><th>Sells</th></tr></thead><tbody>" +
      rows +
      "</tbody></table>"
    );
  }

  // ---------------------------------------------------------- trade log ---

  function renderTradeLog(result, container) {
    const trades = result.strategy.trades;
    if (!trades.length) {
      container.innerHTML = "<p class='muted'>No trades executed.</p>";
      return;
    }
    const nBuys = trades.filter((t) => t.side === "buy").length;
    const nSells = trades.filter((t) => t.side === "sell").length;
    let runningShares = 0;
    const rows = trades.map((t, i) => {
      runningShares += t.side === "buy" ? t.shares : -t.shares;
      return `<tr>` +
        `<td class='num'>${i + 1}</td>` +
        `<td>${t.date}</td>` +
        `<td class='side ${t.side}'>${t.side}</td>` +
        `<td class='num'>${t.shares.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}</td>` +
        `<td class='num'>${fmtMoney(t.price)}</td>` +
        `<td class='num'>${fmtMoney(t.notional)}</td>` +
        `<td class='num'>${fmtMoney(t.commission)}</td>` +
        `<td class='num'>${runningShares.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}</td>` +
        `</tr>`;
    }).join("");
    container.innerHTML = (
      `<p class='muted'>${trades.length} trades — ${nBuys} buys, ${nSells} sells</p>` +
      "<div class='trade-log-wrap'><table class='trade-log'>" +
      "<thead><tr>" +
      "<th class='num'>#</th><th>Date</th><th>Side</th>" +
      "<th class='num'>Shares</th><th class='num'>Exec price</th>" +
      "<th class='num'>Notional</th><th class='num'>Commission</th>" +
      "<th class='num'>Shares held</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table></div>"
    );
  }

  // ---------------------------------------------------------------- init ---

  function init(state) {
    state.currentConfig = {
      strategy: state.strategy,
      start: state.defaults.start,
      end: state.defaults.end,
      total_budget: state.defaults.total_budget,
      commission_bps: state.defaults.commission_bps,
      slippage_bps: state.defaults.slippage_bps,
      params: { ...state.defaults.params },
    };
    state.currentParams = state.currentConfig.params;

    const panel = document.getElementById("controls");
    const commonSchema = buildCommonControls(state);
    const commonValues = {
      start: state.currentConfig.start,
      end: state.currentConfig.end,
      total_budget: state.currentConfig.total_budget,
      commission_bps: state.currentConfig.commission_bps,
      slippage_bps: state.currentConfig.slippage_bps,
    };
    renderControlsInto(panel, commonSchema, commonValues, "Window & costs");
    if (state.params_schema && state.params_schema.length) {
      renderControlsInto(panel, state.params_schema, state.currentParams, "Strategy parameters");
    }

    const resetBtn = document.getElementById("reset-btn");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        for (const input of panel.querySelectorAll("[data-control-name]")) {
          const name = input.dataset.controlName;
          const def = commonSchema.find((s) => s.name === name) ||
            (state.params_schema || []).find((s) => s.name === name);
          if (!def) continue;
          if (input.dataset.controlType === "boolean") input.checked = def.default;
          else input.value = def.default;
        }
        recompute(state);
      });
    }

    panel.addEventListener("input", () => recompute(state));
    panel.addEventListener("change", () => recompute(state));

    recompute(state);
  }

  function recompute(state) {
    const panel = document.getElementById("controls");
    const values = snapshotCurrentValues(panel);
    const commonKeys = ["start", "end", "total_budget", "commission_bps", "slippage_bps"];
    const params = {};
    for (const k of Object.keys(values)) {
      if (!commonKeys.includes(k)) params[k] = values[k];
    }
    state.currentConfig = {
      strategy: state.strategy,
      start: values.start,
      end: values.end,
      total_budget: Number(values.total_budget),
      commission_bps: Number(values.commission_bps),
      slippage_bps: Number(values.slippage_bps),
      params,
    };
    state.currentParams = params;

    let result;
    try {
      result = window.Backtest.run(state.currentConfig, state.data);
    } catch (err) {
      document.getElementById("error").textContent = err.message;
      return;
    }
    document.getElementById("error").textContent = "";

    const summaryEl = document.getElementById("summary");
    if (summaryEl) renderSummary(result, summaryEl);
    const tradeLogEl = document.getElementById("trade-log");
    if (tradeLogEl) renderTradeLog(result, tradeLogEl);

    const fig = buildFigure(result, state);
    window.Plotly.react("chart", fig.data, fig.layout, { responsive: true });

    const subtitle = document.getElementById("subtitle");
    if (subtitle) {
      subtitle.textContent = `Window ${values.start} → ${values.end} · Budget ${fmtMoney(Number(values.total_budget))}`;
    }
  }

  window.Report = { init };
})();
