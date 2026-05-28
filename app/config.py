from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_BASIC_PLAN = os.getenv("PAYSTACK_BASIC_PLAN")
PAYSTACK_PRO_PLAN = os.getenv("PAYSTACK_PRO_PLAN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://sireai.uk")

FLUTTERWAVE_SECRET_KEY = os.getenv("FLUTTERWAVE_SECRET_KEY")
FLUTTERWAVE_SECRET_HASH = os.getenv("FLUTTERWAVE_SECRET_HASH")
KORAPAY_SECRET_KEY = os.getenv("KORAPAY_SECRET_KEY")

BAMBOO_API_KEY = os.getenv("BAMBOO_API_KEY")
BAMBOO_BASE_URL = os.getenv("BAMBOO_BASE_URL", "https://powered-by-bamboo-sandbox.investbamboo.com")