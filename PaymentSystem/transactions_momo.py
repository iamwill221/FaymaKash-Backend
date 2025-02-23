import requests
import logging
from typing import Dict, List, Optional, Union
from requests.exceptions import RequestException
from django.conf import settings
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TransactionError(Exception):
    """Custom exception for transaction-related errors."""
    pass


class ServiceType(Enum):
    """Enum for different types of mobile money services."""
    CASHIN = "CASHIN"
    CASHOUT = "CASHOUT"


@dataclass
class MomoService:
    """Data class representing a mobile money service."""
    serviceName: str
    serviceCode: str
    country: str
    type: ServiceType


# Structured service definitions
MOMO_SERVICES: List[MomoService] = [
    MomoService("Orange Money Cashin SN", "OM_SN_CASHIN", "SN", ServiceType.CASHIN),
    MomoService("Orange Money Cashout SN", "OM_SN_CASHOUT", "SN", ServiceType.CASHOUT),
    MomoService("Wave Cashout SN", "WAVE_SN_CASHOUT", "SN", ServiceType.CASHOUT),
    MomoService("Wave Cashin SN", "WAVE_SN_CASHIN", "SN", ServiceType.CASHIN),
    MomoService("Free Money Cashin SN", "FM_SN_CASHIN", "SN", ServiceType.CASHIN),
    MomoService("Free Money Cashout SN", "FM_SN_CASHOUT", "SN", ServiceType.CASHOUT),
    MomoService("Wizall Money Cashout SN", "WIZALL_SN_CASHOUT", "SN", ServiceType.CASHOUT),
    MomoService("Wizall Money Cashin SN", "WIZALL_SN_CASHIN", "SN", ServiceType.CASHIN)
]


class DexchangeAPI:
    """Class to handle interactions with the Dexchange API."""

    BASE_URL = "https://api-m.dexchange.sn/api/v1"
    MAX_RETRIES = 3
    TIMEOUT = 30  # seconds

    def __init__(self):
        self.api_key = settings.DEXCHANGE_API_KEY
        if not self.api_key:
            raise ValueError("DEXCHANGE_API_KEY not configured in settings")

    def _get_headers(self) -> Dict[str, str]:
        """Generate API request headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _validate_service_code(self, service_code: str) -> None:
        """Validate that the service code exists."""
        valid_codes = {service.serviceCode for service in MOMO_SERVICES}
        if service_code not in valid_codes:
            raise TransactionError(f"Invalid service code: {service_code}")


    def _validate_amount(self, amount: int) -> None:
        """Validate transaction amount."""
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise TransactionError("Amount must be a positive number")
        if amount > 1000000:  # Example maximum limit
            raise TransactionError("Amount exceeds maximum limit")

    def send_transaction_payload(
            self,
            external_transaction_id: str,
            service_code: str,
            amount: int,
            number: str,
            callback_url: Optional[str] = None,
            success_url: Optional[str] = None,
            failure_url: Optional[str] = None
    ) -> Dict:
        """
        Send a transaction payload to Dexchange API.

        Args:
            external_transaction_id: Unique transaction identifier
            service_code: Mobile money service code
            amount: Transaction amount
            number: Phone number
            callback_url: URL for transaction status updates
            success_url: URL for successful transactions
            failure_url: URL for failed transactions

        Returns:
            Dict containing API response

        Raises:
            TransactionError: For validation or API errors
        """
        # Validate inputs
        self._validate_service_code(service_code)
        self._validate_amount(amount)

        # Remove '+221' prefix if present
        if number.startswith("+221"):
            number = number[4:]  # Remove the first 4 characters

        # Prepare payload
        payload = {
            "externalTransactionId": external_transaction_id,
            "serviceCode": service_code,
            "amount": amount,
            "number": number,
            "callBackURL": callback_url or settings.DEXCHANGE_CALLBACK_URL,
            "successUrl": success_url or settings.DEXCHANGE_SUCCESS_URL,
            "failureUrl": failure_url or settings.DEXCHANGE_FAILURE_URL
        }

        logger.info(f"Initiating transaction: {external_transaction_id}")

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    f"{self.BASE_URL}/transaction/init",
                    json=payload,
                    headers=self._get_headers(),
                    timeout=self.TIMEOUT
                )

                response.raise_for_status()
                response_data = response.json()
                print("Response Status Code:", response.status_code)
                print("Response Headers:", response.headers)
                print("Response Content:", response.text)
                print("Data", response_data.get("transaction", {}))

                # Vérifiez si la transaction est réussie
                transaction_data = response_data.get("transaction", {})

                if not transaction_data.get("success", False):
                    raise TransactionError(f"Transaction failed: {response_data.get('message', 'Unknown error')}")

                logger.info(f"Transaction {external_transaction_id} initiated successfully")
                print("DataRes: ", transaction_data)
                return transaction_data

            except RequestException as e:
                logger.error(f"Attempt {attempt + 1}/{self.MAX_RETRIES} failed: {str(e)}")
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(f"Transaction {external_transaction_id} failed after all retries")
                    raise TransactionError(f"Failed to process transaction: {str(e)}")

    def get_transaction_status(self, transaction_id: str) -> Dict:
        """
        Get the status of a transaction.

        Args:
            transaction_id: Transaction identifier

        Returns:
            Dict containing transaction status
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/transaction/status/{transaction_id}",
                headers=self._get_headers(),
                timeout=self.TIMEOUT
            )

            response.raise_for_status()
            return response.json()

        except RequestException as e:
            logger.error(f"Failed to get transaction status: {str(e)}")
            raise TransactionError(f"Failed to get transaction status: {str(e)}")


# Initialize the API client
dexchange_api = DexchangeAPI()


# Export the send_transaction_payload function to maintain backwards compatibility
def send_transaction_payload(*args, **kwargs):
    """Wrapper function for backwards compatibility."""
    return dexchange_api.send_transaction_payload(*args, **kwargs)