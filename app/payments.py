import httpx
import hmac
import hashlib
import logging
from app.config import PAYSTACK_SECRET_KEY, PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN
from app.database import supabase
from datetime import datetime, UTC, timedelta
import random
import string


logger = logging.getLogger(__name__)

PAYSTACK_BASE = "https://api.paystack.co"

def create_subscription_link(email: str, plan_code: str, telegram_id: int) -> str:
    try:
        # determine amount from plan code
        from app.config import PAYSTACK_BASIC_PLAN, PAYSTACK_PRO_PLAN
        if plan_code == PAYSTACK_BASIC_PLAN:
            amount = 599900  # ₦5,999 in kobo
        else:
            amount = 999900  # ₦9,999 in kobo

        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "email": email,
            "amount": amount,
            "plan": plan_code,
            "metadata": {
                "telegram_id": str(telegram_id)
            }
        }
        logger.info(f"Paystack request: email={email}, plan={plan_code}, amount={amount}")
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
    

def generate_referral_code(telegram_id: int) -> str:
    return f"SO{str(telegram_id)[-4:]}{random.choices(string.ascii_uppercase, k=3)[0]}"

def get_or_create_referral_code(telegram_id: int) -> str:
    user = get_user(telegram_id)
    if not user:
        return None
    
    if user.get("referral_code"):
        return user["referral_code"]
    
    code = generate_referral_code(telegram_id)
    supabase.table("users").update({
        "referral_code": code
    }).eq("telegram_id", telegram_id).execute()
    
    return code

def process_referral(referred_id: int, referral_code: str):
    try:
        referrer = supabase.table("users")\
            .select("telegram_id")\
            .eq("referral_code", referral_code)\
            .execute()
        
        if not referrer.data:
            return
        
        referrer_id = referrer.data[0]["telegram_id"]
        
        if referrer_id == referred_id:
            return
        
        supabase.table("referrals").insert({
            "referrer_id": referrer_id,
            "referred_id": referred_id
        }).execute()
        
        supabase.table("users").update({
            "referred_by": referral_code
        }).eq("telegram_id", referred_id).execute()
        
        logger.info(f"Referral recorded: {referred_id} referred by {referrer_id}")
    except Exception as e:
        logger.error(f"Referral error: {e}")

def reward_referrer(referred_id: int):
    try:
        referral = supabase.table("referrals")\
            .select("*")\
            .eq("referred_id", referred_id)\
            .eq("converted", False)\
            .execute()
        
        if not referral.data:
            return
        
        referrer_id = referral.data[0]["referrer_id"]
        
        # add 7 bonus days to referrer
        referrer = get_user(referrer_id)
        if referrer and referrer.get("expires_at"):
            from datetime import timedelta
            exp = datetime.fromisoformat(referrer["expires_at"].replace("Z", "+00:00"))
            new_exp = exp + timedelta(days=7)
            supabase.table("users").update({
                "expires_at": new_exp.isoformat()
            }).eq("telegram_id", referrer_id).execute()
        
        supabase.table("referrals").update({
            "converted": True
        }).eq("referred_id", referred_id).execute()
        
        logger.info(f"Referrer {referrer_id} rewarded 7 days for referring {referred_id}")
        return referrer_id
    except Exception as e:
        logger.error(f"Reward referrer error: {e}")
        return None

def create_flutterwave_link(email: str, plan: str, telegram_id: int) -> str:
    try:
        from app.config import FLUTTERWAVE_SECRET_KEY
        amount = 9999 if plan == "pro" else 5999
        tier_name = "Pro" if plan == "pro" else "Basic"
        
        headers = {
            "Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "tx_ref": f"SO_{telegram_id}_{int(datetime.now(UTC).timestamp())}",
            "amount": amount,
            "currency": "NGN",
            "redirect_url": "https://sireai.uk",
            "customer": {"email": email},
            "meta": {
                "telegram_id": str(telegram_id),
                "plan": plan
            },
            "customizations": {
                "title": f"StockOracle {tier_name}",
                "description": f"StockOracle {tier_name} subscription"
            }
        }
        response = httpx.post(
            "https://api.flutterwave.com/v3/payments",
            json=data,
            headers=headers,
            timeout=30
        )
        result = response.json()
        logger.info(f"Flutterwave response: {result}")
        if result.get("status") == "success":
            return result["data"]["link"]
        return None
    except Exception as e:
        logger.error(f"Flutterwave error: {e}")
        return None

def create_korapay_link(email: str, plan: str, telegram_id: int) -> str:
    try:
        from app.config import KORAPAY_SECRET_KEY
        amount = 9999 if plan == "pro" else 5999
        tier_name = "Pro" if plan == "pro" else "Basic"
        
        headers = {
            "Authorization": f"Bearer {KORAPAY_SECRET_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "amount": amount,
            "currency": "NGN",
            "reference": f"SO_{telegram_id}_{int(datetime.now(UTC).timestamp())}",
            "customer": {"email": email, "name": email},
            "metadata": {
                "telegram_id": str(telegram_id),
                "plan": plan
            },
            "notification_url": "https://sireai.uk/webhook/korapay",
            "merchant_bears_cost": False
        }
        response = httpx.post(
            "https://api.korapay.com/merchant/api/v1/charges/initialize",
            json=data,
            headers=headers,
            timeout=30
        )
        result = response.json()
        logger.info(f"Korapay response: {result}")
        if result.get("status"):
            return result["data"]["checkout_url"]
        return None
    except Exception as e:
        logger.error(f"Korapay error: {e}")
        return None