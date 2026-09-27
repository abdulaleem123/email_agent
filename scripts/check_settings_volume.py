"""Offline check for the Settings-page volume controls and batch grouping.

No DB, no network, no Celery: fake objects stand in for the SQLAlchemy session
so the pure decision logic can be exercised on a machine with no PostgreSQL.

Run:  PYTHONIOENCODING=utf-8 python -u scripts/check_settings_volume.py
"""
import os
import sys
import types
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

FAILS = []


def ok(cond, label, extra=""):
    if cond:
        print(f"ok     {label}")
    else:
        print(f"FAIL   {label} {extra}")
        FAILS.append(label)


# ── stub the packages we cannot import here ────────────────────────────────
class _Msg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Query:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._f = None

    def filter(self, *a, **k):
        q = _Query(self._apply(a))
        q._f = self._f
        return q

    def _apply(self, conds):
        out = self._rows
        for c in conds:
            f = getattr(c, "_test_pred", None)
            if f:
                out = [r for r in out if f(r)]
        return out

    def with_entities(self, *a):
        return self

    def scalar(self):
        return len(self._rows)

    def count(self):
        return len(self._rows)

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, messages=None, settingkv=None, agents=None, batches=None):
        self.messages = messages or []
        self.kv = {k: types.SimpleNamespace(key=k, value=v)
                   for k, v in (settingkv or {}).items()}
        self.agents = agents or []
        self.batches = batches or []
        self.committed = 0

    def query(self, *a):
        if a and a[0] is Msg:
            return _Query(self.messages)
        if a and a[0] is SettingKV:
            return _Query(list(self.kv.values()))
        if a and a[0] is Agent:
            return _Query(self.agents)
        if a and a[0] is Batch:
            return _Query(self.batches)
        return _Query()

    def get(self, model, key):
        if model is SettingKV:
            return self.kv.get(key)
        if model is Agent:
            return next((a for a in self.agents if a.id == key), None)
        return None

    def add(self, o):
        return o

    def add_all(self, o):
        return o

    def flush(self):
        return None

    def commit(self):
        self.committed += 1


# Real modules get their heavy dependencies faked before import.
sys.modules["sqlalchemy"] = types.ModuleType("sqlalchemy")
sys.modules["sqlalchemy"].Column = lambda *a, **k: None
sys.modules["sqlalchemy"].__version__ = "2.0.0"
sys.modules["sqlalchemy.orm"] = types.ModuleType("sqlalchemy.orm")
sys.modules["sqlalchemy.orm"].Session = object

models = types.ModuleType("app.models")
Msg = type("EmailMessage", (), {})
SettingKV = type("SettingKV", (), {})
Agent = type("Agent", (), {})
Batch = type("Batch", (), {})
Lead = type("Lead", (), {})
models.EmailMessage = Msg
models.SettingKV = SettingKV
models.Agent = Agent
models.Batch = Batch
models.Lead = Lead
sys.modules["app.models"] = models

cfg = types.ModuleType("app.config")
cfg.settings = types.SimpleNamespace(
    OPENAI_MODERATION=False, MX_VERIFY_BEFORE_SEND=True,
    DAILY_SEND_LIMIT=150, EMAIL_BATCH_SIZE=50, BATCH_SIZE_MIN=20,
    BATCH_SIZE_MAX=50, EMAIL_POLL_SIZE=100, OUTBOUND_DELAY_MIN_SECONDS=60,
    OUTBOUND_DELAY_MAX_SECONDS=300, INBOUND_REPLY_DELAY_SECONDS=900,
    FOLLOWUP_AFTER_HOURS=24, MAX_FOLLOWUPS=3, FOLLOWUP_MAX_DAYS=30,
    GARBAGE_RETENTION_DAYS=30, ESCALATION_RETENTION_DAYS=30,
    NOT_INTERESTED_RETENTION_DAYS=30, STALE_LEAD_DAYS=30)
sys.modules["app.config"] = cfg

database = types.ModuleType("app.database")
database.get_db = lambda: None
sys.modules["app.database"] = database

app = types.ModuleType("app")
app.__path__ = [os.path.join(ROOT, "backend", "app")]
sys.modules["app"] = app

routers = types.ModuleType("app.routers")
routers.__path__ = [os.path.join(ROOT, "backend", "app", "routers")]
sys.modules["app.routers"] = routers

services = types.ModuleType("app.services")
services.__path__ = [os.path.join(ROOT, "backend", "app", "services")]
sys.modules["app.services"] = services

from app.routers import app_settings as S     # noqa: E402
from app.services import enroller             # noqa: E402

print("── settings: every knob the operator asked for exists ──")
for key in ("daily_send_limit", "email_batch_size", "email_poll_size",
            "batch_size_min", "batch_size_max", "followup_after_hours",
            "max_followups", "followup_max_days", "garbage_retention_days",
            "escalation_retention_days", "not_interested_retention_days",
            "stale_lead_days", "outbound_delay_min", "outbound_delay_max",
            "inbound_reply_delay", "auto_reply_enabled"):
    ok(key in S.DEFAULTS, f"setting {key} has a default")

print()
print("── batch size comes from Settings, clamped to its own bounds ──")
db = _DB(settingkv={"email_batch_size": "30", "batch_size_min": "20",
                    "batch_size_max": "50"})
ok(enroller.resolve_batch_size(db) == 30, "uses the Settings value (30)")
db2 = _DB(settingkv={})
ok(enroller.resolve_batch_size(db2) == 50, "falls back to the env default (50)")
db3 = _DB(settingkv={"email_batch_size": "30", "batch_size_min": "20",
                     "batch_size_max": "50"})
ok(enroller.resolve_batch_size(db3, 5) == 20, "an explicit 5 is clamped up to 20")
ok(enroller.resolve_batch_size(db3, 999) == 50, "an explicit 999 is clamped to 50")
ok(enroller.resolve_batch_size(db3, 40) == 40, "an explicit 40 passes through")
db4 = _DB(settingkv={"email_batch_size": "junk", "batch_size_min": "20",
                     "batch_size_max": "50"})
ok(enroller.resolve_batch_size(db4) == 50, "garbage in the value cannot crash it")
db5 = _DB(settingkv={"email_batch_size": "30", "batch_size_min": "50",
                     "batch_size_max": "20"})
got5 = enroller.resolve_batch_size(db5)
ok(20 <= got5 <= 50, "inverted min/max still returns a usable number", f"(got {got5})")

print()
print("── daily cap: global is a ceiling, the smaller of the two wins ──")
tasks = types.ModuleType("app.tasks")
tasks._today_start = lambda: datetime.utcnow().replace(hour=0, minute=0, second=0,
                                                       microsecond=0)
_get_setting_int = lambda d, k, default=None: int(
    (d.get(models.SettingKV, k).value if d.get(models.SettingKV, k) else default) or 0)
tasks._get_setting_int = _get_setting_int
tasks._outbound_delay_bounds = lambda a, db=None: (180, 720)
tasks._park_until_tomorrow = lambda task, *a: "daily-limit-requeued"
sys.modules["app.tasks"] = tasks

src = open(os.path.join(ROOT, "backend", "app", "tasks.py"),
           encoding="utf-8").read()
ns = {"models": {"EmailMessage": Msg}, "settings": cfg.settings,
      "_get_setting_int": _get_setting_int,
      "getattr": getattr, "datetime": datetime, "timedelta": timedelta}
start = src.index("def _daily_limit(")
end = src.index("def _daily_limit_reached(")
end2 = src.index("\n", src.index("return sent_today >=", end))
exec("from datetime import datetime, timedelta\n" + src[start:end2], ns)
_daily_limit = ns["_daily_limit"]

a1 = types.SimpleNamespace(id=1, daily_send_limit=0)
a2 = types.SimpleNamespace(id=2, daily_send_limit=200)
dbg = _DB(settingkv={"daily_send_limit": "150"})
ok(_daily_limit(dbg, a1) == 150, "agent with no cap uses the global 150")
ok(_daily_limit(dbg, a2) == 150, "global 150 caps an agent set to 200")
dbg2 = _DB(settingkv={"daily_send_limit": "300"})
ok(_daily_limit(dbg2, a2) == 200, "agent set lower than global keeps its 200")
dbg3 = _DB(settingkv={"daily_send_limit": "0"})
ok(_daily_limit(dbg3, a2) == 200, "global 0 means no global cap, agent's 200 stands")
ok(_daily_limit(dbg3, a1) == 150, "global 0 + agent 0 falls back to a sane 150")

print()
print("── batches never straddle two Excel files ──")
made = []
real_batch = Batch


def mklead(i, tag):
    return types.SimpleNamespace(id=i, upload_tag=tag, not_interested=False,
                                 needs_human=False, escalated=False,
                                 unsubscribed=False, campaign_id=None,
                                 agent_id=None, batch_id=None, status="new")


class FakeBatch:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.id = len(made) + 1
        self.status = "pending"
        made.append(self)


Batch = FakeBatch
made.clear()


def fake_dispatch(batch_id, **kw):
    return types.SimpleNamespace(apply_async=lambda **k: None)


class _Dispatch:
    def apply_async(self, *a, **k):
        dispatched.append((a, k))


dispatched = []
tasks.dispatch_batch = _Dispatch()
models.Batch = FakeBatch
models.BatchStatus = types.SimpleNamespace(pending="pending")
models.LeadStatus = types.SimpleNamespace(new="new", enrolled="enrolled")
enroller.models = models
leads = ([mklead(i, "alpha") for i in range(1, 6)]
         + [mklead(i, "beta") for i in range(6, 11)])
out = enroller.enqueue_fifo(_DB(), None, None, leads, batch_size=20)
files = [b.source_filename for b in made]
ok(all(f for f in files), f"every batch has a source file: {files}")
ok(len(set(files)) >= 2, "two files produce at least two distinct groups")
ok(len(made) == 2, f"5+5 leads at size 20 -> 2 batches (got {len(made)})")
ok([b.total for b in made] == [5, 5], f"each batch holds only its own file: {[b.total for b in made]}")
ok(out["queued"] == 10, "all 10 leads queued")
ok(out["batch_size"] == 20, "returned batch_size is the resolved one")
ok(sorted(out["source_filenames"]) == ["alpha", "beta"],
   f"both files reported back: {out['source_filenames']}")

made.clear()
leads2 = [mklead(i, "solo") for i in range(1, 46)]
dispatched.clear()
enroller.enqueue_fifo(_DB(), None, None, leads2, batch_size=20)
ok(len(made) == 3, f"45 leads at 20 -> 3 batches (got {len(made)})")
ok([b.total for b in made] == [20, 20, 5],
   f"20/20/5 split (got {[b.total for b in made]})")
ok(all(b.source_filename == "solo" for b in made), "one file -> same name on all 3")
ok([b.number for b in made] == [1, 2, 3], "batch numbers increment")
ok(len(dispatched) == 3, f"one Celery task per batch, not per lead (got {len(dispatched)})")
ok([d[1]["args"][0] for d in dispatched] == [b.id for b in made],
   "each task carries its own batch id")

print()
print("── settings values are clamped, not rejected ──")
ok(S._coerce("email_batch_size", "99999") == "2000", "batch size clamped to its max")
ok(S._coerce("email_batch_size", "-5") == "10", "negative batch size clamped to min")
ok(S._coerce("daily_send_limit", "not a number") == S.DEFAULTS["daily_send_limit"],
   "junk falls back to the default instead of raising")
ok(S._coerce("email_poll_size", "250") == "250", "poll size kept when in range")
ok(S._coerce("auto_reply_enabled", "yes") == "true", "boolean coerced")
ok(S._coerce("auto_reply_enabled", "no") == "false", "boolean off")
ok(S._coerce("garbage_retention_days", 45) == "45", "int accepted as a value")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    sys.exit(1)
print("ALL PASS")
