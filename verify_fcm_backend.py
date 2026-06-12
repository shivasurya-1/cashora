#!/usr/bin/env python3
"""
Automated FCM Backend Verification Script

This script verifies that the FCM backend is properly configured and working.
Run this AFTER the Flutter app has registered at least one device token.

Usage:
    python verify_fcm_backend.py
    python verify_fcm_backend.py --test-token <paste-token-here>
"""

import asyncio
import os
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# ANSI color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'

def print_section(title):
    print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{BLUE}{title}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")

def print_check(passed, message):
    symbol = f"{GREEN}✅{RESET}" if passed else f"{RED}❌{RESET}"
    print(f"{symbol} {message}")

def print_warning(message):
    print(f"{YELLOW}⚠️  {message}{RESET}")

def print_info(message):
    print(f"{BLUE}ℹ️  {message}{RESET}")


async def check_database_tables():
    """Verify database tables exist"""
    print_section("Step 1: Database Tables")
    
    try:
        from app.db.session import async_session
        from sqlalchemy import text
        
        async with async_session() as db:
            # Check for tables
            result = await db.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('user_device_tokens', 'notification_audit')
            """))
            tables = [row[0] for row in result.all()]
            
            has_tokens = 'user_device_tokens' in tables
            has_audit = 'notification_audit' in tables
            
            print_check(has_tokens, "user_device_tokens table exists")
            print_check(has_audit, "notification_audit table exists")
            
            if not has_tokens or not has_audit:
                print_warning("Missing tables! Run: alembic upgrade head")
                return False
            
            # Check token count
            result = await db.execute(text("SELECT COUNT(*) FROM user_device_tokens WHERE is_active = true"))
            token_count = result.scalar()
            
            print_check(token_count > 0, f"Active device tokens found: {token_count}")
            
            if token_count == 0:
                print_warning("No active tokens! Have users logged in from the Flutter app?")
                return False
            
            # Show recent tokens
            result = await db.execute(text("""
                SELECT user_id, platform, app_version, last_seen_at 
                FROM user_device_tokens 
                WHERE is_active = true 
                ORDER BY last_seen_at DESC 
                LIMIT 5
            """))
            
            print_info("Recent active tokens:")
            for row in result.all():
                print(f"   User {row[0]} | {row[1]} | v{row[2]} | Last seen: {row[3]}")
            
            return True
            
    except Exception as e:
        print_check(False, f"Database check failed: {str(e)}")
        return False


def check_environment_variables():
    """Verify FCM environment variables are set"""
    print_section("Step 2: Environment Variables")
    
    fcm_enabled = os.getenv("FCM_ENABLED", "false").lower() in ("1", "true", "yes")
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
    private_key = os.getenv("FIREBASE_PRIVATE_KEY", "")
    
    print_check(fcm_enabled, f"FCM_ENABLED = {fcm_enabled}")
    print_check(bool(project_id), f"FIREBASE_PROJECT_ID = {project_id or '(not set)'}")
    print_check(bool(client_email), f"FIREBASE_CLIENT_EMAIL = {client_email or '(not set)'}")
    print_check(len(private_key) > 100, f"FIREBASE_PRIVATE_KEY length = {len(private_key)} chars")
    
    if not fcm_enabled:
        print_warning("FCM is disabled! Set FCM_ENABLED=True in .env")
        return False
    
    if not project_id or not client_email or len(private_key) < 100:
        print_warning("Missing Firebase credentials in .env file")
        return False
    
    # Check for common private key issues
    if "\\n" in private_key and "\n" not in private_key:
        print_warning("FIREBASE_PRIVATE_KEY might have escaped \\n instead of real newlines")
        print_info("The code handles this automatically, but verify if you have issues")
    
    return True


def check_firebase_initialization():
    """Verify Firebase Admin SDK can initialize"""
    print_section("Step 3: Firebase Initialization")
    
    try:
        import firebase_admin
        from firebase_admin import credentials
        
        print_check(True, "firebase-admin package is installed")
        
        # Try to get existing app or initialize
        try:
            app = firebase_admin.get_app()
            print_check(True, "Firebase app already initialized")
            return True
        except ValueError:
            pass
        
        # Try to initialize
        project_id = os.getenv("FIREBASE_PROJECT_ID")
        client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
        private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")
        
        cert_dict = {
            "type": "service_account",
            "project_id": project_id,
            "private_key": private_key,
            "client_email": client_email,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
        
        print_check(True, "Firebase Admin SDK initialized successfully")
        return True
        
    except ImportError:
        print_check(False, "firebase-admin is not installed")
        print_warning("Run: pip install firebase-admin")
        return False
    except Exception as e:
        print_check(False, f"Firebase initialization failed: {str(e)}")
        if "Invalid PEM" in str(e):
            print_warning("FIREBASE_PRIVATE_KEY format issue - check the \\n escaping")
        return False


async def test_fcm_send(token=None):
    """Test sending a push notification"""
    print_section("Step 4: Test FCM Send")
    
    if not token:
        # Get a token from database
        try:
            from app.db.session import async_session
            from sqlalchemy import text
            
            async with async_session() as db:
                result = await db.execute(text("""
                    SELECT token FROM user_device_tokens 
                    WHERE is_active = true 
                    ORDER BY last_seen_at DESC 
                    LIMIT 1
                """))
                row = result.first()
                if row:
                    token = row[0]
        except Exception as e:
            print_check(False, f"Could not fetch token from database: {str(e)}")
            return False
    
    if not token:
        print_warning("No token available for testing")
        print_info("Provide a token with: python verify_fcm_backend.py --test-token <token>")
        return False
    
    print_info(f"Testing with token: {token[:30]}...")
    
    try:
        from firebase_admin import messaging
        
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(
                title="Backend Verification Test ✅",
                body="If you see this, FCM backend is working perfectly!",
            ),
            data={
                "event_type": "expense_approved",
                "expense_id": "999",
                "request_id": "TEST-VERIFICATION",
                "status": "test",
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="cashora_push_channel",
                    sound="default",
                    click_action="FLUTTER_NOTIFICATION_CLICK",
                ),
            ),
        )
        
        result = messaging.send(message)
        
        print_check(True, f"Push sent successfully! Message ID: {result}")
        print_info("Check the device - it should buzz within 3 seconds")
        
        return True
        
    except Exception as e:
        print_check(False, f"FCM send failed: {str(e)}")
        
        error_str = str(e).lower()
        if "not found" in error_str or "unregistered" in error_str:
            print_warning("Token is stale or belongs to a different Firebase project")
        elif "permission denied" in error_str or "403" in error_str:
            print_warning("Service account lacks permissions or credentials are wrong")
        elif "invalid pem" in error_str:
            print_warning("FIREBASE_PRIVATE_KEY format issue")
        
        return False


async def check_notification_history():
    """Check notification audit history"""
    print_section("Step 5: Notification History")
    
    try:
        from app.db.session import async_session
        from sqlalchemy import text
        
        async with async_session() as db:
            # Get stats
            result = await db.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN is_success THEN 1 ELSE 0 END) as successful,
                    MAX(sent_at) as last_sent
                FROM notification_audit
            """))
            stats = result.first()
            
            total = stats[0] or 0
            successful = stats[1] or 0
            last_sent = stats[2]
            
            print_info(f"Total notifications sent: {total}")
            print_info(f"Successful deliveries: {successful}")
            print_info(f"Last sent: {last_sent or 'Never'}")
            
            if total == 0:
                print_warning("No notifications have been sent yet")
                print_info("Trigger a business event (approve/reject an expense) to test")
                return False
            
            # Show recent notifications
            result = await db.execute(text("""
                SELECT title, is_success, error_message, sent_at
                FROM notification_audit 
                ORDER BY sent_at DESC 
                LIMIT 5
            """))
            
            print_info("\nRecent notifications:")
            for row in result.all():
                status = f"{GREEN}✓{RESET}" if row[1] else f"{RED}✗{RESET}"
                error = f" - {row[2]}" if row[2] else ""
                print(f"   {status} {row[0]} | {row[3]}{error}")
            
            return successful > 0
            
    except Exception as e:
        print_check(False, f"History check failed: {str(e)}")
        return False


async def verify_push_service():
    """Verify the push service code is correct"""
    print_section("Step 6: Push Service Code Check")
    
    try:
        from app.services import push_service
        
        # Check required functions exist
        has_send = hasattr(push_service, 'send_push_to_tokens')
        has_dispatch = hasattr(push_service, 'dispatch_push_notifications')
        has_get_app = hasattr(push_service, '_get_firebase_app')
        
        print_check(has_send, "send_push_to_tokens() function exists")
        print_check(has_dispatch, "dispatch_push_notifications() function exists")
        print_check(has_get_app, "_get_firebase_app() function exists")
        
        return has_send and has_dispatch and has_get_app
        
    except ImportError as e:
        print_check(False, f"Could not import push_service: {str(e)}")
        return False


def verify_event_triggers():
    """Verify business event triggers are wired"""
    print_section("Step 7: Business Event Triggers")
    
    from pathlib import Path
    
    files_to_check = [
        ("app/api/v1/approver.py", ["dispatch_push_notifications"], 2),  # approve/reject + clarification
        ("app/api/v1/requestor.py", ["dispatch_push_notifications"], 1),  # clarification response
        ("app/api/v1/accountant.py", ["dispatch_push_notifications"], 1),  # payment processed
    ]
    
    all_good = True
    for filepath, patterns, expected_count in files_to_check:
        file_path = Path(filepath)
        if not file_path.exists():
            print_check(False, f"{filepath} not found")
            all_good = False
            continue
        
        content = file_path.read_text(encoding='utf-8')
        count = sum(content.count(p) for p in patterns)
        
        passed = count >= expected_count
        print_check(passed, f"{filepath}: {count} dispatch calls (expected {expected_count})")
        
        if not passed:
            all_good = False
    
    if all_good:
        print_info("All 5 business event triggers are properly wired! ✨")
    
    return all_good


async def main():
    """Run all verification checks"""
    print(f"\n{BOLD}{GREEN}╔═══════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{GREEN}║        FCM Backend Verification Tool                          ║{RESET}")
    print(f"{BOLD}{GREEN}╚═══════════════════════════════════════════════════════════════╝{RESET}\n")
    
    # Parse command line args
    test_token = None
    if "--test-token" in sys.argv:
        idx = sys.argv.index("--test-token")
        if idx + 1 < len(sys.argv):
            test_token = sys.argv[idx + 1]
    
    results = []
    
    # Run checks
    results.append(("Database Tables", await check_database_tables()))
    results.append(("Environment Variables", check_environment_variables()))
    results.append(("Firebase Initialization", check_firebase_initialization()))
    results.append(("Push Service Code", await verify_push_service()))
    results.append(("Event Triggers", verify_event_triggers()))
    results.append(("Notification History", await check_notification_history()))
    
    if all(r[1] for r in results[:5]):  # All pre-checks passed
        results.append(("Test FCM Send", await test_fcm_send(test_token)))
    
    # Summary
    print_section("Summary")
    
    for name, passed in results:
        print_check(passed, name)
    
    total_passed = sum(1 for _, passed in results if passed)
    total_checks = len(results)
    
    print(f"\n{BOLD}Result: {total_passed}/{total_checks} checks passed{RESET}\n")
    
    if total_passed == total_checks:
        print(f"{GREEN}{BOLD}🎉 All checks passed! FCM backend is fully functional.{RESET}")
        print(f"{GREEN}If pushes still don't arrive on devices, the issue is likely:{RESET}")
        print(f"{GREEN}  1. Flutter app's google-services.json uses a different Firebase project{RESET}")
        print(f"{GREEN}  2. Device network can't reach FCM servers{RESET}")
        print(f"{GREEN}  3. Device notifications are disabled in OS settings{RESET}")
    else:
        print(f"{RED}{BOLD}❌ Some checks failed. Review the output above for details.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
