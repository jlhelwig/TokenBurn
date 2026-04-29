"""
TokenBurn — real-time API spend dashboard.
Three circular speedometer gauges (Claude · Gemini · Ollama) in one window.
Double-click to reset session. Drag to move. Shows/hides with VS Code.
"""

import os, sys, time, math, sqlite3, threading, subprocess
import tkinter as tk
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict

# ── Pricing (per million tokens) ─────────────────────────────────────────────

# Ordered most-specific → least-specific; substring matched against model ID
CLAUDE_PRICING = [
    ("claude-opus-4",   {"input": 15.00, "output": 75.00, "cache_read": 1.50,  "cache_write": 18.75}),
    ("claude-sonnet-4", {"input": 3.00,  "output": 15.00, "cache_read": 0.30,  "cache_write": 3.75}),
    ("claude-haiku-4",  {"input": 0.80,  "output": 4.00,  "cache_read": 0.08,  "cache_write": 1.00}),
    ("claude-opus",     {"input": 15.00, "output": 75.00, "cache_read": 1.50,  "cache_write": 18.75}),
    ("claude-sonnet",   {"input": 3.00,  "output": 15.00, "cache_read": 0.30,  "cache_write": 3.75}),
    ("claude-haiku",    {"input": 0.80,  "output": 4.00,  "cache_read": 0.08,  "cache_write": 1.00}),
]
CLAUDE_DEFAULT = {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75}

GEMINI_PRICING = {
    "gemini-2.5-pro":   {"input": 1.25,  "output": 10.00},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro":   {"input": 1.25,  "output": 5.00},
}
GEMINI_DEFAULT = {"input": 0.075, "output": 0.30}

# ── Theme ─────────────────────────────────────────────────────────────────────

BG           = "#0d1117"
GAUGE_FACE   = "#080c08"
TEXT_WHITE   = "#e6edf3"
TEXT_GREY    = "#8b949e"
GREEN        = "#3fb950"
YELLOW       = "#d29922"
RED          = "#f85149"
OLLAMA_TEAL  = "#4fc3f7"
MODEL_COLORS = ["#4fc3f7", "#81c784", "#ffb74d", "#f48fb1", "#ce93d8", "#80cbc4"]

# ── Gauge geometry ────────────────────────────────────────────────────────────

GAUGE_R  = 88    # face radius
BEZEL_R  = 100   # outer chrome radius
NEEDLE_R = 72    # needle length
HUB_R    = 5

# Canvas dimensions per gauge
CW  = BEZEL_R * 2 + 20         # 220  canvas width
CY  = BEZEL_R + 10             # 110  gauge centre y

# Below the gauge: model rows + odometer + rate label
MODEL_ROW_H = 13
N_MODEL_ROWS = 6
BOTTOM_H = 16 + N_MODEL_ROWS * MODEL_ROW_H + 22 + 16  # gap + rows + odo + rate
CH = CY + BEZEL_R + BOTTOM_H   # total canvas height

# Activity dot colors (shared footer dots)
DOT_REGEX_DIM    = "#1a3a1a"
DOT_REGEX_BRIGHT = "#3fb950"
DOT_API_DIM      = "#1a2a3a"
DOT_API_BRIGHT   = "#4fc3f7"
DOT_FLASH_MS     = 2500

# Speedometer arc: 0 at 7-o'clock (225°), max at 5-o'clock (−45°), CW = −270°
A_START =  225
A_SWEEP = -270


# ── Helpers ───────────────────────────────────────────────────────────────────

def _short_model(name: str) -> str:
    """Return a short display name for any model ID, including unknown future models."""
    n = name.lower().strip()
    # Strip common prefixes so the interesting part is visible
    for prefix in ("models/", "anthropic/", "google/"):
        if n.startswith(prefix):
            n = n[len(prefix):]
    # Friendly labels for known patterns
    for pat, label in [
        ("claude-opus-4",    "Opus 4"),
        ("claude-sonnet-4",  "Sonnet 4"),
        ("claude-haiku-4",   "Haiku 4"),
        ("gemini-2.5-pro",   "G 2.5 Pro"),
        ("gemini-2.5-flash", "G 2.5 Flash"),
        ("gemini-2.0-flash", "G 2.0 Flash"),
        ("gemini-1.5-pro",   "G 1.5 Pro"),
        ("gemini-1.5-flash", "G 1.5 Flash"),
    ]:
        if pat in n:
            return label
    # Local / Ollama models — strip organisation prefix (e.g. "meta/llama3" → "llama3")
    if "/" in n:
        n = n.split("/")[-1]
    # Return cleaned ID truncated to fit the column — keeps version numbers visible
    return n[:11]


def _is_known_claude(model: str) -> bool:
    return any(k in model.lower() for k, _ in CLAUDE_PRICING)


def _is_known_gemini(model: str) -> bool:
    return any(k in model.lower() for k in GEMINI_PRICING)


def _claude_cost(usage: dict, model: str) -> float:
    m = model.lower()
    p = next((v for k, v in CLAUDE_PRICING if k in m), CLAUDE_DEFAULT)
    return (
        usage.get("input_tokens", 0)                * p["input"]
        + usage.get("output_tokens", 0)             * p["output"]
        + usage.get("cache_read_input_tokens", 0)   * p.get("cache_read",  p["input"] * 0.10)
        + usage.get("cache_creation_input_tokens",0) * p.get("cache_write", p["input"] * 1.25)
    ) / 1_000_000


def _gemini_cost(inp: int, out: int, model: str) -> float:
    key = next((k for k in GEMINI_PRICING if k in model.lower()), None)
    p   = GEMINI_PRICING[key] if key else GEMINI_DEFAULT
    return (inp * p["input"] + out * p["output"]) / 1_000_000


def _vscode_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-f", "Visual Studio Code"],
                              capture_output=True).returncode == 0
    except Exception:
        return True


def _needle_tip(cx: int, cy: int, frac: float, length: float):
    angle = math.radians(A_START + A_SWEEP * frac)
    return cx + length * math.cos(angle), cy - length * math.sin(angle)


# ── DB discovery ─────────────────────────────────────────────────────────────

_DEV_ROOTS = [
    Path.home() / "Dev",
    Path.home() / "Projects",
    Path("/Volumes/MyDrive/Dev"),
]
_EXTRA_DB = os.environ.get("JOPLIN_GOVERNANCE_METRICS_DB")
_DB_RESCAN_INTERVAL = 30   # seconds between full filesystem scans


def _find_dbs() -> list:
    """Walk dev roots for governance_metrics.db files. O(dev tree), called every 30s."""
    found = set()
    # Explicit override always included
    if _EXTRA_DB:
        p = Path(_EXTRA_DB)
        if p.exists():
            found.add(p)
    # Default ~/.joplin/ location
    default = Path.home() / ".joplin" / "governance_metrics.db"
    if default.exists():
        found.add(default)
    # Walk dev roots
    for root in _DEV_ROOTS:
        if not root.exists():
            continue
        try:
            for p in root.rglob("governance_metrics.db"):
                found.add(p)
        except PermissionError:
            pass
    return sorted(found)


# ── Collectors ────────────────────────────────────────────────────────────────

class _DbCollector:
    provider: str = ""

    def __init__(self):
        self._lock           = threading.Lock()
        self.session_cost    = 0.0
        self.model_costs: Dict[str, float] = defaultdict(float)
        self.unknown_models: set = set()
        self._events: deque  = deque()
        self._last_id: Dict[str, int] = {}   # db_path → last row id seen

    def reset(self):
        with self._lock:
            self.session_cost   = 0.0
            self.model_costs    = defaultdict(float)
            self.unknown_models = set()
            self._events.clear()
            self._last_id       = {}

    def refresh(self, db_paths: list):
        for path in db_paths:
            self._refresh_one(path)

    def _refresh_one(self, path):
        key = str(path)
        try:
            con = sqlite3.connect(str(path), timeout=2)
            cur = con.cursor()
            with self._lock:
                last = self._last_id.get(key, 0)
            is_initial = (last == 0 and key not in self._last_id)
            cur.execute(
                "SELECT id, model, prompt_tokens, completion_tokens, cost_usd "
                "FROM eval_calls WHERE provider=? AND id > ? ORDER BY id ASC",
                (self.provider, last),
            )
            rows = cur.fetchall()
            con.close()
        except Exception:
            return
        if rows:
            self._process(rows, key, is_initial)

    def _process(self, rows, db_key: str, is_initial: bool = False):
        raise NotImplementedError

    def dollars_per_minute(self) -> float:
        cutoff = time.time() - 60.0
        with self._lock:
            return sum(c for ts, c in self._events if ts >= cutoff) * 60.0

    def snapshot(self):
        with self._lock:
            return dict(self.model_costs), self.session_cost, set(self.unknown_models)


class ClaudeCollector(_DbCollector):
    provider = "claude"

    def _process(self, rows, db_key: str, is_initial: bool = False):
        new_costs: Dict[str, float] = {}
        new_unknown = set()
        events = []
        for row_id, model, inp, out, cost_usd in rows:
            model = model or "unknown"
            if not _is_known_claude(model):
                new_unknown.add(model)
            cost  = float(cost_usd) if cost_usd else _claude_cost(
                {"input_tokens": inp or 0, "output_tokens": out or 0}, model)
            new_costs[model] = new_costs.get(model, 0.0) + cost
            if not is_initial:
                events.append((time.time(), cost))
        with self._lock:
            for m, c in new_costs.items():
                self.model_costs[m] = self.model_costs.get(m, 0.0) + c
            self.unknown_models.update(new_unknown)
            self.session_cost += sum(new_costs.values())
            self._events.extend(events)
            self._last_id[db_key] = rows[-1][0]


class GeminiCollector(_DbCollector):
    provider = "gemini"

    def _process(self, rows, db_key: str, is_initial: bool = False):
        new_costs: Dict[str, float] = {}
        new_unknown = set()
        events = []
        for row_id, model, inp, out, cost_usd in rows:
            model = model or "unknown"
            if not _is_known_gemini(model):
                new_unknown.add(model)
            cost  = float(cost_usd) if cost_usd else _gemini_cost(inp or 0, out or 0, model)
            new_costs[model] = new_costs.get(model, 0.0) + cost
            if not is_initial:
                events.append((time.time(), cost))
        with self._lock:
            for m, c in new_costs.items():
                self.model_costs[m] = self.model_costs.get(m, 0.0) + c
            self.unknown_models.update(new_unknown)
            self.session_cost += sum(new_costs.values())
            self._events.extend(events)
            self._last_id[db_key] = rows[-1][0]


class OllamaCollector:
    """Local models: always $0, tracks token volume instead of cost."""

    def __init__(self):
        self._lock          = threading.Lock()
        self.session_tokens = 0
        self.model_tokens: Dict[str, int] = defaultdict(int)
        self._tok_events: deque = deque()
        self._last_id: Dict[str, int] = {}   # db_path → last row id seen

    def reset(self):
        with self._lock:
            self.session_tokens = 0
            self.model_tokens   = defaultdict(int)
            self._tok_events.clear()
            self._last_id       = {}

    def refresh(self, db_paths: list):
        for path in db_paths:
            self._refresh_one(path)

    def _refresh_one(self, path):
        key = str(path)
        try:
            con = sqlite3.connect(str(path), timeout=2)
            cur = con.cursor()
            with self._lock:
                last = self._last_id.get(key, 0)
            cur.execute(
                "SELECT id, model, prompt_tokens, completion_tokens "
                "FROM eval_calls WHERE provider='local' AND id > ? ORDER BY id ASC",
                (last,),
            )
            rows = cur.fetchall()
            con.close()
        except Exception:
            return
        if not rows:
            return
        with self._lock:
            for row_id, model, inp, out in rows:
                toks  = (inp or 0) + (out or 0)
                model = model or "unknown"
                self.model_tokens[model]  += toks
                self.session_tokens       += toks
                self._tok_events.append((time.time(), toks))
            self._last_id[key] = rows[-1][0]

    def tokens_per_minute(self) -> float:
        cutoff = time.time() - 60.0
        with self._lock:
            return float(sum(t for ts, t in self._tok_events if ts >= cutoff))

    def snapshot_tokens(self):
        with self._lock:
            return dict(self.model_tokens), self.session_tokens


# ── Activity monitor (regex vs LLM hit counts across all DBs) ────────────────

class ActivityMonitor:
    """Counts regex hits and LLM eval hits independently across all discovered DBs."""

    def __init__(self):
        self._lock         = threading.Lock()
        self.regex_total   = 0
        self.llm_total     = 0
        self._last_id: Dict[str, int] = {}   # db_path → last row id seen

    def reset(self):
        with self._lock:
            self.regex_total = 0
            self.llm_total   = 0
            self._last_id    = {}

    def refresh(self, db_paths: list):
        for path in db_paths:
            self._refresh_one(path)

    def _refresh_one(self, path):
        key = str(path)
        try:
            con = sqlite3.connect(str(path), timeout=2)
            cur = con.cursor()
            with self._lock:
                last = self._last_id.get(key, 0)
            cur.execute(
                "SELECT id, provider FROM eval_calls WHERE id > ? ORDER BY id ASC",
                (last,),
            )
            rows = cur.fetchall()
            con.close()
        except Exception:
            return
        if not rows:
            return
        regex_n = sum(1 for _, p in rows if p == "regex")
        llm_n   = sum(1 for _, p in rows if p != "regex")
        with self._lock:
            self.regex_total += regex_n
            self.llm_total   += llm_n
            self._last_id[key] = rows[-1][0]

    def snapshot(self):
        with self._lock:
            return self.regex_total, self.llm_total


# ── Gauge widget ──────────────────────────────────────────────────────────────

class GaugeWidget:
    """Circular speedometer drawn on its own Canvas."""

    def __init__(self, parent, title: str, collector, mode: str = "dollars"):
        self.collector = collector
        self.mode      = mode          # "dollars" | "tokens"
        self._peak     = 0.00001 if mode == "dollars" else 1.0
        self._cx       = CW // 2
        self._cy       = CY

        frame = tk.Frame(parent, bg=BG)
        frame.pack(side=tk.LEFT, padx=3, pady=6)

        self._c = tk.Canvas(frame, width=CW, height=CH, bg=BG, highlightthickness=0)
        self._c.pack()

        self._draw_static(title)
        self._build_dynamic()

    # ── Static drawing (called once) ──────────────────────────────────────────

    def _draw_static(self, title: str):
        c = self._c
        cx, cy = self._cx, self._cy

        # Chrome bezel — concentric ovals
        for r, col in [
            (BEZEL_R,      "#4a4a4a"),
            (BEZEL_R - 2,  "#b0b0b0"),
            (BEZEL_R - 5,  "#909090"),
            (BEZEL_R - 9,  "#505050"),
            (BEZEL_R - 13, "#1e1e1e"),
        ]:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="")

        # Gauge face
        c.create_oval(cx - GAUGE_R, cy - GAUGE_R,
                      cx + GAUGE_R, cy + GAUGE_R,
                      fill=GAUGE_FACE, outline="#2a2a2a", width=1)

        # Colour zone arcs
        ar   = GAUGE_R - 10
        bbox = (cx - ar, cy - ar, cx + ar, cy + ar)
        c.create_arc(*bbox, start=A_START,                  extent=A_SWEEP * 0.60,
                     outline=GREEN,  width=5, style="arc")
        c.create_arc(*bbox, start=A_START + A_SWEEP * 0.60, extent=A_SWEEP * 0.20,
                     outline=YELLOW, width=5, style="arc")
        c.create_arc(*bbox, start=A_START + A_SWEEP * 0.80, extent=A_SWEEP * 0.20,
                     outline=RED,    width=5, style="arc")

        # Tick marks (21 ticks = every 5% of range)
        outer_r = GAUGE_R - 16
        for i in range(21):
            frac     = i / 20
            angle    = math.radians(A_START + A_SWEEP * frac)
            ca, sa   = math.cos(angle), math.sin(angle)
            is_major = (i % 5 == 0)
            inner_r  = outer_r - (9 if is_major else 4)
            c.create_line(cx + outer_r * ca, cy - outer_r * sa,
                          cx + inner_r * ca, cy - inner_r * sa,
                          fill=TEXT_WHITE if is_major else "#555555",
                          width=2 if is_major else 1)

        # Scale number labels at 0 / 25 / 50 / 75 / 100 % positions
        lbl_r = GAUGE_R - 32
        self._scale_labels = []
        for i in range(5):
            frac  = i / 4
            angle = math.radians(A_START + A_SWEEP * frac)
            lbl = c.create_text(
                cx + lbl_r * math.cos(angle),
                cy - lbl_r * math.sin(angle),
                text="", fill=TEXT_GREY, font=("Menlo", 6),
            )
            self._scale_labels.append(lbl)

        # Gauge title (inside face, below center)
        color = OLLAMA_TEAL if self.mode == "tokens" else TEXT_GREY
        c.create_text(cx, cy + 26, text=title,
                      fill=color, font=("Helvetica", 8, "bold"))

        # Unit label
        unit = "tok/min" if self.mode == "tokens" else "$/min"
        c.create_text(cx, cy + 40, text=unit,
                      fill=TEXT_GREY, font=("Menlo", 6))

    # ── Dynamic elements (needle + readouts) ──────────────────────────────────

    def _build_dynamic(self):
        c = self._c
        cx, cy = self._cx, self._cy

        # Needle
        nx, ny = _needle_tip(cx, cy, 0.0, NEEDLE_R)
        self._needle = c.create_line(cx, cy, nx, ny,
                                     fill=TEXT_WHITE, width=2, capstyle=tk.ROUND)
        self._current_frac = 0.0
        self._target_frac  = 0.0

        # Hub (drawn on top of needle base)
        c.create_oval(cx - HUB_R, cy - HUB_R, cx + HUB_R, cy + HUB_R,
                      fill="#cccccc", outline="")

        base_y = CY + BEZEL_R + 18

        # Model rows
        self._model_rows = []
        for i in range(N_MODEL_ROWS):
            row = c.create_text(8, base_y + i * MODEL_ROW_H, anchor="w",
                                text="", fill=MODEL_COLORS[i],
                                font=("Menlo", 7))
            self._model_rows.append(row)

        odo_y  = base_y + N_MODEL_ROWS * MODEL_ROW_H + 10
        rate_y = odo_y + 18

        self._odo      = c.create_text(cx, odo_y,  text="$0.0000",
                                       fill=TEXT_WHITE, font=("Menlo", 14, "bold"))
        self._rate_lbl = c.create_text(cx, rate_y, text="0.0000 $/min",
                                       fill=TEXT_GREY,  font=("Menlo", 7))

    # ── Update (called every tick) ────────────────────────────────────────────

    def update(self, rate: float, model_values: dict, total,
               unknown_models: set = None):
        c = self._c
        cx, cy = self._cx, self._cy
        unknown_models = unknown_models or set()

        # Auto-scale peak
        if rate > self._peak * 0.75:
            self._peak = rate * 2.0
        elif rate < self._peak * 0.05 and self._peak > 0.0000001:
            self._peak = max(0.0000001, self._peak * 0.95)

        # Scale labels
        for i, lbl in enumerate(self._scale_labels):
            val = self._peak * (i / 4)
            if self.mode == "tokens":
                text = f"{val/1000:.0f}K" if val >= 1000 else f"{int(val)}"
            else:
                text = f"{val:.2f}" if val >= 0.1 else f"{val:.4f}"
            c.itemconfigure(lbl, text=text)

        # Needle — set target, animation sweeps to it over 3 seconds
        self._target_frac = min(rate / self._peak, 1.0) if self._peak > 0 else 0.0

        # Model rows — unknown models shown in orange with ? marker
        sorted_m = sorted(model_values.items(), key=lambda x: -x[1])[:N_MODEL_ROWS]
        for i, row in enumerate(self._model_rows):
            if i < len(sorted_m):
                name, val = sorted_m[i]
                is_unknown = name in unknown_models
                color  = "#ff9500" if is_unknown else MODEL_COLORS[i]
                marker = "?" if is_unknown else "●"
                label  = _short_model(name)
                if is_unknown:
                    label = label[:9] + "?"   # flag unknown in the name too
                if self.mode == "tokens":
                    c.itemconfigure(row, text=f"{marker} {label:<11} {int(val):,}t",
                                    fill=color)
                else:
                    c.itemconfigure(row, text=f"{marker} {label:<11} ${val:.4f}",
                                    fill=color)
            else:
                c.itemconfigure(row, text="")

        # Odometer + rate
        if self.mode == "tokens":
            c.itemconfigure(self._odo,      text=f"{int(total):,} tok")
            c.itemconfigure(self._rate_lbl, text=f"{int(rate)} tok/min")
        else:
            c.itemconfigure(self._odo,      text=f"${float(total):.4f}")
            c.itemconfigure(self._rate_lbl, text=f"{float(rate):.4f} $/min")

    def animate(self):
        """Step needle toward target over 3 seconds (30 frames × 100ms)."""
        step = (self._target_frac - self._current_frac) / 8
        self._current_frac += step
        if abs(self._current_frac - self._target_frac) < 0.001:
            self._current_frac = self._target_frac
        nx, ny = _needle_tip(self._cx, self._cy, self._current_frac, NEEDLE_R)
        self._c.coords(self._needle, self._cx, self._cy, nx, ny)


# ── App ───────────────────────────────────────────────────────────────────────

class TokenBurn:
    def __init__(self):
        self._claude_c   = ClaudeCollector()
        self._gemini_c   = GeminiCollector()
        self._ollama_c   = OllamaCollector()
        self._activity   = ActivityMonitor()
        self._visible    = True
        self._stop     = threading.Event()

        self.root = tk.Tk()
        self.root.title("TokenBurn")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.wm_attributes("-topmost", True)
        self.root.bind("<ButtonPress-1>",   self._drag_start)
        self.root.bind("<B1-Motion>",       self._drag_move)
        self.root.bind("<Double-Button-1>", self._reset_all)
        self._dx = self._dy = 0

        container = tk.Frame(self.root, bg=BG)
        container.pack(padx=4, pady=4)

        self._claude_g = GaugeWidget(container, "Claude", self._claude_c, "dollars")
        self._gemini_g = GaugeWidget(container, "Gemini", self._gemini_c, "dollars")
        self._ollama_g = GaugeWidget(container, "Ollama", self._ollama_c, "tokens")

        # Shared activity footer — one pair of dots for the whole window
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(pady=(0, 6))
        dot_canvas = tk.Canvas(footer, width=160, height=16, bg=BG, highlightthickness=0)
        dot_canvas.pack()
        dot_r = 5
        self._dot_regex = dot_canvas.create_oval(10, 4, 10+dot_r*2, 4+dot_r*2,
                                                  fill=DOT_REGEX_DIM, outline="")
        dot_canvas.create_text(24, 8, text="regex", anchor="w",
                               fill=TEXT_GREY, font=("Menlo", 7))
        self._dot_api = dot_canvas.create_oval(80, 4, 80+dot_r*2, 4+dot_r*2,
                                                fill=DOT_API_DIM, outline="")
        dot_canvas.create_text(94, 8, text="api", anchor="w",
                               fill=TEXT_GREY, font=("Menlo", 7))
        self._dot_canvas   = dot_canvas
        self._prev_regex   = 0
        self._prev_llm     = 0

        # Position bottom-right of primary screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ww = self.root.winfo_reqwidth()
        wh = self.root.winfo_reqheight()
        self.root.geometry(f"+{sw - ww - 20}+{sh - wh - 60}")

        self._db_paths = []

        t = threading.Thread(target=self._refresh_loop, daemon=True)
        t.start()

        self.root.after(200,    self._initial_refresh)
        self.root.after(5_000,  self._tick)
        self.root.after(10_000, self._check_vscode)
        self.root.after(100,    self._animate)

    def _reset_all(self, _e=None):
        self._claude_c.reset()
        self._gemini_c.reset()
        self._ollama_c.reset()

    def _initial_refresh(self):
        self._db_paths = _find_dbs()
        self._claude_c.refresh(self._db_paths)
        self._gemini_c.refresh(self._db_paths)
        self._ollama_c.refresh(self._db_paths)
        self._activity.refresh(self._db_paths)
        self._tick()

    def _refresh_loop(self):
        last_scan = 0.0
        while not self._stop.is_set():
            now = time.time()
            if now - last_scan >= _DB_RESCAN_INTERVAL:
                self._db_paths = _find_dbs()
                last_scan = now
            self._claude_c.refresh(self._db_paths)
            self._gemini_c.refresh(self._db_paths)
            self._ollama_c.refresh(self._db_paths)
            self._activity.refresh(self._db_paths)
            time.sleep(5)

    def _animate(self):
        self._claude_g.animate()
        self._gemini_g.animate()
        self._ollama_g.animate()
        self.root.after(100, self._animate)

    def _flash_dot(self, dot, bright, dim):
        self._dot_canvas.itemconfigure(dot, fill=bright)
        self._dot_canvas.after(DOT_FLASH_MS,
                               lambda: self._dot_canvas.itemconfigure(dot, fill=dim))

    def _tick(self):
        rx, lx = self._activity.snapshot()

        if rx > self._prev_regex:
            self._flash_dot(self._dot_regex, DOT_REGEX_BRIGHT, DOT_REGEX_DIM)
            self._prev_regex = rx
        if lx > self._prev_llm:
            self._flash_dot(self._dot_api, DOT_API_BRIGHT, DOT_API_DIM)
            self._prev_llm = lx

        cm, ct, cu = self._claude_c.snapshot()
        self._claude_g.update(self._claude_c.dollars_per_minute(), cm, ct, unknown_models=cu)

        gm, gt, gu = self._gemini_c.snapshot()
        self._gemini_g.update(self._gemini_c.dollars_per_minute(), gm, gt, unknown_models=gu)

        mt, tt = self._ollama_c.snapshot_tokens()
        self._ollama_g.update(self._ollama_c.tokens_per_minute(), mt, tt)

        self.root.after(5_000, self._tick)

    def _check_vscode(self):
        running = _vscode_running()
        if running and not self._visible:
            self.root.deiconify()
            self._visible = True
        elif not running and self._visible:
            self.root.withdraw()
            self._visible = False
        self.root.after(10_000, self._check_vscode)

    def _drag_start(self, e): self._dx, self._dy = e.x, e.y
    def _drag_move(self, e):
        self.root.geometry(
            f"+{self.root.winfo_x() + e.x - self._dx}"
            f"+{self.root.winfo_y() + e.y - self._dy}"
        )

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self._stop.set()


if __name__ == "__main__":
    TokenBurn().run()
