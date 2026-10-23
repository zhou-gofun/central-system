"""
检查数据库中现有数据和ID格式
"""
import psycopg2

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"
DB_NAME = "central_system"

print("=" * 60)
print("检查现有数据和ID格式")
print("=" * 60)

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    cur = conn.cursor()

    tables = [
        'wechat_app',
        'wechat_mp_config',
        'wechat_scan_session'
    ]

    for table in tables:
        print(f"\n📊 表: {table}")
        print("-" * 60)

        # 检查表是否存在
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = %s
            )
        """, (table,))

        table_exists = cur.fetchone()[0]

        if not table_exists:
            print(f"  ⚠️  表不存在")
            continue

        # 统计记录数
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"  记录数: {count}")

        if count > 0:
            # 查看前5条记录的ID
            cur.execute(f"SELECT id FROM {table} LIMIT 5")
            ids = cur.fetchall()
            print(f"  示例ID:")
            for id_row in ids:
                id_val = id_row[0]
                print(f"    - {id_val} (长度: {len(id_val)})")

    cur.close()
    conn.close()

    print("\n" + "=" * 60)
    print("✅ 检查完成")

except psycopg2.OperationalError as e:
    print(f"❌ 无法连接到数据库: {e}")
    print("💡 可能原因:")
    print("  1. 数据库服务未运行")
    print("  2. 数据库还未创建")
    print("  3. 网络连接问题")
except Exception as e:
    print(f"❌ 错误: {e}")
