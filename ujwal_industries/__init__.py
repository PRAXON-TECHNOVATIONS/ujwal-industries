__version__ = "0.0.1"

# Import overrides module to apply monkey-patches on app load
from ujwal_industries.ujwal_industries.overrides import job_card as _job_card_overrides  # noqa: F401
