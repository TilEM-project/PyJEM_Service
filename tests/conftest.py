from __future__ import annotations

import sys
from types import ModuleType


if "PyJEM" not in sys.modules:
    pyjem = ModuleType("PyJEM")
    tem3 = ModuleType("PyJEM.TEM3")

    class TEM3Error(Exception):
        pass

    tem3.TEM3Error = TEM3Error
    tem3.connect = lambda: True
    tem3.EOS3 = lambda: None
    tem3.Def3 = lambda: None
    tem3.Apt3 = lambda: None
    tem3.Stage3 = lambda: None
    tem3.GUN3 = lambda: None
    pyjem.TEM3 = tem3
    sys.modules["PyJEM"] = pyjem
    sys.modules["PyJEM.TEM3"] = tem3

