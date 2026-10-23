"""
生成详细的数据库表报告
"""
import psycopg2

DB_HOST = "central-system-db-postgresql.ns-2z3k0kqh.svc"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "d5rtwm47"
DB_NAME = "central_system"

conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME
)
cur = conn.cursor()

print("=" * 80)
print("中心系统数据库表详细报告")
print("=" * 80)
print(f"\n数据库: {DB_NAME}")
print(f"连接: postgresql://{DB_USER}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}\n")
print("=" * 80)

# 获取微信相关的表
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name LIKE 'wechat%'
    ORDER BY table_name
""")
tables = cur.fetchall()

print(f"\n找到 {len(tables)} 个表:\n")

for idx, (table_name,) in enumerate(tables, 1):
    print(f"{idx}. {table_name}")
    print("-" * 80)

    # 获取表的列信息
    cur.execute(f"""
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = '{table_name}'
        ORDER BY ordinal_position
    """)
    columns = cur.fetchall()

    print(f"   列数: {len(columns)}\n")
    print(f"   {'列名':<25} {'类型':<30} {'可空':<10} {'默认值'}")
    print("   " + "-" * 75)

    for col_name, data_type, max_len, nullable, default in columns:
        type_str = data_type
        if max_len:
            type_str = f"{data_type}({max_len})"
        nullable_str = "YES" if nullable == "YES" else "NO"
        default_str = str(default)[:30] if default else ""
        print(f"   {col_name:<25} {type_str:<30} {nullable_str:<10} {default_str}")

    # 获取索引信息
    cur.execute(f"""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        AND tablename = '{table_name}'
        ORDER BY indexname
    """)
    indexes = cur.fetchall()

    if indexes:
        print(f"\n   索引 ({len(indexes)} 个):")
        for idx_name, idx_def in indexes:
            print(f"   - {idx_name}")

    # 获取行数
    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cur.fetchone()[0]
    print(f"\n   数据行数: {count}")

    # 如果有数据，显示示例
    if count > 0:
        cur.execute(f"SELECT * FROM {table_name} LIMIT 3")
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]

        print(f"\n   示例数据 (前3条):")
        for row in rows:
            print(f"\n   记录:")
            for col_name, value in zip(col_names, row):
                if value is not None:
                    value_str = str(value)[:50]
                    print(f"     {col_name}: {value_str}")

    print("\n" + "=" * 80 + "\n")

cur.close()
conn.close()

print("✅ 报告生成完成！")
print("\n连接信息:")
print(f"  数据库名: {DB_NAME}")
print(f"  Schema: public")
print(f"  完整表名: public.wechat_app, public.wechat_mp_config, public.wechat_scan_session")
print("\n如果在工具中看不到表，请确认:")
print("  1. 连接的数据库是 'central_system' (不是 'postgres')")
print("  2. 查看的 schema 是 'public'")
print("  3. 刷新数据库连接或表列表")
