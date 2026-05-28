import httpx
import logging
from app.config import BAMBOO_API_KEY, BAMBOO_BASE_URL
from app.database import supabase

logger = logging.getLogger(__name__)

# Bamboo sandbox: https://powered-by-bamboo-sandbox.investbamboo.com
# Bamboo live: https://powered-by-bamboo.investbamboo.com

class BambooClient:
    def __init__(self):
        self.base_url = BAMBOO_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {BAMBOO_API_KEY}",
            "Content-Type": "application/json"
        }

    async def create_account(self, user_data: dict) -> dict:
        """Create a Bamboo brokerage account for a user"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/one_step_registration",
                    json=user_data,
                    headers=self.headers,
                    timeout=30
                )
                return response.json()
        except Exception as e:
            logger.error(f"Bamboo create account error: {e}")
            return None

    async def get_portfolio(self, bamboo_account_id: str) -> dict:
        """Get user's portfolio"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/portfolio/{bamboo_account_id}",
                    headers=self.headers,
                    timeout=30
                )
                return response.json()
        except Exception as e:
            logger.error(f"Bamboo portfolio error: {e}")
            return None

    async def place_order(self, bamboo_account_id: str, ticker: str, 
                         amount: float, order_type: str = "buy") -> dict:
        """Place a buy or sell order"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/orders",
                    json={
                        "account_id": bamboo_account_id,
                        "symbol": ticker,
                        "amount": amount,
                        "type": order_type,
                        "market": "NGX"
                    },
                    headers=self.headers,
                    timeout=30
                )
                result = response.json()
                logger.info(f"Order placed: {ticker} {order_type} ${amount} — {result}")
                return result
        except Exception as e:
            logger.error(f"Bamboo order error: {e}")
            return None

    async def get_account_balance(self, bamboo_account_id: str) -> float:
        """Get available cash balance"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/portfolio/{bamboo_account_id}",
                    headers=self.headers,
                    timeout=30
                )
                data = response.json()
                return data.get("cash", 0)
        except Exception as e:
            logger.error(f"Bamboo balance error: {e}")
            return 0

bamboo = BambooClient()