# PA-MTF Hybrid V2

This repository uses a deterministic-first hybrid architecture for VVV_USDT market analysis.

## 1. Data integrity

Source:
- MEXC Futures public OHLC and contract snapshot.
- Production analysis fetches 420 candles per timeframe: 4H, 1H, 15M.
- Signals are calculated only from fully closed candles.
- The currently-forming exchange candle is excluded from BOS, CHoCH, FVG, Supply/Demand, sweep, displacement, retest, setup and trend calculations.
- Charts render the latest 160 closed candles.
- The AI layer receives the latest 64 closed candles per timeframe plus Python-derived market facts.
- Live MEXC ticker price can still be shown separately from the last closed analysis price.

This separation is intentional: live price is informational, while signal logic is non-repainting at candle level.

## 2. Deterministic Price Action / SMC engine

Structural trend:
- HH + HL = bullish.
- LH + LL = bearish.
- Other combinations = mixed/neutral.
- Swings use confirmed centered swing points.

Structure:
- BOS / CHoCH require a close through a confirmed swing level.
- Wick-only breaks are not treated as structure breaks.

Market regime adds context on top of the swing trend:
- BULLISH_TREND
- BULLISH_PULLBACK
- BULLISH_TO_BEARISH_TRANSITION
- BEARISH_TREND
- BEARISH_PULLBACK
- BEARISH_TO_BULLISH_TRANSITION
- BULLISH_TRANSITION
- BEARISH_TRANSITION
- RANGE

15M setup sequence:
- liquidity sweep
- displacement
- BOS/CHoCH structure event
- retest

The setup score is 0-4. CONFIRMED requires valid event ordering, not only a 4/4 count.

Status vocabulary remains:
- WAIT
- DEVELOPING LONG
- DEVELOPING SHORT
- CONFIRMED LONG
- CONFIRMED SHORT

CONFIRMED means the 15M signal sequence is confirmed. It does not mean execution is automatically allowed.

## 3. Supply / Demand V3

Price-action origin patterns:
- DBR / RBR demand
- RBD / DBD supply

Zone scoring uses:
- departure strength
- excursion
- freshness
- mitigation count
- age
- structural impact
- FVG
- liquidity sweep context
- clean-base quality
- fast return penalty
- distance from current price

Existing quality labels:
- HIGH
- MEDIUM
- LOW

Calibration grade:
- A+ >= 8.5
- A >= 7.0
- B >= 5.0
- C < 5.0

Grade is logged for evaluation. Grade C cannot pass the execution gate. B remains observable while forward/backtest data is collected; the system does not automatically force A+/A-only gating without enough evidence.

Historical/reference zones remain context only and can never become Entry/SL/TP sources.

## 4. Multi-timeframe alignment

4H = macro context.
1H = intermediate structure and decision context.
15M = execution signal/timing.

A separate deterministic MTF Alignment is calculated:
- ALIGNED
- PARTIAL
- CONFLICT
- NEUTRAL

The 15M setup owns the signal status. MTF Alignment owns execution quality.

If MTF Alignment is CONFLICT, the deterministic Trade Plan cannot become READY.

## 5. Trade Plan

Python owns:
- entry zone
- invalidation / stop
- liquidity targets
- R fallback targets
- RR
- execution blockers
- READY / WAIT

Execution blockers include:
- MTF CONFLICT
- grade C Supply/Demand entry
- 15M score below threshold
- missing displacement
- missing BOS/CHoCH
- first liquidity target below 1R
- opposing active 1H setup

Fallback R targets are required to remain monotonic after real liquidity targets, so the scenario path cannot move backward.

## 6. Derivatives context

MEXC holdVol is treated as an exchange-specific open-position/OI proxy, not aggregated market open interest.

Price + holdVol context:
- PRICE_UP_HOLD_UP
- PRICE_DOWN_HOLD_UP
- PRICE_UP_HOLD_DOWN
- PRICE_DOWN_HOLD_DOWN
- NEUTRAL_MIXED

This is context only and never a standalone LONG/SHORT signal.

Funding is also context only.

## 7. Technical confirmation

Supplementary context:
- EMA20 / EMA50
- anchored VWAP
- RSI14
- ATR
- relative volume
- 20-bar range location

These do not override structural Price Action or the Python execution gate.

## 8. AI interpretation layer

Default route:
- Primary: Qwen3.8 27B free via OpenRouter, `qwen/qwen3.8-27b:free`.
- Fallback: `openrouter/free`.
- OpenRouter OpenAI-compatible Chat Completions API.

AI receives:
- Python status
- MTF Alignment
- Trade Plan
- market snapshot / participation context
- 4H / 1H / 15M trend and regime
- active Supply/Demand and grade
- BSL / SSL
- BOS / CHoCH
- sweep
- displacement
- FVG
- retest
- technical confirmation
- 64 recent real closed candles per timeframe

AI may:
- explain market context
- compare 4H / 1H / 15M
- describe confluence and conflict
- provide conditional bullish/bearish scenarios
- provide a qualitative BULLISH / BEARISH / MIXED / WAIT bias

AI may not:
- invent or change numerical levels
- draw or replace candles
- promote reference zones to active zones
- create Entry / SL / TP
- override execution_ready
- state unsupported probabilities

## 9. Post-AI deterministic validator

Before Telegram, Python validates AI output:
- JSON structure
- required fields
- Vietnamese explanatory language
- no invented price-like decimal levels
- no unsupported percentage/probability language
- Python execution gate enforcement

If Execution is WAIT, Python replaces the AI execution line with deterministic WAIT wording.

A failed AI validation triggers the fallback model. If all AI routes fail, Telegram falls back to the deterministic Python report.

## 10. Production self-check

Every hourly run executes `self_check.py` before AI.

It validates:
- closed-candle-only mode
- actual returned history of at least 360 closed bars per timeframe for the zone-policy horizon
- exact status vocabulary
- no forming candle in the chart/AI packet
- no READY state during MTF CONFLICT
- no READY state with blockers
- monotonic TP ordering
- no Historical/Reference entry source

A failed invariant stops the workflow before AI/Telegram can publish a bad deterministic report.

## 11. Forward evaluation journal

`signal_history.json` is persisted across hourly runs.

Each unique setup records:
- status and direction
- MTF Alignment
- 4H / 1H / 15M regimes
- setup score
- entry / stop / targets
- zone grade
- participation context
- funding / holdVol
- AI bias when available
- entry time
- MFE / MAE in R
- TP hits
- stop / timeout / no-entry outcome

If the entry candle also reaches stop/target, it is marked AMBIGUOUS_ENTRY_BAR. Later candles that reach both stop and a new target are marked AMBIGUOUS_SAME_BAR. Intrabar order is never guessed.

Calibration summaries are written to:
- `output/VVVUSDT_signal_stats.json`

Breakdowns include:
- zone grade
- MTF Alignment
- 15M regime

Threshold auto-tuning is disabled. The calibration layer waits for at least 30 resolved forward signals before marking the sample READY_FOR_REVIEW.

## 12. Walk-forward backtest

`walk_forward_backtest.py` performs a no-lookahead multi-timeframe evaluation.

Rules:
- decisions are evaluated hourly
- each historical decision sees only candles closed by that timestamp
- future 15M candles are used only after the signal is frozen
- the same production SMC, regime, MTF and Trade Plan code is reused
- ambiguous same-bar outcomes are not guessed

A weekly GitHub Actions workflow runs:
- `.github/workflows/vvv-backtest.yml`

Report:
- `output/VVVUSDT_walk_forward_backtest.json`

Backtest and forward-test statistics are calibration evidence, not guarantees of future performance.

## 13. Telegram workflow

Hourly production:
MEXC closed candles -> Python SMC/PA -> regime + MTF alignment -> Trade Plan -> self-check -> OpenRouter AI -> AI validator -> Telegram.

Fallback:
- AI failure or validation failure -> Python report.
- Deterministic charts remain unaffected.

Required secret:
- OPENROUTER_API_KEY

Optional model overrides:
- OPENROUTER_MODEL
- OPENROUTER_FALLBACK_MODEL

Telegram secrets:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
