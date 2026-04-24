# Requestor and Admin API Integration Guide

This document defines the backend contract implemented for Requestor and Admin frontend screens.

## Base Details

- Base paths: /requestor and /admin
- Auth: Bearer token required
- Role guard: requestor endpoints require requestor role, admin endpoints require admin role

## 1) Requestor Dashboard

Endpoint:
- GET /requestor/dashboard

Response shape:
- user.shortName: string
- monthlyExpense.amountSpent: number
- monthlyExpense.monthlyLimit: number
- monthlyExpense.progressRatio: number (0.0 to 1.0)
- pendingApprovals.pendingCount: number
- recentRequests: array (max 5)

recentRequests item:
- id: string (request id)
- purpose: string
- date: ISO datetime string
- amount: number
- status: string
- category: string

Status mapping returned:
- pending
- approved
- auto_approved
- rejected
- clarification

## 2) Requestor History (My Requests)

Endpoint:
- GET /requestor/requests

Query params:
- search (optional)
- status (optional): All, Pending, Clarification, Approved, Rejected, Unpaid

Response:
- array of request objects

Request object fields:
- id: string
- purpose: string
- date: ISO datetime string
- category: string
- amount: number
- status: string
- rejection_reason: string | null

Filter behavior:
- Pending: status == pending
- Clarification: clarification_required + clarification_responded
- Approved: approved + auto_approved + paid
- Rejected: rejected
- Unpaid: approved + auto_approved

## 3) Admin Dashboard

Endpoint:
- GET /admin/dashboard

Response shape:
- user.shortName: string
- overview.pendingRequestsCount: number
- overview.approvedAmount: number

Admin dashboard logic:
- pendingRequestsCount uses pending + clarification_responded queue items
- approvedAmount includes approved + auto_approved + paid totals

## 4) Admin History

Endpoint:
- GET /admin/history

Query params:
- search (optional)
- status (optional): All, approved, auto_approved, rejected, clarification

Response:
- array of history objects

History object fields:
- id: string
- request_id: string
- updated_at: ISO datetime string
- amount: number
- requestor.first_name: string
- requestor.last_name: string
- requestor.email: string
- user: string (fallback)
- purpose: string
- status: string

Status mapping returned:
- approved
- auto_approved
- rejected
- clarification

## Error Patterns

- 401: missing or invalid token
- 403: role mismatch
- 400: invalid filter values
