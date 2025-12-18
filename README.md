## What’s Implemented here
- Skia-based rendering  
- Browser chrome (address bar, tabs, back button)  
- Per-tab navigation history  
- Keyboard and mouse input handling  
- Image loading

> Some modern websites may produce JavaScript errors due to limited JS support. This is expected.

---

## Setup Instructions (5 Steps)


1. **Create and activate a virtual environment (optional)**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies**
   ```bash
   pip install skia-python pysdl2 pysdl2-dll dukpy
   ```

3. **Run the browser**
   ```bash
   python browser_final.py https://github.com
   ```

5. **Verify basic functionality**
   - Scroll using mouse or arrow keys  
   - Navigate using the address bar  
   - Use back button and tabs  

---

## Notes
- `browser_skia_base.py` is the stable rendering base  
- `browser_final.py` is the final runnable file  
- This project is for learning purposes only
