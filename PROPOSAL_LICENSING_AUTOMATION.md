# Proposal: Automated Registration & Licensing Flow

## Overview
This document outlines the plan to automate the user registration, payment, and licensing process for SchoolPoints. The goal is to allow users to register via a web form, pay for a subscription or one-time license, and automatically receive a valid license key via email, eliminating manual intervention.

## Current State
- **License Generation**: Manual via `license_key_generator.py` (CLI/GUI).
- **Key Types**:
  - `Legacy`: Simple station limit.
  - `SP5`: Payload-based (Days, Max Stations, Cashier).
  - `Monthly`: Expiry date based.
- **Distribution**: Manual (Phone/Email).

## Proposed Architecture

### 1. Web Registration Portal (`/web/register`)
A new public-facing page on the SchoolPoints website.
- **Form Fields**:
  - Institution Name (Hebrew/English)
  - Contact Name
  - Email Address (Username)
  - Password (for account creation)
  - Phone Number
  - Plan Selection:
    - **Basic** (2 Stations) - ₪50/mo
    - **Extended** (5 Stations) - ₪100/mo
    - **Unlimited** - ₪200/mo
  - Billing Period: Monthly / Yearly (discounted)

### 2. Backend API (`/api/register`, `/api/payment/*`)
New endpoints in `cloud_service/app.py` (or a dedicated service).

#### Flow:
1.  **Initiate Registration**:
    - User submits form.
    - Server creates a `pending_registrations` record.
    - Server initiates a payment session with a provider (e.g., Stripe, Pelecard, Tranzila).
    - Redirects user to Payment Gateway.

2.  **Payment Webhook**:
    - Payment Provider calls `/api/payment/webhook` with status `success`.
    - Server validates signature.
    - Server locates `pending_registrations` record.
    - **Action**:
        - Create Tenant in `institutions` table (Tenant ID generated from School Name).
        - Generate **License Key**.
        - Send Welcome Email.

### 3. License Key Generation Logic
Adapt logic from `license_manager.py` to the cloud environment.
- **Recommendation**: Use **SP5 (Payload)** or **Monthly** scheme.
- **Monthly Scheme**: Best for subscriptions. Key contains `expiry_date`.
- **Automation**: When a payment renews (webhook), generate a *new* key with extended expiry and email it, OR implement an online check in the client that updates the license validity without a new key (requires `sync_agent` to fetch license status).

**Preferred Approach (Online Check):**
Instead of emailing a new key every month:
1.  The License Key generated is a "Cloud Identity Key".
2.  The `sync_agent` checks `/api/license/status` daily.
3.  If payment is active, the server returns `valid: true`.
4.  If payment fails, server returns `valid: false` (after grace period).
5.  *Fallback*: If offline, the local key has an expiry date (e.g., 30 days + 7 days grace).

### 4. Email Notification
Using `smtplib` (as implemented for Contact Form):
- **User Email**: "Welcome to SchoolPoints! Your Tenant ID is `school_name_123` and your License Key is `XXXX-XXXX...`. Download the software here: ..."
- **Admin Email**: "New Subscription: Yeshiva X, Plan: Extended."

### 5. Client-Side Changes (`admin_station.py`, `license_manager.py`)
- Update `LicenseManager` to support "Cloud License" or "Auto-Renewing Monthly".
- Allow entering the License Key once.
- Periodic background check to extend local expiry date based on cloud status.

## Implementation Steps
1.  **Select Payment Provider**: Choose one (Stripe is easiest for dev, Israeli providers for local tax invoices).
2.  **Database Update**: Add `pending_registrations`, `subscriptions`, `payment_logs` tables.
3.  **API Development**: Implement registration and webhook endpoints.
4.  **License Logic Port**: Port `_make_monthly_license_key` logic to `cloud_service`.
5.  **Frontend**: Build the Registration & Pricing pages.
6.  **Testing**: Sandbox payment testing.

## Immediate Action Items
- [ ] Finalize Payment Provider selection.
- [ ] Build the `/web/register` page (UI).
- [ ] Implement `_send_license_email` helper.
