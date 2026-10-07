# PB_HACKATHON
ACTIVITY 14

# CPU Scheduling Algorithm Simulator — "Mission Control" Edition

**Coursework / Hackathon:** B25CS0311 Portfolio Building – Hackathon Abhinava  
**Problem Statement:** Problem Statement 13  

---

## 📌 Project Overview

This project is an interactive, GUI-based **CPU Scheduling Algorithm Simulator** developed in Python. It simulates standard operating system scheduling algorithms, calculates critical CPU scheduling performance metrics, visualizes execution through animated Gantt charts and live hardware pipelines, and provides side-by-side benchmark tools.

The core scheduling engine (`CPUScheduler`) is fully decoupled from the graphical presentation layer, enabling standalone verification, simulation, and automated testing.

---

## 🚀 Key Features

* **6 Scheduling Algorithms:**
  * **FCFS** (First-Come, First-Served)
  * **SJF** (Shortest Job First – Non-preemptive)
  * **SRTF** (Shortest Remaining Time First – Preemptive SJF)[cite: 1, 2]
  * **Round Robin** (with configurable Time Quantum)[cite: 1, 2]
  * **Priority (Non-preemptive)**[cite: 1, 2]
  * **Priority (Preemptive)**[cite: 1, 2]
* **Computed Metrics:**
  * Completion Time ($\text{CT}$)
  * Turnaround Time ($\text{TAT} = \text{CT} - \text{AT}$)
  * Waiting Time ($\text{WT} = \text{TAT} - \text{BT}$)
  * Response Time ($\text{RT} = \text{First CPU Time} - \text{AT}$)
  * CPU Utilization ($\% = \frac{\text{Busy Time}}{\text{Total Time}} \times 100$)
  * Context Switches count
* **Visualization & Analysis Tabs:**
  * **Gantt Chart:** Interactive timeline with idle interval detection and step-by-step playback animation[cite: 1, 2].
  * **Live CPU View:** Hardware animation showing `NEW` $\rightarrow$ `READY QUEUE` $\rightarrow$ `CPU CORE` $\rightarrow$ `TERMINATED` stages with play, pause, step, and scrubbing controls[cite: 1, 2].
  * **Process Timeline:** Multi-lane swim-lane diagram detailing process arrival, waiting state, active runtime, and termination[cite: 1, 2].
  * **Event Log:** Chronological textual narrative of scheduler dispatches, preemptions, and completions[cite: 1, 2].
  * **Quantum Lab:** Sweep analysis for Round Robin to identify the optimal quantum size for minimum waiting time and context switches[cite: 1, 2].
  * **Algorithm Guide:** Theoretical documentation and automatic algorithm recommendation based on the loaded workload[cite: 1, 2].
* **Exporting & Utilities:**
  * **Compare All:** Benchmark window with comparative bar charts across all 6 algorithms[cite: 1, 2].
  * **HTML Report:** Printable self-contained report with embedded base64 chart visuals and result tables[cite: 1, 2].
  * **Data Persistence:** JSON workspace save/load and CSV process import/export[cite: 1, 2].
  * **UI Themes:** Dark and Light mode options[cite: 1, 2].

---

## 🛠️ Tech Stack & Requirements

* **Language:** Python 3.8+
* **GUI Framework:** `tkinter` (included with standard Python installations)[cite: 1, 2]
* **Data Visualization:** `matplotlib >= 3.5`

---

## 💻 Installation & Setup

### Method 1: Automatic One-Click Launch (Windows)
Double-click `run.bat` in the project root[cite: 2, 4]. It checks your Python environment, installs dependencies, runs the engine self-test, and opens the simulator[cite: 4].

### Method 2: Manual Setup via Terminal

1. **Verify Python & Tkinter:**
   ```cmd
   python --version
