# Scripts

Dev/maintenance scripts. Not part of the package.

## `check_engine_parity.py`

Compares the Python backtest engine (`src/engine.py`) against the browser-JS engine (`docs/engine.js`) for every committed report under `docs/runs/`.

Why: the interactive reports re-run the backtest in the browser, so we maintain two engines. If they drift, users see different numbers than the agent produced. This script catches drift early.

```sh
uv run python scripts/check_engine_parity.py
# 8/8 reports passed parity.
# exit 0
```

Exit code is `1` on any divergence above tolerance, `0` otherwise — wire it into CI or a pre-push hook when ready.

**Tolerances** (see top of script):
- monetary fields: $1 absolute
- ratio fields (returns, CAGR, max DD): 1e-4 (0.01%)
- trade counts: exact match required

The tight `1e-6` tolerance is too strict — float64 summation order between pandas and raw JS arithmetic produces sub-cent noise on long windows that isn't worth chasing. A real algorithmic bug shifts numbers by orders of magnitude more than that (verified via mutation test: halving the JS commission shifts a $34K result by $8+, well above the $1 floor).

**Requires Node** on `PATH` for the JS half. `brew install node` on macOS.

## `_js_engine_runner.js`

Tiny stdin/stdout wrapper that loads `docs/engine.js` in Node (using a `global.window = {}` shim) so the Python parity checker can shell out to it. Not meant to be called directly.
