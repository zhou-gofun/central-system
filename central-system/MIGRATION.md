# 数据库迁移指南

## 方式一：使用 SQLAlchemy ORM（推荐 - 最简单）

项目使用 SQLAlchemy ORM，可以直接通过 Python 脚本创建表：

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 使用 ORM 创建表
python3 init_db.py create

# 这会自动：
# - 创建数据库（如果不存在）
# - 根据模型定义创建所有表
# - 显示创建的表列表
```

**注意**：使用此方式不会插入示例数据，需要手动插入或执行 `migrations/002_sample_data.sql`

## 方式二：使用 psql 客户端（传统 SQL 方式）

如果你的环境中有 psql 命令：

```bash
# 1. 创建数据库（如果不存在）
psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/postgres" -c "CREATE DATABASE central_system;"

# 2. 执行初始化脚本
psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system" -f migrations/001_init.sql

# 3. 执行示例数据脚本（可选）
psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system" -f migrations/002_sample_data.sql

# 4. 验证表是否创建成功
psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system" -c "\dt"
```

## 方式三：使用 Python 自动迁移脚本

如果你有 Python 和 asyncpg 库：

```bash
# 1. 安装依赖
pip install asyncpg

# 2. 运行迁移脚本
python3 migrate.py
```

## 方式四：使用数据库管理工具

使用 DBeaver、pgAdmin、Navicat 等图形化工具：

1. 连接信息：
   - Host: central-system-db-postgresql.ns-2z3k0kqh.svc
   - Port: 5432
   - Database: postgres（初始连接）
   - Username: postgres
   - Password: d5rtwm47

2. 创建数据库 `central_system`

3. 连接到 `central_system` 数据库

4. 依次执行以下SQL文件：
   - migrations/001_init.sql
   - migrations/002_sample_data.sql

## 方式五：使用 kubectl（如果在 Kubernetes 环境）

```bash
# 1. 找到 PostgreSQL Pod
kubectl get pods -n ns-2z3k0kqh | grep central-system-db

# 2. 进入 Pod
kubectl exec -it <pod-name> -n ns-2z3k0kqh -- bash

# 3. 在 Pod 内执行
psql -U postgres -c "CREATE DATABASE central_system;"
psql -U postgres -d central_system -f /path/to/001_init.sql
```

## 验证迁移成功

执行以下SQL检查表是否创建成功：

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

应该看到以下表：
- wechat_app
- wechat_mp_config
- wechat_scan_session
