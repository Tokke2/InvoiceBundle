from __future__ import annotations

"""
FakturaRäknaren — main.pyw
================================
Fil    : FakturaRäknaren_/main.pyw
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Tunn startfil för start UTAN konsolfönster
(Windows-dubbelklick och pythonw-start).

All logik ligger i main.py — denna fil importerar och anropar
enbart run-funktionen. Används även av AutostartManager som
autostart-kommando:  "pythonw.exe" "main.pyw".

Copyright © dynamiskt år Rickard Längkvist
"""

import sys
from pathlib import Path

# Säkerställer att projektroten finns i sys.path även vid dubbelklick
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from main import main  # noqa: E402

if __name__ == "__main__":
    main()
