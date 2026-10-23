-- 示例数据插入脚本

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
