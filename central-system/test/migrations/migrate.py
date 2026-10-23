"""
数据库迁移脚本
执行SQL迁移文件
"""
import asyncio
import asyncpg
import sys
from pathlib import Path


async def run_migration():
    """执行数据库迁移"""

    # 数据库连接配置
    db_url = "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/postgres"
    db_name = "central_system"

    print(f"🔗 连接到PostgreSQL服务器...")

    try:
        # 连接到postgres数据库（默认数据库）
        conn = await asyncpg.connect(db_url)

        # 检查数据库是否存在
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )

        if not exists:
            print(f"📦 创建数据库: {db_name}")
            await conn.execute(f'CREATE DATABASE {db_name}')
        else:
            print(f"✅ 数据库 {db_name} 已存在")

        await conn.close()

        # 连接到目标数据库
        target_db_url = f"postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/{db_name}"
        conn = await asyncpg.connect(target_db_url)

        print(f"🔗 连接到数据库: {db_name}")

        # 读取并执行迁移脚本
        migrations_dir = Path(__file__).parent / "migrations"
        migration_files = sorted(migrations_dir.glob("*.sql"))

        for migration_file in migration_files:
            print(f"📄 执行迁移: {migration_file.name}")
            sql = migration_file.read_text(encoding='utf-8')

            # 分割SQL语句（简单处理，按分号分割）
            statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

            for statement in statements:
                if statement:
                    try:
                        await conn.execute(statement)
                    except Exception as e:
                        print(f"⚠️  警告: {e}")
                        # 继续执行，某些语句可能因为已存在而失败

            print(f"✅ 完成: {migration_file.name}")

        # 验证表是否创建成功
        tables = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)

        print(f"\n📊 当前数据库表:")
        for table in tables:
            print(f"  - {table['table_name']}")

        await conn.close()
        print(f"\n🎉 数据库迁移完成！")

    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_migration())
