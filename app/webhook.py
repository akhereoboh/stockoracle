from fastapi import FastAPI, Request, HTTPException
from app.payments import verify_webhook_signature, upgrade_user, get_user, register_user
from app.config import PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN, TELEGRAM_BOT_TOKEN
import logging
import json
import httpx
from app.payments import reward_referrer

logger = logging.getLogger(__name__)
webhook_app = FastAPI()

async def send_telegram_message(telegram_id: int, text: str):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": telegram_id, "text": text}
            )
    except Exception as e:
        logger.error(f"Failed to send telegram message: {e}")

@webhook_app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not verify_webhook_signature(payload, signature):
        logger.warning("Invalid Paystack webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = json.loads(payload)
    event_type = event.get("event")
    logger.info(f"Paystack event: {event_type}")

    if event_type in ["charge.success", "subscription.create"]:
        data = event.get("data", {})
        metadata = data.get("metadata", {})
        telegram_id = metadata.get("telegram_id")
        email = data.get("customer", {}).get("email")
        plan_code = data.get("plan", {}).get("plan_code", "")

        logger.info(f"Payment: telegram_id={telegram_id}, plan={plan_code}")

        if telegram_id:
            tid = int(telegram_id)
            tier = "pro" if plan_code == PAYSTACK_PRO_PLAN else "basic"
            tier_name = "Pro" if tier == "pro" else "Basic"
            amount = "₦9,999" if tier == "pro" else "₦5,999"

            existing = get_user(tid)
            if not existing:
                register_user(tid, email or "user")

            upgrade_user(tid, tier, email)
            referrer_id = reward_referrer(tid)
            if referrer_id:
                await send_telegram_message(
                    referrer_id,
                    "🎁 Referral bonus! Someone you referred just subscribed.\n"
                    "7 free days have been added to your subscription automatically."
                )
            logger.info(f"User {tid} upgraded to {tier}")

            # send upgrade notification
            await send_telegram_message(
                tid,
                f"🎉 Payment confirmed! Your account has been upgraded to {tier_name}.\n\n"
                f"Plan: {tier_name} ({amount}/month)\n"
                f"You now have access to:\n"
                + ("- All 5 weekly signals every Monday\n"
                   "- Take profit and stop loss alerts\n"
                   "- Unlimited AI stock analysis\n"
                   + ("- Daily signals\n- Portfolio audit (/audit)\n" if tier == "pro" else "")
                   + "\nUse /signals to see this week's picks!")
            )

    return {"status": "ok"}

@webhook_app.get("/health")
async def health():
    return {"status": "running"}