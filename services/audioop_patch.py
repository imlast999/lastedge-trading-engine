import sys
from types import ModuleType

# Parche para compatibilidad con Python 3.13+
# Mockea el módulo 'audioop' que fue eliminado de la librería estándar de Python 3.13.
if 'audioop' not in sys.modules:
    audioop_mock = ModuleType('audioop')
    audioop_mock.error = Exception
    audioop_mock.mul = lambda data, size, factor: data
    audioop_mock.tomono = lambda data, size, fac1, fac2: data
    audioop_mock.toster = lambda data, size, fac1, fac2: data
    audioop_mock.lin2lin = lambda data, size, size2: data
    audioop_mock.ratecv = lambda data, size, channels, inrate, outrate, state: (data, state)
    sys.modules['audioop'] = audioop_mock
