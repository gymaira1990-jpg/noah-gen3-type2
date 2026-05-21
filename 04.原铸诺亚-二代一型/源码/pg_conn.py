#!/usr/bin/env python3
"""PG连接管理 · pg_conn.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 统一数据库连接入口
替代所有文件中的 psycopg2.connect() 硬编码
"""

import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "noah_prime",
    "user": "gcat",
}


@contextmanager
def connect(autocommit: bool = False):
    """统一连接上下文——自动关闭"""
    conn = psycopg2.connect(**DB_CONFIG)
    if autocommit:
        conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def cursor(autocommit: bool = False, dict_cursor: bool = False):
    """连接+游标上下文——自动提交+关闭"""
    conn = psycopg2.connect(**DB_CONFIG)
    if autocommit:
        conn.autocommit = True
    try:
        if dict_cursor:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        cur.close()
        conn.close()


def execute(sql: str, params: tuple = None):
    """单次执行——INSERT/UPDATE/DELETE"""
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def query(sql: str, params: tuple = None):
    """查询——返回dict列表"""
    with cursor(dict_cursor=True) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple = None) -> dict | None:
    """查询单行"""
    with cursor(dict_cursor=True) as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def health() -> bool:
    """快速健康检查"""
    try:
        with connect():
            return True
    except Exception:
        return False


def get_conn(autocommit: bool = False):
    """直接返回连接对象（非上下文管理器用）"""
    conn = psycopg2.connect(**DB_CONFIG)
    if autocommit:
        conn.autocommit = True
    return conn
