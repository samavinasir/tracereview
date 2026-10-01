import os

# Settings are instantiated at import time. CI uses placeholders only; all LLM
# and external-source calls are replaced by mocks in tests.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://research:research@localhost:5432/research")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-a-real-secret")

