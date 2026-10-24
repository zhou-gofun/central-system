-- 中心系统数据库迁移 - 支付模块
-- 数据库: PostgreSQL
-- 说明:
--   资金模式为「各业务平台自有商户号」：中心系统只做收银台 API、验签回调、
--   订单台账、幂等与发货通知，不归集资金，也不需要分账资质。

-- 1. 支付商户配置表（业务平台 × 支付渠道）
CREATE TABLE IF NOT EXISTS pay_merchant (
    id VARCHAR(26) PRIMARY KEY,
    app_code VARCHAR(32) NOT NULL,
    provider VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    mp_appid VARCHAR(50),
    status SMALLINT DEFAULT 1,
    remark VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE pay_merchant IS '支付商户配置表：业务平台×支付渠道';
COMMENT ON COLUMN pay_merchant.id IS 'ULID';
COMMENT ON COLUMN pay_merchant.app_code IS '归属的业务平台';
COMMENT ON COLUMN pay_merchant.provider IS '支付渠道 wxpay/alipay/easypay';
COMMENT ON COLUMN pay_merchant.name IS '商户配置名称，同平台同渠道下唯一';
COMMENT ON COLUMN pay_merchant.config IS '渠道参数(含密钥)，JSONB';
COMMENT ON COLUMN pay_merchant.mp_appid IS '关联公众号AppID(微信JSAPI用)';
COMMENT ON COLUMN pay_merchant.status IS '1=启用 0=禁用';
COMMENT ON COLUMN pay_merchant.remark IS '备注';
COMMENT ON COLUMN pay_merchant.created_at IS '创建时间';
COMMENT ON COLUMN pay_merchant.updated_at IS '更新时间';

CREATE UNIQUE INDEX idx_pay_merchant_unique ON pay_merchant(app_code, provider, name);
CREATE INDEX idx_pay_merchant_app ON pay_merchant(app_code, provider, status);


-- 2. 支付订单表
CREATE TABLE IF NOT EXISTS pay_order (
    id VARCHAR(26) PRIMARY KEY,
    out_trade_no VARCHAR(64) UNIQUE NOT NULL,
    client_order_no VARCHAR(64),
    app_code VARCHAR(32) NOT NULL,
    provider VARCHAR(20) NOT NULL,
    merchant_id VARCHAR(26),
    trade_type VARCHAR(20) NOT NULL,
    subject VARCHAR(200),
    description VARCHAR(500),
    amount NUMERIC(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'CNY',
    payer_openid VARCHAR(100),
    payer_id VARCHAR(100),
    pay_params JSONB,
    provider_trade_no VARCHAR(128),
    provider_prepay_id VARCHAR(128),
    status VARCHAR(20) DEFAULT 'PENDING',
    notify_status VARCHAR(20) DEFAULT 'PENDING',
    notify_count INTEGER DEFAULT 0,
    notified_at TIMESTAMP,
    paid_at TIMESTAMP,
    closed_at TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    attach VARCHAR(200),
    notify_url VARCHAR(500),
    provider_notify_url VARCHAR(500),
    provider_snapshot JSONB,
    extra JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE pay_order IS '支付订单台账';
COMMENT ON COLUMN pay_order.id IS 'ULID';
COMMENT ON COLUMN pay_order.out_trade_no IS '中心系统生成的商户订单号';
COMMENT ON COLUMN pay_order.client_order_no IS '业务平台自己的订单号(幂等用)';
COMMENT ON COLUMN pay_order.app_code IS '下单的业务平台';
COMMENT ON COLUMN pay_order.provider IS '支付渠道';
COMMENT ON COLUMN pay_order.merchant_id IS '使用的商户配置ID';
COMMENT ON COLUMN pay_order.trade_type IS 'jsapi/native/h5/app/page/wap/qr';
COMMENT ON COLUMN pay_order.subject IS '订单标题';
COMMENT ON COLUMN pay_order.description IS '订单描述';
COMMENT ON COLUMN pay_order.amount IS '订单金额(元)';
COMMENT ON COLUMN pay_order.currency IS '币种';
COMMENT ON COLUMN pay_order.payer_openid IS '付款人openid(JSAPI)';
COMMENT ON COLUMN pay_order.payer_id IS '付款人渠道用户ID(支付宝user_id等)';
COMMENT ON COLUMN pay_order.pay_params IS '前端拉起支付所需参数';
COMMENT ON COLUMN pay_order.provider_trade_no IS '渠道交易号';
COMMENT ON COLUMN pay_order.provider_prepay_id IS '渠道预支付ID';
COMMENT ON COLUMN pay_order.status IS 'PENDING/PAID/FAILED/CLOSED/REFUNDED/PARTIALLY_REFUNDED';
COMMENT ON COLUMN pay_order.notify_status IS 'PENDING/SUCCESS/FAILED 对业务平台的通知状态';
COMMENT ON COLUMN pay_order.notify_count IS '通知次数';
COMMENT ON COLUMN pay_order.notified_at IS '通知成功时间';
COMMENT ON COLUMN pay_order.paid_at IS '支付成功时间';
COMMENT ON COLUMN pay_order.closed_at IS '关单时间';
COMMENT ON COLUMN pay_order.expires_at IS '订单过期时间';
COMMENT ON COLUMN pay_order.attach IS '业务透传参数';
COMMENT ON COLUMN pay_order.notify_url IS '支付成功后通知业务平台的地址';
COMMENT ON COLUMN pay_order.provider_notify_url IS '提交给支付渠道的回调地址';
COMMENT ON COLUMN pay_order.provider_snapshot IS '下单时渠道关键参数快照(用于回调校验)';
COMMENT ON COLUMN pay_order.extra IS '扩展信息';
COMMENT ON COLUMN pay_order.created_at IS '创建时间';
COMMENT ON COLUMN pay_order.updated_at IS '更新时间';

CREATE INDEX idx_pay_order_out_trade_no ON pay_order(out_trade_no);
CREATE UNIQUE INDEX idx_pay_order_client_no ON pay_order(app_code, client_order_no);
CREATE INDEX idx_pay_order_app_status ON pay_order(app_code, status);
CREATE INDEX idx_pay_order_provider_trade ON pay_order(provider_trade_no);
CREATE INDEX idx_pay_order_created ON pay_order(created_at);


-- 3. 回调通知日志表（幂等）
CREATE TABLE IF NOT EXISTS pay_notify_log (
    id VARCHAR(26) PRIMARY KEY,
    provider VARCHAR(20) NOT NULL,
    event_id VARCHAR(128) NOT NULL,
    out_trade_no VARCHAR(64),
    provider_trade_no VARCHAR(128),
    event_type VARCHAR(50),
    result VARCHAR(20),
    message TEXT,
    raw_body TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE pay_notify_log IS '支付回调通知日志，用于幂等与排查';
COMMENT ON COLUMN pay_notify_log.id IS 'ULID';
COMMENT ON COLUMN pay_notify_log.provider IS '支付渠道';
COMMENT ON COLUMN pay_notify_log.event_id IS '渠道事件ID，同渠道唯一';
COMMENT ON COLUMN pay_notify_log.out_trade_no IS '中心系统订单号';
COMMENT ON COLUMN pay_notify_log.provider_trade_no IS '渠道交易号';
COMMENT ON COLUMN pay_notify_log.event_type IS '事件类型';
COMMENT ON COLUMN pay_notify_log.result IS 'SUCCESS/DUPLICATE/AMOUNT_MISMATCH/FAILED';
COMMENT ON COLUMN pay_notify_log.message IS '处理说明';
COMMENT ON COLUMN pay_notify_log.raw_body IS '原始报文';
COMMENT ON COLUMN pay_notify_log.created_at IS '创建时间';

CREATE UNIQUE INDEX idx_pay_notify_unique ON pay_notify_log(provider, event_id);
CREATE INDEX idx_pay_notify_order ON pay_notify_log(out_trade_no);


-- 4. 退款表
CREATE TABLE IF NOT EXISTS pay_refund (
    id VARCHAR(26) PRIMARY KEY,
    refund_no VARCHAR(64) UNIQUE NOT NULL,
    out_trade_no VARCHAR(64) NOT NULL,
    app_code VARCHAR(32) NOT NULL,
    provider VARCHAR(20) NOT NULL,
    provider_refund_no VARCHAR(128),
    amount NUMERIC(12,2) NOT NULL,
    total_amount NUMERIC(12,2) NOT NULL,
    reason VARCHAR(200),
    status VARCHAR(20) DEFAULT 'PENDING',
    notify_status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE pay_refund IS '退款单表';
COMMENT ON COLUMN pay_refund.id IS 'ULID';
COMMENT ON COLUMN pay_refund.refund_no IS '中心系统退款单号';
COMMENT ON COLUMN pay_refund.out_trade_no IS '原订单号';
COMMENT ON COLUMN pay_refund.app_code IS '业务平台';
COMMENT ON COLUMN pay_refund.provider IS '支付渠道';
COMMENT ON COLUMN pay_refund.provider_refund_no IS '渠道退款单号';
COMMENT ON COLUMN pay_refund.amount IS '退款金额(元)';
COMMENT ON COLUMN pay_refund.total_amount IS '原订单金额(元)';
COMMENT ON COLUMN pay_refund.reason IS '退款原因';
COMMENT ON COLUMN pay_refund.status IS 'PENDING/SUCCESS/FAILED';
COMMENT ON COLUMN pay_refund.notify_status IS '通知状态';
COMMENT ON COLUMN pay_refund.created_at IS '创建时间';
COMMENT ON COLUMN pay_refund.updated_at IS '更新时间';

CREATE INDEX idx_pay_refund_order ON pay_refund(out_trade_no);
CREATE INDEX idx_pay_refund_app ON pay_refund(app_code, status);
