-- ============================================================
-- FCM Setup Verification Queries
-- Run these queries in order to verify the backend FCM setup
-- ============================================================

-- 1. Check if required tables exist
-- Expected: Should see both 'user_device_tokens' and 'notification_audit'
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('user_device_tokens', 'notification_audit')
ORDER BY table_name;

-- 2. Check device token registrations
-- Expected: At least one row per logged-in user
-- Token should be 150-200 characters long
-- is_active should be true
SELECT 
    id,
    user_id,
    LEFT(token, 30) || '...' as token_preview,
    platform,
    app_version,
    is_active,
    last_seen_at,
    created_at
FROM user_device_tokens 
ORDER BY last_seen_at DESC 
LIMIT 10;

-- 3. Count active tokens per user
-- Expected: Each user can have multiple active tokens (phone + tablet)
SELECT 
    user_id,
    COUNT(*) as active_token_count,
    MAX(last_seen_at) as most_recent_activity
FROM user_device_tokens 
WHERE is_active = true 
GROUP BY user_id
ORDER BY most_recent_activity DESC;

-- 4. Check notification audit history
-- Expected: If pushes have been sent, you'll see records here
-- is_success = true means FCM accepted the message
-- is_success = false means check error_message column
SELECT 
    id,
    user_id,
    LEFT(token, 30) || '...' as token_preview,
    title,
    LEFT(body, 50) || '...' as body_preview,
    is_success,
    error_message,
    sent_at
FROM notification_audit 
ORDER BY sent_at DESC 
LIMIT 20;

-- 5. Get a specific user's tokens (replace USER_ID_HERE)
-- Use this to get a token for testing with test_push.py
SELECT 
    token,
    platform,
    is_active,
    last_seen_at
FROM user_device_tokens 
WHERE user_id = USER_ID_HERE  -- Replace with actual user_id
ORDER BY last_seen_at DESC;

-- 6. Check recent notification sends for a specific token (replace TOKEN_HERE)
-- Use this to debug why a specific device isn't receiving pushes
SELECT 
    title,
    body,
    is_success,
    error_message,
    sent_at
FROM notification_audit 
WHERE token = 'TOKEN_HERE'  -- Replace with actual token
ORDER BY sent_at DESC 
LIMIT 10;

-- 7. Summary statistics
SELECT 
    (SELECT COUNT(*) FROM user_device_tokens WHERE is_active = true) as active_tokens,
    (SELECT COUNT(DISTINCT user_id) FROM user_device_tokens WHERE is_active = true) as users_with_tokens,
    (SELECT COUNT(*) FROM notification_audit WHERE is_success = true) as successful_pushes,
    (SELECT COUNT(*) FROM notification_audit WHERE is_success = false) as failed_pushes,
    (SELECT MAX(sent_at) FROM notification_audit) as last_push_sent;

-- 8. Find tokens that have never received a push successfully
-- These might be stale tokens that should be cleaned up
SELECT 
    udt.id,
    udt.user_id,
    LEFT(udt.token, 30) || '...' as token_preview,
    udt.platform,
    udt.created_at,
    udt.last_seen_at,
    COUNT(na.id) as total_attempts,
    SUM(CASE WHEN na.is_success THEN 1 ELSE 0 END) as successful_sends
FROM user_device_tokens udt
LEFT JOIN notification_audit na ON na.token = udt.token
WHERE udt.is_active = true
GROUP BY udt.id, udt.user_id, udt.token, udt.platform, udt.created_at, udt.last_seen_at
HAVING SUM(CASE WHEN na.is_success THEN 1 ELSE 0 END) = 0
ORDER BY udt.last_seen_at DESC;
