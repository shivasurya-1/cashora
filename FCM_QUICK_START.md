# FCM Quick Start & Test Guide

**🎯 Goal:** Verify push notifications work end-to-end

**⏱️ Time Required:** 5-10 minutes

---

## Prerequisites

- ✅ Backend server running (uvicorn)
- ✅ Two test devices or one device + web browser
- ✅ Flutter app installed on at least one device
- ✅ Test users: one REQUESTOR, one ADMIN

---

## Option 1: Automated Verification (Recommended)

Run the automated verification script:

```bash
cd "d:\eskooly_conversion_v1\petty cash"
python verify_fcm_backend.py
```

This will check:
1. Database tables
2. Environment variables
3. Firebase initialization
4. Push service code
5. Event triggers
6. Notification history
7. Live FCM send test

**Expected output:** All checks should pass ✅

---

## Option 2: Manual Testing (Step-by-Step)

### Step 1: Verify Database Setup (30 seconds)

Open PostgreSQL client and run:

```sql
SELECT COUNT(*) FROM user_device_tokens WHERE is_active = true;
```

**Expected:** At least 1 (number of logged-in devices)

**If 0:** Have a user log in from the Flutter app first.

### Step 2: Get a Test Token (15 seconds)

```sql
SELECT token FROM user_device_tokens WHERE is_active = true LIMIT 1;
```

Copy the token value (it's a long string, ~150-200 characters).

### Step 3: Test FCM Send (30 seconds)

```bash
cd "d:\eskooly_conversion_v1\petty cash"
python test_push.py
```

When prompted, paste the token from Step 2.

**Expected output:**
```
✅ Firebase initialized
✅ Sending test push...
✅ Message ID: projects/sria-cashora/messages/...
```

**Device should buzz within 3 seconds.**

**If it buzzes:** ✅ Backend → Firebase → Device pipeline works!

**If it doesn't buzz:**
- Check if FCM returned an error (e.g., "token not registered")
- Verify device has internet connection
- Check if notifications are enabled in device settings

### Step 4: Integration Test (2 minutes)

**Device A (Requestor):**
1. Open Flutter app
2. Log in as REQUESTOR
3. Submit a test expense request
4. Note the request ID (e.g., EXP-A1B2C3D4)

**Device B (Admin) or Web:**
1. Log in as ADMIN
2. Go to pending expenses
3. Find the expense from Device A
4. Click "Approve"

**Expected:** Device A should receive push notification within 3 seconds with title "Expense Approved ✅"

**If notification arrives:** 🎉 **Everything works!**

**If notification doesn't arrive:** Continue to Step 5.

### Step 5: Debug (2 minutes)

Check the audit table:

```sql
SELECT 
    title,
    is_success,
    error_message,
    sent_at
FROM notification_audit 
ORDER BY sent_at DESC 
LIMIT 5;
```

**Scenario A: No rows appear**
→ Push service didn't execute. Check server logs for exceptions.

**Scenario B: `is_success = false`**
→ FCM rejected the message. Check `error_message` column:
- "token not registered" → Token is stale, have user log out and log back in
- "permission denied" → Firebase credentials are wrong
- "invalid argument" → Payload format issue (shouldn't happen with our code)

**Scenario C: `is_success = true` but device didn't buzz**
→ Push was sent to FCM successfully but device didn't receive it:
- Different Firebase projects (app vs backend)
- Device offline or network blocked FCM
- Device has notifications disabled

---

## Common Issues

### Issue: "firebase-admin not installed"

```bash
pip install firebase-admin==6.8.0
```

### Issue: "Invalid PEM format"

The `FIREBASE_PRIVATE_KEY` in your `.env` needs to have literal `\n` characters, not actual newlines.

**Correct format:**
```env
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIEv...\n-----END PRIVATE KEY-----\n"
```

**Our code handles this automatically** with `.replace("\\n", "\n")`, so this shouldn't be an issue.

### Issue: "Tables don't exist"

Run migrations:

```bash
cd "d:\eskooly_conversion_v1\petty cash"
alembic upgrade head
```

### Issue: Test push works but real events don't

Check server logs during the approval request. The push should trigger in the background.

Also verify the endpoint being called:
- ✅ `POST /api/v1/approver/expenses/{id}/decision` with `{"action": "approve"}`
- ❌ Some other custom approve endpoint

---

## Quick Checklist

Copy this into your ticket/Slack:

```
FCM Backend Test Results:

Database:
[ ] user_device_tokens table exists
[ ] notification_audit table exists
[ ] Active tokens: ___ (fill in count)

Manual Test:
[ ] python test_push.py sends successfully
[ ] Device buzzed when test_push.py ran
[ ] Message ID: ___ (paste from output)

Integration Test:
[ ] Requestor submitted expense on Device A
[ ] Admin approved expense on Device B
[ ] Device A received push notification
[ ] Notification title: "Expense Approved ✅"
[ ] Tapping notification opened expense detail screen

If any box is unchecked, paste the error message here:
___
```

---

## Expected Behavior Summary

| Trigger | Who Gets Notified | Title | event_type |
|---|---|---|---|
| Admin approves expense | Requestor | "Expense Approved ✅" | expense_approved |
| Admin rejects expense | Requestor | "Expense Rejected ❌" | expense_rejected |
| Admin asks clarification | Requestor | "Clarification Needed 💬" | clarification_required |
| Requestor responds | All admins/approvers | "Clarification Responded" | clarification_responded |
| Accountant marks paid | Requestor | "Payment Processed 💸" | expense_paid |

---

## Success Criteria

✅ **Backend is working if:**
1. `python verify_fcm_backend.py` passes all checks
2. `python test_push.py` sends successfully (returns message ID)
3. Device buzzes when test_push.py runs
4. Audit table shows `is_success = true` entries

✅ **Integration is working if:**
1. All backend checks pass (above)
2. Device A receives push when Device B approves expense
3. Tapping notification opens correct expense detail screen
4. All 5 event types work (approve, reject, clarification ask/respond, paid)

---

## Next Steps After Testing

**If all tests pass:** 🎉 Push notifications are working! Deploy to production.

**If Step 3 (test_push.py) fails:** Issue is with Firebase credentials or initialization. Check `.env` file.

**If Step 3 passes but Step 4 fails:** Issue is with event wiring or token matching. Check server logs during approval.

**If nothing works:** Run the automated script and share the full output:
```bash
python verify_fcm_backend.py > fcm_test_results.txt
```

---

## Files Reference

- **Status Report:** `FCM_BACKEND_STATUS_REPORT.md` - Complete implementation details
- **Backend Guide:** `BACKEND_FCM_GUIDE.md` - Original specification from Flutter team
- **Audit Doc:** `FCM_AUDIT.md` - Flutter side audit (for reference)
- **Verification Script:** `verify_fcm_backend.py` - Automated checker
- **SQL Queries:** `verify_fcm_setup.sql` - Manual DB verification
- **Manual Test:** `test_push.py` - Send a test push to a specific token
- **This File:** `FCM_QUICK_START.md` - You are here!

---

## Support Contact

If you need help:
1. Run: `python verify_fcm_backend.py > results.txt`
2. Paste the output of `results.txt`
3. Include the last 20 lines of server logs
4. Share which step failed

---

**Remember:** The backend code is already 100% complete. You're just verifying the configuration! 🚀
