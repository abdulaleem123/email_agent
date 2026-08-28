"""Chatversio AI Email CRM — central configuration. All secrets via .env."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Core ---
    APP_NAME: str = "Chatversio AI Email CRM"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite:///./chatversio.db"     # postgres:// in prod
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    PUBLIC_API_URL: str = "http://localhost:8000"     # publicly reachable backend URL, used to build the
                                                        # unsubscribe link email clients call directly (no auth)
    SERVE_FRONTEND: bool = False
    AUTO_SEED: bool = True

    # --- Auth (single admin, no public registration) ---
    ADMIN_EMAIL: str = "admin@chatversio.ai"
    ADMIN_PASSWORD: str = "change-me-now"      # hashed on first boot
    JWT_SECRET: str = "generate-a-long-random-string"
    JWT_EXPIRE_HOURS: int = 12
    OTP_ENABLED: bool = True                   # email OTP on every login
    OTP_EXPIRE_MINUTES: int = 10
    # Super admin: sees AI usage + manages API keys (nothing else extra)
    SUPERADMIN_EMAIL: str = ""
    SUPERADMIN_PASSWORD: str = ""

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- LLM ---
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"   # cheapest solid model
    OPENAI_MODERATION: bool = True
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-6"

    # --- Tavily (advanced company + pain-point research) ---
    TAVILY_API_KEY: str = ""
    # (email verification is free-only: MX + SMTP probe, see mailer.py)
    TAVILY_DEPTH: str = "advanced"

    # --- Embeddings (per-agent knowledge base, pgvector on Postgres) ---
    EMBED_MODEL: str = "text-embedding-3-large"
    EMBED_DIM: int = 3072
    EMBED_CHUNK_SIZE: int = 800                # chars per chunk
    EMBED_CHUNK_OVERLAP: int = 120

    # --- Outbound SMTP ---
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "Chatversio AI"

    # --- DKIM signing (optional — deliverability). DNS SPF/DKIM/DMARC still required. ---
    DKIM_DOMAIN: str = ""
    DKIM_SELECTOR: str = "default"
    DKIM_PRIVATE_KEY_PATH: str = ""            # path to PEM private key

    # --- Inbound IMAP ---
    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_FOLDER: str = "INBOX"

    # --- Behaviour knobs (also editable per-agent / Settings page) ---
    OUTBOUND_DELAY_MIN_SECONDS: int = 60       # 1 min
    OUTBOUND_DELAY_MAX_SECONDS: int = 300      # 5 min
    INBOUND_REPLY_DELAY_SECONDS: int = 900     # ~15 min humanized reply
    FOLLOWUP_AFTER_HOURS: int = 24
    MAX_FOLLOWUPS: int = 3
    MAX_AGENTS: int = 4
    BATCH_SIZE_MIN: int = 20
    BATCH_SIZE_MAX: int = 50
    GARBAGE_RETENTION_DAYS: int = 30           # auto-purge old garbage
    MX_VERIFY_BEFORE_SEND: bool = True         # unverified domain -> garbage
    SMTP_VERIFY_MAILBOX: bool = True           # SMTP RCPT probe (mailbox exists?)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()