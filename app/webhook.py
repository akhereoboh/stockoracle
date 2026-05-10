from fastapi import FastAPI, Request, HTTPException
from app.payments import verify_webhook_signature, upgrade_user, get_user, register_user
from app.config import PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN
import logging
import json

logger = logging.getLogger(__name__)

webhook_app = FastAPI()

@webhook_app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    
    if not verify_webhook_signature(payload, signature):
        logger.warning("Invalid Paystack webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    event = json.loads(payload)
    event_type = event.get("event")
    logger.info(f"Paystack event received: {event_type}")
    
    if event_type in ["charge.success", "subscription.create"]:
        data = event.get("data", {})
        metadata = data.get("metadata", {})
        telegram_id = metadata.get("telegram_id")
        email = data.get("customer", {}).get("email")
        plan_code = data.get("plan", {}).get("plan_code", "")
        
        logger.info(f"Payment data: telegram_id={telegram_id}, email={email}, plan={plan_code}")
        
        if telegram_id:
            tid = int(telegram_id)
            tier = "pro" if plan_code == PAYSTACK_PRO_PLAN else "basic"
            
            existing = get_user(tid)
            if not existing:
                register_user(tid, email or "user")
            
            upgrade_user(tid, tier, email)
            logger.info(f"User {tid} upgraded to {tier}")
    
    return {"status": "ok"}

@webhook_app.get("/health")
async def health():
    return {"status": "running"}