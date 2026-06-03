# Petty Cash — FastAPI Backend API Audit Report

**Generated:** May 15, 2026  
**Base URL:** Configured per deployment (e.g. `http://localhost:8000`)  
**App Title:** Enterprise Expense Manager v1.0.0

---

## 7. Middleware & CORS Settings

| Setting | Value |
|---|---|
| CORS `allow_origins` | `["*"]` ⚠️ All origins allowed |
| CORS `allow_methods` | `["*"]` All HTTP methods |
| CORS `allow_headers` | `["*"]` All headers |
| Custom handler | `RequestValidationError` → `422` with single `{ "detail": "..." }` |

---

## 6. Authentication / Authorization

| Mechanism | Detail |
|---|---|
| Scheme | JWT Bearer Token (`OAuth2PasswordBearer`) |
| Token URL | `POST /auth/login` |
| Header | `Authorization: Bearer <token>` |
| Token payload | `{ "sub": "<user_id>", "exp": <timestamp> }` |
| Roles | `admin`, `approver`, `requestor`, `accountant` |

> Endpoints marked **🔒 Auth** require the `Authorization: Bearer <token>` header.  
> Endpoints marked **🚨 No Auth** are unprotected — see security notes.

---

## 1–5. All Endpoints by Router

---

### `/auth` — Authentication

#### `POST /auth/setup-organization`
| | |
|---|---|
| **Auth** | None (public) |
| **Content-Type** | `application/json` |
| **Path Params** | None |
| **Query Params** | None |

**Request Body:**
```json
{
  "org_name": "string (required)",
  "admin_details": {
    "email": "EmailStr (required)",
    "first_name": "string (required)",
    "last_name": "string (required)",
    "phone_number": "string (required)"
  }
}
```

**Response `200` (`UserOut`):**
```json
{
  "id": "int",
  "email": "string",
  "first_name": "string",
  "last_name": "string",
  "phone_number": "string | null",
  "role": "admin",
  "org_id": "int",
  "department_id": "int | null",
  "is_active": "bool"
}
```

---

#### `POST /auth/login`
| | |
|---|---|
| **Auth** | None (public) |
| **Content-Type** | `application/json` |
| **Path Params** | None |
| **Query Params** | None |

**Request Body:**
```json
{
  "email": "EmailStr (required)",
  "password": "string (required)"
}
```

**Response `200` (`LoginResponse`):**
```json
{
  "access_token": "string",
  "token_type": "bearer",
  "email": "string",
  "first_name": "string",
  "last_name": "string",
  "phone_number": "string | null",
  "role": "string",
  "organization": {
    "id": "int",
    "name": "string",
    "org_code": "string"
  }
}
```

---

#### `POST /auth/forgot-password`
| | |
|---|---|
| **Auth** | None (public) |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "email": "EmailStr (required)"
}
```

**Response `200`:**
```json
{ "msg": "OTP sent to registered email" }
```

---

#### `POST /auth/verify-otp`
| | |
|---|---|
| **Auth** | None (public) |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "email": "EmailStr (required)",
  "otp": "string (required)"
}
```

**Response `200`:**
```json
{ "msg": "OTP verified successfully. You may now reset your password." }
```

---

#### `POST /auth/reset-password`
| | |
|---|---|
| **Auth** | None (public) |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "email": "EmailStr (required)",
  "otp": "string (required)",
  "new_password": "string (required, min 8 chars, 1 upper, 1 lower, 1 digit, 1 special)"
}
```

**Response `200`:**
```json
{ "msg": "Password has been reset successfully. You can now login." }
```

---

#### `POST /auth/add-staff`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin only** |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "email": "EmailStr (required)",
  "first_name": "string (required)",
  "last_name": "string (required)",
  "phone_number": "string (required)",
  "role": "string (required) — 'admin' | 'requestor' | 'approver' | 'accountant'",
  "department_id": "int (optional)"
}
```

**Response `200` (`UserOut`):** *(same as setup-organization response)*

---

#### `GET /auth/users`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin only** |
| **Path Params** | None |
| **Query Params** | None |

**Response `200` (`list[UserListOut]`):**
```json
[
  {
    "id": "int",
    "first_name": "string",
    "last_name": "string",
    "email": "string",
    "role": "string",
    "department_id": "int | null",
    "phone_number": "string | null",
    "is_active": "bool",
    "org_id": "int",
    "created_at": "datetime"
  }
]
```

---

### `/requestor` — Requestor

#### `GET /requestor/dashboard`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Requestor role** |
| **Query Params** | None |

**Response `200`:**
```json
{
  "user": { "shortName": "string" },
  "monthlyExpense": {
    "amountSpent": "float",
    "monthlyLimit": "float",
    "progressRatio": "float"
  },
  "pendingApprovals": { "pendingCount": "int" },
  "recentRequests": [
    {
      "id": "string (request_id)",
      "purpose": "string",
      "date": "ISO datetime string",
      "amount": "float",
      "status": "pending | approved | auto_approved | rejected | clarification",
      "category": "string"
    }
  ]
}
```

---

#### `GET /requestor/requests`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Requestor role** |

**Query Params:**

| Param | Type | Required | Description |
|---|---|---|---|
| `search` | string | Optional | Matches request_id, purpose, description |
| `status` | string | Optional (default: `"All"`) | `All` \| `pending` \| `clarification` \| `approved` \| `rejected` \| `unpaid` |

**Response `200`:**
```json
[
  {
    "id": "string (request_id)",
    "purpose": "string",
    "date": "ISO datetime string",
    "category": "string",
    "amount": "float",
    "status": "string",
    "rejection_reason": "string | null"
  }
]
```

---

#### `GET /requestor/history/{expense_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Path Params:**

| Param | Type | Description |
|---|---|---|
| `expense_id` | int | Internal DB ID of the expense |

**Response `200` (`list[ClarificationOut]`):**
```json
[
  {
    "id": "int",
    "expense_id": "int",
    "question": "string",
    "response": "string | null",
    "asked_at": "datetime",
    "responded_at": "datetime | null"
  }
]
```

---

#### `GET /requestor/categories`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Query Params** | None |

**Response `200`:**
```json
["travel", "food", "accommodation", ...]
```
*(Returns all `ExpenseCategory` enum values)*

---

#### `POST /requestor/submit`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `multipart/form-data` |

**Form Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `amount` | float | ✅ Required | |
| `purpose` | string | ✅ Required | |
| `category` | string | ✅ Required | Must match `ExpenseCategory` enum |
| `request_type` | string | Optional (default: `pre_approved`) | `pre_approved` \| `post_approved` |
| `description` | string | Optional | |
| `receipt_file` | file | Optional | Max 10MB; JPEG/PNG/GIF/PDF/HEIC/HEIF/WEBP. Required if `post_approved`. |
| `payment_qr_file` | file | Optional | Max 5MB; same allowed types |
| `payment_note` | string | Optional | |
| `file` | file (array) | Optional | Generic fallback — first maps to receipt, second to payment_qr |

**Response `200` (`ExpenseOut`):**
```json
{
  "id": "int",
  "request_id": "string",
  "request_type": "string",
  "amount": "float",
  "purpose": "string",
  "description": "string | null",
  "category": "string",
  "receipt_url": "string | null",
  "payment_qr_url": "string | null",
  "payment_note": "string | null",
  "payment_method": "string | null",
  "transaction_reference": "string | null",
  "status": "string",
  "created_at": "datetime",
  "clarifications": [],
  "requestor": { "first_name": "string", "last_name": "string", "email": "string" }
}
```

---

#### `GET /requestor/my-requests`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Query Params:**

| Param | Type | Required | Values |
|---|---|---|---|
| `status` | string | Optional | `All` \| `pending` \| `approved` \| `clarification` \| etc. |
| `payment_status` | string | Optional | `All` \| `pending` \| `paid` |

**Response `200` (`list[ExpenseOut]`):** *(same schema as submit response)*

---

#### `POST /requestor/respond-clarification/{expense_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `application/json` |

**Path Params:**

| Param | Type | Description |
|---|---|---|
| `expense_id` | int | Internal DB ID |

**Request Body:**
```json
{
  "response_text": "string (required)"
}
```

**Response `200`:**
```json
{ "msg": "Response submitted successfully" }
```

---

#### `POST /requestor/upload-receipt/{expense_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `multipart/form-data` |

**Path Params:** `expense_id` (int)

**Form Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | ✅ Required | Max 10MB; JPEG/PNG/GIF/PDF |

**Response `200`:**
```json
{
  "msg": "Receipt uploaded successfully",
  "receipt_url": "string",
  "file_size": "int",
  "format": "string"
}
```

---

#### `POST /requestor/upload-payment-qr/{expense_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `multipart/form-data` |

**Path Params:** `expense_id` (int)

**Form Fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | ✅ Required | Max 5MB; JPEG/PNG/GIF/PDF/HEIC/HEIF/WEBP |
| `payment_note` | string | Optional | Form field |

**Response `200`:**
```json
{
  "msg": "Payment QR uploaded successfully",
  "payment_qr_url": "string",
  "payment_note": "string | null"
}
```

---

### `/approver` — Approver

#### `GET /approver/org-expenses`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin or Approver role** |

**Query Params:**

| Param | Type | Required | Values |
|---|---|---|---|
| `status` | string | Optional | `all` \| `pending` \| `approved` \| `rejected` \| `clarification` \| `clarification_required` \| `clarification_responded` |
| `payment_status` | string | Optional | `all` \| `pending` \| `paid` |

**Response `200` (`list[ExpenseOut]`):** *(full ExpenseOut schema)*

---

#### `GET /approver/dashboard-stats`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Response `200`:**
```json
{
  "pending_count": "int",
  "total_approved_amount": "float"
}
```

---

#### `POST /approver/expenses/{expense_id}/decision`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin or Approver role** |
| **Content-Type** | `application/json` |

**Path Params:** `expense_id` (int)

**Request Body:**
```json
{
  "action": "string (required) — 'approve' | 'reject'",
  "rejection_reason": "string (required if action = 'reject')"
}
```

**Response `200` (`ApprovalDecisionResponse`):**
```json
{
  "success": true,
  "message": "string",
  "expense_id": "int",
  "request_id": "string",
  "new_status": "string",
  "approver_name": "string",
  "approved_at": "datetime | null"
}
```

---

#### `POST /approver/ask-clarification`
| | |
|---|---|
| **Auth** | 🚨 No `get_current_user` dependency — effectively unprotected |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "expense_id": "int (required)",
  "question": "string (required)"
}
```

**Response `200`:**
```json
{ "msg": "Clarification sent to requester" }
```

---

#### `GET /approver/history/{expense_id}`
| | |
|---|---|
| **Auth** | 🚨 No `get_current_user` dependency — effectively unprotected |

**Path Params:** `expense_id` (int)

**Response `200`:** List of `ClarificationHistory` ORM objects (all fields)

---

### `/accountant` — Accountant

#### `GET /accountant/payment-methods`
| | |
|---|---|
| **Auth** | 🚨 No auth |

**Response `200`:**
```json
[
  { "value": "upi", "label": "UPI" },
  { "value": "bank_transfer", "label": "Bank Transfer" },
  { "value": "cash", "label": "Cash" },
  { "value": "cheque", "label": "Cheque" },
  { "value": "neft", "label": "NEFT" },
  { "value": "rtgs", "label": "RTGS" },
  { "value": "imps", "label": "IMPS" },
  { "value": "other", "label": "Other" }
]
```

---

#### `GET /accountant/dashboard`
| | |
|---|---|
| **Auth** | 🚨 No `get_current_user` — unprotected |

**Response `200`:**
```json
{
  "amount_out": "float",
  "pending_payments": "int",
  "opening_balance": 100000.00
}
```

---

#### `POST /accountant/process-payout`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Accountant role** |

**Query Params:**

| Param | Type | Required | Description |
|---|---|---|---|
| `expense_id` | int | ✅ Required | Internal DB ID |
| `reference_number` | string | Optional | Payment reference |
| `accountant_note` | string | Optional | Note from accountant |

**Response `200`:**
```json
{ "status": "success", "message": "Expense marked as PAID" }
```

---

#### `GET /accountant/analytics/spend-by-category`
| | |
|---|---|
| **Auth** | 🚨 No auth |

**Response `200`:**
```json
{
  "travel": 1200.50,
  "food": 300.00
}
```
*(Key = category string, Value = total paid amount)*

---

#### `GET /accountant/expenses/pending-payments`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Accountant role** |

**Query Params:**

| Param | Type | Required | Default |
|---|---|---|---|
| `page` | int | Optional | `1` |
| `size` | int | Optional | `25` |
| `search` | string | Optional | — |

**Response `200` (`PaginatedExpenses`):**
```json
{
  "total": "int",
  "page": "int",
  "size": "int",
  "items": ["...AccountantExpenseOut objects..."]
}
```

`AccountantExpenseOut` extends `ExpenseOut` with:
```json
{
  "approver": { "id": "int", "first_name": "string", "last_name": "string" } 
}
```

---

#### `GET /accountant/expenses/paid`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Accountant role** |

**Query Params:** Same as `pending-payments` (`page`, `size`, `search`)

**Response `200` (`PaginatedExpenses`):** Same schema as above

---

#### `POST /accountant/expenses/{expense_id}/mark-as-paid`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Accountant role** |
| **Content-Type** | `application/json` |

**Path Params:** `expense_id` (int)

**Request Body** (all optional):
```json
{
  "payment_method": "upi | bank_transfer | cash | cheque | neft | rtgs | imps | other",
  "transaction_reference": "string",
  "payment_note": "string"
}
```

**Response `200`:**
```json
{
  "status": "success",
  "message": "Expense marked as PAID successfully.",
  "expense_id": "int",
  "request_id": "string",
  "new_status": "paid"
}
```

---

### `/admin` — Admin

#### `GET /admin/dashboard`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |

**Response `200`:**
```json
{
  "user": { "shortName": "string" },
  "overview": {
    "pendingRequestsCount": "int",
    "approvedAmount": "float"
  },
  "departmentSummary": {
    "totalDepartments": "int",
    "activeDepartments": "int",
    "unassignedUsers": "int"
  }
}
```

---

#### `GET /admin/history`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |

**Query Params:**

| Param | Type | Required | Values |
|---|---|---|---|
| `search` | string | Optional | Matches request_id, purpose, description |
| `status` | string | Optional (default: `All`) | `All` \| `approved` \| `auto_approved` \| `rejected` \| `clarification` |

**Response `200`:**
```json
[
  {
    "id": "string (request_id)",
    "request_id": "string",
    "updated_at": "ISO datetime string",
    "amount": "float",
    "requestor": {
      "first_name": "string",
      "last_name": "string",
      "email": "string"
    },
    "user": "string (display name fallback)",
    "purpose": "string",
    "status": "approved | auto_approved | rejected | clarification | pending",
    "clarification_history": [
      {
        "id": "int",
        "question": "string",
        "response": "string | null",
        "asked_at": "ISO datetime | null",
        "responded_at": "ISO datetime | null"
      }
    ]
  }
]
```

---

### `/users` — User Management (profile.py)

#### `GET /users/me`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Response `200`:**
```json
{
  "id": "int",
  "email": "string",
  "first_name": "string",
  "last_name": "string",
  "phone_number": "string | null",
  "role": "string",
  "org_id": "int",
  "is_active": "bool",
  "org_code": "string",
  "org_name": "string",
  "department_id": "int | null",
  "department_name": "string | null",
  "department_code": "string | null"
}
```

---

#### `POST /users/change-password`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "current_password": "string (required)",
  "new_password": "string (required, min 8 chars, 1 upper, 1 lower, 1 digit, 1 special)"
}
```

**Response `200`:**
```json
{ "msg": "Password updated successfully" }
```

---

#### `GET /users/approval-limit`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token (any role) |

**Response `200`:**
```json
{
  "org_id": "int",
  "org_name": "string",
  "deemed_approval_limit": "float"
}
```

---

#### `PATCH /users/approval-limit`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "deemed_approval_limit": "float (required, >= 0)"
}
```

**Response `200`:**
```json
{
  "msg": "Approval limit updated successfully",
  "org_id": "int",
  "org_name": "string",
  "deemed_approval_limit": "float"
}
```

---

#### `POST /users/add-user`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |
| **Content-Type** | `application/json` |

**Request Body** (`UserCreate`):
```json
{
  "email": "EmailStr (required)",
  "first_name": "string (required)",
  "last_name": "string (required)",
  "phone_number": "string (optional)",
  "password": "string (required)",
  "org_id": "int (required)",
  "department_id": "int (optional)",
  "role": "admin | requestor | approver | accountant (default: requestor)"
}
```

**Response `200` (`UserOut`):** *(same as setup-organization)*

---

#### `GET /users/manage-list`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |

**Response `200` (`list[UserOut]`):** List of all users in the organization

---

#### `PATCH /users/update/{user_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — Admin (any in org) or Self |
| **Content-Type** | `application/json` |

**Path Params:** `user_id` (int)

**Request Body** (all optional, only sent fields updated):
```json
{
  "first_name": "string",
  "last_name": "string",
  "phone_number": "string",
  "role": "string (Admin only)",
  "department_id": "int | null (Admin only)",
  "is_active": "bool (Admin only)"
}
```

**Response `200`:**
```json
{
  "id": "int",
  "email": "string",
  "first_name": "string",
  "last_name": "string",
  "phone_number": "string | null",
  "role": "string",
  "org_id": "int",
  "is_active": "bool"
}
```

---

### `/departments` — Departments

#### `POST /departments`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "name": "string (required, min 2 chars)",
  "code": "string (optional)"
}
```

**Response `200`:**
```json
{ "id": "int", "name": "string", "code": "string | null", "is_active": true }
```

---

#### `GET /departments`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Query Params:**

| Param | Type | Required | Default |
|---|---|---|---|
| `include_inactive` | bool | Optional | `false` |

**Response `200`:** `list[{ id, name, code, is_active }]`

---

#### `GET /departments/{department_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Path Params:** `department_id` (int)

**Response `200`:** `{ id, name, code, is_active }`

---

#### `PATCH /departments/{department_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |
| **Content-Type** | `application/json` |

**Path Params:** `department_id` (int)

**Request Body** (all optional):
```json
{
  "name": "string",
  "code": "string",
  "is_active": "bool"
}
```

**Response `200`:** `{ id, name, code, is_active }`

---

#### `DELETE /departments/{department_id}`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |

**Path Params:** `department_id` (int)

> **Note:** Soft delete — sets `is_active = false`, does not remove from DB.

**Response `200`:**
```json
{ "message": "Department deactivated successfully" }
```

---

#### `GET /departments/{department_id}/users`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |

**Path Params:** `department_id` (int)

**Response `200`:**
```json
{
  "department": { "id": "int", "name": "string", "code": "string" },
  "users": [
    { "id": "int", "first_name": "string", "last_name": "string", "email": "string", "role": "string" }
  ]
}
```

---

#### `POST /departments/seed-defaults`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token — **Admin role** |

Seeds: Finance (FIN), Human Resources (HR), Operations (OPS), Information Technology (IT)

**Response `200`:**
```json
{
  "message": "Default departments processed",
  "created": ["string"],
  "skipped": ["string"]
}
```

---

### `/notifications` — Push Notifications

#### `POST /notifications/devices/register`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "token": "string (required, 20–1024 chars)",
  "platform": "android | ios (required)",
  "app_version": "string (optional, max 50 chars)"
}
```

**Response `200` (`DeviceTokenResponse`):**
```json
{ "success": true, "message": "Device token registered successfully." }
```

---

#### `POST /notifications/devices/unregister`
| | |
|---|---|
| **Auth** | 🔒 Bearer Token |
| **Content-Type** | `application/json` |

**Request Body:**
```json
{
  "token": "string (required, 20–1024 chars)"
}
```

**Response `200`:**
```json
{ "success": true, "message": "Device token unregistered successfully." }
```

---

### Root

#### `GET /`
| | |
|---|---|
| **Auth** | None (public health check) |

**Response `200`:**
```json
{ "status": "online", "system": "Expense Management Backend" }
```

---

## Quick Reference Table

| Method | Path | Auth Required | Role | Content-Type |
|---|---|---|---|---|
| POST | /auth/setup-organization | ❌ | — | JSON |
| POST | /auth/login | ❌ | — | JSON |
| POST | /auth/forgot-password | ❌ | — | JSON |
| POST | /auth/verify-otp | ❌ | — | JSON |
| POST | /auth/reset-password | ❌ | — | JSON |
| POST | /auth/add-staff | ✅ | admin | JSON |
| GET | /auth/users | ✅ | admin | — |
| GET | /requestor/dashboard | ✅ | requestor | — |
| GET | /requestor/requests | ✅ | requestor | — |
| GET | /requestor/history/{expense_id} | ✅ | any | — |
| GET | /requestor/categories | ✅ | any | — |
| POST | /requestor/submit | ✅ | any | multipart/form-data |
| GET | /requestor/my-requests | ✅ | any | — |
| POST | /requestor/respond-clarification/{expense_id} | ✅ | any | JSON |
| POST | /requestor/upload-receipt/{expense_id} | ✅ | any | multipart/form-data |
| POST | /requestor/upload-payment-qr/{expense_id} | ✅ | any | multipart/form-data |
| GET | /approver/org-expenses | ✅ | admin, approver | — |
| GET | /approver/dashboard-stats | ✅ | any | — |
| POST | /approver/expenses/{expense_id}/decision | ✅ | admin, approver | JSON |
| POST | /approver/ask-clarification | 🚨 NONE | — | JSON |
| GET | /approver/history/{expense_id} | 🚨 NONE | — | — |
| GET | /accountant/payment-methods | 🚨 NONE | — | — |
| GET | /accountant/dashboard | 🚨 NONE | — | — |
| POST | /accountant/process-payout | ✅ | accountant | Query params |
| GET | /accountant/analytics/spend-by-category | 🚨 NONE | — | — |
| GET | /accountant/expenses/pending-payments | ✅ | accountant | — |
| GET | /accountant/expenses/paid | ✅ | accountant | — |
| POST | /accountant/expenses/{expense_id}/mark-as-paid | ✅ | accountant | JSON |
| GET | /admin/dashboard | ✅ | admin | — |
| GET | /admin/history | ✅ | admin | — |
| GET | /users/me | ✅ | any | — |
| POST | /users/change-password | ✅ | any | JSON |
| GET | /users/approval-limit | ✅ | any | — |
| PATCH | /users/approval-limit | ✅ | admin | JSON |
| POST | /users/add-user | ✅ | admin | JSON |
| GET | /users/manage-list | ✅ | admin | — |
| PATCH | /users/update/{user_id} | ✅ | admin/self | JSON |
| POST | /departments | ✅ | admin | JSON |
| GET | /departments | ✅ | any | — |
| GET | /departments/{department_id} | ✅ | any | — |
| PATCH | /departments/{department_id} | ✅ | admin | JSON |
| DELETE | /departments/{department_id} | ✅ | admin | — |
| GET | /departments/{department_id}/users | ✅ | any | — |
| POST | /departments/seed-defaults | ✅ | admin | — |
| POST | /notifications/devices/register | ✅ | any | JSON |
| POST | /notifications/devices/unregister | ✅ | any | JSON |
| GET | / | ❌ | — | — |

---

## ⚠️ Security Findings

| Severity | Endpoint | Issue |
|---|---|---|
| 🔴 HIGH | `POST /approver/ask-clarification` | No authentication — anyone can send clarifications |
| 🔴 HIGH | `GET /approver/history/{expense_id}` | No authentication — expense data exposed publicly |
| 🔴 HIGH | `GET /accountant/dashboard` | No authentication — financial totals exposed |
| 🟡 MEDIUM | `GET /accountant/analytics/spend-by-category` | No authentication — org spending patterns exposed |
| 🟡 MEDIUM | `GET /accountant/payment-methods` | No authentication — low risk but inconsistent with API design |
| 🟡 MEDIUM | CORS `allow_origins=["*"]` | All origins allowed — should be restricted to known frontend origin in production |
| 🟠 LOW | `POST /accountant/process-payout` | Uses query params for `expense_id` — inconsistent with REST conventions (use path param or request body) |
