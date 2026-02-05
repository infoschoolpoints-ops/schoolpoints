import os
import logging
from typing import Dict

# Configure logging
logger = logging.getLogger("schoolpoints.features")

class FeatureFlags:
    """
    Simple Feature Flags management.
    Flags are loaded from environment variables (prefix FF_) or defaults.
    """
    def __init__(self):
        self._flags: Dict[str, bool] = {}
        self._defaults: Dict[str, bool] = {
            "snapshot2": True,
            "new_admin_ui": True,
            "strict_schema_check": False,
            "enable_purchases": True,
            "enable_smtp": True,
        }
        self.reload()

    def reload(self):
        """Reload flags from environment variables."""
        # Start with defaults
        self._flags = self._defaults.copy()
        
        # Override from env
        for key, val in os.environ.items():
            if key.startswith("FF_"):
                name = key[3:].lower()
                is_on = val.lower() in ('true', '1', 'yes', 'on')
                self._flags[name] = is_on

    def is_enabled(self, name: str, default: bool = False) -> bool:
        """Check if a feature is enabled."""
        return self._flags.get(name.lower(), default)

    def get_all(self) -> Dict[str, bool]:
        return self._flags.copy()

# Global instance
features = FeatureFlags()

def is_feature_enabled(name: str) -> bool:
    return features.is_enabled(name)
