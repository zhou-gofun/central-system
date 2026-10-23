"""
直接使用 psycopg2 执行 SQL 初始化（不需要额外安装包）
"""
import sys

# 检查是否有 psycopg2
try:
    import psycopg2
except ImportError:
    print("❌ 错误: 需要安装 psycopg2")
    print("请运行: apt install python3-psycopg2")
    sys.exit(1)

# 数据库连接配置
DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"
DB_NAME = "central_system"


def init_database():
    """初始化数据库"""

    print(f"🔗 连接到 PostgreSQL...")

    # 首先连接到默认的 postgres 数据库
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database="postgres"
        )
        conn.autocommit = True
        cur = conn.cursor()

        # 检查数据库是否存在
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        exists = cur.fetchone()

        if not exists:
            print(f"📦 创建数据库: {DB_NAME}")
            cur.execute(f'CREATE DATABASE {DB_NAME}')
        else:
            print(f"✅ 数据库 {DB_NAME} 已存在")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ 创建数据库失败: {e}")
        sys.exit(1)

    # 连接到目标数据库并创建表
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cur = conn.cursor()

        print(f"📄 读取 SQL 脚本...")

        # 读取并执行 SQL 脚本
        with open('migrations/full_init.sql', 'r', encoding='utf-8') as f:
            sql = f.read()

        print(f"🔧 执行 SQL 脚本...")
        cur.execute(sql)
        conn.commit()

        # 验证表
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cur.fetchall()

        print(f"\n✅ 数据库初始化完成！")
        print(f"\n📊 已创建的表:")
        for table in tables:
            print(f"  - {table[0]}")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"❌ 执行 SQL 失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    init_database()
