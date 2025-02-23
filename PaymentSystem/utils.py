import random

from twilio.rest import Client

from FaymaKashProject import settings


# Function to send OTP via Twilio Verify
def send_otp_via_twilio(phone_number):
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    # Start the verification process
    verification = client.verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID) \
        .verifications.create(to=phone_number, channel='sms')

    return verification.sid  # Return the verification SID for tracking the process


# Function to check the OTP entered by the user
def check_otp_via_twilio(phone_number, otp):
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    # Check the verification status
    verification_check = client.verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID) \
        .verification_checks.create(to=phone_number, code=otp)

    return verification_check.status == 'approved'  # Return True if the OTP is valid

