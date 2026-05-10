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