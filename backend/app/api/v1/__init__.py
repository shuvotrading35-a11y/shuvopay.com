from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.device.router import router as device_router
from app.api.v1.sms.router import router as sms_router
from app.api.v1.invoice.router import router as invoice_router
from app.api.v1.webhook.router import router as webhook_router
from app.api.v1.merchant.router import router as merchant_router
from app.api.v1.admin.router import router as admin_router
from app.api.v1.websocket import router as ws_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(device_router)
router.include_router(sms_router)
router.include_router(invoice_router)
router.include_router(webhook_router)
router.include_router(merchant_router)
router.include_router(admin_router)
router.include_router(ws_router)
