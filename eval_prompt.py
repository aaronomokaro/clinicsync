import os
import json
import time
from unittest.mock import patch
from datetime import date, timedelta
from dotenv import load_dotenv
from anthropic import Anthropic
from conversation import handle_message, sessions
from sheets import sheet

load_dotenv()

client = Anthropic()
results = []
total_score = 0
max_score = 0

def check(test_name, condition, details=""):
    global total_score, max_score
    max_score += 1
    if condition:
        total_score += 1
        status = "PASS"
    else:
        status = "FAIL"
    results.append(f"{status} -- {test_name} {details}")

def model_grade(criteria, patient_message, assistant_response, context=""):
    prompt = f"""You are an evaluator for a WhatsApp clinic booking assistant.

Criteria: {criteria}
Patient message: {patient_message}
Assistant response: {assistant_response}
Additional context: {context}

Score 1 if the criteria is met, 0 if not.
Reply with only a JSON object with no markdown:
{{"score": 0, "reason": "brief explanation"}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        result = json.loads(response.content[0].text)
        return result["score"], result["reason"]
    except:
        return 0, "Could not parse grader response"

def run_conversation(phone, messages):
    sessions.pop(phone, None)
    responses = []
    with patch("conversation.send_message") as mock_send:
        for message in messages:
            handle_message(phone, message)
            if mock_send.called:
                responses.append(mock_send.call_args[0][1])
            time.sleep(1)
    return responses

def get_latest_booking(name, booking_date):
    bookings_sheet = sheet.worksheet("Bookings")
    all_bookings = bookings_sheet.get_all_records()
    matches = [b for b in all_bookings if b["Patient Name"] == name and b["Date"] == str(booking_date)]
    return matches[-1] if matches else None

# ─────────────────────────────────────────
# TEST 1 -- English booking intent detection
# ─────────────────────────────────────────
phone = "whatsapp:+44111111111"
responses = run_conversation(phone, ["I want to book an appointment"])
response = responses[0] if responses else ""

check(
    "English booking intent -- GDPR message sent",
    "YES" in response and "NO" in response
)

score, reason = model_grade(
    "Did the assistant respond in English matching the patient's language?",
    "I want to book an appointment",
    response
)
check(f"English booking intent -- language mirroring ({reason})", score == 1)

score, reason = model_grade(
    "Is the response relevant to a patient wanting to book an appointment?",
    "I want to book an appointment",
    response
)
check(f"English booking intent -- answer relevancy ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 2 -- Pidgin booking intent detection
# ─────────────────────────────────────────
phone = "whatsapp:+44222222222"
responses = run_conversation(phone, ["I wan book appointment"])
response = responses[0] if responses else ""

score, reason = model_grade(
    "Did the assistant acknowledge the patient's intent to book and start the booking process?",
    "I wan book appointment",
    response
)
check(f"Pidgin booking intent -- booking process started ({reason})", score == 1)

score, reason = model_grade(
    "Did the assistant respond in Pidgin or informal Nigerian English matching the patient's language?",
    "I wan book appointment",
    response
)
check(f"Pidgin booking intent -- language mirroring ({reason})", score == 1)

score, reason = model_grade(
    "Is the response relevant to a patient wanting to book an appointment?",
    "I wan book appointment",
    response
)
check(f"Pidgin booking intent -- answer relevancy ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 3 -- Walk-in intent detection
# ─────────────────────────────────────────
phone = "whatsapp:+44333333333"
responses = run_conversation(phone, ["I don reach the hospital"])
response = responses[0] if responses else ""

score, reason = model_grade(
    "Did the assistant recognise this as a walk-in patient arriving at the clinic?",
    "I don reach the hospital",
    response
)
check(f"Walk-in intent detection ({reason})", score == 1)

score, reason = model_grade(
    "Is the response relevant to a patient who has just arrived at the clinic?",
    "I don reach the hospital",
    response
)
check(f"Walk-in intent -- answer relevancy ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 4 -- HELP trigger
# ─────────────────────────────────────────
phone = "whatsapp:+44444444444"
responses = run_conversation(phone, ["HELP"])
response = responses[0] if responses else ""

clinic_phone = os.getenv("CLINIC_PHONE")
check(
    "HELP trigger -- clinic phone number included",
    clinic_phone in response
)
check(
    "HELP trigger -- session cleared after HELP",
    phone not in sessions
)

score, reason = model_grade(
    "Did the assistant direct the patient to call or visit in person without continuing the booking flow?",
    "HELP",
    response
)
check(f"HELP trigger -- response quality ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 5 -- GDPR decline
# ─────────────────────────────────────────
phone = "whatsapp:+44555555555"
responses = run_conversation(phone, ["I want to book", "NO"])
response = responses[-1] if responses else ""

score, reason = model_grade(
    "Did the assistant end the conversation politely after the patient declined data collection?",
    "NO",
    response
)
check(f"GDPR decline -- polite ending ({reason})", score == 1)

score, reason = model_grade(
    "Did the assistant avoid collecting any personal data after the patient said NO?",
    "NO",
    response
)
check(f"GDPR decline -- no data collected ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 6 -- English booking confirmation
# ─────────────────────────────────────────
phone = "whatsapp:+44666666666"
tomorrow = date.today() + timedelta(days=1)
sessions.pop(phone, None)

responses = run_conversation(phone, [
    "I want to book an appointment",
    "YES",
    "TestEnglish",
    "Tomorrow at 9am"
])

last_response = responses[-1] if responses else ""
booking = get_latest_booking("TestEnglish", tomorrow)

check(
    "English confirmation -- booking written to Sheet",
    booking is not None
)

if booking:
    check(
        "English confirmation -- correct date written",
        booking["Date"] == str(tomorrow)
    )
    check(
        "English confirmation -- correct type written",
        booking["Type"] == "ADVANCE"
    )

score, reason = model_grade(
    "Did the assistant confirm the booking with the date and time clearly?",
    "Tomorrow at 9am",
    last_response
)
check(f"English confirmation -- response quality ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 7 -- Pidgin booking confirmation
# ─────────────────────────────────────────
phone = "whatsapp:+44777777777"
sessions.pop(phone, None)

responses = run_conversation(phone, [
    "I wan book",
    "YES",
    "TestPidgin",
    "Tomorrow 9am"
])

last_response = responses[-1] if responses else ""
pidgin_booking = get_latest_booking("TestPidgin", tomorrow)

check(
    "Pidgin confirmation -- booking written to Sheet",
    pidgin_booking is not None
)

score, reason = model_grade(
    "Did the assistant respond in Pidgin or informal Nigerian English throughout the conversation?",
    "I wan book",
    last_response
)
check(f"Pidgin confirmation -- language mirroring ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 8 -- Slot manufacturing check
# ─────────────────────────────────────────
from sheets import get_available_slots
today_slots = get_available_slots(date.today())
available_times = list(today_slots.keys())

phone = "whatsapp:+44888888888"
responses = run_conversation(phone, ["I want to book for today"])
response = responses[0] if responses else ""

score, reason = model_grade(
    f"The only available slots for today are: {available_times}. Did the assistant avoid mentioning any time not in this list?",
    "I want to book for today",
    response,
    context=f"Available slots: {available_times}"
)
check(f"Slot manufacturing -- no invented slots ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 9 -- 7 day window check
# ─────────────────────────────────────────
max_date = date.today() + timedelta(days=7)

phone = "whatsapp:+44999999999"
sessions.pop(phone, None)
responses = run_conversation(phone, [
    "I want to book",
    "YES",
    "TestWindow",
    "Next month"
])

response = responses[-1] if responses else ""

score, reason = model_grade(
    f"Today is {date.today()}. The maximum date allowed is {max_date}. Did the assistant avoid offering any dates beyond {max_date}?",
    "Next month",
    response,
    context=f"Max allowed date: {max_date}"
)
check(f"7 day window -- no dates beyond limit ({reason})", score == 1)

time.sleep(10)

# ─────────────────────────────────────────
# TEST 10 -- Invalid input handling
# ─────────────────────────────────────────
phone = "whatsapp:+44100000000"
responses = run_conversation(phone, [
    "xxxxxxxxxxx",
    "qqqqqqqqqq",
    "zzzzzzzzzz"
])

response = responses[-1] if responses else ""

check(
    "Invalid input -- clinic phone number sent after 3 attempts",
    clinic_phone in response
)

# ─────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────
print("\n=== LAYER 2 -- PROMPT EVALUATION ===\n")
for result in results:
    print(result)

print(f"\nScore: {total_score}/{max_score} = {round(total_score/max_score*100)}%")