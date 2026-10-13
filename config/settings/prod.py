"""Railway production entry point, sharing container configuration."""
from .production import *

if DEBUG:
    raise ValueError("config.settings.prod cannot run with DEBUG=True.")
