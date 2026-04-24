# Accountant API Integration Guide

This document defines the backend API contract implemented for the accountant module.

## Base Details

- Base path: /accountant
- Auth: Bearer token required
- Role guard: accountant-only for all endpoints in this document
- Amounts: numeric values in INR units (frontend formats currency)

## 1) Dashboard

Endpoint:
- GET /accountant/dashboard

Response shape:
- user.shortName: string
- accountOverview.inHandCash: number
- accountOverview.inHandCashGrowth: string (example: +2.4%)
- accountOverview.openBalance: number
- accountOverview.closingBalance: number
- tasksSummary.pendingPaymentsCount: number
- todayTransactions: array

Today transaction item fields:
- id: string
- title: string
- subtitle: string (request id + time)
- vendorName: string (request id currently)
- timestamp: ISO datetime
- amount: number (negative for expenses)
- iconType: string

Balance behavior:
- accountOverview.openBalance is sourced from the saved daily opening balance for today.
- If no balance has been saved yet for today, backend uses default value 100000.00.
- After frontend posts /accountant/balance, re-fetch /accountant/dashboard to refresh openBalance and closingBalance.

## 2) Reports Summary

Endpoint:
- GET /accountant/reports/summary

Query params:
- month (optional, 1-12)
- year (optional, 2000-2100)
- category (optional, category label like Office Supplies)

Behavior:
- If month/year not provided, current month is used.
- If category is omitted or All Categories, all paid rows are included.

Response shape:
- filters.categories: string[]
- previewSummary.monthYear: string
- previewSummary.totalExpenses: number
- previewSummary.transactions: array

Transaction row fields:
- date: string (example: Oct 24)
- category: string
- amount: number

## 3) Spend Analytics

Endpoint:
- GET /accountant/analytics/spend

Query params:
- time_range (optional: This Month, Last Month; default This Month)
- department (optional; currently informational only)
- category (optional; Category/All Categories means no category filter)

Response shape:
- filters.timeRanges: string[]
- filters.departments: string[]
- filters.categories: string[]
- scoreCards.totalSpend.amount: number
- scoreCards.totalSpend.trendText: string
- scoreCards.totalSpend.isPositiveTrend: boolean
- scoreCards.avgTransaction.amount: number
- scoreCards.avgTransaction.trendText: string
- scoreCards.avgTransaction.isPositiveTrend: boolean
- monthlyTrend.trendSummaryText: string
- monthlyTrend.isPositiveTrend: boolean
- monthlyTrend.graphData: [{ weekOrDay, amount }]
- spendByCategory: [{ categoryName, percentage }]
- departmentSpend: [{ departmentName, amount, progressRatio }]

Department note:
- Current schema does not store department on expenses or users.
- Backend currently returns a stable fallback bucket: General.
- Once department is added in schema, this endpoint can return true per-department splits.

## 4) Update Daily Balance

Endpoint:
- POST /accountant/balance

Request body:
- openingBalance: number (required, must be >= 0)

Example request:
{
	"openingBalance": 5000.0
}

Response shape:
- status: string
- message: string
- data.balanceDate: string (YYYY-MM-DD)
- data.openingBalance: number

## 5) Export CSV

Endpoint:
- GET /accountant/reports/export/csv

Query params:
- start_date (optional, YYYY-MM-DD)
- end_date (optional, YYYY-MM-DD)
- category (optional)

Behavior:
- If date range is missing, current month is exported.
- Returns downloadable CSV attachment.
- Validation: start_date must be <= end_date.

CSV columns:
- Date
- Request ID
- Category
- Amount
- Purpose
- Status

## 6) Export PDF

Endpoint:
- GET /accountant/reports/export/pdf

Query params:
- start_date (optional, YYYY-MM-DD)
- end_date (optional, YYYY-MM-DD)
- category (optional)

Behavior:
- If date range is missing, current month is exported.
- Returns downloadable PDF attachment.
- Validation: start_date must be <= end_date.

Dependency:
- reportlab added in requirements.txt for PDF generation.

## Error Patterns

- 401: invalid or missing auth token
- 403: role is not accountant
- 400: invalid filter values (example: invalid category/time_range)
- 500: PDF export dependency missing (if reportlab not installed)

## Frontend Integration Notes

- Use subtitle directly if needed for compact cards.
- iconType is mapped from expense category enum values in uppercase.
- For analytics trend colors, use isPositiveTrend boolean instead of parsing trendText.
- For category filter values, frontend can send display text (example: Office Supplies).
