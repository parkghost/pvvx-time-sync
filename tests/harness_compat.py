"""Early pytest plugin: lets pytest-homeassistant-custom-component load on 2026.11.

No harness release targets this core yet. Delete this file, and the `-p` entry
in pyproject.toml, once one does.
"""

import homeassistant.components.logger
from homeassistant.components.logger.helpers import _clear_logger_overwrites

homeassistant.components.logger._clear_logger_overwrites = _clear_logger_overwrites
