"""
支付渠道实现注册
"""
from app.service.payment.provider import register_provider
from app.service.payment.providers.wxpay import WxPayProvider
from app.service.payment.providers.alipay import AlipayProvider
from app.service.payment.providers.easypay import EasyPayProvider

register_provider(WxPayProvider())
register_provider(AlipayProvider())
register_provider(EasyPayProvider())

__all__ = ["WxPayProvider", "AlipayProvider", "EasyPayProvider"]
