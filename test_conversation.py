from unittest.mock import patch
from conversation import handle_message, sessions

def test_booking_flow():
    phone = "whatsapp:+447350166919"
    
    # Clear any existing session
    sessions.pop(phone, None)
    
    with patch("conversation.send_message") as mock_send:
        
        # Step 1 -- patient sends booking intent
        print("\n--- Step 1: Booking intent ---")
        handle_message(phone, "I want to book an appointment")
        print("Claude response:", mock_send.call_args[0][1])
        
        # Step 2 -- patient accepts GDPR
        print("\n--- Step 2: GDPR consent ---")
        handle_message(phone, "YES")
        print("Claude response:", mock_send.call_args[0][1])
        
        # Step 3 -- patient gives name
        print("\n--- Step 3: Name ---")
        handle_message(phone, "Aaron")
        print("Claude response:", mock_send.call_args[0][1])
        
        # Step 4 -- patient gives preferred time
        print("\n--- Step 4: Preferred time ---")
        handle_message(phone, "Tomorrow at 10am")
        print("Claude response:", mock_send.call_args[0][1])

def test_help_trigger():
    phone = "whatsapp:+447350166919"
    sessions.pop(phone, None)
    
    with patch("conversation.send_message") as mock_send:
        print("\n--- HELP trigger ---")
        handle_message(phone, "HELP")
        print("Claude response:", mock_send.call_args[0][1])
        print("Session cleared:", phone not in sessions)

if __name__ == "__main__":
    test_booking_flow()
    test_help_trigger()

def test_walkin_flow():
    phone = "whatsapp:+447350166920"
    sessions.pop(phone, None)
    
    with patch("conversation.send_message") as mock_send:
        print("\n--- Walk-in Step 1: Arrival ---")
        handle_message(phone, "I don reach the hospital")
        print("Claude response:", mock_send.call_args[0][1])
        
        print("\n--- Walk-in Step 2: GDPR consent ---")
        handle_message(phone, "yes")
        print("Claude response:", mock_send.call_args[0][1])
        
        print("\n--- Walk-in Step 3: Name ---")
        handle_message(phone, "Emeka")
        print("Claude response:", mock_send.call_args[0][1])

import time

if __name__ == "__main__":
    test_booking_flow()
    time.sleep(30)
    test_help_trigger()
    time.sleep(30)
    test_walkin_flow()
