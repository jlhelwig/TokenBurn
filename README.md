# TokenBurn

Real-time API spend dashboard for Claude, Gemini, and Ollama.  
Three circular speedometer gauges in one floating window. Shows and hides automatically with VS Code.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│      ◉ Claude              ◉ Gemini              ◉ Ollama               │
│      $/min                 $/min                 tok/min                 │
│                                                                          │
│   ● Haiku 4.5   $0.0031  ● 2.5 Flash $0.0041  ● llama3     42,100t    │
│   ● Sonnet 4    $0.0012  ● 2.5 Pro   $0.0009  ● mistral     8,300t    │
│   ● Haiku 4     $0.0008  ● 2.0 Flash $0.0002  ● phi3          900t    │
│   ● Opus 4      $0.0001  ●                    ●                        │
│   ●                      ●                    ●                        │
│   ●                      ●                    ●                        │
│                                                                          │
│      $0.0063                $0.0052               87,400 tok            │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## How it works

### Gauges

Each gauge is a circular speedometer drawn on a tkinter Canvas:

- **Needle** — points to the current rate ($/min or tok/min). Sweeps 270° from 7-o'clock (zero) to 5-o'clock (max).
- **Color zones** — green (0–60% of peak), yellow (60–80%), red (80–100%).
- **Auto-scaling peak** — the max value on the dial grows when your rate exceeds 75% of the current peak, and slowly decays when activity drops off. The needle always uses the full arc.
- **Tick marks** — 21 ticks (every 5%), major ticks at 0/25/50/75/100% with scale labels that update as the peak scales.
- **Chrome bezel** — five concentric rings in graded greys for the 3D instrument look.

### Model rows

Up to **6 models per gauge**, stacked by spend (highest first). Each row shows:
```
● Model name      $0.0000
```
- Colors cycle through blue → green → orange → pink → purple → teal.
- **Unknown models** (not in the pricing table) appear in orange with a `?` marker — so new or experimental model IDs are visible immediately without crashing.

### Odometer

Session total below the model rows. Resets on double-click. Persists across polls within a session.

### Rate label

Rolling 60-second window. Each API call is timestamped when ingested; the rate is the sum of costs in the last 60 seconds, scaled to per-minute.

---

## Data sources

TokenBurn automatically scans for `governance_metrics.db` files across your dev environment:

```
~/.joplin/governance_metrics.db          ← default Joplin location
~/Dev/**/governance_metrics.db           ← local dev root
/Volumes/MyDrive/Dev/**/governance_metrics.db   ← external drive dev root
```

**How discovery works:**
1. On startup — full recursive walk of both dev roots to find all existing databases.
2. Every 30 seconds — rescan to pick up new databases from new projects. No restart needed.
3. Each database is tracked independently with its own cursor position (last row ID seen), so new rows are never double-counted across DBs.

All discovered databases are aggregated into the same three gauges. Running 20 concurrent experiments across two dev folders shows true combined spend.

Override or force-add a specific database:
```bash
export JOPLIN_GOVERNANCE_METRICS_DB=/path/to/your/governance_metrics.db
```

The gauges show **actual API spend** — only calls logged to `eval_calls` with a valid `provider` value (`claude`, `gemini`, or `local`). Claude Code conversation history (Max plan subscription) is not counted.

---

## Pricing tables

### Claude (per million tokens)

| Model family | Input | Output | Cache read | Cache write |
|-------------|-------|--------|------------|-------------|
| claude-opus-4 / claude-opus | $15.00 | $75.00 | $1.50 | $18.75 |
| claude-sonnet-4 / claude-sonnet | $3.00 | $15.00 | $0.30 | $3.75 |
| claude-haiku-4 / claude-haiku | $0.80 | $4.00 | $0.08 | $1.00 |

Matched by substring, most-specific first — so `claude-haiku-4-5-20251001` correctly resolves to haiku-4 pricing. Unknown Claude models fall back to sonnet pricing and show the `?` marker.

### Gemini (per million tokens)

| Model | Input | Output |
|-------|-------|--------|
| gemini-2.5-pro | $1.25 | $10.00 |
| gemini-2.5-flash / 2.0-flash / 1.5-flash | $0.075 | $0.30 |
| gemini-1.5-pro | $1.25 | $5.00 |

### Ollama

Always $0. Tracks tokens/min and total tokens only.

---

## Requirements

- macOS (tested on macOS 15 Sequoia)
- Python 3.12 via Homebrew: `/opt/homebrew/bin/python3.12`
- `python-tk@3.12`: `brew install python-tk@3.12`

---

## Install

### 1. Install the tkinter dependency (one time)

```bash
brew install python-tk@3.12
```

### 2. Install as a LaunchAgent (auto-start on login)

```bash
/opt/homebrew/bin/python3.12 /path/to/TokenBurn/install.py
```

Writes `~/Library/LaunchAgents/com.tokenburn.app.plist` and loads it immediately.  
TokenBurn starts automatically on every login.

---

## Start / stop

### Run manually

```bash
/opt/homebrew/bin/python3.12 /path/to/TokenBurn/tokenburn.py
```

### LaunchAgent controls

```bash
launchctl start com.tokenburn.app    # start now
launchctl stop com.tokenburn.app     # stop
launchctl list | grep tokenburn      # check status
```

Logs:
```
~/Library/Logs/tokenburn.log
~/Library/Logs/tokenburn.err
```

---

## Interaction

| Action | Effect |
|--------|--------|
| **Drag** anywhere | Reposition the window |
| **Double-click** any gauge | Reset all session totals (all three gauges) |

---

## VS Code integration

TokenBurn checks every 10 seconds whether VS Code is running (`pgrep -f "Visual Studio Code"`):
- VS Code opens → window appears
- VS Code quits → window hides

The window stays hidden when you're not coding — it's not a distraction when you're in the browser or a meeting.

---

## Wiring to Joplin

TokenBurn reads from the same `governance_metrics.db` files that Joplin's `metrics_collector.py` writes to. No configuration needed.

The gauges only move when:
- A real LLM API call is made (not regex hot-path evals — those are $0 and correct)
- The eval row has a valid `provider` value (`claude`, `gemini`, or `local`)

**Baseline / clean persona** forge runs hit 100% regex → $0 cost → needles stay at zero (correct).  
**Inconsistent persona** forge runs exercise the LLM eval path → Claude needle moves → spend accumulates.

---

## Customizing the activity dots

Each gauge has two dots at the bottom:

- **regex** (green) — flashes when a new row with `provider='regex'` is ingested. This is your zero-cost hot path firing.
- **api** (blue) — flashes when any non-regex eval row is ingested (Claude, Gemini, local). This is a real model call.

To change what the dots track, edit `ActivityMonitor._refresh_one()` in [tokenburn.py](tokenburn.py):

```python
# Current logic — split on provider='regex' vs everything else
regex_n = sum(1 for _, p in rows if p == "regex")
llm_n   = sum(1 for _, p in rows if p != "regex")
```

Swap in any condition you want. Examples:

```python
# Track Claude-only vs Gemini-only
regex_n = sum(1 for _, p in rows if p == "claude")
llm_n   = sum(1 for _, p in rows if p == "gemini")

# Track low-cost vs high-cost models (custom logic)
HIGH_COST = {"claude-opus-4", "gemini-2.5-pro"}
regex_n = sum(1 for _, p in rows if p not in HIGH_COST)
llm_n   = sum(1 for _, p in rows if p in HIGH_COST)
```

To change dot colors, edit the four constants near the top of the file:

```python
DOT_REGEX_DIM    = "#1a3a1a"   # dim green (idle)
DOT_REGEX_BRIGHT = "#3fb950"   # bright green (flash)
DOT_API_DIM      = "#1a2a3a"   # dim blue (idle)
DOT_API_BRIGHT   = "#4fc3f7"   # bright blue (flash)
DOT_FLASH_MS     = 500         # flash duration in milliseconds
```

---

## Uninstall

```bash
/opt/homebrew/bin/python3.12 /path/to/TokenBurn/install.py --uninstall
```

Unloads and removes the LaunchAgent plist. Source files are not deleted.
