# Frontend Guide: Push Notifications (Phase 1 + Phase 2)

This guide explains exactly what was implemented in backend Phase 1 and how frontend/mobile should integrate it safely.

## Scope

Implemented in backend:
- Device token registration endpoint
- Device token unregister endpoint
- Push notifications for expense decision events:
  - approved
  - rejected
- Push notifications for workflow events:
  - clarification required
  - clarification responded
  - paid
- Auto-invalidation of dead tokens & Audit Logging (Phase 3)

---

## Setting Up Firebase Credentials (Crucial for Testing)

To test push notifications locally or in production, you need the correct Firebase credentials. Note that the **Backend** and **Frontend/Mobile** require *different* sets of credentials from the same Firebase project.

### 1. Backend Secrets (The `.env` file)
The backend uses a Service Account to act as an administrator. You must configure these inside your `petty cash/.env` file:

1. Go to **Firebase Console** -> **Project settings** (⚙️) -> **Service accounts**.
2. Select **Firebase Admin SDK**.
3. Click **Generate new private key** (downloads a `.json` file).
4. Open the downloaded `.json` file and copy the values exactly into your backend `.env` file:
```env
FCM_ENABLED=True
FIREBASE_PROJECT_ID="your-project-id"
FIREBASE_CLIENT_EMAIL="firebase-adminsdk-xxxxx@your-project-id.iam.gserviceaccount.com"
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nYOUR_LONG_KEY_HERE\n-----END PRIVATE KEY-----\n"
```
*(Once copied into `.env`, you can safely delete the downloaded `.json` file.)*

### 2. Frontend / Mobile App Keys
The frontend (React/Flutter/Mobile) uses client keys. You must embed these into your frontend project's environment variables:

1. Go to **Firebase Console** -> **Project settings** (⚙️) -> **General** tab.
2. Scroll down to **Your apps**.
3. Select your Web, Android, or iOS app (or click "Add app" if none exist).
4. Copy the `firebaseConfig` object block. It looks like this:
```javascript
const firebaseConfig = {
  apiKey: "AIzaSyDOCAbC123...",
  authDomain: "your-project-id.firebaseapp.com",
  projectId: "your-project-id",
  storageBucket: "your-project-id.appspot.com",
  messagingSenderId: "123456789012",
  appId: "1:123456789012:web:abc123def456",
  measurementId: "G-ABCDEF123"
};
```
Use these parameters in your frontend application to generate a **Device Token (FCM Token)**.

---

## Backend Endpoints Added

Base path: `/notifications`

### 1) Register Device Token

Endpoint:
- `POST /notifications/devices/register`

Headers:
- `Authorization: Bearer <access_token>`
- `Content-Type: application/json`

Request body:
```json
{
  "token": "<fcm_device_token>",
  "platform": "android",
  "app_version": "1.0.0"
}
```

Allowed platform values:
- `android`
- `ios`

Success response:
```json
{
  "success": true,
  "message": "Device token registered successfully."
}
```

Notes:
- Call this after login when token is available.
- Call this again when FCM token refreshes.
- The API is upsert-safe: existing tokens are updated/re-linked.

### 2) Unregister Device Token

Endpoint:
- `POST /notifications/devices/unregister`

Headers:
- `Authorization: Bearer <access_token>`
- `Content-Type: application/json`

Request body:
```json
{
  "token": "<fcm_device_token>"
}
```

Success response:
```json
{
  "success": true,
  "message": "Device token unregistered successfully."
}
```

Notes:
- Call on logout.
- Safe to call even if token was already removed.

## Push Events You Will Receive

When approver/admin decides an expense request:

1) Approved event
- `data.event_type = "expense_approved"`

2) Rejected event
- `data.event_type = "expense_rejected"`

3) Clarification required event
- `data.event_type = "clarification_required"`

4) Clarification responded event
- `data.event_type = "clarification_responded"`

5) Paid event
- `data.event_type = "expense_paid"`

Common push data payload keys:
- `event_type`
- `expense_id`
- `request_id`
- `status`

Notification title/body:
- title: `Expense Update`
- body examples:
  - `Your expense EXP-1001 was approved.`
  - `Your expense EXP-1001 was rejected.`

- title: `Clarification Required`
- body example:
  - `Your expense EXP-1001 needs clarification.`

- title: `Clarification Responded`
- body example:
  - `Requester responded for expense EXP-1001.`

- title: `Expense Paid`
- body example:
  - `Your expense EXP-1001 has been marked as paid.`

## Frontend Step-by-Step Integration

### Step 1: Configure FCM in mobile app

- Android: add Firebase config and dependencies.
- iOS: add APNs capability and Firebase config.
- Ensure app can obtain FCM token.

### Step 2: Register token after login

Flow:
1. User logs in and gets backend access token.
2. Mobile obtains FCM token.
3. Mobile calls `POST /notifications/devices/register`.

Recommended implementation details:
- Retry registration once if network fails.
- Debounce repeated register calls on app start.

### Step 3: Re-register on token refresh

FCM tokens can rotate. Whenever token refresh callback is triggered:
- Call `POST /notifications/devices/register` again with latest token.

### Step 4: Unregister on logout

Before clearing local auth:
- Call `POST /notifications/devices/unregister` with current token.

If unregister fails due to network:
- Continue logout anyway.
- Try best-effort unregister next login cycle.

### Step 5: Handle notification tap navigation

Use payload fields for routing:
- If `event_type` is one of these:
  - `expense_approved`
  - `expense_rejected`
  - `clarification_required`
  - `clarification_responded`
  - `expense_paid`
  - Navigate to expense detail screen
  - Use `expense_id` (or `request_id`) to fetch detail

### Step 6: Foreground behavior

When app is open and push arrives:
- Show in-app toast/banner
- Update any expense list cache for that request
- Optionally trigger expense detail refetch

## Error Handling Contract

Possible backend outcomes for register/unregister:
- `200`: success
- `400`: invalid request body/token
- `401`: access token invalid/expired
- `500`: backend error

Frontend handling:
- On `401`: refresh auth or force re-login
- On `500`: retry with backoff (max 2 retries)

## Security and Reliability Notes

- Always send backend JWT in Authorization header.
- Never store FCM server credentials in frontend/mobile.
- Do not trust push payload alone for sensitive decisions; fetch expense detail from API on screen open.

## Suggested Frontend Checklist

- [ ] Device token captured
- [ ] Register API called after login
- [ ] Token refresh hook implemented
- [ ] Unregister API called on logout
- [ ] Tap navigation to expense details working
- [ ] Foreground in-app message handling working
- [ ] Retry and error handling added

## Example Minimal API Wrapper

```ts
async function registerDeviceToken(apiBase: string, accessToken: string, token: string, platform: "android" | "ios", appVersion?: string) {
  const res = await fetch(`${apiBase}/notifications/devices/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ token, platform, app_version: appVersion ?? null }),
  });

  if (!res.ok) {
    throw new Error(`Register token failed: ${res.status}`);
  }

  return res.json();
}

async function unregisterDeviceToken(apiBase: string, accessToken: string, token: string) {
  const res = await fetch(`${apiBase}/notifications/devices/unregister`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ token }),
  });

  if (!res.ok) {
    throw new Error(`Unregister token failed: ${res.status}`);
  }

  return res.json();
}
```
