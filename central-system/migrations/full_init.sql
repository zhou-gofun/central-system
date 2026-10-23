-- =====================================================
-- 中心系统数据库完整初始化脚本
-- 包含：表结构 + 示例数据
--
-- 执行方式：
-- psql "postgresql://postgres:d5rtwm47@central-system-db-postgresql.ns-2z3k0kqh.svc:5432/central_system" -f migrations/full_init.sql
-- =====================================================

-- 1. 业务应用表
CREATE TABLE IF NOT EXISTS wechat_app (
    id VARCHAR(26) PRIMARY KEY,
    app_code VARCHAR(32) UNIQUE NOT NULL,
    app_name VARCHAR(100),
    app_secret VARCHAR(64) NOT NULL,
    mp_appid VARCHAR(50),
    callback_url VARCHAR(500),
    status SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE wechat_app IS '业务应用表';
COMMENT ON COLUMN wechat_app.id IS 'ULID';
COMMENT ON COLUMN wechat_app.app_code IS '应用标识 如jgweb_prod';
COMMENT ON COLUMN wechat_app.app_name IS '应用名称';
COMMENT ON COLUMN wechat_app.app_secret IS '应用密钥';
COMMENT ON COLUMN wechat_app.mp_appid IS '绑定的公众号AppID';
COMMENT ON COLUMN wechat_app.callback_url IS '回调地址(可选)';
COMMENT ON COLUMN wechat_app.status IS '1=启用 0=禁用';
COMMENT ON COLUMN wechat_app.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_wechat_app_code ON wechat_app(app_code);


-- 2. 扫码会话表
CREATE TABLE IF NOT EXISTS wechat_scan_session (
    id VARCHAR(26) PRIMARY KEY,
    scene_key VARCHAR(64) UNIQUE NOT NULL,
    app_code VARCHAR(32) NOT NULL,
    mp_appid VARCHAR(50),
    purpose VARCHAR(20) NOT NULL,
    openid VARCHAR(100),
    unionid VARCHAR(100),
    nickname VARCHAR(100),
    headimgurl TEXT,
    status SMALLINT DEFAULT 0,
    extra_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expired_at TIMESTAMP NOT NULL
);

COMMENT ON TABLE wechat_scan_session IS '扫码会话表';
COMMENT ON COLUMN wechat_scan_session.id IS 'ULID';
COMMENT ON COLUMN wechat_scan_session.scene_key IS '场景值';
COMMENT ON COLUMN wechat_scan_session.app_code IS '来源应用';
COMMENT ON COLUMN wechat_scan_session.mp_appid IS '公众号AppID';
COMMENT ON COLUMN wechat_scan_session.purpose IS 'login/register/bind';
COMMENT ON COLUMN wechat_scan_session.openid IS '微信openid';
COMMENT ON COLUMN wechat_scan_session.unionid IS '微信unionid';
COMMENT ON COLUMN wechat_scan_session.nickname IS '微信昵称';
COMMENT ON COLUMN wechat_scan_session.headimgurl IS '头像URL';
COMMENT ON COLUMN wechat_scan_session.status IS '0=待扫码 1=已扫码 2=已消费';
COMMENT ON COLUMN wechat_scan_session.extra_data IS '额外数据';
COMMENT ON COLUMN wechat_scan_session.created_at IS '创建时间';
COMMENT ON COLUMN wechat_scan_session.expired_at IS '过期时间';

CREATE INDEX IF NOT EXISTS idx_scan_scene_key ON wechat_scan_session(scene_key);
CREATE INDEX IF NOT EXISTS idx_scan_app_status ON wechat_scan_session(app_code, status);
CREATE INDEX IF NOT EXISTS idx_scan_expired ON wechat_scan_session(expired_at);


-- 3. 公众号配置表
CREATE TABLE IF NOT EXISTS wechat_mp_config (
    id VARCHAR(26) PRIMARY KEY,
    appid VARCHAR(50) UNIQUE NOT NULL,
    secret VARCHAR(100) NOT NULL,
    token VARCHAR(100) NOT NULL,
    aes_key VARCHAR(100),
    name VARCHAR(100),
    status SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE wechat_mp_config IS '微信公众号配置表';
COMMENT ON COLUMN wechat_mp_config.id IS 'ULID';
COMMENT ON COLUMN wechat_mp_config.appid IS '公众号AppID';
COMMENT ON COLUMN wechat_mp_config.secret IS '公众号Secret';
COMMENT ON COLUMN wechat_mp_config.token IS '微信Token';
COMMENT ON COLUMN wechat_mp_config.aes_key IS '消息加密密钥';
COMMENT ON COLUMN wechat_mp_config.name IS '公众号名称';
COMMENT ON COLUMN wechat_mp_config.status IS '1=启用 0=禁用';
COMMENT ON COLUMN wechat_mp_config.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_mp_appid ON wechat_mp_config(appid);


-- =====================================================
-- 示例数据（可选）
-- =====================================================

-- 插入示例公众号配置
-- 注意：请替换为实际的公众号信息
INSERT INTO wechat_mp_config (id, appid, secret, token, name, status)
VALUES (
    '01HZTEST0000000000000001',
    'wx1234567890abcdef',
    'your_mp_secret_here',
    'your_token_here',
    '测试公众号',
    1
) ON CONFLICT (appid) DO NOTHING;

-- 插入示例业务应用
-- jgweb_prod 生产环境
INSERT INTO wechat_app (id, app_code, app_name, app_secret, mp_appid, status)
VALUES (
    '01HZTEST0000000000000002',
    'jgweb_prod',
    '监管平台-生产环境',
    'prod_secret_change_me',
    'wx1234567890abcdef',
    1
) ON CONFLICT (app_code) DO NOTHING;

-- jgweb_test 测试环境
INSERT INTO wechat_app (id, app_code, app_name, app_secret, mp_appid, status)
VALUES (
    '01HZTEST0000000000000003',
    'jgweb_test',
    '监管平台-测试环境',
    'test_secret_change_me',
    'wx1234567890abcdef',
    1
) ON CONFLICT (app_code) DO NOTHING;


-- =====================================================
-- 验证
-- =====================================================
-- 显示所有创建的表
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;
