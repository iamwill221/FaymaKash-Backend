# FaymaKash Payment System

A Django-based NFC payment processing system with Twilio SMS verification and Dexchange integration for secure transactions.

<img src="static/images/logo.png" alt="FaymaKash Logo" width="200" height="auto">


## Prerequisites

- Python 3.x
- PostgreSQL
- Virtual environment (recommended)
- Twilio account
- DExchange account

## Installation

1. Clone the repository:
```bash
git clone https://github.com/iamwill221/FaymaKash.git
cd FaymaKash
```

2. Set up virtual environment:
```bash
python -m venv env
source env/bin/activate  # On Windows use: env\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create `.env` file with the following variables:
```
SECRET_KEY=your_secret_key
DEBUG=False
DATABASE_NAME=your_db_name
DATABASE_USER=your_db_user
DATABASE_PASSWORD=your_db_password
DATABASE_HOST=localhost
DATABASE_PORT=your_db_port
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_VERIFY_SERVICE_SID=your_verify_sid
DEXCHANGE_API_KEY=your_dexchange_key
BASE_DOMAIN=your_domain
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Start the development server:
```bash
python manage.py runserver
```

## API Endpoints

### Authentication & User Management
- `POST /api/auth/send-otp/` - Send OTP via SMS for verification
- `POST /api/auth/verify-otp/` - Verify OTP code
- `POST /api/auth/check-user/` - Check if user exists by phone number
- `POST /api/auth/login/` - Login with phone number and pincode
- `POST /api/auth/users/` - Register new user
- `POST /api/auth/jwt/create/` - Get JWT tokens
- `POST /api/auth/jwt/refresh/` - Refresh JWT token
- `POST /api/auth/jwt/verify/` - Verify JWT token
- `POST /api/auth/users/activation/` - Activate user account
- `POST /api/auth/users/resend_activation/` - Resend activation email
- `POST /api/auth/users/reset_password/` - Request password reset
- `POST /api/auth/users/reset_password_confirm/` - Confirm password reset
- `POST /api/auth/users/set_password/` - Set new password (authenticated)
- `GET /api/auth/users/me/` - Get current user profile
- `PUT /api/auth/users/me/` - Update current user profile
- `PATCH /api/auth/users/me/` - Partially update current user profile
- `DELETE /api/auth/users/me/` - Delete current user account

### Transaction Management
- `GET /api/transactions/` - Get transaction history for authenticated user
- `POST /api/transactions/deposit/` - Deposit funds using NFC card
- `POST /api/transactions/withdraw/` - Withdraw funds using NFC card  
- `POST /api/transactions/transfer/` - Transfer funds between users
- `POST /api/transactions/payment/` - Make payment using NFC card
- `POST /api/transactions/deposit_momo/` - Deposit via Mobile Money
- `POST /api/transactions/withdraw_momo/` - Withdraw via Mobile Money
- `POST /api/transactions/callback/dexchange/` - DExchange payment callback
- `GET /api/transactions/success/` - Transaction success page
- `GET /api/transactions/failure/` - Transaction failure page

### NFC Card Management  
- `POST /api/nfc/manage/` - Lock/unlock NFC card
- `POST /api/nfc/update_vcard_id/` - Update virtual card identifier

### Admin
- `/admin/` - Django admin interface

## Project Structure

```
FaymaKash/
├── FaymaKashProject/      # Main project directory
│   ├── settings.py        # Project settings
│   ├── urls.py           # Main URL configuration
│   └── wsgi.py           # WSGI configuration
├── PaymentSystem/         # Main application
├── static/               # Static files
├── templates/            # HTML templates
├── .env                 # Environment variables
├── .gitignore           # Git ignore rules
└── manage.py            # Django management script
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

![Made-In-Senegal](https://github.com/GalsenDev221/made.in.senegal/blob/master/assets/badge.svg)