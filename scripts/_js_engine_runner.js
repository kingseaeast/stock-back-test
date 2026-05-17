/* Run docs/engine.js in Node so the Python parity checker can compare results.
 *
 * Reads a JSON document from stdin shaped like:
 *   { "config": { strategy, start, end, total_budget, commission_bps, slippage_bps, params },
 *     "data":   { prices: [...], fear_greed?: [...] } }
 *
 * Writes the JS engine's result (metrics for strategy + each benchmark) as JSON
 * to stdout. Exits non-zero on engine error.
 */
"use strict";

const fs = require("fs");
const path = require("path");

global.window = {};
require(path.resolve(__dirname, "..", "docs", "engine.js"));

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const result = global.window.Backtest.run(input.config, input.data);

function toEntry(run) {
  return { name: run.name, metrics: run.metrics };
}

process.stdout.write(JSON.stringify({
  strategy: toEntry(result.strategy),
  benchmarks: result.benchmarks.map(toEntry),
}));
