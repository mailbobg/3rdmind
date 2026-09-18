# Local Research Studio

The Studio route is a three-column research workspace: a left rail with the work sections, a middle column for
actions, and a right column for results.

- AI Research: start a native RD-Agent run (factor, model, joint, factor-from-report with PDF uploads, or
  model-from-paper with a PDF or link). The work column lists every experiment the server knows (scenario, rounds,
  accepted rounds, status, last update, from `/studio/experiments`), live runs first; expanding one shows its rounds
  under it, and the right column shows the selected round's hypothesis, Qlib evaluation, return chart, feedback and
  generated code. The form's 股票池 picks the instrument universe (any `instruments/*.txt` in the Qlib data;
  `/universes` lists them): the run's Qlib configs, prompt and factor input data follow it, and a universe other
  than CSI300 has its daily OHLCV exported once by `studio_universe.py` before the first run. A finished factor,
  model or joint experiment can be continued for N more rounds ("继续研究"):
  the server restores the loop from the trace's `__session__` snapshots (`/resume`), so the agent keeps its
  history and appends the new rounds to the same experiment. The Data Science scenario stays in the native
  Playground because it needs an MLE-bench competition and dataset.
- Factor Library: every factor with a `result.h5` produced by a research round, grouped by experiment, with the
  agent's description, formulation and verdict, a single-factor analysis (daily IC / Rank IC against next-day return,
  ICIR, positive-day ratio, monthly bars, coverage; computed by `studio_analysis.py` on demand and cached next to
  `result.h5`), and a basket bar showing the pairwise cross-sectional correlation of the selected factors. There is
  no manual factor entry. Research factors are computed on the experiment's own input window (2022-10 to 2025-12);
  "重算到最新" re-runs a factor's `factor.py` on CSI300 data pulled from Qlib up to its last day
  (`studio_refresh.py`, results under `traces/studio_refresh/`), and backtests and analyses then read that copy.
- Portfolio Backtest: the basket (research factors and, for rounds that trained a Qlib model, its `pred.pkl`
  prediction), the signal-synthesis choice, strategy parameters, the read-only worker source and the run button; the
  right column shows the backtest history, metrics, signal IC, equity/drawdown curve, a portfolio diagnosis for
  multi-signal runs (each signal's IC on the window, its agreement with the final score, pairwise correlation, and
  on demand a take-apart pass that backtests every signal alone and the portfolio without each one), the LightGBM
  training report, holdings, per-instrument P&L, the trade timeline and the log. A "组合搜索" tab runs a greedy
  portfolio search over the basket's factors (`/studio/searches`, worker `--search`): every candidate alone,
  forward selection, backward elimination, judged on the first two thirds of the window and reported on the
  held-out last third next to the everything-in portfolio, with the search path and validation curves.
- Strategies: a verified portfolio saved by name ("保存为策略" beside a completed backtest or a search
  recommendation) with its members, weights, parameters and the evidence run; "更新到最新" recomputes the
  members on the latest data and backtests from the evidence start to the last market day, appending a
  tracking run, so a strategy's excess return can be watched as time passes. "最新信号" exports the newest run's
  closing book (the position going into the next trading day) and the last signal day's ranking as CSV/JSON
  (`/studio/strategies/<id>/signal?format=csv`) for an execution system. "围着这个策略继续研究" starts a
  factor-research run with the members' `factor.py` as RD-Agent base features (`/research/from-strategy`), so
  the agent looks for incremental signals instead of starting from scratch. Stored as JSON under
  `traces/studio_strategies/`, served by `/studio/strategies`.
- Runs: research experiments and backtests in one list.

Stock names beside codes come from `git_ignore_folder/traces/studio_data/instrument_names.json`, a
`{"source": "...", "names": {"SH600000": {"name": "浦发银行", "industry": "银行"}}}` file the user builds from their
own listing source (the current one was converted from a Tushare `stock_basic` snapshot); without it only codes show.

## Run

Use a Python environment with RD-Agent and Qlib's runtime dependencies installed.
RD-Agent research may additionally require its configured LLM provider and execution environment.
The worker imports a `qlib/` source checkout placed next to this repository when one exists; otherwise the installed qlib package.

```sh
UI_LOAD_LEGACY_PICKLE_TRACES=true sh scripts/start-studio.sh
```

The rail's "同步数据" block keeps the Qlib snapshot current: it shows the local release against the latest
chenditc/investment_data release, syncs on demand (download, sha256 check, unpack, swap the data directory; refused
while a worker or experiment runs) and, when switched on, once a day at a chosen hour (`/studio/data/sync`,
settings in `traces/studio_data/sync.json`). After a sync, factor refreshes and universe exports rebuild themselves.

The rail's "模型设置" block picks the LLM for research runs: provider (DeepSeek, OpenAI, Anthropic, Gemini,
DashScope, Moonshot or any OpenAI-compatible endpoint), model, API key, optional base URL and retry count, with a
one-message connection test (`/studio/llm`, `/studio/llm/test`). Saved settings go to
`traces/studio_data/llm.json` (mode 600, one key per provider, never echoed back beyond its last four
characters) and are injected into the environment of every research process started afterwards, so switching
provider needs no restart; until something is saved, runs use whatever the .env file gave the server.

`UI_LOAD_LEGACY_PICKLE_TRACES=true` loads finished experiments from the trace folder so they can be replayed;
without it only experiments started by this server process are visible.

The Studio is a React 19 + HeroUI v3 (Tailwind CSS v4) app in `studio/`. Its production build is served by
the log server at http://127.0.0.1:19899/app/ (`npm run build` writes `git_ignore_folder/static/app/`). For
development:

```sh
cd studio
npm install
npm run dev
```

and open http://127.0.0.1:8081/app/. The Vite proxy forwards the Studio and native RD-Agent APIs to port 19899.
The Vue app in `web/` now holds only the native Playground; its old `/Studio` routes redirect to `/app/`.
The rail's "原生 Playground" link opens it at the server root, which needs that app built into the same static
folder (`cd web && npm run build:flask` writes `git_ignore_folder/static/`); in development the link goes to the log
server directly, since the React dev server has nothing at its root.
For an authenticated backend, establish the backend's normal authentication session through the same origin.
Do not place provider credentials in the frontend.

## Following a run

Each round's four steps (hypothesis, coding, Qlib evaluation, verdict) are read off the trace timestamps: step
strips with durations on the round rows, a live line on the running experiment's row, and a status card above
the round detail with the current step, iteration count, elapsed time, an estimate from earlier rounds, a
quiet-too-long warning and a cleaned tail of the process log (`/studio/trace-tail`).

Confirmations are served by the server, not the page. Every run carries a policy (`confirm_mode`: `all`,
`hypothesis` (default) or `auto`; `confirm_timeout` minutes, 0 = wait forever); a watcher thread answers requests
the policy does not need a human for, and any request left unanswered past the timeout, with the agent's own
proposal, leaving a `user_interaction.auto` event that says so. Requests that do need a human appear in
`/studio/attention`, which drives the badge on the AI 研究 menu item, the banner above every page, the `●` in
the tab title and, when switched on in the banner, desktop notifications and a chime. The confirmation card is
a form for the decision at hand (accept or rewrite a hypothesis, accept or flip a verdict, prune the feature
list, write the instruction) with the raw JSON under 高级. Round and run completions (`/studio/recent`) become
toasts; a finished run shows a summary card with backtest and continue actions.

## Background jobs

Every long task is a job in one registry (`studio_jobs.py`, `/studio/jobs`): backtests, portfolio searches and
take-apart diagnoses (tracked from their result files), 重算到最新, 更新到最新 and the first export of a
universe's factor data (run on server threads; the last two used to block their HTTP request for up to half an
hour), plus live research runs, the data sync and the US data build. A job carries kind, label, status,
progress, market and a link to the page it belongs to. The rail's 运行记录 item shows how many are running, the
runs page lists them all with progress (live first), completions become toasts (and desktop notifications when
switched on), and failures sit in the banner until dismissed. Starting research on a universe whose data is not
exported yet answers 409 with the export job; the client waits for it and retries.

## Other markets (US example)

Markets are workspaces: the toggle at the top of the rail (A 股 | 美股) switches the whole Studio, like a
mode switch. Each workspace has its own experiments, factor library, basket, backtests, searches, strategies and
runs (every list endpoint takes `?region=`; records carry their market and unmarked ones count as A-shares),
its own data status line (A-shares: 同步数据; US: 重建数据, which runs `scripts/build-us-data.py` in the
background via `/studio/data/build`) and its own instrument names. Model settings and layout are shared. The
US workspace lives under `/#/us/...`; a workspace without data shows a single "not built yet" card instead
of its pages. `/studio/regions` lists the workspaces with their data span.


Universes come from `studio_markets.py`: the default Qlib directory (`QLIB_PROVIDER_URI`, the A-share
snapshot) contributes every `instruments/*.txt` it holds, and any sibling directory that carries a
`studio-universe.json` contributes its own markets with their region and benchmark:

```json
{"region": "us", "label": "美股", "benchmark": "^ndx", "markets": {"nasdaq100": "纳斯达克 100"}}
```

Research runs on such a universe get `QLIB_*_REGION`, `QLIB_*_PROVIDER_URI` and `QLIB_*_LIMIT_THRESHOLD`
beside market and benchmark (the Qlib yaml templates render all five), and their factor input data is
exported from that directory. Backtests, analyses and "重算到最新" read the same registry, so a US backtest
runs with `region=us`, no price limit, a 1-dollar minimum commission and 0.01% brokerage each way (A-shares keep
0.05% / 0.15%); the commission defaults live in the registry and reach both RD-Agent's templates and the Studio's
backtest form. The report-factor prompts name the market too, and RD-Agent's result cache is keyed by market. Each run records its universe in
`studio-run.json` beside its trace; the factor library and experiment list show it, and the backtest form
follows the basket's universe. RD-Agent's factor-evaluation LightGBM carries L1/L2 leaf penalties tuned for
CSI300 (205.7 / 581); on a universe with fewer than 300 names they are scaled by size (`QLIB_*_LGB_LAMBDA_L1/L2`),
because at the original size the model never splits on 100 stocks and predicts a constant.

The NASDAQ-100 data in `~/.qlib/qlib_data/us_ndx` was built once from Yahoo Finance with qlib's collector:
monthly membership snapshots from indexes.nasdaqomx.com (2008 onward) give `instruments/nasdaq100.txt`;
`yahooquery` downloads every ever-member plus `^NDX`; `scripts/data_collector/yahoo/collector.py
normalize_data --region US` and `scripts/dump_bin.py dump_all` produce the binary files. Tickers that were
delisted or acquired are no longer on Yahoo (74 of 274 names), so the history carries survivorship bias
before roughly 2020; the current 101 members are complete. There is no automatic update for this data yet.

## Model research on macOS

The model, factor × model and paper scenarios need PyTorch and an embedding model (the knowledge graph embeds
every node; DeepSeek has no embeddings endpoint, so the LLM panel's embedding section points at another
provider or a local Ollama). Two things bite on macOS: Qlib's PyTorch models fork DataLoader workers
(`n_jobs: 20` in the templates), which crash there, so the server sets `QLIB_*_N_JOBS=0` for runs it starts;
and the pip wheels of PyTorch and LightGBM each ship an OpenMP runtime, and `qrun` loads both, which
segfaults at the first training batch. Replace `torch/lib/libomp.dylib` in the virtualenv with a symlink to
Homebrew's `libomp` so one runtime serves both (see the README); reinstalling PyTorch undoes it.

## Qlib environment

The default daily data directory is `~/.qlib/qlib_data/cn_data`. `QLIB_PROVIDER_URI` must be set before starting the
backend if you want a different directory; the run form has no field for it. A valid Qlib binary dataset needs
calendars, instrument membership, and feature files. Choose dates within its coverage. Missing data is reported as
an error, never replaced with demo results.

Set `STUDIO_PYTHON` to an absolute Python executable if the Qlib runtime uses a different environment from RD-Agent.

## Portfolio semantics

The backtest reads each selected factor workspace's `result.h5`. For each date, the values are cross-sectionally
percentile-ranked, and the score is the weighted sum divided by the sum of absolute weights (equal weight by
default). All selected factors must be present. Negative weights invert a factor.
The code reader exposes the actual `studio_worker.py` implementation plus per-round Agent-generated files.
`TopkDropoutStrategy` uses the previous trading day's scores and trades at the current day's close, with explicit
buy/sell costs, a minimum commission of 5 and the Qlib CN limit threshold of 0.095.

Reported total return and drawdown use compounded net-of-cost returns. Annualization uses 252 trading days.
Sharpe uses net daily return and a zero risk-free rate. Native RD-Agent metrics retain their original metric names
and are displayed separately, so annualized excess return cannot be confused with total return.

Each run saves `config.json`, `result.json` and `stdout.log` under the configured trace directory's
`studio_backtests/<uuid>/` folder. Browser refresh preserves the selected experiment, round and backtest parameters. Navigation does not stop
research or backtest workers. Qlib jobs currently finish independently; there is no UI cancellation control for them.

## Signal synthesis

`rank` (default) cross-sectionally percentile-ranks every signal, weights them and divides by the sum of absolute
weights. `lgbm` trains LightGBM on the ranked signals with the label `Ref($close, -2)/Ref($close, -1) - 1`
z-scored per day (Qlib's CSZScoreNorm), early-stopping on the validation window, and uses its prediction as the
score. Training, validation and backtest windows must follow each other without overlap; a signal with no data
inside a window is reported by name. Every result carries the mean daily IC and Rank IC of the final score against
that label over the backtest window.

## Native research

The UI calls RD-Agent's existing factor, model and joint-research scenarios. Hypotheses, code files, configs,
feedback and charts come from native trace events. User instructions and feature selection are submitted through
native initialization interactions. The JSON confirmation editor preserves payload types, including booleans and
feature dictionaries. It also handles hypothesis/feedback approval without leaving Studio.

Studio retrieves trace snapshots using `snapshot=true`. The backend returns the full event list without changing
the legacy IP-scoped cursor, allowing Studio and Playground to observe the same experiment independently.

## Verification scope

Vue SFC compilation and Python syntax/parameter tests can run without market data. They do not establish that the
LLM research environment or Qlib market-data backtest is installed and functioning. Verify a short backtest with
real data before relying on numerical results.

Verified 2026-09-14 against `Finance Data Building/undirected-joist-resume` (STR_5, RVOL_20, VOLSURGE_5_20, equal
weights, CSI300, topk 10 / n_drop 2, 2025-01-02 to 2025-06-30): 117 trading days, total return +5.11%, Sharpe 0.53,
max drawdown -16.44%. A window past the factor coverage (2025-12-31) is rejected rather than back-filled.
