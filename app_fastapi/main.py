import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
import psycopg2.pool
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

DB_HOST = os.environ["DB_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_PORT = int(os.getenv("DB_PORT", "5432"))

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT,
            connect_timeout=5,
        )
        logger.info("Connection pool created")
    return _pool


def init_db() -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id   SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        conn.commit()
        logger.info("Database schema initialised")
    finally:
        pool.putconn(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception:
        logger.exception("Failed to initialise database — startup aborted")
        raise
    yield
    if _pool:
        _pool.closeall()
        logger.info("Connection pool closed")


app = FastAPI(title="FastAPI App", lifespan=lifespan)


class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ItemResponse(BaseModel):
    id: int
    name: str


class HealthResponse(BaseModel):
    status: str
    db: str


@app.get("/health", response_model=HealthResponse)
def health():
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        db_status = "ok"
    except Exception:
        logger.exception("DB health check failed")
        db_status = "error"
    finally:
        pool.putconn(conn)

    if db_status != "ok":
        raise HTTPException(status_code=503, detail="Database unavailable")

    return {"status": "ok", "db": db_status}


@app.post("/items", response_model=ItemResponse, status_code=201)
def insert_item(body: ItemCreate):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO items (name) VALUES (%s) RETURNING id, name",
                (body.name,),
            )
            row = cur.fetchone()
        conn.commit()
        logger.info("Item inserted: id=%s name=%s", row[0], row[1])
        return {"id": row[0], "name": row[1]}
    except Exception:
        conn.rollback()
        logger.exception("Failed to insert item name=%s", body.name)
        raise HTTPException(status_code=500, detail="Failed to insert item")
    finally:
        pool.putconn(conn)


@app.get("/items", response_model=list[ItemResponse])
def list_items(limit: int = Query(default=50, ge=1, le=500)):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM items ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]
    except Exception:
        logger.exception("Failed to list items")
        raise HTTPException(status_code=500, detail="Failed to retrieve items")
    finally:
        pool.putconn(conn)
