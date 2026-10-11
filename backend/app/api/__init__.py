"""HTTP routes, one module per area. `main.py` creates the app and includes every router listed here."""
from . import arrange, fabrication, formatting, library, projects, publishing, record, settings, studio

ROUTERS = [m.router for m in (projects, library, arrange, formatting, fabrication, studio, publishing, record, settings)]
