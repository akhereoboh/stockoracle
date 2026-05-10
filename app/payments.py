import httpx
import hmac
import hashlib
import logging
from app.config import PAYSTACK_SECRET_KEY, PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN
from app.database import supabase
from datetime import datetime, UTC, timedelta


logger = logging.getLogger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"

def create_subscription_link(email: str, plan_code: str, telegram_id: int) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "email": email,
            "plan": plan_code,
            "metadata": {
                "telegram_id": str(telegram_id)
            }
        }
        logger.info(f"Paystack request: email={email}, plan={plan_code}, telegram_id={telegram_id}")
        response = httpx.post(
            f"{PAYSTACK_BASE}/transaction/initialize",
            json=data,
            headers=headers,
            timeout=30
        )
        logger.info(f"Paystack status: {response.status_code}")
        logger.info(f"Paystack response: {response.text}")
        result = response.json()
        if result.get("status"):
            return result["data"]["authorization_url"]
        return None
    except Exception as e:
        logger.error(f"Paystack link error: {e}")
        return None

def verify_transaction(reference: str) -> dict:
    try:
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        response = httpx.get(
            f"{PAYSTACK_BASE}/transaction/verify/{reference}",
            headers=headers
        )
        return response.json()
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return {}

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    computed = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha512
    ).hexdigest()
    return computed == signature

def upgrade_user(telegram_id: int, tier: str, email: str = None):
    try:
        
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        
        existing = supabase.table("users")\
            .select("id")\
            .eq("telegram_id", telegram_id)\
            .execute()
        
        if existing.data:
            supabase.table("users").update({
                "tier": tier,
                "subscribed_at": datetime.now(UTC).isoformat(),
                "expires_at": expires_at
            }).eq("telegram_id", telegram_id).execute()
        else:
            supabase.table("users").insert({
                "telegram_id": telegram_id,
                "tier": tier,
                "email": email,
                "subscribed_at": datetime.now(UTC).isoformat(),
                "expires_at": expires_at
            }).execute()
        
        logger.info(f"Upgraded user {telegram_id} to {tier}")
    except Exception as e:
        logger.error(f"Upgrade error: {e}")

def get_user(telegram_id: int) -> dict:
    try:
        result = supabase.table("users")\
            .select("*")\
            .eq("telegram_id", telegram_id)\
            .execute()
        return result.data[0] if result.data else None
    except:
        return None

def register_user(telegram_id: int, name: str) -> dict:
    try:
        existing = get_user(telegram_id)
        if existing:
            return existing
        
        supabase.table("users").insert({
            "telegram_id": telegram_id,
            "name": name,
            "tier": "free"
        }).execute()
        
        return get_user(telegram_id)
    except Exception as e:
        logger.error(f"Register error: {e}")
        return None