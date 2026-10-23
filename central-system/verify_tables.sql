-- =========================================
-- 直接在数据库工具中执行此SQL验证
-- =========================================

-- 1. 首先，列出所有数据库
SELECT datname AS "数据库名称"
FROM pg_database
WHERE datistemplate = false
ORDER BY datname;

-- 2. 切换到 central_system 数据库后，执行以下查询

-- 查看所有表
SELECT
    schemaname AS "Schema",
    tablename AS "表名"
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- 查看 wechat 相关的表
SELECT table_name AS "表名",
       (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) AS "列数"
FROM information_schema.tables t
WHERE table_schema = 'public'
  AND table_name LIKE 'wechat%'
ORDER BY table_name;

-- 查看表数据
SELECT '=== wechat_app ===' AS info;
SELECT * FROM wechat_app;

SELECT '=== wechat_mp_config ===' AS info;
SELECT * FROM wechat_mp_config;

SELECT '=== wechat_scan_session ===' AS info;
SELECT COUNT(*) AS "会话数量" FROM wechat_scan_session;
