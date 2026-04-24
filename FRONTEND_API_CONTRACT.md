# Frontend API Contract (Requestor, Admin, Accountant)

This is the consolidated backend contract for the petty cash frontend.

## 1. Global Conventions

- Base URL example (LAN): http://192.168.0.149:8000
- Auth: Authorization: Bearer <token>
- Content-Type:
  - application/json for normal APIs
  - multipart/form-data for file upload APIs
- Role guard:
  - Requestor APIs: requestor
  - Admin APIs: admin
  - Accountant APIs: accountant
- Money fields are numeric. Frontend should format INR display.

## 2. Endpoint Matrix

### Requestor

- GET /requestor/dashboard
- GET /requestor/requests
- POST /requestor/submit
- POST /requestor/respond-clarification/{expense_id}
- POST /requestor/upload-receipt/{expense_id}
- POST /requestor/upload-payment-qr/{expense_id}

User mapping endpoints used by frontend:
- POST /auth/add-staff
- PATCH /users/update/{user_id}

### Admin

- GET /admin/dashboard
- GET /admin/history

### Departments

- POST /departments
- POST /departments/seed-defaults
- GET /departments
- GET /departments/{department_id}
- PATCH /departments/{department_id}
- DELETE /departments/{department_id}
- GET /departments/{department_id}/users

### Accountant

- GET /accountant/dashboard
- POST /accountant/balance
- GET /accountant/reports/summary
- GET /accountant/analytics/spend
- GET /accountant/reports/export/csv
- GET /accountant/reports/export/pdf
- GET /accountant/expenses/pending-payments
- GET /accountant/expenses/paid
- POST /accountant/expenses/{expense_id}/mark-as-paid

## 3. Requestor Contract

### 3.1 GET /requestor/dashboard

Response shape:
- user.shortName: string
- monthlyExpense.amountSpent: number
- monthlyExpense.monthlyLimit: number
- monthlyExpense.progressRatio: number (0.0 to 1.0)
- pendingApprovals.pendingCount: number
- recentRequests: array (max 5)

recentRequests item:
- id: string
- purpose: string
- date: ISO string
- amount: number
- status: pending | approved | auto_approved | rejected | clarification
- category: string

### 3.2 GET /requestor/requests

Query params:
- search (optional)
- status (optional): All | Pending | Clarification | Approved | Rejected | Unpaid

Response item:
- id: string
- purpose: string
- date: ISO string
- category: string
- amount: number
- status: pending | approved | auto_approved | rejected | clarification
- rejection_reason: string | null

Filter behavior:
- Pending: pending
- Clarification: clarification_required + clarification_responded
- Approved: approved + auto_approved + paid
- Rejected: rejected
- Unpaid: approved + auto_approved

User create/update integration:
- POST /auth/add-staff accepts department_id (optional)
- PATCH /users/update/{user_id} supports department_id update (admin only)

User profile response note:
- GET /users/me now includes:
  - department_id: number | null
  - department_name: string | null
  - department_code: string | null

## 4. Admin Contract

### 4.1 GET /admin/dashboard

Response shape:
- user.shortName: string
- overview.pendingRequestsCount: number
- overview.approvedAmount: number
- departmentSummary.totalDepartments: number
- departmentSummary.activeDepartments: number
- departmentSummary.unassignedUsers: number

### 4.2 GET /admin/history

Query params:
- search (optional)
- status (optional): All | approved | auto_approved | rejected | clarification

Response item:
- id: string
- request_id: string
- updated_at: ISO string
- amount: number
- requestor.first_name: string
- requestor.last_name: string
- requestor.email: string
- user: string (fallback)
- purpose: string
- status: approved | auto_approved | rejected | clarification
- clarification_history: array of {
  - id: number
  - question: string
  - response: string | null
  - asked_at: ISO string | null
  - responded_at: ISO string | null
}

## 5. Department Contract

Departments are organization-scoped from the authenticated user's org.

### 5.1 POST /departments

Access:
- Admin only

Request body:
- name: string (required)
- code: string (optional)

Response:
- id: number
- name: string
- code: string | null
- is_active: boolean

### 5.2 GET /departments

Query params:
- include_inactive: boolean (optional, default false)

Response:
- array of { id, name, code, is_active }

### 5.3 POST /departments/seed-defaults

Access:
- Admin only

Behavior:
- Creates standard departments for the current organization if they do not already exist.
- Current default set:
  - Finance (FIN)
  - Human Resources (HR)
  - Operations (OPS)
  - Information Technology (IT)

Response:
- message: string
- created: string[]
- skipped: string[]

### 5.4 GET /departments/{department_id}

Response:
- id, name, code, is_active

### 5.5 PATCH /departments/{department_id}

Access:
- Admin only

Request body (all optional):
- name
- code
- is_active

### 5.6 DELETE /departments/{department_id}

Access:
- Admin only

Behavior:
- Soft delete (is_active=false)

### 5.7 GET /departments/{department_id}/users

Response:
- department: { id, name, code }
- users: array of { id, first_name, last_name, email, role }

Validation rules:
- Department name and code must be unique within the organization.
- Department assignment for users is restricted to same organization active departments.
- Cross-organization department access returns 404.

## 6. Accountant Contract

### 6.1 GET /accountant/dashboard

Response shape:
- user.shortName: string
- accountOverview.inHandCash: number
- accountOverview.inHandCashGrowth: string
- accountOverview.openBalance: number
- accountOverview.closingBalance: number
- tasksSummary.pendingPaymentsCount: number
- todayTransactions: array

Today transaction item:
- id: string
- title: string
- subtitle: string
- vendorName: string
- timestamp: ISO string
- amount: number (negative for expense)
- iconType: string

### 6.2 POST /accountant/balance

Request body:
{
  "openingBalance": 5000.0
}

Validation:
- openingBalance >= 0

Response:
- status: string
- message: string
- data.balanceDate: YYYY-MM-DD
- data.openingBalance: number

Balance behavior:
- Dashboard openBalance uses saved daily opening balance.
- If no row exists for today, default fallback is 100000.00.
- Frontend should re-fetch GET /accountant/dashboard after successful POST /accountant/balance.

### 6.3 GET /accountant/reports/summary

Query params:
- month (optional, 1-12)
- year (optional)
- category (optional)

Response:
- filters.categories: string[]
- previewSummary.monthYear: string
- previewSummary.totalExpenses: number
- previewSummary.transactions: array of { date, category, amount }

### 6.4 GET /accountant/analytics/spend

Query params:
- time_range: This Month | Last Month
- department (optional)
- category (optional)

Response:
- filters.timeRanges: string[]
- filters.departments: string[]
- filters.categories: string[]
- scoreCards.totalSpend: { amount, trendText, isPositiveTrend }
- scoreCards.avgTransaction: { amount, trendText, isPositiveTrend }
- monthlyTrend: { trendSummaryText, isPositiveTrend, graphData }
- spendByCategory: array of { categoryName, percentage }
- departmentSpend: array of { departmentName, amount, progressRatio }

Current department note:
- Department values are resolved from Department records in the organization.
- departmentSpend is calculated from paid expenses grouped by requestor department.
- If no grouped rows exist, fallback row is returned: Unassigned with 0 amount.

### 6.5 Exports

- GET /accountant/reports/export/csv
- GET /accountant/reports/export/pdf

Query params:
- start_date (optional, YYYY-MM-DD)
- end_date (optional, YYYY-MM-DD)
- category (optional)

Rules:
- If date range not provided, current month export is generated.
- start_date must be <= end_date.

## 7. Common Error Mapping

- 401: missing or invalid token
- 403: role mismatch
- 400: invalid filter or payload
- 500: server-side processing issue (example: missing PDF dependency)

## 8. Frontend Integration Order

1. Authenticate and cache access token.
2. Wire role-based landing dashboards:
   - requestor -> /requestor/dashboard
   - admin -> /admin/dashboard
   - accountant -> /accountant/dashboard
3. Wire history/list pages:
   - requestor -> /requestor/requests
   - admin -> /admin/history
4. Build department master flow:
  - create/list/update departments
  - map staff to department_id in add/edit user flows
5. Wire accountant reports/analytics and exports.
6. Wire accountant opening-balance popup to POST /accountant/balance and refresh dashboard.
