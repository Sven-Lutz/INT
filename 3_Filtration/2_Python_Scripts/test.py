"""
import propar
instrument = propar.instrument("COM5")
print(instrument.wink(time=3))
print(instrument.id)
"""

from Elveflow64 import *

Instr_ID = c_int32()
_initialize_device()
