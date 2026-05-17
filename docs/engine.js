/* Browser backtest engine.
 *
 * Ports src/engine.py + src/strategies/*.py + src/metrics.py to vanilla JS so
 * reports can recompute interactively without a server. Same algorithm and
 * same date-execution semantics as the Python engine (orders signaled on day
 * D execute at day D+1's adjusted close; orders signaled on the last day are
 * dropped; idle cash earns 0%).
 *
 * Inputs are plain JS objects (no pandas). Dates are ISO strings ("YYYY-MM-DD")
 * which compare lexicographically — sufficient for our day-resolution data.
 *
 * Exposed as window.Backtest = { strategies, run, simulate, metrics }.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- utils ---

  function isoToDate(s) { return new Date(s + "T00:00:00Z"); }
  function dateToIso(d) { return d.toISOString().slice(0, 10); }

  function sliceByWindow(series, start, end) {
    // series: array of {date: "YYYY-MM-DD", ...} sorted ascending
    return series.filter((row) => row.date >= start && row.date <= end);
  }

  function alignByDate(target, source, column) {
    // Forward-fill `source[column]` onto `target.date`. Both sorted ascending.
    const out = new Array(target.length).fill(null);
    let j = 0;
    let last = null;
    for (let i = 0; i < target.length; i++) {
      while (j < source.length && source[j].date <= target[i].date) {
        last = source[j][column];
        j++;
      }
      out[i] = last;
    }
    return out;
  }

  // ---------------------------------------------------------- DCA cadence ---

  function cadenceContributionDates(tradingDates, cadence) {
    // Mirror Python: take pandas-style period starts and snap each to the next trading day.
    if (cadence === "monthly") return monthlyStarts(tradingDates);
    if (cadence === "biweekly") return periodicStarts(tradingDates, 14);
    if (cadence === "weekly") return periodicStarts(tradingDates, 7);
    throw new Error("Unknown cadence: " + cadence);
  }

  function monthlyStarts(tradingDates) {
    // Mirror Python's `pd.date_range(start=first_trading_day, freq="MS")` + snap-right:
    // generate the 1st of each month starting from the first trading day's month
    // (or the NEXT month if that day isn't already the 1st), and snap each to the
    // next trading day. So a window beginning 2015-01-02 first contributes on
    // 2015-02-02 (the first trading day on or after 2015-02-01), not 2015-01-02.
    if (!tradingDates.length) return [];
    const first = isoToDate(tradingDates[0]);
    const last = isoToDate(tradingDates[tradingDates.length - 1]);
    let cursor = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1));
    if (cursor < first) {
      cursor = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1));
    }
    const seen = new Set();
    const out = [];
    while (cursor <= last) {
      const iso = dateToIso(cursor);
      const idx = lowerBound(tradingDates, iso);
      if (idx < tradingDates.length) {
        const snapped = tradingDates[idx];
        if (!seen.has(snapped)) {
          seen.add(snapped);
          out.push(snapped);
        }
      }
      cursor = new Date(Date.UTC(cursor.getUTCFullYear(), cursor.getUTCMonth() + 1, 1));
    }
    return out;
  }

  function periodicStarts(tradingDates, days) {
    // Approximates pd.date_range(freq="W-MON") / 2W-MON by stepping `days` days
    // from the first date and snapping each to the next trading day.
    if (tradingDates.length === 0) return [];
    const first = isoToDate(tradingDates[0]);
    const last = isoToDate(tradingDates[tradingDates.length - 1]);
    const out = [];
    const seen = new Set();
    let cursor = new Date(first);
    while (cursor <= last) {
      const iso = dateToIso(cursor);
      const idx = lowerBound(tradingDates, iso);
      if (idx < tradingDates.length) {
        const snapped = tradingDates[idx];
        if (!seen.has(snapped)) {
          seen.add(snapped);
          out.push(snapped);
        }
      }
      cursor.setUTCDate(cursor.getUTCDate() + days);
    }
    return out;
  }

  function lowerBound(sortedArr, target) {
    let lo = 0;
    let hi = sortedArr.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (sortedArr[mid] < target) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  // ----------------------------------------------------------- Wilder RSI ---

  function wilderRsi(closes, period) {
    // Matches Python: gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean().
    // pandas EWM with adjust=False seeds s[0] = x[0] (the FIRST observation, no SMA pre-warmup)
    // and recurses s[t] = alpha*x[t] + (1-alpha)*s[t-1]. With min_periods=period the first
    // `period - 1` outputs are masked NaN; the first valid value is at the `period`-th
    // observation (closes index `period`, since the diff drops the very first row).
    if (period < 2) throw new Error("RSI period must be >= 2");
    const n = closes.length;
    const rsi = new Array(n).fill(NaN);
    if (n < 2) return rsi;

    const alpha = 1 / period;
    let avgGain = 0;
    let avgLoss = 0;
    let observations = 0;
    for (let i = 1; i < n; i++) {
      const delta = closes[i] - closes[i - 1];
      const gain = delta > 0 ? delta : 0;
      const loss = delta < 0 ? -delta : 0;
      observations += 1;
      if (observations === 1) {
        avgGain = gain;
        avgLoss = loss;
      } else {
        avgGain = alpha * gain + (1 - alpha) * avgGain;
        avgLoss = alpha * loss + (1 - alpha) * avgLoss;
      }
      if (observations < period) continue;
      if (avgLoss === 0 && avgGain === 0) rsi[i] = 50;
      else if (avgLoss === 0) rsi[i] = 100;
      else rsi[i] = 100 - 100 / (1 + avgGain / avgLoss);
    }
    return rsi;
  }

  // ------------------------------------------------------- order actions ---

  const Action = Object.freeze({
    DEPOSIT_AND_BUY: "deposit_and_buy",
    BUY_ALL_CASH: "buy_all_cash",
    SELL_ALL: "sell_all",
    SELL_FRACTION: "sell_fraction",
    DEPLOY_RESERVE: "deploy_reserve",
  });

  function order(date, action, amount) {
    return { date, action, amount: amount || 0 };
  }

  // ----------------------------------------------------------- strategies ---

  const strategies = {};

  strategies.buy_hold = {
    name: "buy_hold",
    dataRequirements: ["prices"],
    orders(ctx, totalBudget, _params) {
      const prices = ctx.prices;
      if (!prices.length) return [];
      return [order(prices[0].date, Action.DEPOSIT_AND_BUY, totalBudget)];
    },
  };

  strategies.dca = {
    name: "dca",
    dataRequirements: ["prices"],
    orders(ctx, totalBudget, params) {
      const prices = ctx.prices;
      if (!prices.length) return [];
      const cadence = (params && params.cadence) || "monthly";
      const tradingDates = prices.map((p) => p.date);
      const dates = cadenceContributionDates(tradingDates, cadence);
      if (!dates.length) return [];
      const per = totalBudget / dates.length;
      return dates.map((d) => order(d, Action.DEPOSIT_AND_BUY, per));
    },
  };

  strategies.dca_btd = {
    name: "dca_btd",
    dataRequirements: ["prices"],
    orders(ctx, totalBudget, params) {
      const prices = ctx.prices;
      if (!prices.length) return [];
      const p = params || {};
      const cadence = p.cadence || "monthly";
      const dipReserve = p.dip_reserve_pct ?? 0.20;
      const dipThreshold = p.dip_threshold_pct ?? 0.10;
      const dipLookback = p.dip_lookback ?? 90;
      const dipBuys = p.dip_buys ?? 4;
      if (!(dipReserve >= 0 && dipReserve < 1)) throw new Error("dip_reserve_pct must be in [0,1)");
      if (dipThreshold <= 0) throw new Error("dip_threshold_pct must be > 0");
      if (dipBuys < 1) throw new Error("dip_buys must be >= 1");

      const dcaTotal = totalBudget * (1 - dipReserve);
      const reserveTotal = totalBudget * dipReserve;
      const perDip = dipBuys > 0 ? reserveTotal / dipBuys : 0;

      const tradingDates = prices.map((row) => row.date);
      const contribDates = cadenceContributionDates(tradingDates, cadence);
      const perContribution = contribDates.length ? dcaTotal / contribDates.length : 0;
      const orders = contribDates.map((d) => order(d, Action.DEPOSIT_AND_BUY, perContribution));

      // Trailing-max excluding today, of the prior `dip_lookback` closes.
      const closes = prices.map((row) => row.adj_close);
      let reserveRemaining = reserveTotal;
      let inDip = false;
      for (let i = 1; i < prices.length && reserveRemaining > 0; i++) {
        const start = Math.max(0, i - dipLookback);
        let trailingMax = -Infinity;
        for (let j = start; j < i; j++) {
          if (closes[j] > trailingMax) trailingMax = closes[j];
        }
        const thresholdPrice = trailingMax * (1 - dipThreshold);
        const below = closes[i] <= thresholdPrice;
        if (below && !inDip) {
          const amount = Math.min(perDip, reserveRemaining);
          orders.push(order(prices[i].date, Action.DEPOSIT_AND_BUY, amount));
          reserveRemaining -= amount;
          inDip = true;
        } else if (!below) {
          inDip = false;
        }
      }
      orders.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
      return orders;
    },
  };

  strategies.rsi = {
    name: "rsi",
    dataRequirements: ["prices"],
    orders(ctx, totalBudget, params) {
      const prices = ctx.prices;
      if (!prices.length) return [];
      const p = params || {};
      const period = p.period ?? 14;
      const oversold = p.oversold ?? 30;
      const overbought = p.overbought ?? 70;
      const startInCash = !!p.start_in_cash;
      if (!(oversold > 0 && oversold < overbought && overbought < 100)) {
        throw new Error("Need 0 < oversold < overbought < 100");
      }
      const closes = prices.map((row) => row.adj_close);
      const rsi = wilderRsi(closes, period);
      const orders = [order(prices[0].date, Action.DEPOSIT_AND_BUY, totalBudget)];
      if (startInCash) orders.push(order(prices[0].date, Action.SELL_ALL));
      let inPosition = !startInCash;
      for (let i = 1; i < prices.length; i++) {
        const r = rsi[i];
        if (!Number.isFinite(r)) continue;
        if (inPosition && r > overbought) {
          orders.push(order(prices[i].date, Action.SELL_ALL));
          inPosition = false;
        } else if (!inPosition && r < oversold) {
          orders.push(order(prices[i].date, Action.BUY_ALL_CASH));
          inPosition = true;
        }
      }
      return orders;
    },
  };

  strategies.dca_fg = {
    name: "dca_fg",
    dataRequirements: ["prices", "fear_greed"],
    orders(ctx, totalBudget, params) {
      const prices = ctx.prices;
      const fg = ctx.fear_greed;
      if (!prices.length) return [];
      const p = params || {};
      const cadence = p.cadence || "monthly";
      const reserve = p.fear_reserve_pct ?? 0.20;
      const fearThreshold = p.fear_threshold ?? 25;
      const fearBuys = p.fear_buys ?? 4;
      const indexCol = p.index_type || "fear_greed";
      if (!(reserve >= 0 && reserve < 1)) throw new Error("fear_reserve_pct must be in [0,1)");
      if (!(fearThreshold > 0 && fearThreshold < 100)) throw new Error("fear_threshold must be in (0,100)");
      if (fearBuys < 1) throw new Error("fear_buys must be >= 1");

      const dcaTotal = totalBudget * (1 - reserve);
      const reserveTotal = totalBudget * reserve;
      const perFearBuy = fearBuys > 0 ? reserveTotal / fearBuys : 0;

      const tradingDates = prices.map((row) => row.date);
      const contribDates = cadenceContributionDates(tradingDates, cadence);
      const perContribution = contribDates.length ? dcaTotal / contribDates.length : 0;
      const orders = contribDates.map((d) => order(d, Action.DEPOSIT_AND_BUY, perContribution));

      const signal = alignByDate(prices, fg, indexCol);
      let reserveRemaining = reserveTotal;
      let inFear = false;
      for (let i = 1; i < prices.length && reserveRemaining > 0; i++) {
        const v = signal[i];
        if (v == null || !Number.isFinite(v)) continue;
        const below = v < fearThreshold;
        if (below && !inFear) {
          const amount = Math.min(perFearBuy, reserveRemaining);
          orders.push(order(prices[i].date, Action.DEPOSIT_AND_BUY, amount));
          reserveRemaining -= amount;
          inFear = true;
        } else if (!below) {
          inFear = false;
        }
      }
      orders.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
      return orders;
    },
  };

  strategies.dca_fg_rebalance = {
    name: "dca_fg_rebalance",
    dataRequirements: ["prices", "fear_greed"],
    orders(ctx, totalBudget, params) {
      const prices = ctx.prices;
      const fg = ctx.fear_greed;
      if (!prices.length) return [];
      const p = params || {};
      const cadence = p.cadence || "monthly";
      const greedThreshold = p.greed_threshold ?? 75;
      const fearThreshold = p.fear_threshold ?? 25;
      const sellPct = p.sell_pct ?? 0.25;
      const indexCol = p.index_type || "fear_greed";
      if (!(fearThreshold > 0 && fearThreshold < greedThreshold && greedThreshold < 100)) {
        throw new Error("Need 0 < fear_threshold < greed_threshold < 100");
      }
      if (!(sellPct > 0 && sellPct < 1)) throw new Error("sell_pct must be in (0,1)");

      const tradingDates = prices.map((row) => row.date);
      const contribDates = cadenceContributionDates(tradingDates, cadence);
      const perContribution = contribDates.length ? totalBudget / contribDates.length : 0;
      const orders = contribDates.map((d) => order(d, Action.DEPOSIT_AND_BUY, perContribution));

      const signal = alignByDate(prices, fg, indexCol);
      let inGreed = false;
      let inFear = false;
      for (let i = 1; i < prices.length; i++) {
        const v = signal[i];
        if (v == null || !Number.isFinite(v)) continue;
        if (v > greedThreshold) {
          if (!inGreed) {
            orders.push(order(prices[i].date, Action.SELL_FRACTION, sellPct));
            inGreed = true;
          }
          inFear = false;
        } else if (v < fearThreshold) {
          if (!inFear) {
            orders.push(order(prices[i].date, Action.DEPLOY_RESERVE));
            inFear = true;
          }
          inGreed = false;
        } else {
          inGreed = false;
          inFear = false;
        }
      }
      orders.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
      return orders;
    },
  };

  strategies.fear_greed = {
    name: "fear_greed",
    dataRequirements: ["prices", "fear_greed"],
    orders(ctx, totalBudget, params) {
      const prices = ctx.prices;
      const fg = ctx.fear_greed;
      if (!prices.length) return [];
      const p = params || {};
      const buyBelow = p.buy_below ?? 25;
      const exitAbove = p.exit_above ?? 75;
      const indexCol = p.index_type || "fear_greed";
      const startInMarket = !!p.start_in_market;
      if (!(buyBelow > 0 && buyBelow < exitAbove && exitAbove < 100)) {
        throw new Error("Need 0 < buy_below < exit_above < 100");
      }
      const fgAligned = alignByDate(prices, fg, indexCol);
      const orders = [order(prices[0].date, Action.DEPOSIT_AND_BUY, totalBudget)];
      if (!startInMarket) orders.push(order(prices[0].date, Action.SELL_ALL));
      let inPosition = startInMarket;
      for (let i = 1; i < prices.length; i++) {
        const v = fgAligned[i];
        if (v == null || !Number.isFinite(v)) continue;
        if (!inPosition && v < buyBelow) {
          orders.push(order(prices[i].date, Action.BUY_ALL_CASH));
          inPosition = true;
        } else if (inPosition && v > exitAbove) {
          orders.push(order(prices[i].date, Action.SELL_ALL));
          inPosition = false;
        }
      }
      return orders;
    },
  };

  // ------------------------------------------------------------ simulator ---

  function simulate(prices, orders, commissionBps, slippageBps) {
    const slip = (slippageBps || 0) / 10000;
    const comm = (commissionBps || 0) / 10000;

    // Group orders by execution day = next trading day after their signal date.
    const dateToIdx = new Map();
    for (let i = 0; i < prices.length; i++) dateToIdx.set(prices[i].date, i);
    const byExec = new Map();
    for (const o of orders) {
      let signalIdx = dateToIdx.get(o.date);
      if (signalIdx == null) {
        // Snap to first trading day >= signal
        const idx = lowerBound(prices.map((p) => p.date), o.date);
        if (idx >= prices.length) continue;
        signalIdx = idx - 1;
      }
      const execIdx = signalIdx + 1;
      if (execIdx >= prices.length) continue;
      const execDate = prices[execIdx].date;
      if (!byExec.has(execDate)) byExec.set(execDate, []);
      byExec.get(execDate).push(o);
    }

    let cash = 0;
    let reserveCash = 0;  // earmarked from SELL_FRACTION; only DEPLOY_RESERVE spends it
    let shares = 0;
    let deployedTotal = 0;
    const equity = new Array(prices.length);
    const deployed = new Array(prices.length);
    const trades = [];

    function buyFromPocket(date, price, available) {
      // Spend `available` cash on shares; returns the amount actually consumed.
      if (available <= 0) return 0;
      const execPrice = price * (1 + slip);
      const spendOnShares = available / (1 + comm);
      const bought = spendOnShares / execPrice;
      const notional = bought * execPrice;
      const commission = notional * comm;
      shares += bought;
      trades.push({ date, side: "buy", shares: bought, price: execPrice, notional, commission });
      return notional + commission;
    }

    function sellAll(date, price) {
      if (shares <= 0) return;
      const execPrice = price * (1 - slip);
      const notional = shares * execPrice;
      const commission = notional * comm;
      cash += notional - commission;
      trades.push({ date, side: "sell", shares, price: execPrice, notional, commission });
      shares = 0;
    }

    function sellFractionToReserve(date, price, fraction) {
      if (shares <= 0 || fraction <= 0) return;
      const clip = Math.max(0, Math.min(1, fraction));
      const qty = shares * clip;
      const execPrice = price * (1 - slip);
      const notional = qty * execPrice;
      const commission = notional * comm;
      reserveCash += notional - commission;
      trades.push({ date, side: "sell", shares: qty, price: execPrice, notional, commission });
      shares -= qty;
    }

    for (let i = 0; i < prices.length; i++) {
      const row = prices[i];
      const price = row.adj_close;
      const todays = byExec.get(row.date) || [];
      for (const o of todays) {
        if (o.action === Action.DEPOSIT_AND_BUY) {
          cash += o.amount;
          deployedTotal += o.amount;
          cash -= buyFromPocket(row.date, price, cash);
        } else if (o.action === Action.BUY_ALL_CASH) {
          cash -= buyFromPocket(row.date, price, cash);
        } else if (o.action === Action.SELL_ALL) {
          sellAll(row.date, price);
        } else if (o.action === Action.SELL_FRACTION) {
          sellFractionToReserve(row.date, price, o.amount);
        } else if (o.action === Action.DEPLOY_RESERVE) {
          reserveCash -= buyFromPocket(row.date, price, reserveCash);
        }
      }
      equity[i] = cash + reserveCash + shares * price;
      deployed[i] = deployedTotal;
    }

    return { equity, deployed, trades };
  }

  // -------------------------------------------------------------- metrics ---

  function totalReturn(equity, deployed) {
    const d = deployed[deployed.length - 1];
    if (d <= 0) return 0;
    return equity[equity.length - 1] / d - 1;
  }

  function cagr(equity, deployed, dates) {
    const d = deployed[deployed.length - 1];
    if (d <= 0 || equity.length < 2) return 0;
    const first = isoToDate(dates[0]);
    const last = isoToDate(dates[dates.length - 1]);
    const years = (last - first) / (1000 * 60 * 60 * 24) / 365.25;
    if (years <= 0) return 0;
    const final = equity[equity.length - 1];
    if (final <= 0) return -1;
    return Math.pow(final / d, 1 / years) - 1;
  }

  function maxDrawdown(equity) {
    if (!equity.length) return 0;
    let peak = -Infinity;
    let worst = 0;
    for (const v of equity) {
      if (v > peak) peak = v;
      if (peak > 0) {
        const dd = (v - peak) / peak;
        if (dd < worst) worst = dd;
      }
    }
    return worst;
  }

  function drawdownSeries(equity) {
    const out = new Array(equity.length).fill(0);
    let peak = -Infinity;
    for (let i = 0; i < equity.length; i++) {
      if (equity[i] > peak) peak = equity[i];
      out[i] = peak > 0 ? (equity[i] - peak) / peak : 0;
    }
    return out;
  }

  function summarize(equity, deployed, dates, nBuys, nSells) {
    return {
      final_value: equity[equity.length - 1],
      cash_deployed: deployed[deployed.length - 1],
      total_return: totalReturn(equity, deployed),
      cagr: cagr(equity, deployed, dates),
      max_drawdown: maxDrawdown(equity),
      n_buys: nBuys,
      n_sells: nSells,
    };
  }

  // -------------------------------------------------------------- runner ---

  function runOne(name, strategy, context, config) {
    const orders = strategy.orders(context, config.total_budget, config.params || {});
    const sim = simulate(
      context.prices, orders, config.commission_bps || 0, config.slippage_bps || 0,
    );
    const dates = context.prices.map((p) => p.date);
    const nBuys = sim.trades.filter((t) => t.side === "buy").length;
    const nSells = sim.trades.filter((t) => t.side === "sell").length;
    return {
      name,
      equity: sim.equity,
      cash_deployed: sim.deployed,
      drawdown: drawdownSeries(sim.equity),
      dates,
      trades: sim.trades,
      metrics: summarize(sim.equity, sim.deployed, dates, nBuys, nSells),
    };
  }

  function run(config, data) {
    // config: { strategy, start, end, total_budget, commission_bps, slippage_bps, params }
    // data:   { prices: [{date, adj_close}], fear_greed: [{date, fear_greed}] (optional) }
    const strat = strategies[config.strategy];
    if (!strat) throw new Error("Unknown strategy: " + config.strategy);

    const slicedPrices = sliceByWindow(data.prices, config.start, config.end);
    if (!slicedPrices.length) throw new Error("No price rows in window");

    const ctx = { prices: slicedPrices };
    if (strat.dataRequirements.includes("fear_greed")) {
      if (!data.fear_greed) throw new Error("Strategy needs fear_greed data");
      ctx.fear_greed = sliceByWindow(data.fear_greed, config.start, config.end);
    }

    const strategyRun = runOne(config.strategy, strat, ctx, config);

    const benchmarks = [];
    const priceCtx = { prices: slicedPrices };
    if (config.strategy !== "buy_hold") {
      benchmarks.push(runOne("buy_hold", strategies.buy_hold, priceCtx, {
        ...config, strategy: "buy_hold", params: {},
      }));
    }
    if (config.strategy !== "dca") {
      benchmarks.push(runOne("dca_monthly", strategies.dca, priceCtx, {
        ...config, strategy: "dca", params: { cadence: "monthly" },
      }));
    }

    return { strategy: strategyRun, benchmarks };
  }

  window.Backtest = {
    Action, strategies, simulate, run,
    metrics: { totalReturn, cagr, maxDrawdown, drawdownSeries, summarize },
    _internals: { wilderRsi, cadenceContributionDates, alignByDate, lowerBound },
  };
})();
