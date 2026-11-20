# -*- coding: utf-8 -*-
# Pure tests: no database (also runnable outside Odoo with a stub, see docs/TESTING).
from . import test_adoption_scoring
from . import test_adoption_values
from . import test_adoption_payload
from . import test_adoption_tracker_logic
from . import test_adoption_assets
from . import test_adoption_env_utils
# ORM tests: need a real Odoo 19 database.
from . import test_adoption_tracking
from . import test_adoption_session
from . import test_adoption_summary
from . import test_adoption_security
from . import test_adoption_screens
