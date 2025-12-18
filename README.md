# Python Web Browser

## Project Title
**Educational Python Web Browser with Rendering, History Analytics, and Visualization**

---

## Team Members
- **Sri Sai Sarath Chandra Konuru**
- **Sri Lasya Siripurapu**
- **Nikhil Krishna Bramhandam** 

> All team members contributed multiple meaningful commits to the shared GitHub repository, satisfying the equal-contribution requirement.

---

## Problem Description

Web browsers are among the most complex real-world software systems, combining networking, document parsing, layout computation, rendering, and user interaction.  
The engineering problem addressed in this project is the **design and implementation of a functional web browser engine from scratch using Python**.

The challenge lies in transforming raw network data into a structured, interactive visual interface. This project demonstrates how core browser concepts can be implemented using modular, object-oriented design and advanced Python libraries.

---

## Solution Approach

The browser is built as a collection of modular components that mirror real browser architecture:

1. **Networking** – Handles HTTP/HTTPS requests, URL parsing, redirects, cookies, and secure connections.
2. **Parsing** – Converts HTML into a DOM tree and CSS into structured style rules.
3. **Layout Engine** – Computes element sizes and positions using the CSS box model.
4. **Rendering & Interactivity** – Displays content, handles scrolling, clicks, tabs, and JavaScript execution.
5. **Data Persistence & Analytics** – Stores browsing history locally and visualizes user behavior using data analysis tools.

This approach demonstrates how real-world browser systems can be modeled using Python classes, composition, and modular design.

---

## Program Structure

```
browser/
│
├── browser.py       # Main Browser and Tab logic (UI, navigation, events)
├── networking.py    # URL parsing and HTTP/HTTPS requests
├── dom.py           # HTML parsing and DOM tree construction
├── css.py           # CSS parsing and selector handling
├── layout.py        # Layout engine and rendering logic
├── javascript.py    # JavaScript execution via DukPy
├── stats.py         # Browsing history analytics (Pandas + Matplotlib)
├── __init__.py
│
tests/
├── test_browser.py  # Pytest unit tests
│
main.ipynb           # Main program entry point (Jupyter Notebook)
browser_history.csv  # Persistent browsing history (auto-generated)
README.md
```

---

## Setup Instructions

### Requirements
- **Python 3.12 or 3.13**
- Required libraries:
```bash
pip install pandas matplotlib dukpy pytest
```

> Tkinter is included with most Python installations.

---

## How to Run the Program

### Main Entry Point (Required)
Open `browser_notebook.ipynb` and run the first cell:

```python
from browser.browser import Browser
app = Browser()
app.window.mainloop()
```

---

### Optional: Run from Command Line
```bash
python -m browser.browser https://github.com
```

---

## Browser Controls
- Navigation: Enter URL and press Enter
- Tabs: Ctrl+T
- History Statistics: Ctrl+S / Cmd+S
- Scrolling: Mouse wheel or arrow keys

---

## Data Persistence & Visualization

Browsing history is saved to:
```
browser_history.csv
```

### Advanced Libraries Used
- **Pandas** – Data storage and CSV persistence
- **Matplotlib** – Visualization of browsing statistics

---

## Running Unit Tests
```bash
python -m pytest tests/test_browser.py
```

---

## Main Contributions of Each Teammate

### Sri Sai Sarath Chandra Konuru
- Implemented browsing history persistence using Pandas
- Added history visualization using Matplotlib
- Created the Jupyter Notebook entry point
- Integrated and stabilized rendering (fonts, images, white-screen fixes)
- Implemented tab handling, button functionality, and focus management
- Added unit tests, exception handling, and security improvements
- Resolved merge conflicts and ensured repository stability

### Sri Lasya Siripurapu
- Refactored the codebase into a modular architecture
- Implemented foundational layout components
- Added CSS and hyperlink handling logic
- Managed experimental features via separate branches
- Contributed incremental fixes and structural improvements

### Nikhil Krishna Bramhandam
- Integrated DukPy for JavaScript execution
- Implemented CSS parsing and layout logic
- Enhanced layout height calculations and scrollbar behavior
- Added server-side testing components
- Contributed to core browser functionality

---

## Notes
- Experimental Rendering: Developed a prototype Skia-based rendering engine with image support (not in the scope of the project)
- Moved the complex/incomplete Skia rendering code to the ```experimental``` branch to maintain the stability of the main branch
- To test and validate the browser during development, a small local static website was created and served using Python’s built-in HTTP server

```
cd sites/focusdash_site
python -m http.server 8000
```
- open the below url in the browser
```
http://localhost:8000/index.html
```

