"""Functional test for services/ownership.py.

Runs on a private SQLite database via a stubbed `app.database`, so it never
touches the real Postgres / live data. Covers the ownership rules:
paused agent, silence timeline, Settings override, inbound-activity, and
the P0 fix (BatchStatus.cancelled)."""
import os
import sys
import types
import tempfile
from datetime import datetime, timedelta

DB_PATH = os.path.join(tempfile.gettempdir(), "cv_ownership_test.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

# ── stub app.database BEFORE anything imports it (models does `from .database
# import Base`); real database.py refuses SQLite, this module must not. ─────
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base, sessionmaker

_engine = sa.create_engine(f"sqlite:///{DB_PATH.replace(os.sep, '/')}")
_Base = declarative_base()
_Session = sessionmaker(bind=_engine)

_stub = types.ModuleType("app.database")
_stub.Base = _Base
_stub.engine = _engine
_stub.SessionLocal = _Session


def _get_db():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


_stub.get_db = _get_db

import app  # package (empty __init__)  # noqa: E402
sys.modules["app.database"] = _stub
app.database = _stub

from app import models                      # noqa: E402
from app.services import ownership          # noqa: E402

_Base.metadata.create_all(_engine)
db = _Session()

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   [{detail}]"))


# ── seed ──────────────────────────────────────────────────────────────────
osaja = models.Agent(name="Osaja", is_active=True)
saif = models.Agent(name="Saif", is_active=True)
db.add_all([osaja, saif])
db.commit()

now = datetime.utcnow()

# 1. Fresh lead, no owner -> free
l1 = models.Lead(email="a@x.com", status=models.LeadStatus.new, created_at=now)
db.add(l1); db.commit()
held, why = ownership.held(db, l1)
check("unassigned lead is free", not held, why)

# 2. Owner active + recent outbound -> HELD
l2 = models.Lead(email="b@x.com", status=models.LeadStatus.contacted,
                 agent_id=osaja.id, last_outbound_at=now - timedelta(days=1),
                 created_at=now - timedelta(days=10))
db.add(l2); db.commit()
held, why = ownership.held(db, l2)
check("active owner + 1d-old outbound -> held", held, why)

# 3. Same lead, owner PAUSED -> released immediately
osaja.is_active = False
db.commit()
held, why = ownership.held(db, l2)
check("paused owner -> released", (not held) and ("paused" in why), why)

# 4. Owner active again, but silent 10 days (> default 7) -> released
osaja.is_active = True
l2.last_outbound_at = now - timedelta(days=10)
db.commit()
held, why = ownership.held(db, l2)
check("silent 10d > 7d timeline -> released", (not held) and ("silent" in why), why)

# 5. Silent 3 days (< 7) -> held again
l2.last_outbound_at = now - timedelta(days=3)
db.commit()
held, why = ownership.held(db, l2)
check("silent 3d < 7d timeline -> held", held, why)

# 6. Settings override: lead_ownership_days = 2 -> 3d silence releases
db.add(models.SettingKV(key="lead_ownership_days", value="2"))
db.commit()
held, why = ownership.held(db, l2)
check("Settings override (2d) releases a 3d-silent lead",
      (not held) and ("silent 3d" in why), why)

# 7. Inbound reply counts as activity (message newer than outbound)
db.query(models.SettingKV).filter_by(key="lead_ownership_days").delete()
l2.last_outbound_at = now - timedelta(days=10)
db.add(models.EmailMessage(lead_id=l2.id, agent_id=osaja.id, direction="in",
                           from_addr="b@x.com", subject="re", body="hi",
                           created_at=now - timedelta(hours=2)))
db.commit()
held, why = ownership.held(db, l2)
check("recent INBOUND reply counts as communication -> held", held, why)

# 8. Enrolled 5h ago, never mailed -> held
l3 = models.Lead(email="c@x.com", status=models.LeadStatus.enrolled,
                 agent_id=saif.id, created_at=now - timedelta(hours=5))
db.add(l3); db.commit()
held, why = ownership.held(db, l3)
check("enrolled 5h ago, never mailed -> held", held, why)

# 9. Deleted owner agent -> free
l4 = models.Lead(email="d@x.com", status=models.LeadStatus.contacted,
                 agent_id=99999, last_outbound_at=now, created_at=now)
db.add(l4); db.commit()
held, why = ownership.held(db, l4)
check("owner agent missing -> free", not held, why)

# 10. ownership_days default is 7 (no Settings row now)
check("ownership_days default = 7", ownership.ownership_days(db) == 7,
      str(ownership.ownership_days(db)))

# 11. P0 fix
check("BatchStatus.cancelled exists", hasattr(models.BatchStatus, "cancelled"))

# 12. days= argument honours an explicit value (bulk-check optimisation)
#     — fresh lead, 3d-old outbound, NO messages at all.
l5 = models.Lead(email="e@x.com", status=models.LeadStatus.contacted,
                 agent_id=saif.id, last_outbound_at=now - timedelta(days=3),
                 created_at=now - timedelta(days=9))
db.add(l5); db.commit()
held, why = ownership.held(db, l5, days=2)
check("explicit days=2 releases a 3d-silent lead", (not held) and ("silent 3d" in why), why)
held, why = ownership.held(db, l5, days=7)
check("explicit days=7 keeps a 3d-silent lead held", held, why)

fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
db.close()
_engine.dispose()
os.remove(DB_PATH)
sys.exit(1 if fails else 0)
