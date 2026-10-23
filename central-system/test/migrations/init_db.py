"""
使用 SQLAlchemy ORM 初始化数据库表结构

这是 SQL 脚本迁移的替代方案
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.common.database import engine, Base
from app.common.config import settings

# 导入所有模型（必须在创建表之前导入）
import app.model  # noqa


async def init_database():
    """使用 ORM 创建所有表"""

    print(f"🔗 连接到数据库: {settings.DATABASE_URL}")
    print(f"📦 准备创建表结构...")

    try:
        # 创建所有表
        async with engine.begin() as conn:
            # 删除所有表（慎用！仅用于开发环境）
            # await conn.run_sync(Base.metadata.drop_all)

            # 创建所有表
            await conn.run_sync(Base.metadata.create_all)

        print(f"✅ 表结构创建成功！")

        # 显示已创建的表
        print(f"\n📊 已创建的表:")
        for table_name in Base.metadata.tables.keys():
            print(f"  - {table_name}")

    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)
    finally:
        await engine.dispose()


async def drop_all_tables():
    """删除所有表（危险操作！）"""
    print(f"⚠️  警告: 即将删除所有表!")
    confirm = input("确认删除所有表? 输入 'yes' 确认: ")

    if confirm.lower() != 'yes':
        print("操作已取消")
        return

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        print(f"✅ 所有表已删除")
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="数据库表管理工具")
    parser.add_argument(
        "action",
        choices=["create", "drop"],
        help="操作类型: create=创建表, drop=删除表"
    )

    args = parser.parse_args()

    if args.action == "create":
        asyncio.run(init_database())
    elif args.action == "drop":
        asyncio.run(drop_all_tables())
