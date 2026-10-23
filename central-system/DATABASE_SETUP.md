# 数据库迁移操作指南

## 当前状态

项目已完成开发，数据库迁移脚本已准备就绪，但当前环境缺少必要的工具。

### 已准备好的文件：

1. **ORM 模型** - 已统一使用 Base 类
   - `app/model/wechat/app.py` - WechatApp
   - `app/model/wechat/mp_config.py` - WechatMpConfig
   - `app/model/wechat/session.py` - ScanSession

2. **迁移脚本**
   - `migrations/001_init.sql` - 表结构定义
   - `migrations/002_sample_data.sql` - 示例数据
   - `migrations/full_init.sql` - 完整初始化（推荐）

3. **自动化工具**
   - `init_db.py` - ORM 方式创建表
   - `migrate.py` - 自动执行 SQL 脚本
   - `init_db_simple.py` - 简化版脚本

## 执行迁移的步骤

### 方案 A：在有数据库工具的环境执行（推荐）

如果你在本地开发机器或服务器上：

```bash
# 1. 安装 PostgreSQL 客户端
sudo apt install postgresql-client  # Ubuntu/Debian
# 或
brew install postgresql  # macOS

# 2. 执行迁移
psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/postgres" \
  -c "CREATE DATABASE central_system;"

psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system" \
  -f migrations/full_init.sql

# 3. 验证
psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system" \
  -c "\dt"
```

### 方案 B：使用 Python ORM 方式

如果你有 Python 环境：

```bash
# 1. 创建虚拟环境（如果需要）
python3 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行 ORM 初始化
python3 init_db.py create

# 这会自动根据模型定义创建所有表
```

### 方案 C：使用数据库 GUI 工具

1. 下载并安装以下任一工具：
   - DBeaver (https://dbeaver.io/)
   - pgAdmin (https://www.pgadmin.org/)
   - Navicat
   - DataGrip

2. 连接信息：
   ```
   Host: central-system-db-postgresql.ns-2z3k0kqh.svc
   Port: 5432
   Database: postgres (初始连接)
   Username: postgres
   Password: d5rtwm47
   ```

3. 步骤：
   - 连接到 postgres 数据库
   - 执行: `CREATE DATABASE central_system;`
   - 切换到 central_system 数据库
   - 打开 `migrations/full_init.sql`
   - 执行 SQL 脚本

### 方案 D：使用 Docker 容器

如果数据库在 Docker 中：

```bash
# 1. 找到 PostgreSQL 容器
docker ps | grep postgres

# 2. 进入容器
docker exec -it <container-id> bash

# 3. 在容器内执行
psql -U postgres -c "CREATE DATABASE central_system;"

# 4. 复制 SQL 文件到容器
docker cp migrations/full_init.sql <container-id>:/tmp/

# 5. 执行 SQL
docker exec -it <container-id> psql -U postgres -d central_system -f /tmp/full_init.sql
```

### 方案 E：使用 Kubernetes

如果在 K8s 环境：

```bash
# 1. 找到 PostgreSQL Pod
kubectl get pods -n ns-2z3k0kqh | grep central-system-db

# 2. 执行迁移
kubectl exec -it <pod-name> -n ns-2z3k0kqh -- \
  psql -U postgres -c "CREATE DATABASE central_system;"

# 3. 复制 SQL 文件
kubectl cp migrations/full_init.sql ns-2z3k0kqh/<pod-name>:/tmp/

# 4. 执行 SQL
kubectl exec -it <pod-name> -n ns-2z3k0kqh -- \
  psql -U postgres -d central_system -f /tmp/full_init.sql
```

## 验证迁移成功

执行以下命令检查表是否创建：

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

应该看到：
- wechat_app
- wechat_mp_config
- wechat_scan_session

## 下一步

迁移完成后：

1. 更新示例数据中的配置信息（公众号 AppID、Secret、Token）
2. 创建业务应用记录（app_code、app_secret）
3. 启动中心系统服务：
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
4. 访问 API 文档：http://localhost:8000/docs

## 常见问题

### Q: 连接不上数据库？
A: 检查网络连接，确保可以访问 `central-system-db-postgresql.ns-2z3k0kqh.svc:5432`

### Q: 提示数据库已存在？
A: 正常，脚本会跳过已存在的对象

### Q: 想重新创建表？
A: 先删除数据库：`DROP DATABASE central_system;` 然后重新执行迁移

### Q: 使用 ORM 方式创建表后没有示例数据？
A: 需要手动执行 `migrations/002_sample_data.sql` 或使用 `full_init.sql`
