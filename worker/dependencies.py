import os

from sentence_transformers import SentenceTransformer
from redis.asyncio import Redis
from dotenv import load_dotenv
from openai import AsyncOpenAI
from psycopg_pool import AsyncConnectionPool as ConnectionPool

load_dotenv()

# Worker Params
WORKER_ID: str = os.getenv("WORKER_ID", "")
NODE_ENV = os.getenv("NODE_ENV", "unknown")
PREFIX_ENV = "DEV" if NODE_ENV == "development" else ""

# LLM Params
LLM_MODEL: str = os.getenv("LLM_MODEL", "")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")

llm_client = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
)

# Encoder
encoder_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device="cpu")

# DB Params 
HOST_DB = os.getenv(f"PG_HOST_{PREFIX_ENV}", os.getenv("PG_HOST", "localhost"))
USERNAME = os.getenv(f"PG_USER_{PREFIX_ENV}", os.getenv("PG_USER", "user"))
PASSWORD = os.getenv(f"PG_PASSWORD_{PREFIX_ENV}", os.getenv("PG_PASSWORD", "password"))
DATABASE = os.getenv(f"PG_DATABASE_{PREFIX_ENV}", os.getenv("PG_DATABASE", "database"))
PORT = int(os.getenv("PG_PORT", 5432))

DATABASE_URL = (
    f"host={HOST_DB} "
    f"port={PORT} "
    f"dbname={DATABASE} "
    f"user={USERNAME} "
    f"password={PASSWORD}"
)

_pool: ConnectionPool | None = None


async def init_postgres_pool() -> None:
    global _pool
    if _pool is not None:
        return

    _pool = ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=1,
        max_size=5,
        max_lifetime=180,
        max_idle=60,
        reconnect_timeout=5,
    )
    await _pool.open()


async def close_postgres_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized. Call init_postgres_pool() first.")
    return _pool

# Redis
REDIS_HOST = os.getenv(f"REDIS_HOST_{PREFIX_ENV}", os.getenv("REDIS_HOST", "localhost"))
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

redis_client = Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
)

# RabbitMQ 

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
    
RABBITMQ_URL = (
    f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASSWORD}" f"@{RABBITMQ_HOST}:{RABBITMQ_PORT}/"
)

# R2
CLOUDFLARE_R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
CLOUDFLARE_R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
CLOUDFLARE_R2_BUCKET = os.getenv("R2_BUCKET_NAME")
CLOUDFLARE_R2_ENDPOINT = os.getenv("R2_ENDPOINT")

