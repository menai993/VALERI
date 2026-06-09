"""Import every ORM model module so the shared `Base.metadata` is complete.

Cross-table foreign keys (e.g. ``app.investigation.signal_id`` → ``app.signal``,
``app.tool_call_log.message_id`` → ``app.message``) are resolved lazily by
SQLAlchemy at flush time, and resolution only works if the *target* model class
has been imported into the registry. The FastAPI app gets there transitively via
its routers, and Alembic via ``migrations/env.py`` — but a process that flushes
ORM objects WITHOUT that import chain (the worker's scans/audits/investigation
poll, or an ad-hoc script) would otherwise hit ``NoReferencedTableError`` and,
for the investigation poll, leave runs stuck in ``queued``.

Importing this module once registers them all. Keep it in sync with the model
modules (mirrors the list in ``migrations/env.py``).
"""

import valeri_api.approvals.models  # noqa: F401
import valeri_api.audit.models  # noqa: F401
import valeri_api.auth.models  # noqa: F401
import valeri_api.capabilities.models  # noqa: F401
import valeri_api.conversation.models  # noqa: F401
import valeri_api.crm.models  # noqa: F401
import valeri_api.documents.models  # noqa: F401
import valeri_api.domain.models  # noqa: F401
import valeri_api.ingest.models  # noqa: F401
import valeri_api.investigation.models  # noqa: F401
import valeri_api.kb.models  # noqa: F401
import valeri_api.reports.models  # noqa: F401
import valeri_api.rules.models  # noqa: F401
import valeri_api.signals.models  # noqa: F401
import valeri_api.tools.models  # noqa: F401
