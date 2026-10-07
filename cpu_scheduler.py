"""
CPU Scheduling Algorithm Simulator  -  "Mission Control" edition
Requires only: tkinter (standard library) and matplotlib.

Run:        python cpu_scheduler.py
Self-test:  python cpu_scheduler.py --selftest   (no window; checks engine, charts and file formats)

Formulas (CT = completion time, AT = arrival time, BT = burst time):
    Turnaround time (TAT) = CT - AT          Waiting time (WT) = TAT - BT
    Response time   (RT)  = first CPU time - AT
    CPU utilization       = busy time / total time * 100
    Context switches      = number of times the CPU is handed to a process - 1

Bonus features beyond the 4 required algorithms (FCFS, SJF, Round Robin, Priority):
    1. Live CPU view      - animated CPU chip, ready queue, terminated bin, play/pause/step/scrub
    2. Process timeline   - one swim-lane per process (arrival, running, waiting, completion)
    3. Event log          - readable story of what the scheduler did and when
    4. Quantum Lab        - sweeps the Round Robin quantum and finds the best one
    5. Algorithm guide    - how each algorithm works + an automatic recommendation for YOUR data
    6. Dark / Light theme - projector friendly
    7. Save / Load workspace (JSON), CSV import/export, PNG chart export
    8. HTML report        - one-click printable report with Gantt chart and comparison table
    9. Extra algorithms   - SRTF and preemptive Priority; response time and context-switch metrics
"""
import base64
import colorsys
import copy
import csv
import datetime
import html
import io
import json
import math
import os
import pathlib
import random
import sys
import webbrowser
from dataclasses import dataclass, field
try:                                    # Tkinter is only needed for the window, not for --selftest
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, font as tkfont
    HAS_TK = True
except ImportError:
    tk = ttk = messagebox = filedialog = tkfont = None
    HAS_TK = False

import matplotlib
matplotlib.use("TkAgg" if HAS_TK else "Agg")
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
if HAS_TK:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

ALGORITHMS = [
    "FCFS",
    "SJF (Non-preemptive)",
    "SRTF (Preemptive SJF)",
    "Round Robin",
    "Priority (Non-preemptive)",
    "Priority (Preemptive)",
]
IDLE = "Idle"

# Input limits keep the simulator (and the charts) responsive.
MAX_PROCS = 30
MAX_TIME = 9999          # max arrival / burst / quantum
MAX_PRIORITY = 999
MAX_SLICES = 20000       # Round Robin guard: quantum too small for the bursts

PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
           "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#8CD17D"]
KIND_COLOR = {"arrive": "#f0b429", "run": "#4ea1ff", "preempt": "#ff9f43",
              "done": "#3ddc84", "idle": "#8b98a9"}

THEMES = {
    "Dark": dict(bg="#11151c", panel="#1a2029", panel2="#232b37", fg="#e6edf3", muted="#8b98a9",
                 accent="#4ea1ff", accent_fg="#ffffff", stripe="#202833", grid="#2e3846",
                 idle="#3a4352", good="#1f4d36", err="#ff6b6b", entry="#0f131a",
                 head1="#0b3d91", head2="#12997f", canvas="#0d1117", zone="#161c25",
                 zone_edge="#2b3544", chip="#2a2f3a", chip_edge="#5b6578", pin="#c9a227",
                 sel="#2d5a8c"),
    "Light": dict(bg="#eef2f7", panel="#ffffff", panel2="#e3e9f2", fg="#1b2430", muted="#5d6b7e",
                  accent="#1f6fd1", accent_fg="#ffffff", stripe="#f4f7fb", grid="#dddddd",
                  idle="#d9d9d9", good="#c8f7c5", err="#b00020", entry="#ffffff",
                  head1="#0b3d91", head2="#12997f", canvas="#f6f8fb", zone="#ffffff",
                  zone_edge="#cfd8e3", chip="#3b4252", chip_edge="#1f2430", pin="#b8860b",
                  sel="#b9d7ff"),
}
T = dict(THEMES["Dark"])          # the active theme; read by every drawing function


def set_theme(name):
    global T
    T = dict(THEMES[name])


ALGO_INFO = {   # kind, how it decides, strengths, weaknesses, best for, cost
    "FCFS": ("Non-preemptive", "Runs processes strictly in the order they arrive.",
             "Simple and predictable; no starvation.",
             "Convoy effect: one long job makes every short job behind it wait.",
             "Simple batch systems with similar job lengths.", "O(1) per decision with a FIFO queue"),
    "SJF (Non-preemptive)": ("Non-preemptive", "Among the ready processes, runs the one with the shortest burst.",
                             "Lowest average waiting time of any non-preemptive algorithm.",
                             "Needs burst times in advance; long jobs may starve.",
                             "Batch jobs whose run time can be estimated.", "O(n) per decision (O(log n) with a heap)"),
    "SRTF (Preemptive SJF)": ("Preemptive", "Always runs the process with the least remaining time; a shorter arrival preempts.",
                              "Optimal average waiting time.",
                              "More context switches; long jobs may starve; needs burst estimates.",
                              "Mixed workloads where short jobs must finish fast.", "O(n) per arrival/completion"),
    "Round Robin": ("Preemptive", "Gives every process a fixed time quantum in a circular queue.",
                    "Fair; good response time; no starvation.",
                    "Tiny quantum = many context switches; huge quantum = behaves like FCFS.",
                    "Time-sharing and interactive systems.", "O(1) per time slice"),
    "Priority (Non-preemptive)": ("Non-preemptive", "Runs the ready process with the best priority; it keeps the CPU until it finishes.",
                                  "Important work goes first.",
                                  "Low-priority processes can starve (fix: aging).",
                                  "Systems with clear importance levels.", "O(n) per decision"),
    "Priority (Preemptive)": ("Preemptive", "Like Priority, but a higher-priority arrival immediately takes the CPU.",
                              "Urgent work starts at once.",
                              "Starvation of low priorities; more context switches.",
                              "Real-time or interactive systems with urgent tasks.", "O(n) per arrival/completion"),
}


# =====================================================================
#  Small utilities
# =====================================================================
def parse_int(text, name, lo, hi, default=None):
    """Convert text to an int in [lo, hi]; raise ValueError with a friendly message."""
    text = text.strip()
    if text == "" and default is not None:
        return default
    try:
        v = int(text)
    except ValueError:
        raise ValueError(f"{name} must be a whole number.") from None
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}.")
    return v


def parse_process_csv(text):
    """Read 'arrival,burst[,priority]' rows (optional header, optional leading
    process-name column). Returns a list of (at, bt, pr) tuples."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    out = []
    for n, row in enumerate(rows, 1):
        cells = [c.strip() for c in row]
        if n == 1 and not any(c.lstrip("-").isdigit() for c in cells):
            continue                                   # header row
        if len(cells) == 4:
            cells = cells[1:]                          # drop the process-name column
        if len(cells) not in (2, 3):
            raise ValueError(f"Row {n}: expected arrival, burst[, priority].")
        at = parse_int(cells[0], f"Row {n}: arrival", 0, MAX_TIME)
        bt = parse_int(cells[1], f"Row {n}: burst", 1, MAX_TIME)
        pr = parse_int(cells[2] if len(cells) > 2 else "", f"Row {n}: priority",
                       -MAX_PRIORITY, MAX_PRIORITY, default=0)
        out.append((at, bt, pr))
    if not out:
        raise ValueError("No process rows found in the file.")
    if len(out) > MAX_PROCS:
        raise ValueError(f"The file has {len(out)} processes; the maximum is {MAX_PROCS}.")
    return out


def parse_workspace(text):
    """Validate the JSON written by 'Save Workspace'. Returns a dict."""
    data = json.loads(text)                            # JSONDecodeError is a ValueError
    rows = data.get("processes") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("The file contains no processes.")
    if len(rows) > MAX_PROCS:
        raise ValueError(f"The file has {len(rows)} processes; the maximum is {MAX_PROCS}.")
    out = []
    for n, r in enumerate(rows, 1):
        if not isinstance(r, list) or len(r) != 3:
            raise ValueError(f"Process {n} must be [arrival, burst, priority].")
        out.append((parse_int(str(r[0]), f"Process {n}: arrival", 0, MAX_TIME),
                    parse_int(str(r[1]), f"Process {n}: burst", 1, MAX_TIME),
                    parse_int(str(r[2]), f"Process {n}: priority", -MAX_PRIORITY, MAX_PRIORITY)))
    algo = data.get("algorithm")
    return {"rows": out,
            "algorithm": algo if algo in ALGORITHMS else ALGORITHMS[0],
            "quantum": parse_int(str(data.get("quantum", 2)), "Quantum", 1, MAX_TIME),
            "lower": bool(data.get("lower_is_higher", True))}


def mix(c1, c2, f):
    """Blend hex colour c1 toward c2 by fraction f (0..1)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * f) for x, y in zip(a, b))


def process_colors(pids):
    """Fixed palette for the first 10 processes, evenly spaced hues after that."""
    colors = {}
    for i, pid in enumerate(pids):
        if i < len(PALETTE):
            colors[pid] = PALETTE[i]
        else:
            r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.55, 0.85)
            colors[pid] = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    return colors


def text_color(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "black" if 0.299 * r + 0.587 * g + 0.114 * b > 150 else "white"


# =====================================================================
#  Scheduling engine (no GUI code in here)
# =====================================================================
@dataclass
class Process:
    pid: str
    at: int                  # arrival time
    bt: int                  # burst time
    pr: int = 0              # priority
    rem: int = 0             # remaining burst time (while simulating)
    ct: int = 0              # completion time
    tat: int = 0             # turnaround time = CT - AT
    wt: int = 0              # waiting time    = TAT - BT
    rt: int = 0              # response time   = first CPU time - AT
    order: int = field(default=0, repr=False)   # entry order, used as tie-breaker


class CPUScheduler:
    """Every algorithm returns (processes, gantt).
    gantt is a list of (start, end, pid) segments; pid == 'Idle' for CPU gaps."""

    def __init__(self, processes, lower_is_higher=True):
        self.procs = copy.deepcopy(processes)
        for i, p in enumerate(self.procs):
            p.rem = p.bt
            p.order = i
        self.psign = 1 if lower_is_higher else -1   # flips the priority comparison

    # ---------- helpers ----------
    @staticmethod
    def _add(gantt, start, end, pid):
        """Append a segment, merging with the previous one if same process."""
        if end <= start:
            return
        if gantt and gantt[-1][2] == pid and gantt[-1][1] == start:
            gantt[-1] = (gantt[-1][0], end, pid)
        else:
            gantt.append((start, end, pid))

    def _finish(self, gantt):
        """Fill in TAT, WT and RT once every process has its completion time."""
        first = {}
        for s, _e, pid in gantt:
            if pid != IDLE:
                first.setdefault(pid, s)
        for p in self.procs:
            p.tat = p.ct - p.at
            p.wt = p.tat - p.bt
            p.rt = first[p.pid] - p.at
        return self.procs, gantt

    def _idle_until_next_arrival(self, t, gantt):
        nxt = min(p.at for p in self.procs if p.rem > 0)
        self._add(gantt, t, nxt, IDLE)
        return nxt

    # ---------- non-preemptive family: FCFS, SJF, Priority ----------
    # Pick the best ready process (smallest `key`) and let it run to completion.
    def _non_preemptive(self, key):
        t, gantt, done = 0, [], 0
        n = len(self.procs)
        while done < n:
            ready = [p for p in self.procs if p.rem > 0 and p.at <= t]
            if not ready:
                t = self._idle_until_next_arrival(t, gantt)
                continue
            p = min(ready, key=key)
            self._add(gantt, t, t + p.rem, p.pid)
            t += p.rem
            p.rem, p.ct = 0, t
            done += 1
        return self._finish(gantt)

    def fcfs(self):
        return self._non_preemptive(lambda p: (p.at, p.order))

    def sjf(self):
        return self._non_preemptive(lambda p: (p.bt, p.at, p.order))

    def priority_np(self):
        return self._non_preemptive(lambda p: (self.psign * p.pr, p.at, p.order))

    # ---------- preemptive family: SRTF, Priority ----------
    # Event-driven: the choice can only change when a process arrives or the
    # running one finishes, so we jump straight to the next event instead of
    # stepping 1 time unit at a time (same result, far faster).
    def _preemptive(self, key):
        t, gantt, done = 0, [], 0
        n = len(self.procs)
        while done < n:
            ready = [p for p in self.procs if p.rem > 0 and p.at <= t]
            if not ready:
                t = self._idle_until_next_arrival(t, gantt)
                continue
            p = min(ready, key=key)
            future = [q.at for q in self.procs if q.at > t]
            run = p.rem if not future else min(p.rem, min(future) - t)
            self._add(gantt, t, t + run, p.pid)
            t += run
            p.rem -= run
            if p.rem == 0:
                p.ct = t
                done += 1
        return self._finish(gantt)

    def srtf(self):
        return self._preemptive(lambda p: (p.rem, p.at, p.order))

    def priority_p(self):
        return self._preemptive(lambda p: (self.psign * p.pr, p.at, p.order))

    # ---------- Round Robin ----------
    def round_robin(self, quantum):
        if quantum < 1:
            raise ValueError("Time quantum must be at least 1.")
        t, gantt, done = 0, [], 0
        n = len(self.procs)
        pending = sorted(self.procs, key=lambda p: (p.at, p.order))
        queue, idx = [], 0

        def admit(upto):                       # move newly arrived processes into the queue
            nonlocal idx
            while idx < n and pending[idx].at <= upto:
                queue.append(pending[idx])
                idx += 1

        while done < n:
            admit(t)
            if not queue:                      # CPU idle until the next arrival
                self._add(gantt, t, pending[idx].at, IDLE)
                t = pending[idx].at
                continue
            p = queue.pop(0)
            run = min(quantum, p.rem)          # a short job may finish before the quantum ends
            self._add(gantt, t, t + run, p.pid)
            t += run
            p.rem -= run
            admit(t)                           # arrivals during the slice queue BEFORE the preempted process
            if p.rem > 0:
                queue.append(p)
            else:
                p.ct = t
                done += 1
        return self._finish(gantt)

    # ---------- dispatcher ----------
    def run(self, algo, quantum=2):
        return {
            ALGORITHMS[0]: self.fcfs,
            ALGORITHMS[1]: self.sjf,
            ALGORITHMS[2]: self.srtf,
            ALGORITHMS[3]: lambda: self.round_robin(quantum),
            ALGORITHMS[4]: self.priority_np,
            ALGORITHMS[5]: self.priority_p,
        }[algo]()

    @staticmethod
    def summarize(procs, gantt):
        """Overall metrics for one finished simulation."""
        n = len(procs)
        total = gantt[-1][1]
        busy = sum(e - s for s, e, pid in gantt if pid != IDLE)
        dispatches = sum(1 for _s, _e, pid in gantt if pid != IDLE)
        return {
            "total": total,
            "wt": sum(p.wt for p in procs) / n,
            "tat": sum(p.tat for p in procs) / n,
            "rt": sum(p.rt for p in procs) / n,
            "util": 100.0 * busy / total,
            "cs": dispatches - 1,
        }


# =====================================================================
#  Analysis helpers (pure functions: easy to test, no GUI)
# =====================================================================
def compare_rows(processes, lower, q):
    """Run every algorithm; rows = [(algo, avg_wt, avg_tat, avg_rt, context_switches)]."""
    rows = []
    for algo in ALGORITHMS:
        procs, gantt = CPUScheduler(processes, lower).run(algo, q)
        s = CPUScheduler.summarize(procs, gantt)
        rows.append((algo, s["wt"], s["tat"], s["rt"], s["cs"]))
    return rows


def recommend(rows):
    """Best algorithm = lowest average waiting time; ties go to fewer context switches."""
    return min(rows, key=lambda r: (round(r[1], 9), r[4], r[2]))


def sweep_quantum(processes, qmax):
    """Round Robin for q = 1..qmax -> [(q, avg_wt, avg_tat, context_switches)]."""
    out = []
    for q in range(1, qmax + 1):
        if sum(math.ceil(p.bt / q) for p in processes) > MAX_SLICES:
            continue
        procs, gantt = CPUScheduler(processes).round_robin(q)
        s = CPUScheduler.summarize(procs, gantt)
        out.append((q, s["wt"], s["tat"], s["cs"]))
    return out


def best_quantum(data):
    return min(data, key=lambda r: (round(r[1], 9), r[3]))


def build_events(procs, gantt):
    """Readable event list [(time, kind, text)] derived from a finished schedule."""
    by = {p.pid: p for p in procs}
    ran = {p.pid: 0 for p in procs}
    ev = [(p.at, "arrive", f"{p.pid} arrives (burst {p.bt}, priority {p.pr})") for p in procs]
    for s, e, pid in gantt:
        if pid == IDLE:
            ev.append((s, "idle", f"CPU is idle until t={e}"))
            continue
        p = by[pid]
        ev.append((s, "run", f"{pid} gets the CPU for {e - s} unit(s)"))
        ran[pid] += e - s
        if ran[pid] == p.bt:
            ev.append((e, "done", f"{pid} completes  (TAT {p.tat}, WT {p.wt}, RT {p.rt})"))
        else:
            ev.append((e, "preempt", f"{pid} is preempted, {p.bt - ran[pid]} unit(s) left"))
    order = {"done": 0, "preempt": 1, "arrive": 2, "idle": 3, "run": 4}
    ev.sort(key=lambda x: (x[0], order[x[1]]))
    return ev


def snapshot(procs, gantt, t):
    """State of the whole system at time t (the running segment satisfies s <= t < e)."""
    cur = next(((s, e, pid) for s, e, pid in gantt if s <= t < e), None)
    running = cur[2] if cur and cur[2] != IDLE else None
    ran = {p.pid: 0 for p in procs}
    nxt = {}
    for s, e, pid in gantt:
        if pid == IDLE:
            continue
        if s < t:
            ran[pid] += min(e, t) - s
        elif s > t and pid not in nxt:
            nxt[pid] = s                      # when this process will next get the CPU
    ready = sorted((p.pid for p in procs if p.at <= t and ran[p.pid] < p.bt and p.pid != running),
                   key=lambda pid: nxt.get(pid, math.inf))      # queue order = order of next dispatch
    by = {p.pid: p for p in procs}
    return {
        "running": running,
        "idle": cur is not None and cur[2] == IDLE,
        "finished": cur is None,
        "ready": ready,
        "incoming": sorted((p.pid for p in procs if p.at > t), key=lambda pid: by[pid].at),
        "done": sorted((p.pid for p in procs if ran[p.pid] >= p.bt), key=lambda pid: by[pid].ct, reverse=True),
        "ran": ran,
    }


# =====================================================================
#  Report / image helpers
# =====================================================================
def render_png(draw, size=(9, 3.2)):
    """Render a chart with the Light theme and return PNG bytes (print-friendly output)."""
    global T
    saved = T
    T = dict(THEMES["Light"])
    try:
        fig = Figure(figsize=size, dpi=130, layout="constrained")
        draw(fig.add_subplot(111))
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        T = saved


REPORT_CSS = ("body{font-family:Segoe UI,Arial,sans-serif;max-width:900px;margin:30px auto;color:#1b2430}"
              "h1{color:#0b3d91;margin-bottom:0}h2{color:#0b3d91;border-bottom:2px solid #dde5f0;padding-bottom:4px}"
              "table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border:1px solid #cfd8e3;"
              "padding:6px 10px;text-align:center}th{background:#e8eef8}tr.best td{background:#d6f5d6;font-weight:600}"
              ".meta{color:#5d6b7e}.cards span{display:inline-block;background:#eef3fb;border-radius:8px;"
              "padding:8px 14px;margin:4px 6px 4px 0}img{max-width:100%}")


def build_report_html(algo, procs, gantt, rows, q, lower, gantt_png):
    """One self-contained HTML page (chart embedded as base64) for submission or printing."""
    esc = html.escape
    s = CPUScheduler.summarize(procs, gantt)
    best = recommend(rows)

    def tr(cells, cls=""):
        tag = "th" if cls == "head" else "td"
        c = f' class="{cls}"' if cls not in ("", "head") else ""
        return f"<tr{c}>" + "".join(f"<{tag}>{esc(str(x))}</{tag}>" for x in cells) + "</tr>"

    res = tr(["Process", "AT", "BT", "Priority", "CT", "TAT", "WT", "RT"], "head") + "".join(
        tr([p.pid, p.at, p.bt, p.pr, p.ct, p.tat, p.wt, p.rt]) for p in procs)
    cmp_ = tr(["Algorithm", "Avg WT", "Avg TAT", "Avg RT", "Context switches"], "head") + "".join(
        tr([a, f"{w:.2f}", f"{t:.2f}", f"{r:.2f}", cs], "best" if a == best[0] else "")
        for a, w, t, r, cs in rows)
    settings = f"Round Robin quantum = {q} &nbsp;|&nbsp; Priority: {'lower' if lower else 'higher'} number = higher priority"
    img = base64.b64encode(gantt_png).decode("ascii")
    now = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    cards = "".join(f"<span><b>{k}</b><br>{v}</span>" for k, v in (
        ("Total time", s["total"]), ("Avg waiting", f"{s['wt']:.2f}"), ("Avg turnaround", f"{s['tat']:.2f}"),
        ("Avg response", f"{s['rt']:.2f}"), ("CPU utilization", f"{s['util']:.1f}%"), ("Context switches", s["cs"])))
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>CPU Scheduling Report</title>"
            f"<style>{REPORT_CSS}</style></head><body>"
            f"<h1>CPU Scheduling Simulation Report</h1><p class='meta'>Generated {now} &nbsp;|&nbsp; "
            f"Algorithm: <b>{esc(algo)}</b><br>{settings}</p>"
            f"<h2>Summary</h2><div class='cards'>{cards}</div>"
            f"<h2>Gantt chart</h2><img alt='Gantt chart' src='data:image/png;base64,{img}'>"
            f"<h2>Per-process results</h2><table>{res}</table>"
            f"<h2>Algorithm comparison</h2><table>{cmp_}</table>"
            f"<p><b>Recommendation:</b> {esc(best[0])} gives the lowest average waiting time "
            f"({best[1]:.2f}) for this workload.</p>"
            f"<p class='meta'>TAT = CT - AT &nbsp; WT = TAT - BT &nbsp; RT = first CPU time - AT</p></body></html>")


# =====================================================================
#  Drawing helpers: matplotlib charts (testable without a window)
# =====================================================================
def style_axes(ax, hide=("top", "right")):
    """Apply the active theme to an axes (colours, spines, ticks)."""
    ax.figure.set_facecolor(T["panel"])
    ax.set_facecolor(T["panel"])
    ax.tick_params(colors=T["muted"], labelsize=8)
    for obj in (ax.xaxis.label, ax.yaxis.label, ax.title):
        obj.set_color(T["fg"])
    for name, sp in ax.spines.items():
        sp.set_visible(name not in hide)
        sp.set_color(T["grid"])


def themed_legend(ax, **kw):
    leg = ax.legend(frameon=False, **kw)
    for txt in leg.get_texts():
        txt.set_color(T["fg"])
    return leg


def draw_gantt(ax, pids, gantt, title, upto=None):
    """Draw the Gantt chart. If `upto` is given, draw only the first `upto` time units
    (used by the animation) but keep the full time axis."""
    ax.clear()
    colors = process_colors(pids)
    total = gantt[-1][1]
    shown = gantt if upto is None else [(s, min(e, upto), pid) for s, e, pid in gantt if s < upto]
    face = [T["idle"] if pid == IDLE else colors[pid] for _, _, pid in shown]
    ax.broken_barh([(s, e - s) for s, e, _ in shown], (-0.3, 0.6),
                   facecolors=face, edgecolors=T["panel"], linewidth=1.5)
    if len(shown) <= 300:                       # skip labels when there are thousands of slices
        for (s, e, pid), bg in zip(shown, face):
            if (e - s) / total >= 0.04:         # only label segments wide enough to hold text
                ax.text((s + e) / 2, 0, pid, ha="center", va="center", fontsize=9,
                        fontweight="bold", color=text_color(bg))
    if upto is not None and upto < total:       # moving "now" marker during the animation
        ax.axvline(upto, color=T["fg"], linewidth=1.2, linestyle="--")

    bounds = sorted({s for s, _, _ in gantt} | {total})
    if len(bounds) <= 25:
        ax.set_xticks(bounds)
    else:
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=20))
    ax.set_xlim(0, total)
    ax.set_ylim(-0.6, 0.6)
    ax.set_yticks([])
    ax.set_xlabel("Time")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="x", color=T["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    style_axes(ax, hide=("top", "right", "left"))

    handles = [Patch(facecolor=colors[pid], label=pid) for pid in pids]
    if any(pid == IDLE for _, _, pid in gantt):
        handles.append(Patch(facecolor=T["idle"], label=IDLE))
    themed_legend(ax, handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.30),
                  ncol=min(len(handles), 10), fontsize=8)


def draw_swimlane(ax, procs, gantt, title):
    """One lane per process: thin line = lifetime (waiting), thick blocks = running."""
    ax.clear()
    colors = process_colors([p.pid for p in procs])
    total = gantt[-1][1]
    n = len(procs)
    for i, p in enumerate(procs):
        ax.barh(i, p.ct - p.at, left=p.at, height=0.14, color=T["idle"])
        segs = [(s, e - s) for s, e, pid in gantt if pid == p.pid]
        ax.broken_barh(segs, (i - 0.3, 0.6), facecolors=colors[p.pid], edgecolors=T["panel"], linewidth=1)
        ax.plot([p.at], [i - 0.42], marker="v", color=T["fg"], ms=4, zorder=3)
        ax.plot([p.ct], [i + 0.42], marker="s", color=T["fg"], ms=3.5, zorder=3)
        if n <= 20:
            ax.text(p.ct + total * 0.012, i, f"WT {p.wt}", va="center", fontsize=7, color=T["muted"])
    ax.set_yticks(range(n))
    ax.set_yticklabels([p.pid for p in procs], fontsize=8 if n <= 15 else 6)
    ax.set_ylim(n - 0.4, -0.8)
    ax.set_xlim(0, total * 1.1 if n <= 20 else total)
    ax.set_xlabel("Time      \u25BC arrival      \u2588 running      \u2500 waiting / lifetime      \u25A0 completed")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="x", color=T["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    style_axes(ax)


def draw_empty_gantt(ax, message="Run a simulation to see the Gantt chart", title="Gantt Chart"):
    ax.clear()
    ax.set_xticks([])
    ax.set_yticks([])
    ax.text(0.5, 0.5, message, ha="center", va="center", color=T["muted"],
            transform=ax.transAxes, fontsize=11)
    ax.set_title(title, fontsize=11, fontweight="bold")
    style_axes(ax, hide=("top", "right", "left", "bottom"))


def draw_compare(ax, rows):
    """Grouped bars: average waiting, turnaround and response time per algorithm.
    rows = [(algo, avg_wt, avg_tat, avg_rt, ...), ...]"""
    ax.clear()
    y = list(range(len(rows)))
    h = 0.26
    for k, (idx, label) in enumerate(((1, "Avg waiting"), (2, "Avg turnaround"), (3, "Avg response"))):
        bars = ax.barh([i + (k - 1) * h for i in y], [r[idx] for r in rows], height=h,
                       color=PALETTE[k], label=label)
        ax.bar_label(bars, fmt="%.1f", fontsize=7, padding=2, color=T["fg"])
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8)
    ax.invert_yaxis()
    ax.margins(x=0.12)
    ax.set_xlabel("Time units (lower is better)", fontsize=9)
    ax.grid(axis="x", color=T["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    style_axes(ax)
    themed_legend(ax, fontsize=8, loc="lower right")


def draw_quantum(fig, data, current_q=None):
    """Quantum Lab: waiting/turnaround vs quantum (top) and context switches (bottom)."""
    fig.clear()
    fig.set_facecolor(T["panel"])
    if not data:
        fig.text(0.5, 0.5, "Add processes to sweep the Round Robin time quantum",
                 ha="center", va="center", color=T["muted"], fontsize=11)
        return
    ax1, ax2 = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    qs = [r[0] for r in data]
    ax1.plot(qs, [r[1] for r in data], marker="o", ms=4, color=PALETTE[0], label="Avg waiting")
    ax1.plot(qs, [r[2] for r in data], marker="s", ms=4, color=PALETTE[1], label="Avg turnaround")
    best = best_quantum(data)
    ax1.axvline(best[0], color=PALETTE[4], linestyle="--", linewidth=1.2, label=f"Best q = {best[0]}")
    if current_q in qs:
        ax1.axvline(current_q, color=T["muted"], linestyle=":", linewidth=1.4, label=f"Current q = {current_q}")
    ax1.set_ylabel("Time units")
    ax1.set_title("Round Robin: effect of the time quantum", fontsize=11, fontweight="bold")
    ax2.bar(qs, [r[3] for r in data], color=PALETTE[3])
    ax2.set_ylabel("Context\nswitches")
    ax2.set_xlabel("Time quantum")
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
    for ax in (ax1, ax2):
        ax.grid(axis="y", color=T["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        style_axes(ax)
    themed_legend(ax1, fontsize=8, loc="best")


# =====================================================================
#  Drawing helpers: the animated "inside the computer" scene (tk.Canvas)
# =====================================================================
def round_rect(c, x1, y1, x2, y2, r=10, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def draw_cards(c, ff, pids, box, colors, sub, rtl=False):
    """Draw process cards in a wrapping grid inside box; extra cards become '+N'."""
    x1, y1, x2, y2 = box
    cw, ch, gap = 58, 40, 6
    cols = max(1, int((x2 - x1 + gap) // (cw + gap)))
    rows = max(1, int((y2 - y1 + gap) // (ch + gap)))
    cap = cols * rows
    shown = pids if len(pids) <= cap else pids[:cap - 1]

    def slot(i):
        r, col = divmod(i, cols)
        x = (x2 - cw - col * (cw + gap)) if rtl else (x1 + col * (cw + gap))
        return x, y1 + r * (ch + gap)

    for i, pid in enumerate(shown):
        x, y = slot(i)
        fill = colors[pid]
        round_rect(c, x, y, x + cw, y + ch, 8, fill=fill, outline=mix(fill, "#000000", 0.35))
        fg = text_color(fill)
        c.create_text(x + cw / 2, y + 14, text=pid, fill=fg, font=(ff, 10, "bold"))
        c.create_text(x + cw / 2, y + 29, text=sub(pid), fill=fg, font=(ff, 8))
    if len(shown) < len(pids):
        x, y = slot(len(shown))
        c.create_text(x + cw / 2, y + ch / 2, text=f"+{len(pids) - len(shown)}", fill=T["muted"],
                      font=(ff, 11, "bold"))


def draw_live_scene(c, w, h, ff, procs, gantt, events, t):
    """Pipeline view: NEW -> READY QUEUE -> CPU -> TERMINATED, plus a Gantt strip with a playhead."""
    c.delete("all")
    c.configure(bg=T["canvas"])
    if w < 300 or h < 200:
        return
    if not procs:
        c.create_text(w / 2, h / 2, text="Run a simulation to watch processes move through the CPU",
                      fill=T["muted"], font=(ff, 12))
        return
    snap = snapshot(procs, gantt, t)
    colors = process_colors([p.pid for p in procs])
    by = {p.pid: p for p in procs}
    total = gantt[-1][1]
    m, top, bot = 12, 30, h - 74
    zones = [("NEW  (not arrived)", m, int(w * 0.21)),
             ("READY QUEUE  (front \u2192)", int(w * 0.23), int(w * 0.56)),
             ("CPU", int(w * 0.58), int(w * 0.79)),
             ("TERMINATED", int(w * 0.81), w - m)]
    for title, x1, x2 in zones:
        c.create_text(x1 + 4, 15, text=title, anchor="w", fill=T["muted"], font=(ff, 9, "bold"))
        round_rect(c, x1, top, x2, bot, 12, fill=T["zone"], outline=T["zone_edge"])
    ymid = (top + bot) / 2
    for a, b in ((zones[0][2], zones[1][1]), (zones[1][2], zones[2][1]), (zones[2][2], zones[3][1])):
        c.create_line(a + 2, ymid, b - 2, ymid, arrow="last", fill=T["muted"], width=2)

    def box(zone):
        return zone[1] + 10, top + 12, zone[2] - 10, bot - 10

    rem = lambda pid: by[pid].bt - snap["ran"][pid]
    draw_cards(c, ff, snap["incoming"], box(zones[0]), colors, lambda pid: f"AT {by[pid].at}")
    draw_cards(c, ff, snap["ready"], box(zones[1]), colors, lambda pid: f"{rem(pid)}/{by[pid].bt}", rtl=True)
    draw_cards(c, ff, snap["done"], box(zones[3]), colors, lambda pid: f"CT {by[pid].ct}")

    # ----- the CPU chip -----
    cx, cy = (zones[2][1] + zones[2][2]) / 2, ymid + 4
    hw = min((zones[2][2] - zones[2][1]) / 2 - 16, 80)
    hh = min((bot - top) / 2 - 22, 80)
    run = snap["running"]
    col = colors[run] if run else None
    if run:                                              # glow rings
        for i, f in enumerate((0.8, 0.55, 0.3), start=1):
            d = 3 * i
            round_rect(c, cx - hw - d, cy - hh - d, cx + hw + d, cy + hh + d, 14,
                       fill="", outline=mix(col, T["zone"], f), width=2)
    for k in range(1, 7):                                # pins
        px, py = cx - hw + k * 2 * hw / 7, cy - hh + k * 2 * hh / 7
        c.create_line(px, cy - hh - 8, px, cy - hh, fill=T["pin"], width=3)
        c.create_line(px, cy + hh, px, cy + hh + 8, fill=T["pin"], width=3)
        c.create_line(cx - hw - 8, py, cx - hw, py, fill=T["pin"], width=3)
        c.create_line(cx + hw, py, cx + hw + 8, py, fill=T["pin"], width=3)
    round_rect(c, cx - hw, cy - hh, cx + hw, cy + hh, 12, fill=T["chip"], outline=T["chip_edge"], width=2)
    c.create_text(cx, cy - hh + 10, text="CPU CORE", fill="#9aa7b8", font=(ff, 7, "bold"))
    dx1, dy1, dx2, dy2 = cx - hw + 12, cy - hh + 20, cx + hw - 12, cy + hh - 24
    die_fill = col if run else ("#0f131a" if snap["idle"] or snap["finished"] else T["idle"])
    round_rect(c, dx1, dy1, dx2, dy2, 6, fill=die_fill, outline=T["chip_edge"])
    dcy = (dy1 + dy2) / 2
    if run:
        fg = text_color(col)
        c.create_text(cx, dcy - 6, text=run, fill=fg, font=(ff, 16, "bold"))
        c.create_text(cx, dcy + 11, text=f"{rem(run)} left", fill=fg, font=(ff, 8))
        frac = snap["ran"][run] / by[run].bt
        c.create_rectangle(dx1, dy2 + 6, dx2, dy2 + 14, fill="#0f131a", outline="")
        c.create_rectangle(dx1, dy2 + 6, dx1 + (dx2 - dx1) * frac, dy2 + 14, fill=col, outline="")
    else:
        word, note = ("DONE", "all finished") if snap["finished"] else ("IDLE", "no ready process")
        c.create_text(cx, dcy - 6, text=word, fill="#9aa7b8", font=(ff, 14, "bold"))
        c.create_text(cx, dcy + 11, text=note, fill="#6b778a", font=(ff, 8))

    # ----- bottom: latest event, clock, Gantt strip with playhead -----
    last = None
    for ev in events or []:
        if ev[0] <= t:
            last = ev
        else:
            break
    if last:
        c.create_text(m + 2, bot + 16, anchor="w", text=f"t={last[0]}:  {last[2]}",
                      fill=KIND_COLOR[last[1]], font=(ff, 10, "bold"))
    c.create_text(w - m, bot + 16, anchor="e", text=f"clock  t = {t}", fill=T["accent"], font=(ff, 12, "bold"))
    sy1, sy2, x0, x1 = bot + 36, bot + 56, m, w - m
    X = lambda v: x0 + (x1 - x0) * v / total
    for s, e, pid in gantt:
        base = T["idle"] if pid == IDLE else colors[pid]
        dim = mix(base, T["canvas"], 0.7)
        parts = [(s, e, base)] if e <= t else [(s, e, dim)] if s >= t else [(s, t, base), (t, e, dim)]
        for a, b, fill in parts:
            c.create_rectangle(X(a), sy1, max(X(b), X(a) + 1), sy2, fill=fill, outline=T["canvas"])
    px = X(t)
    c.create_line(px, sy1 - 5, px, sy2 + 5, fill=T["fg"], width=2)
    c.create_polygon(px - 5, sy1 - 12, px + 5, sy1 - 12, px, sy1 - 5, fill=T["fg"], outline="")
    c.create_text(x0, sy2 + 10, text="0", anchor="w", fill=T["muted"], font=(ff, 8))
    c.create_text(x1, sy2 + 10, text=str(total), anchor="e", fill=T["muted"], font=(ff, 8))


class LiveView(ttk.Frame if HAS_TK else object):
    """Canvas + playback controls around draw_live_scene()."""

    def __init__(self, master, font_family):
        super().__init__(master)
        self.ff = font_family
        self.procs = self.gantt = self.events = None
        self.t, self.times, self.step_size, self.job, self._lock = 0, [0], 1, None, False
        self.canvas = tk.Canvas(self, highlightthickness=0, height=280)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(4, 2))
        ttk.Button(bar, text="Reset", width=7, command=self.reset).pack(side="left", padx=2)
        ttk.Button(bar, text="\u25C0 Step", width=8, command=lambda: self.step(-1)).pack(side="left", padx=2)
        self.play_btn = ttk.Button(bar, text="\u25B6 Play", width=9, command=self.toggle)
        self.play_btn.pack(side="left", padx=2)
        ttk.Button(bar, text="Step \u25B6", width=8, command=lambda: self.step(1)).pack(side="left", padx=2)
        ttk.Label(bar, text="Speed").pack(side="left", padx=(12, 2))
        self.speed = tk.DoubleVar(value=5)
        ttk.Scale(bar, from_=1, to=20, variable=self.speed, length=100).pack(side="left")
        self.time_var = tk.StringVar(value="t = 0")
        ttk.Label(bar, textvariable=self.time_var, width=14, anchor="e").pack(side="right", padx=4)
        self.scrub = ttk.Scale(bar, from_=0, to=1, command=self._on_scrub)
        self.scrub.pack(side="left", fill="x", expand=True, padx=10)

    @property
    def total(self):
        return self.gantt[-1][1] if self.gantt else 0

    def set_data(self, procs, gantt, events):
        self.pause()
        self.procs, self.gantt, self.events = procs, gantt, events
        total = self.total
        self.times = sorted({0, total} | {x for s, e, _ in gantt for x in (s, e)}
                            | {p.at for p in procs if p.at <= total})
        self.step_size = max(1, math.ceil(total / 150))
        self._lock = True
        self.scrub.configure(to=max(1, total))
        self._lock = False
        self.t = 0
        self._sync()
        self.redraw()

    def clear(self):
        self.pause()
        self.procs = self.gantt = self.events = None
        self.t = 0
        self._sync()
        self.redraw()

    def _sync(self):
        self._lock = True
        self.scrub.set(self.t)
        self._lock = False
        self.time_var.set(f"t = {self.t} / {self.total}")

    def redraw(self):
        draw_live_scene(self.canvas, self.canvas.winfo_width(), self.canvas.winfo_height(), self.ff,
                        self.procs, self.gantt, self.events, self.t)

    def _on_scrub(self, value):
        if self._lock or not self.procs:
            return
        self.pause()
        self.t = int(round(float(value)))
        self.time_var.set(f"t = {self.t} / {self.total}")
        self.redraw()

    def toggle(self):
        if self.job is not None:
            self.pause()
            return
        if not self.procs:
            return
        if self.t >= self.total:
            self.t = 0
        self.play_btn.configure(text="Pause")
        self._tick()

    def _tick(self):
        self.t = min(self.total, self.t + self.step_size)
        self._sync()
        self.redraw()
        if self.t >= self.total:
            self.pause()
        else:
            self.job = self.after(max(25, int(1000 / self.speed.get())), self._tick)

    def pause(self):
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.play_btn.configure(text="\u25B6 Play")

    def step(self, direction):
        """Jump to the next / previous interesting moment (arrival, dispatch, preemption, completion)."""
        if not self.procs:
            return
        self.pause()
        if direction > 0:
            later = [x for x in self.times if x > self.t]
            self.t = later[0] if later else self.t
        else:
            earlier = [x for x in self.times if x < self.t]
            self.t = earlier[-1] if earlier else 0
        self._sync()
        self.redraw()

    def reset(self):
        self.pause()
        self.t = 0
        self._sync()
        self.redraw()


# =====================================================================
#  Main window
# =====================================================================
class SchedulerGUI:
    SAMPLE = [("P1", 0, 8, 3), ("P2", 1, 4, 1), ("P3", 2, 9, 4), ("P4", 3, 5, 2), ("P5", 12, 3, 1)]
    RESULT_COLS = ("pid", "at", "bt", "pr", "ct", "tat", "wt", "rt")
    RESULT_HEADS = ("Process", "AT", "BT", "Priority", "CT", "TAT", "WT", "RT")

    def __init__(self, root):
        self.root = root
        root.title("CPU Scheduling Algorithm Simulator")
        root.geometry("1280x880")
        root.minsize(1100, 740)
        self.processes = []
        self.counter = 1
        self.has_result = False
        self.last = None            # (algo, processes, gantt) of the latest successful run
        self.cmp_win = None
        self.anim_job = None        # id of the pending Gantt-animation frame, if any
        self.qdata = None           # latest quantum-sweep data
        self.theme_name = "Dark"
        self.style = ttk.Style(root)
        self.style.theme_use("clam")          # 'clam' honours custom colours on every OS
        base = tkfont.nametofont("TkDefaultFont")
        self.ff = base.actual("family")
        size = base.cget("size") or 10
        self.font_big = base.copy()
        self.font_big.configure(size=int(size * 1.5), weight="bold")
        self.font_bold = base.copy()
        self.font_bold.configure(weight="bold")
        self._build_header()
        self._build_controls()
        self._build_status()                  # packed before the body so it is never squeezed out
        self._build_body()
        self._apply_theme("Dark")
        root.bind("<F5>", lambda e: self.run_selected())
        self.at_entry.focus_set()
        self._set_status("Add processes (or load the sample data), pick an algorithm, then press Run (F5).")

    # ---------- theme ----------
    def _apply_theme(self, name):
        set_theme(name)
        self.theme_name = name
        st = self.style
        self.root.configure(bg=T["bg"])
        st.configure(".", background=T["bg"], foreground=T["fg"], fieldbackground=T["entry"],
                     bordercolor=T["zone_edge"], lightcolor=T["bg"], darkcolor=T["bg"],
                     troughcolor=T["panel2"], focuscolor=T["accent"], insertcolor=T["fg"])
        st.configure("TLabelframe", background=T["bg"], bordercolor=T["zone_edge"])
        st.configure("TLabelframe.Label", background=T["bg"], foreground=T["accent"], font=self.font_bold)
        st.configure("TButton", background=T["panel2"], foreground=T["fg"], padding=(10, 4))
        st.map("TButton", background=[("active", T["sel"])])
        st.configure("Accent.TButton", background=T["accent"], foreground=T["accent_fg"], font=self.font_bold)
        st.map("Accent.TButton", background=[("active", mix(T["accent"], "#ffffff", 0.2))])
        st.configure("TCombobox", background=T["panel2"], arrowcolor=T["fg"])
        st.map("TCombobox", fieldbackground=[("readonly", T["entry"])], foreground=[("readonly", T["fg"])],
               selectbackground=[("readonly", T["entry"])], selectforeground=[("readonly", T["fg"])])
        for opt, key in (("background", "entry"), ("foreground", "fg"),
                         ("selectBackground", "sel"), ("selectForeground", "fg")):
            self.root.option_add(f"*TCombobox*Listbox.{opt}", T[key])
        st.map("TCheckbutton", background=[("active", T["bg"])])
        st.configure("TNotebook", background=T["bg"], bordercolor=T["zone_edge"])
        st.configure("TNotebook.Tab", background=T["panel2"], foreground=T["muted"], padding=(12, 5))
        st.map("TNotebook.Tab", background=[("selected", T["panel"])], foreground=[("selected", T["accent"])])
        st.configure("Treeview", background=T["panel"], fieldbackground=T["panel"], foreground=T["fg"],
                     rowheight=24, borderwidth=0)
        st.map("Treeview", background=[("selected", T["sel"])], foreground=[("selected", T["fg"])])
        st.configure("Treeview.Heading", background=T["panel2"], foreground=T["fg"], font=self.font_bold,
                     relief="flat")
        st.configure("TScrollbar", background=T["panel2"], troughcolor=T["bg"], arrowcolor=T["fg"])
        st.configure("Stat.TLabel", font=self.font_big, foreground=T["accent"])
        st.configure("Err.TLabel", foreground=T["err"])
        st.configure("Info.TLabel", foreground=T["muted"])
        for tree in (self.tree, self.res_tree):
            tree.tag_configure("odd", background=T["stripe"])
        self.res_tree.tag_configure("avg", background=T["panel2"], foreground=T["accent"], font=self.font_bold)
        for txt in (self.log, self.guide):
            txt.configure(bg=T["panel"], fg=T["fg"], insertbackground=T["fg"], selectbackground=T["sel"])
        self.log.tag_configure("time", foreground=T["muted"])
        for kind, colr in KIND_COLOR.items():
            self.log.tag_configure(kind, foreground=colr)
        self.guide.tag_configure("h1", foreground=T["accent"], font=(self.ff, 13, "bold"))
        self.guide.tag_configure("h2", foreground=T["accent"], font=self.font_bold)
        self.guide.tag_configure("good", foreground=KIND_COLOR["done"], font=self.font_bold)
        self.theme_btn.configure(text="Light Mode" if name == "Dark" else "Dark Mode")
        self._draw_header()
        self._draw_charts()
        self._draw_quantum()
        self.live.redraw()
        self._update_guide()

    def toggle_theme(self):
        self._apply_theme("Light" if self.theme_name == "Dark" else "Dark")

    # ---------- layout ----------
    def _build_header(self):
        self.header = tk.Canvas(self.root, height=58, highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", lambda e: self._draw_header())

    def _draw_header(self):
        c, w = self.header, self.header.winfo_width()
        c.delete("all")
        n = 80
        for i in range(n):                                    # horizontal gradient
            c.create_rectangle(i * w / n, 0, (i + 1) * w / n + 1, 58, outline="",
                               fill=mix(T["head1"], T["head2"], i / (n - 1)))
        x0, y0 = 20, 11                                       # little CPU icon
        for k in range(4):
            c.create_line(x0 + 7 + k * 9, y0 - 4, x0 + 7 + k * 9, y0, fill=T["pin"], width=2)
            c.create_line(x0 + 7 + k * 9, y0 + 36, x0 + 7 + k * 9, y0 + 40, fill=T["pin"], width=2)
            c.create_line(x0 - 4, y0 + 7 + k * 9, x0, y0 + 7 + k * 9, fill=T["pin"], width=2)
            c.create_line(x0 + 36, y0 + 7 + k * 9, x0 + 40, y0 + 7 + k * 9, fill=T["pin"], width=2)
        c.create_rectangle(x0, y0, x0 + 36, y0 + 36, fill="#1b2430", outline="#cfd8e3", width=2)
        c.create_rectangle(x0 + 9, y0 + 9, x0 + 27, y0 + 27, fill="#4ea1ff", outline="")
        c.create_text(74, 21, anchor="w", text="CPU Scheduling Simulator", fill="white", font=(self.ff, 17, "bold"))
        c.create_text(76, 43, anchor="w", fill="#d6e6ff", font=(self.ff, 9),
                      text="FCFS  \u2022  SJF  \u2022  SRTF  \u2022  Round Robin  \u2022  Priority      "
                           "B25CS0311 Portfolio Building  \u2013  Hackathon Abhinava")

    def _build_controls(self):
        bar = ttk.LabelFrame(self.root, text=" Simulation ", padding=8)
        bar.pack(fill="x", padx=10, pady=(8, 4))

        ttk.Label(bar, text="Algorithm").grid(row=0, column=0, padx=(4, 4))
        self.algo_var = tk.StringVar(value=ALGORITHMS[0])
        cb = ttk.Combobox(bar, textvariable=self.algo_var, values=ALGORITHMS, state="readonly", width=26)
        cb.grid(row=0, column=1, padx=(0, 14))
        cb.bind("<<ComboboxSelected>>", self._on_algo_change)

        ttk.Label(bar, text="Time quantum (Round Robin)").grid(row=0, column=2, padx=(0, 4))
        self.q_var = tk.StringVar(value="2")
        self.q_entry = ttk.Entry(bar, textvariable=self.q_var, width=6)
        self.q_entry.grid(row=0, column=3, padx=(0, 14))
        self.q_entry.bind("<Return>", lambda e: self.run_selected())

        self.lower_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Lower number = higher priority", variable=self.lower_var,
                        command=self._on_option_change).grid(row=0, column=4, padx=(0, 14))

        acts = ttk.Frame(bar)
        acts.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(acts, text="\u25B6  Run Simulation", style="Accent.TButton",
                   command=self.run_selected).pack(side="left", padx=(4, 6))
        self.anim_btn = ttk.Button(acts, text="\u25B6  Animate Gantt", command=self.animate)
        self.anim_btn.pack(side="left", padx=4)
        for txt, cmd in (("Compare All", self.compare_all), ("Save Chart (PNG)", self.save_png),
                         ("Export Results (CSV)", self.export_csv), ("HTML Report", self.export_report)):
            ttk.Button(acts, text=txt, command=cmd).pack(side="left", padx=4)
        self.theme_btn = ttk.Button(acts, text="Light Mode", command=self.toggle_theme)
        self.theme_btn.pack(side="left", padx=(16, 4))

    def _build_body(self):
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=10, pady=4)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # ----- left: processes -----
        left = ttk.LabelFrame(body, text=" Processes ", padding=8)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        form = ttk.Frame(left)
        form.pack(fill="x")
        self.at_var, self.bt_var, self.pr_var = tk.StringVar(), tk.StringVar(), tk.StringVar(value="0")
        entries = []
        for i, (lbl, var) in enumerate([("Arrival", self.at_var), ("Burst", self.bt_var),
                                        ("Priority", self.pr_var)]):
            ttk.Label(form, text=lbl).grid(row=0, column=i, sticky="w", padx=2)
            e = ttk.Entry(form, textvariable=var, width=8)
            e.grid(row=1, column=i, padx=2, pady=(0, 4))
            e.bind("<Return>", lambda ev: self.add_process())
            entries.append(e)
        self.at_entry = entries[0]
        ttk.Button(form, text="Add", command=self.add_process).grid(row=1, column=3, padx=(6, 0), pady=(0, 4))

        tbl = ttk.Frame(left)
        tbl.pack(fill="both", expand=True, pady=(4, 6))
        self.tree = ttk.Treeview(tbl, columns=("pid", "at", "bt", "pr"), show="headings",
                                 height=12, selectmode="extended")
        for c, h in zip(("pid", "at", "bt", "pr"), ("Process", "AT", "BT", "Priority")):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=78, anchor="center")
        sb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        btns = ttk.Frame(left)
        btns.pack(fill="x")
        for i, (txt, cmd) in enumerate([("Delete Selected", self.delete_selected), ("Clear All", self.clear_all),
                                        ("Load Sample", self.load_sample), ("Random Set", self.random_set),
                                        ("Import CSV", self.import_csv), ("Save Workspace", self.save_workspace),
                                        ("Load Workspace", self.load_workspace)]):
            ttk.Button(btns, text=txt, command=cmd).grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="ew")

        # ----- right: stats + tabs + results -----
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=4)
        right.rowconfigure(2, weight=2)

        stats = ttk.Frame(right)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.stat_vars = {}
        for i, (key, title) in enumerate([("total", "Total Time"), ("wt", "Avg Waiting"),
                                          ("tat", "Avg Turnaround"), ("rt", "Avg Response"),
                                          ("util", "CPU Utilization"), ("cs", "Context Switches")]):
            stats.columnconfigure(i, weight=1, uniform="stat")
            card = ttk.LabelFrame(stats, text=f" {title} ", padding=(8, 2))
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            self.stat_vars[key] = tk.StringVar(value="\u2014")
            ttk.Label(card, textvariable=self.stat_vars[key], style="Stat.TLabel").pack()

        self.nb = ttk.Notebook(right)
        self.nb.grid(row=1, column=0, sticky="nsew")
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_tab())

        tab = ttk.Frame(self.nb)                                     # 1) Gantt chart
        self.nb.add(tab, text="  Gantt Chart  ")
        self.fig = Figure(figsize=(7, 3.2), dpi=100, layout="constrained")
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=tab)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.live = LiveView(self.nb, self.ff)                       # 2) live CPU
        self.nb.add(self.live, text="  Live CPU  ")

        tab = ttk.Frame(self.nb)                                     # 3) process timeline
        self.nb.add(tab, text="  Process Timeline  ")
        self.fig_tl = Figure(figsize=(7, 3.2), dpi=100, layout="constrained")
        self.ax_tl = self.fig_tl.add_subplot(111)
        self.canvas_tl = FigureCanvasTkAgg(self.fig_tl, master=tab)
        self.canvas_tl.get_tk_widget().pack(fill="both", expand=True)

        tab = ttk.Frame(self.nb)                                     # 4) event log
        self.nb.add(tab, text="  Event Log  ")
        self.log = self._make_text(tab, ("Consolas", 10))

        tab = ttk.Frame(self.nb)                                     # 5) quantum lab
        self.nb.add(tab, text="  Quantum Lab  ")
        qbar = ttk.Frame(tab)
        qbar.pack(fill="x", padx=6, pady=4)
        ttk.Label(qbar, text="Sweep quantum 1 to").pack(side="left")
        self.qmax_var = tk.StringVar(value="10")
        qe = ttk.Entry(qbar, textvariable=self.qmax_var, width=5)
        qe.pack(side="left", padx=4)
        qe.bind("<Return>", lambda e: self._update_quantum_lab())
        ttk.Button(qbar, text="Run Sweep", command=self._update_quantum_lab).pack(side="left", padx=4)
        self.qbest_var = tk.StringVar()
        ttk.Label(qbar, textvariable=self.qbest_var, style="Info.TLabel").pack(side="left", padx=10)
        self.fig_q = Figure(figsize=(7, 3.0), dpi=100, layout="constrained")
        self.canvas_q = FigureCanvasTkAgg(self.fig_q, master=tab)
        self.canvas_q.get_tk_widget().pack(fill="both", expand=True)

        tab = ttk.Frame(self.nb)                                     # 6) algorithm guide
        self.nb.add(tab, text="  Algorithm Guide  ")
        self.guide = self._make_text(tab, (self.ff, 10))

        res = ttk.LabelFrame(right, text=" Results ", padding=6)
        res.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self.res_tree = ttk.Treeview(res, columns=self.RESULT_COLS, show="headings", height=5)
        for c, h in zip(self.RESULT_COLS, self.RESULT_HEADS):
            self.res_tree.heading(c, text=h)
            self.res_tree.column(c, width=70, anchor="center")
        rsb = ttk.Scrollbar(res, orient="vertical", command=self.res_tree.yview)
        self.res_tree.configure(yscrollcommand=rsb.set)
        self.res_tree.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")

    @staticmethod
    def _make_text(parent, font):
        """Read-only text area with a scrollbar."""
        txt = tk.Text(parent, wrap="word", relief="flat", padx=12, pady=8, font=font, state="disabled")
        sb = ttk.Scrollbar(parent, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        return txt

    def _build_status(self):
        self.status_var = tk.StringVar()
        self.status = ttk.Label(self.root, textvariable=self.status_var, style="Info.TLabel",
                                anchor="w", padding=(10, 2))
        self.status.pack(fill="x", side="bottom", pady=(0, 4))

    def _set_status(self, msg, error=False):
        self.status_var.set(msg)
        self.status.configure(style="Err.TLabel" if error else "Info.TLabel")

    def _on_tab(self):
        for cv in (self.canvas, self.canvas_tl, self.canvas_q):
            cv.draw_idle()
        self.live.redraw()

    # ---------- input handling ----------
    def add_process(self):
        try:
            if len(self.processes) >= MAX_PROCS:
                raise ValueError(f"Maximum of {MAX_PROCS} processes reached.")
            at = parse_int(self.at_var.get(), "Arrival time", 0, MAX_TIME)
            bt = parse_int(self.bt_var.get(), "Burst time", 1, MAX_TIME)
            pr = parse_int(self.pr_var.get(), "Priority", -MAX_PRIORITY, MAX_PRIORITY, default=0)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        pid = self._append(f"P{self.counter}", at, bt, pr)
        self.at_var.set("")
        self.bt_var.set("")
        self.at_entry.focus_set()
        self._set_status(f"Added {pid}.")
        self._refresh()

    def _append(self, pid, at, bt, pr):
        self.processes.append(Process(pid, at, bt, pr))
        self.tree.insert("", "end", iid=pid, values=(pid, at, bt, pr),
                         tags=("odd",) if len(self.processes) % 2 == 0 else ())
        self.counter += 1
        return pid

    def _load_rows(self, rows):
        self._reset()
        for at, bt, pr in rows:
            self._append(f"P{self.counter}", at, bt, pr)

    def delete_selected(self):
        sel = list(self.tree.selection())
        if not sel:
            self._set_status("Select one or more processes in the table first.", error=True)
            return
        for iid in sel:
            self.tree.delete(iid)
        gone = set(sel)
        self.processes = [p for p in self.processes if p.pid not in gone]
        for i, iid in enumerate(self.tree.get_children()):      # keep zebra striping tidy
            self.tree.item(iid, tags=("odd",) if i % 2 else ())
        self._set_status(f"Deleted {len(sel)} process(es).")
        self._refresh()

    def _reset(self):
        self.tree.delete(*self.tree.get_children())
        self.processes, self.counter = [], 1
        self._clear_results()

    def clear_all(self):
        if self.processes and not messagebox.askyesno("Clear all", "Remove all processes and results?"):
            return
        self._reset()
        self._set_status("Cleared.")

    def load_sample(self):
        self._reset()
        for s in self.SAMPLE:
            self._append(*s)
        self._set_status("Sample data loaded.")
        self.run_selected()

    def random_set(self):
        """Quick demo data: 4-7 random processes."""
        self._load_rows([(random.randint(0, 10), random.randint(1, 10), random.randint(1, 5))
                         for _ in range(random.randint(4, 7))])
        self._set_status("Random processes generated.")
        self.run_selected()

    def import_csv(self):
        path = filedialog.askopenfilename(title="Import processes",
                                          filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = parse_process_csv(f.read())
        except (OSError, ValueError) as exc:
            self._set_status(f"Import failed: {exc}", error=True)
            return
        self._load_rows(rows)
        self._set_status(f"Imported {len(rows)} processes from {os.path.basename(path)}.")
        self.run_selected()

    def save_workspace(self):
        if not self.processes:
            self._set_status("Add some processes before saving a workspace.", error=True)
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="workspace.json",
                                            filetypes=[("Workspace", "*.json")])
        if not path:
            return
        try:
            q = parse_int(self.q_var.get(), "Quantum", 1, MAX_TIME)
        except ValueError:
            q = 2
        data = {"app": "CPU Scheduling Simulator", "algorithm": self.algo_var.get(), "quantum": q,
                "lower_is_higher": self.lower_var.get(),
                "processes": [[p.at, p.bt, p.pr] for p in self.processes]}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            self._set_status(f"Could not save: {exc}", error=True)
            return
        self._set_status(f"Workspace saved to {os.path.basename(path)}.")

    def load_workspace(self):
        path = filedialog.askopenfilename(title="Load workspace",
                                          filetypes=[("Workspace", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                ws = parse_workspace(f.read())
        except (OSError, ValueError) as exc:
            self._set_status(f"Load failed: {exc}", error=True)
            return
        self.algo_var.set(ws["algorithm"])
        self.q_var.set(str(ws["quantum"]))
        self.lower_var.set(ws["lower"])
        self._load_rows(ws["rows"])
        self._set_status(f"Workspace loaded from {os.path.basename(path)}.")
        self.run_selected()

    # ---------- running ----------
    def _on_algo_change(self, _=None):
        if self.processes:
            self.run_selected()
        else:
            self._update_guide()

    def _on_option_change(self):
        if self.has_result:
            self.run_selected()

    def _refresh(self):
        """Process list changed: re-run if a result is on screen, otherwise nothing to do."""
        if not self.processes:
            self._clear_results()
        elif self.has_result:
            self.run_selected()

    def _quantum(self):
        try:
            return parse_int(self.q_var.get(), "Time quantum", 1, MAX_TIME)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return None

    def _rr_ok(self, q):
        slices = sum(math.ceil(p.bt / q) for p in self.processes)
        if slices > MAX_SLICES:
            self._set_status(f"Time quantum {q} would create {slices:,} time slices. "
                             f"Use a larger quantum (max {MAX_SLICES:,} slices).", error=True)
            return False
        return True

    def run_selected(self):
        """Run the chosen algorithm. Returns True if a result is now on screen."""
        if not self.processes:
            self._set_status("Add at least one process first.", error=True)
            return False
        algo = self.algo_var.get()
        q = 2
        if algo == "Round Robin":
            q = self._quantum()
            if q is None or not self._rr_ok(q):
                return False
        procs, gantt = CPUScheduler(self.processes, self.lower_var.get()).run(algo, q)
        self._show(algo, procs, gantt)
        self._set_status(f"{algo} finished.")
        return True

    def compare_all(self):
        if not self.processes:
            self._set_status("Add at least one process first.", error=True)
            return
        q = self._quantum()
        if q is None or not self._rr_ok(q):
            return
        rows = compare_rows(self.processes, self.lower_var.get(), q)
        best = {i: min(r[i] for r in rows) for i in (1, 2, 3)}
        near = lambda a, b: abs(a - b) < 1e-9

        if self.cmp_win is not None and self.cmp_win.winfo_exists():
            self.cmp_win.destroy()
        win = self.cmp_win = tk.Toplevel(self.root)
        win.title("Algorithm Comparison")
        win.configure(bg=T["bg"])
        win.transient(self.root)
        win.minsize(720, 640)

        t = ttk.Treeview(win, columns=("a", "w", "t", "r", "c"), show="headings", height=len(rows))
        for c, h, w in (("a", "Algorithm", 200), ("w", "Avg Waiting", 110), ("t", "Avg Turnaround", 130),
                        ("r", "Avg Response", 120), ("c", "Context Switches", 130)):
            t.heading(c, text=h)
            t.column(c, width=w, anchor="center")
        t.tag_configure("best", background=T["good"])
        for algo, w, tt, r, cs in rows:
            stars = [near(w, best[1]), near(tt, best[2]), near(r, best[3])]
            t.insert("", "end", tags=("best",) if any(stars) else (),
                     values=(algo, f"{w:.2f}" + (" \u2605" if stars[0] else ""),
                             f"{tt:.2f}" + (" \u2605" if stars[1] else ""),
                             f"{r:.2f}" + (" \u2605" if stars[2] else ""), cs))
        t.pack(fill="x", padx=10, pady=(10, 4))

        for i, label in ((1, "waiting time"), (2, "turnaround time"), (3, "response time")):
            names = ", ".join(r[0] for r in rows if near(r[i], best[i]))
            ttk.Label(win, font=self.font_bold,
                      text=f"\u2605 Lowest avg {label} ({best[i]:.2f}): {names}").pack(anchor="w", padx=12)
        rule = "lower" if self.lower_var.get() else "higher"
        ttk.Label(win, style="Info.TLabel",
                  text=f"Round Robin quantum = {q}.  Priority: {rule} number = higher priority.").pack(
            anchor="w", padx=12, pady=(4, 6))

        fig = Figure(figsize=(7, 3.6), dpi=100, layout="constrained")
        draw_compare(fig.add_subplot(111), rows)
        cv = FigureCanvasTkAgg(fig, master=win)
        cv.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))
        cv.draw()

    # ---------- Gantt animation ----------
    def animate(self):
        """Replay the Gantt chart growing over time (toggle: press again to stop)."""
        if self.anim_job is not None:
            self._stop_anim()
            self._draw_chart()
            return
        if not self.run_selected():
            return
        self.nb.select(0)
        total = self.last[2][-1][1]
        step = max(1, math.ceil(total / 100))        # at most ~100 frames
        self.anim_btn.configure(text="\u25A0  Stop")
        self._anim_frame(step, step)

    def _anim_frame(self, t, step):
        total = self.last[2][-1][1]
        self._draw_chart(upto=min(t, total))
        if t >= total:
            self._stop_anim()
        else:
            self.anim_job = self.root.after(50, self._anim_frame, t + step, step)

    def _stop_anim(self):
        if self.anim_job is not None:
            self.root.after_cancel(self.anim_job)
            self.anim_job = None
        self.anim_btn.configure(text="\u25B6  Animate Gantt")

    # ---------- saving ----------
    def save_png(self):
        if self.last is None:
            self._set_status("Run a simulation first, then save its chart.", error=True)
            return
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile="gantt_chart.png",
                                            filetypes=[("PNG image", "*.png")])
        if not path:
            return
        algo, procs, gantt = self.last
        png = render_png(lambda ax: draw_gantt(ax, [p.pid for p in procs], gantt, f"Gantt Chart \u2013 {algo}"))
        try:
            with open(path, "wb") as f:
                f.write(png)
        except OSError as exc:
            self._set_status(f"Could not save the chart: {exc}", error=True)
            return
        self._set_status(f"Chart saved to {os.path.basename(path)}.")

    def export_csv(self):
        if self.last is None:
            self._set_status("Run a simulation first, then export its results.", error=True)
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="results.csv",
                                            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        algo, procs, gantt = self.last
        s = CPUScheduler.summarize(procs, gantt)
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Process", "Arrival", "Burst", "Priority", "Completion",
                            "Turnaround", "Waiting", "Response"])
                for p in procs:
                    w.writerow([p.pid, p.at, p.bt, p.pr, p.ct, p.tat, p.wt, p.rt])
                w.writerow([])
                w.writerow(["Algorithm", algo])
                w.writerow(["Total time", s["total"]])
                w.writerow(["Average waiting", f"{s['wt']:.2f}"])
                w.writerow(["Average turnaround", f"{s['tat']:.2f}"])
                w.writerow(["Average response", f"{s['rt']:.2f}"])
                w.writerow(["CPU utilization %", f"{s['util']:.1f}"])
                w.writerow(["Context switches", s["cs"]])
        except OSError as exc:
            self._set_status(f"Could not save the results: {exc}", error=True)
            return
        self._set_status(f"Results exported to {os.path.basename(path)}.")

    def export_report(self):
        """Self-contained HTML report (chart + tables + comparison); opens in the browser."""
        if self.last is None:
            self._set_status("Run a simulation first, then create its report.", error=True)
            return
        q = self._quantum()
        if q is None or not self._rr_ok(q):
            return
        path = filedialog.asksaveasfilename(defaultextension=".html", initialfile="scheduling_report.html",
                                            filetypes=[("HTML report", "*.html")])
        if not path:
            return
        algo, procs, gantt = self.last
        png = render_png(lambda ax: draw_gantt(ax, [p.pid for p in procs], gantt, f"Gantt Chart \u2013 {algo}"))
        page = build_report_html(algo, procs, gantt, compare_rows(self.processes, self.lower_var.get(), q),
                                 q, self.lower_var.get(), png)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(page)
        except OSError as exc:
            self._set_status(f"Could not save the report: {exc}", error=True)
            return
        webbrowser.open(pathlib.Path(path).resolve().as_uri())
        self._set_status(f"Report saved to {os.path.basename(path)}.")

    # ---------- output ----------
    def _draw_chart(self, upto=None):
        algo, procs, gantt = self.last
        draw_gantt(self.ax, [p.pid for p in procs], gantt, f"Gantt Chart \u2013 {algo}", upto=upto)
        self.canvas.draw()

    def _draw_charts(self):
        if self.last is None:
            draw_empty_gantt(self.ax)
            draw_empty_gantt(self.ax_tl, "Run a simulation to see one lane per process", "Process Timeline")
        else:
            algo, procs, gantt = self.last
            draw_gantt(self.ax, [p.pid for p in procs], gantt, f"Gantt Chart \u2013 {algo}")
            draw_swimlane(self.ax_tl, procs, gantt, f"Process Timeline \u2013 {algo}")
        self.canvas.draw()
        self.canvas_tl.draw()

    def _draw_quantum(self):
        q = None
        try:
            q = parse_int(self.q_var.get(), "q", 1, MAX_TIME)
        except ValueError:
            pass
        draw_quantum(self.fig_q, self.qdata, q)
        self.canvas_q.draw()

    def _update_quantum_lab(self):
        if not self.processes:
            self.qdata = None
            self.qbest_var.set("")
        else:
            try:
                qmax = parse_int(self.qmax_var.get(), "Sweep limit", 1, 60, default=10)
            except ValueError as exc:
                self._set_status(str(exc), error=True)
                return
            self.qdata = sweep_quantum(self.processes, qmax)
            if self.qdata:
                b = best_quantum(self.qdata)
                self.qbest_var.set(f"Best quantum for waiting time: {b[0]}  "
                                   f"(avg WT {b[1]:.2f}, {b[3]} context switches)")
            else:
                self.qbest_var.set("Bursts are too long for such small quanta; raise the sweep limit.")
        self._draw_quantum()

    def _fill_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        if self.last:
            _algo, procs, gantt = self.last
            for tm, kind, text in build_events(procs, gantt):
                self.log.insert("end", f"t={tm:<5}", "time")
                self.log.insert("end", f"{text}\n", kind)
        else:
            self.log.insert("end", "Run a simulation to see the scheduler's step-by-step story.", "time")
        self.log.configure(state="disabled")

    def _update_guide(self):
        g = self.guide
        g.configure(state="normal")
        g.delete("1.0", "end")
        algo = self.algo_var.get()
        kind, rule, pros, cons, best_for, cost = ALGO_INFO[algo]
        g.insert("end", f"{algo}   ({kind})\n", "h1")
        for label, text in (("How it decides", rule), ("Strengths", pros), ("Weaknesses", cons),
                            ("Best for", best_for), ("Cost", cost)):
            g.insert("end", f"\n{label}: ", "h2")
            g.insert("end", text)
        g.insert("end", "\n\nRecommendation for your data\n", "h1")
        q = 2
        try:
            q = parse_int(self.q_var.get(), "q", 1, MAX_TIME)
        except ValueError:
            pass
        if not self.processes:
            g.insert("end", "Add processes and the simulator will tell you which algorithm suits them best.")
        elif sum(math.ceil(p.bt / q) for p in self.processes) > MAX_SLICES:
            g.insert("end", "The time quantum is too small for these bursts, so no comparison was made.")
        else:
            rows = compare_rows(self.processes, self.lower_var.get(), q)
            top = recommend(rows)
            g.insert("end", f"\u2605 {top[0]}", "good")
            g.insert("end", f" gives the lowest average waiting time ({top[1]:.2f}) "
                            f"with {top[4]} context switch(es).\n\nAverage waiting time by algorithm:\n")
            for a, w, _t, _r, cs in sorted(rows, key=lambda r: (round(r[1], 9), r[4])):
                g.insert("end", f"   {a:<28}{w:6.2f}   ({cs} context switches)\n")
            g.insert("end", "\nTip: the lowest waiting time is not always the 'best' choice; "
                            "Round Robin trades waiting time for fairness and quick first response.")
        g.configure(state="disabled")

    def _clear_results(self):
        self._stop_anim()
        self.res_tree.delete(*self.res_tree.get_children())
        for v in self.stat_vars.values():
            v.set("\u2014")
        self.has_result = False
        self.last = None
        self._draw_charts()
        self.live.clear()
        self._fill_log()
        self._update_quantum_lab()
        self._update_guide()

    def _show(self, algo, procs, gantt):
        self._stop_anim()
        self.last = (algo, procs, gantt)
        self.res_tree.delete(*self.res_tree.get_children())
        for i, p in enumerate(procs):
            self.res_tree.insert("", "end", values=(p.pid, p.at, p.bt, p.pr, p.ct, p.tat, p.wt, p.rt),
                                 tags=("odd",) if i % 2 else ())
        s = CPUScheduler.summarize(procs, gantt)
        self.res_tree.insert("", "end", tags=("avg",),
                             values=("Average", "", "", "", "", f"{s['tat']:.2f}", f"{s['wt']:.2f}", f"{s['rt']:.2f}"))
        self.stat_vars["total"].set(str(s["total"]))
        self.stat_vars["wt"].set(f"{s['wt']:.2f}")
        self.stat_vars["tat"].set(f"{s['tat']:.2f}")
        self.stat_vars["rt"].set(f"{s['rt']:.2f}")
        self.stat_vars["util"].set(f"{s['util']:.1f}%")
        self.stat_vars["cs"].set(str(s["cs"]))
        self.has_result = True
        self._draw_charts()
        self.live.set_data(procs, gantt, build_events(procs, gantt))
        self._fill_log()
        self._update_quantum_lab()
        self._update_guide()


# =====================================================================
#  Self-test (python cpu_scheduler.py --selftest)
# =====================================================================
def _selftest():
    class FakeCanvas:                       # accepts any drawing call, so the scene code can be exercised
        def __getattr__(self, name):
            return lambda *a, **k: None

    def reference(procs, algo, lower):
        """Slow, obviously-correct 1-time-unit simulator for the preemptive algorithms."""
        sign = 1 if lower else -1
        rem = {p.pid: p.bt for p in procs}
        idx = {p.pid: i for i, p in enumerate(procs)}
        ct, t = {}, 0
        while len(ct) < len(procs):
            ready = [p for p in procs if rem[p.pid] > 0 and p.at <= t]
            if not ready:
                t += 1
                continue
            key = (lambda p: (rem[p.pid], p.at, idx[p.pid])) if algo == ALGORITHMS[2] \
                else (lambda p: (sign * p.pr, p.at, idx[p.pid]))
            p = min(ready, key=key)
            rem[p.pid] -= 1
            t += 1
            if rem[p.pid] == 0:
                ct[p.pid] = t
        return ct

    random.seed(7)
    for _ in range(1500):
        n = random.randint(1, 7)
        ps = [Process(f"P{i + 1}", random.randint(0, 12), random.randint(1, 9), random.randint(-2, 4))
              for i in range(n)]
        lower, q = random.random() < 0.5, random.randint(1, 5)
        for algo in ALGORITHMS:
            res, g = CPUScheduler(ps, lower).run(algo, q)
            t = 0
            for s, e, _pid in g:                                   # contiguous, non-empty
                assert s == t and e > s, (algo, g)
                t = e
            for r in res:
                ran = sum(e - s for s, e, pid in g if pid == r.pid)
                assert ran == r.bt, (algo, r)                      # got exactly its burst
                assert all(s >= r.at for s, e, pid in g if pid == r.pid), (algo, r)
                assert r.tat == r.ct - r.at and r.wt == r.tat - r.bt >= 0, (algo, r)
                assert 0 <= r.rt <= r.wt, (algo, r)                # response never exceeds waiting
            if algo in (ALGORITHMS[2], ALGORITHMS[5]):
                assert {r.pid: r.ct for r in res} == reference(ps, algo, lower), (algo, ps)
            # live-view snapshots: every process is in exactly one place at every moment
            ev = build_events(res, g)
            assert sum(1 for e in ev if e[1] == "done") == n and sum(1 for e in ev if e[1] == "arrive") == n
            for t in range(g[-1][1] + 1):
                sn = snapshot(res, g, t)
                placed = sn["incoming"] + sn["ready"] + sn["done"] + ([sn["running"]] if sn["running"] else [])
                assert sorted(placed) == sorted(p.pid for p in res), (algo, t, sn)
                assert sn["running"] not in sn["ready"]

    # textbook case: SRTF on the sample data
    res, g = CPUScheduler([Process(*s) for s in SchedulerGUI.SAMPLE]).srtf()
    assert [r.ct for r in res] == [20, 5, 29, 10, 15]
    s = CPUScheduler.summarize(res, g)
    assert s["cs"] == 6 and abs(s["util"] - 100) < 1e-9
    sn = snapshot(res, g, 7)                                       # P4 running, P1/P3 waiting, P5 not arrived
    assert sn["running"] == "P4" and sn["ready"] == ["P1", "P3"] and sn["incoming"] == ["P5"] and sn["done"] == ["P2"]
    # idle gap lowers utilization: busy 4 of 7 time units
    res, g = CPUScheduler([Process("A", 0, 2), Process("B", 5, 2)]).fcfs()
    assert abs(CPUScheduler.summarize(res, g)["util"] - 400 / 7) < 1e-9
    assert snapshot(res, g, 3)["idle"] and snapshot(res, g, 7)["finished"]
    # huge bursts must not hang
    CPUScheduler([Process("A", 0, 10 ** 9), Process("B", 5, 10 ** 9)]).srtf()

    # analysis helpers
    base = [Process(*s) for s in SchedulerGUI.SAMPLE]
    rows = compare_rows(base, True, 2)
    assert len(rows) == 6 and recommend(rows)[0] in (ALGORITHMS[2], ALGORITHMS[5])
    sw = sweep_quantum(base, 10)
    assert [r[0] for r in sw] == list(range(1, 11)) and sw[0][3] > sw[-1][3]   # smaller quantum = more switches

    # file formats
    assert parse_process_csv("pid,arrival,burst,priority\nP1,0,5,2\nP2,1,3,1\n") == [(0, 5, 2), (1, 3, 1)]
    assert parse_process_csv("0,5\n2,3\n") == [(0, 5, 0), (2, 3, 0)]
    for bad in ("0,0\n", "a,b,c\n1,x\n", "", "1,2,3,4,5\n"):
        try:
            parse_process_csv(bad)
        except ValueError:
            continue
        raise AssertionError(f"should have been rejected: {bad!r}")
    ws = parse_workspace(json.dumps({"processes": [[0, 5, 2], [1, 3, 1]], "algorithm": "Round Robin",
                                     "quantum": 3, "lower_is_higher": False}))
    assert ws == {"rows": [(0, 5, 2), (1, 3, 1)], "algorithm": "Round Robin", "quantum": 3, "lower": False}
    for bad in ("{}", "[]", "not json", '{"processes": [[0, 0, 1]]}', '{"processes": [[1, 2]]}'):
        try:
            parse_workspace(bad)
        except ValueError:
            continue
        raise AssertionError(f"workspace should have been rejected: {bad!r}")

    # drawing code must run in both themes without a window
    res, g = CPUScheduler([Process(f"P{i}", i, 3 + i, i % 4) for i in range(14)]).run(ALGORITHMS[3], 2)
    pids = [p.pid for p in res]
    events = build_events(res, g)
    for theme in THEMES:
        set_theme(theme)
        for upto in (None, 5, g[-1][1]):
            fig = Figure()
            draw_gantt(fig.add_subplot(111), pids, g, "t", upto=upto)
            fig.savefig(io.BytesIO(), format="png")
        for draw in (lambda ax: draw_swimlane(ax, res, g, "t"), lambda ax: draw_compare(ax, rows),
                     lambda ax: draw_empty_gantt(ax)):
            fig = Figure()
            draw(fig.add_subplot(111))
            fig.savefig(io.BytesIO(), format="png")
        for data in (sw, []):
            fig = Figure()
            draw_quantum(fig, data, 2)
            fig.savefig(io.BytesIO(), format="png")
        for t in (0, 1, 7, g[-1][1] // 2, g[-1][1]):
            draw_live_scene(FakeCanvas(), 900, 330, "Arial", res, g, events, t)
        draw_live_scene(FakeCanvas(), 900, 330, "Arial", None, None, None, 0)
    set_theme("Dark")
    page = build_report_html("Round Robin", res, g, rows, 2, True, render_png(lambda ax: draw_gantt(ax, pids, g, "t")))
    assert "data:image/png;base64," in page and "Recommendation" in page and "P13" in page
    print("Self-test passed.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit(0)
    if sys.platform == "win32":                 # crisp text on high-DPI Windows screens
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if not HAS_TK:
        sys.exit("Tkinter is not installed. On Windows, re-run the Python installer and tick "
                 "'tcl/tk and IDLE'. On Linux: sudo apt install python3-tk")
    root = tk.Tk()
    SchedulerGUI(root)
    root.mainloop()
