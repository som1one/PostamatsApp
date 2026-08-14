import asyncio
import logging
import sys
from decimal import Decimal

# Set up logging to console
logging.basicConfig(level=logging.INFO)

from backend.utils.yookassa_service import (
    create_yookassa_preauth_payment,
    cancel_yookassa_payment,
)
from backend.core.settings import settings

async def main():
    print(f"Using Shop ID: {settings.YOOKASSA_SHOP_ID}")
    print(f"Using Secret Key: {settings.YOOKASSA_SECRET_KEY[:5]}***")
    print(f"Dev Stub Mode: {settings.YOOKASSA_DEV_STUB}")
    
    if settings.YOOKASSA_DEV_STUB:
        print("ERROR: YOOKASSA_DEV_STUB is still true!")
        sys.exit(1)

    print("\n--- Testing Payment Creation ---")
    try:
        payment = await create_yookassa_preauth_payment(
            amount_value=Decimal("10.00"),
            currency="RUB",
            return_url="http://127.0.0.1:3001/payment/return",
            metadata={"test": "true"}
        )
        print("Payment created successfully!")
        print(f"Payment ID: {payment['provider_payment_id']}")
        print(f"Status: {payment['status']}")
        print(f"Confirmation URL: {payment['confirmation_url']}")
        
        print("\n--- Testing Payment Cancellation ---")
        cancel_result = await cancel_yookassa_payment(payment["provider_payment_id"])
        print("Payment cancelled successfully!")
        print(f"Cancel Status: {cancel_result['status']}")

    except Exception as e:
        print(f"Error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
