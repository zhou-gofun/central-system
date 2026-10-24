"""
容器启动时的数据库初始化脚本

- 等待 PostgreSQL 就绪
- 按 ORM 模型创建表结构（幂等，已存在则跳过）

只建表结构，不写入示例数据。
"""
import asyncio
import os
import sys
import time

from sqlalchemy import select, text

from app.common.database import engine, Base
from app.model import WechatApp, WechatMpConfig, ScanSession  # noqa: F401  注册模型

DB_NAME = os.getenv("DB_NAME", "central_system")
MAX_WAIT = 120


async def wait_for_db() -> None:
    """等待数据库可连接"""
    deadline = time.time() + MAX_WAIT
    attempt = 0
    while True:
        attempt += 1
        try:
            async with engine.connect() as conn:
                await conn.execute(select(1))
            print(f"[init_db] 数据库连接成功 (第 {attempt} 次尝试)")
            return
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                print(f"[init_db] 等待数据库超时: {exc}", file=sys.stderr)
                raise
            print(f"[init_db] 等待数据库就绪 ({exc})...")
            await asyncio.sleep(2)


async def create_tables() -> None:
    """按 ORM 模型建表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        )
        tables = sorted(row[0] for row in result)

    print(f"[init_db] 数据库 {DB_NAME} 表结构已就绪: {', '.join(tables)}")


async def main() -> None:
    await wait_for_db()
    await create_tables()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
