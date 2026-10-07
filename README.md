# CPU Scheduling Algorithm Simulator

Hackathon Abhinava, B25CS0311 Portfolio Building. Problem statement 13.

## Problem
Simulate CPU scheduling algorithms on a set of processes (arrival time, burst time, priority),
draw the Gantt chart, and compare average waiting and turnaround times.

## Approach
A GUI-free engine (`CPUScheduler`) produces a Gantt schedule and the metrics for every algorithm.
A Tkinter interface collects the input; Matplotlib draws the charts; a Canvas scene animates the CPU.

## Algorithms
Required: FCFS, SJF, Round Robin, Priority.
Extra: SRTF (preemptive SJF) and preemptive Priority.

## Bonus features
1. **Live CPU view**: animated CPU chip, ready queue and terminated bin, with play, pause, step and scrub.
2. **Process timeline**: one swim-lane per process (arrival, running, waiting, completion).
3. **Event log**: a readable story of every arrival, dispatch, preemption and completion.
4. **Quantum Lab**: sweeps the Round Robin quantum and finds the best one.
5. **Algorithm guide**: how each algorithm works, plus an automatic recommendation for your data.
6. **Dark / Light theme**.
7. **Save / Load workspace (JSON)**, CSV import and export, PNG chart export.
8. **HTML report**: printable report with the Gantt chart and the comparison table.
9. **Extra metrics**: response time, CPU utilization and context switches.
10. **Compare All**: table plus bar chart of all six algorithms.

## Tools
Python 3.8+, Tkinter (built in), Matplotlib.

## How to run
1. Install Python 3.8+ (tick "Add Python to PATH" and keep "tcl/tk and IDLE" ticked on Windows).
2. `pip install -r requirements.txt`  (a virtual environment is optional; on Windows you can just double-click `run.bat`)
3. `python cpu_scheduler.py`
   On Linux, also run `sudo apt install python3-tk`.

If `python -m venv` hangs on "ensurepip", skip it: press Ctrl+C, delete the half-made `venv` folder,
then either run without a venv (steps above) or use `python -m venv venv --without-pip`.

Quick start: click **Load Sample**, then explore the tabs. Press **F5** to re-run.

Self-test (no window needed): `python cpu_scheduler.py --selftest`

## CSV import format
`arrival,burst,priority` (header optional, priority optional). See `sample_processes.csv`.

## Team
(Add team name, member names, roll numbers and one-line contributions.)
