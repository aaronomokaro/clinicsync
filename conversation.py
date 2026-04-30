import os
import json
from datetime import date, datetime, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv
from sheets import get_available_slots, write_booking, get_next_queue_number, count_bookings
from twilio_sender import send_message

load_dotenv()

CLINIC_NAME = os.getenv("CLINIC_NAME")
CLINIC_PHONE = os.getenv("CLINIC_PHONE")
SLOTS_PER_DOCTOR = int(os.getenv("SLOTS_PER_DOCTOR", 6))

client = Anthropic()

sessions = {}

INTENT_EXTRACTION_PROMPT = """
<role>
You are an intent extraction engine for a Nigerian clinic WhatsApp booking system. Your only job is to read the patient message and return a JSON object. Nothing else. No conversation. No explanations.
</role>

<context>
Today's date is {today}.
Current time is {current_time}.
Current step is {step}.
Patient message: {message}
</context>

<intent_options>
- booking -- patient wants to book a future appointment
- walkin -- patient is physically at the clinic right now
- help -- patient needs human assistance
- yes -- patient is confirming or consenting
- no -- patient is declining or cancelling
- slot_pick -- patient is selecting a slot from a numbered list or by time
- greeting -- patient is saying hello, hi, good morning, or starting conversation with no clear request yet
- unclear -- only use this if you genuinely cannot determine intent after trying hard
</intent_options>

<rules>
- Always try to resolve intent before returning unclear
- Handle typos, abbreviations, pidgin, and informal language
- "yh", "sure", "ok", "yeah", "oya" all mean yes
- "nah", "nope", "cancel" all mean no
- "tmr" means tomorrow, "nxt week" means next week
- "11" at a slot selection step means slot number 11 or 11:00am depending on context
- "morning" means 09:00, "afternoon" means 13:00, "evening" means 16:00
- If patient gives a name at the name step extract it as the name field
- If patient gives a time like "11" or "11am" convert it to HH:MM format
- If patient gives a date like "tomorrow" or "next tuesday" convert it to YYYY-MM-DD format
</rules>

<output>
Return ONLY this JSON object with no markdown, no backticks, no explanation:
{{
    "intent": "booking | walkin | help | yes | no | slot_pick | unclear",
    "date": "YYYY-MM-DD or null",
    "time": "HH:MM or null",
    "name": "string or null",
    "slot_number": "integer or null",
    "confidence": "high or low"
}}
</output>
"""

RESPONSE_GENERATION_PROMPT = """
<identity>
You are a friendly booking assistant for {clinic_name}. Your job is to generate the next message to send to the patient based on the current step and context provided.
</identity>

<rules>
- Always respond in the same language the patient is using -- English, Pidgin, or a mix
- Never use markdown formatting. No bold, no asterisks, no headers. Plain text only
- Keep responses short and clear. This is WhatsApp not email
- Never mention doctor names or IDs
- Never mention the word UNASSIGNED
- Use the patient name if available to make responses personal
- Never give medical advice or assess urgency
</rules>

<step_context>
At WALKIN_GDPR_WAIT and BOOKING_GDPR_WAIT -- you are expecting YES or NO. Try hard to detect consent or refusal before returning unclear.
At WALKIN_NAME_WAIT and BOOKING_NAME_WAIT -- you are expecting a name. Any word that looks like a person's name should be extracted as the name field.
At BOOKING_TIME_CHECK -- you are expecting a date, time, or both. Try hard to extract any date or time reference before returning unclear.
At BOOKING_DAY_PICK_WAIT -- you are expecting a number from a numbered list of days. Only accept slot_number. Ignore any direct date references.
At BOOKING_TIME_PICK_WAIT -- you are expecting a number from a numbered list of times. Only accept slot_number. Ignore any direct time references.
</step_context>

<current_step>
{step}
</current_step>

<context>
{context}
</context>

<step_instructions>
START -- Greet the patient and ask if they want to walk in or book an appointment. Keep it short and clear.
WALKIN_GDPR -- The patient is physically at the clinic right now. Check context for patient_message to match their language. Acknowledge their arrival warmly, then send the GDPR consent message
BOOKING_GDPR -- The patient wants to book an appointment. Check context for patient_message to match their language. Greet them warmly, then send the GDPR consent message
WALKIN_NAME -- Ask for the patient name
BOOKING_NAME -- Ask for the patient name
BOOKING_TIME -- Ask for their preferred date and time
BOOKING_TIME_CHECK -- Handle based on context:
- If context has missing = date_and_time: ask the patient for both their preferred date and time
- If context has missing = time_only: acknowledge the date the patient gave (in given_date) and ask specifically for the time
- If context has invalid_time: tell the patient that time is outside our working hours and ask for a time between working_hours_start and working_hours_end
- Otherwise: process the booking normally
BOOKING_DAY_PICK -- Show the available days from the context available_days list as a numbered list. Use the exact date strings from the list. Do not shorten or modify them. Ask the patient to pick a day by number only.
BOOKING_TIME_PICK -- Show the available times for the chosen day as a numbered list. Use the exact times from the list. Ask the patient to pick by number only. If context shows the patient sent something other than a valid number tell them to reply only with the number from the list.
WALKIN_CONFIRM -- Confirm the patient has been added to the walk-in queue and to wait for their name to be called
BOOKING_CONFIRM -- Confirm the booking using context.confirmed_slot.date and context.confirmed_slot.time. Always include both date and time explicitly in the message. Remind the patient to arrive on time.
WALKIN_NO_SLOTS -- Tell the patient there are no available slots today and to see the receptionist directly
END_NO -- End the conversation politely after patient declined
END_INVALID -- Tell patient you could not understand and give clinic phone number
END_NO_SLOTS -- Tell patient there are no slots within the booking window and give clinic phone number
HELP -- Give the clinic phone number and tell patient to call or visit in person
</step_instructions>

<gdpr_message>
The exact GDPR message to use:
"We need your name to process your booking. This data is stored securely and used only for appointment purposes. Reply YES to continue or NO to cancel."
</gdpr_message>

<language>
Mirror the patient language at all times. If they write in Pidgin respond in Pidgin. If they write in English respond in English. If they mix you mix.
</language>
"""


def extract_intent(step, message, history):
    today = date.today().strftime("%A %d %B %Y")
    current_time = datetime.now().strftime("%H:%M")

    prompt = INTENT_EXTRACTION_PROMPT.format(
        today=today,
        current_time=current_time,
        step=step,
        message=message
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        temperature=0,
        system=prompt,
        messages=history + [{"role": "user", "content": message}]
    )

    try:
        result = json.loads(response.content[0].text)
        return result
    except:
        return {
            "intent": "unclear",
            "date": None,
            "time": None,
            "name": None,
            "slot_number": None,
            "confidence": "low"
        }


def generate_response(step, context, history):
    prompt = RESPONSE_GENERATION_PROMPT.format(
        clinic_name=CLINIC_NAME,
        step=step,
        context=json.dumps(context, indent=2)
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        temperature=0.1,
        system=prompt,
        messages=history + [{"role": "user", "content": f"Generate the response for step: {step}"}]
    )

    return response.content[0].text.strip()


def route_step(current_step, intent_data, session):
    intent = intent_data.get("intent")

    if intent == "help":
        return "HELP"

    if current_step == "START":
        if intent == "walkin":
            return "WALKIN_GDPR"
        elif intent == "booking":
            return "BOOKING_GDPR"
        elif intent == "help":
            return "HELP"
        elif intent == "greeting":
            return "START"    
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "START"

    if current_step == "WALKIN_GDPR_WAIT":
        if intent == "yes":
            return "WALKIN_NAME"
        elif intent == "no":
            return "END_NO"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "WALKIN_GDPR_WAIT"

    if current_step == "WALKIN_NAME_WAIT":
        if intent_data.get("name"):
            return "WALKIN_CONFIRM"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "WALKIN_NAME_WAIT"

    if current_step == "BOOKING_GDPR_WAIT":
        if intent == "yes":
            return "BOOKING_NAME"
        elif intent == "no":
            return "END_NO"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "BOOKING_GDPR_WAIT"

    if current_step == "BOOKING_NAME_WAIT":
        if intent_data.get("name"):
            return "BOOKING_TIME"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "BOOKING_NAME_WAIT"

    if current_step == "BOOKING_TIME_CHECK":
        if intent_data.get("date") or intent_data.get("time"):
            return "BOOKING_TIME_CHECK"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "BOOKING_TIME_CHECK"

    if current_step == "BOOKING_TIME_PICK_WAIT":
        slot_num = intent_data.get("slot_number")
        available_times = session.get("available_times", [])
        if slot_num and 1 <= int(slot_num) <= len(available_times):
            return "BOOKING_TIME_PICK_WAIT"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "BOOKING_TIME_PICK_WAIT"

    if current_step == "BOOKING_TIME_PICK_WAIT":
        if intent_data.get("slot_number") or intent_data.get("time"):
            return "BOOKING_CONFIRM"
        else:
            session["invalid_count"] += 1
            if session["invalid_count"] >= 3:
                return "END_INVALID"
            return "BOOKING_TIME_PICK_WAIT"

    return current_step

def is_within_working_hours(time_str):
    try:
        hour = int(time_str.split(":")[0])
        start = int(os.getenv("WORKING_HOURS_START", 8))
        end = int(os.getenv("WORKING_HOURS_END", 18))
        return start <= hour < end
    except:
        return False

def handle_business_logic(step, intent_data, session):
    context = {}

    if step == "WALKIN_GDPR":
        today = date.today()
        slots = get_available_slots(today, is_walkin=True)
        if not slots:
            return "WALKIN_NO_SLOTS", {}
        session["available_times"] = list(slots.keys())
        context["slots"] = slots
        return "WALKIN_GDPR", context

    if step == "WALKIN_NAME_WAIT":
        print("Name from intent_data:", intent_data.get("name"))
        name = intent_data.get("name")
        if name:
            session["name"] = name

    if step == "WALKIN_CONFIRM":
        today = date.today()
        slots = get_available_slots(today, is_walkin=True)
        if not slots:
            return "WALKIN_NO_SLOTS", {}
        first_slot = list(slots.keys())[0]
        queue_number = get_next_queue_number(str(today))
        write_booking(
            patient_name=session["name"],
            booking_type="WALKIN",
            date=str(today),
            slot_time=first_slot,
            doctor_id=slots[first_slot][0],
            queue_number=queue_number
        )
        context["queue_number"] = queue_number
        context["slot_time"] = first_slot
        context["date"] = today.strftime("%A %d %B %Y")

    if step == "BOOKING_NAME_WAIT":
        name = intent_data.get("name")
        if name:
            session["name"] = name

    if step == "BOOKING_TIME_CHECK":
        extracted_date = intent_data.get("date")
        extracted_time = intent_data.get("time")
        if extracted_date:
            session["preferred_date"] = extracted_date
        if extracted_time:
            session["preferred_time"] = extracted_time

        preferred_date = session.get("preferred_date")
        preferred_time = session.get("preferred_time")

        if not preferred_date:
            context["missing"] = "date_and_time"
            return "BOOKING_TIME_CHECK", context

        if preferred_date and not preferred_time:
            context["missing"] = "time_only"
            context["given_date"] = datetime.strptime(preferred_date, "%Y-%m-%d").strftime("%A %d %B %Y")
            return "BOOKING_TIME_CHECK", context

        if extracted_time and not is_within_working_hours(preferred_time):
            context["invalid_time"] = preferred_time
            context["working_hours_start"] = os.getenv("WORKING_HOURS_START", "8")
            context["working_hours_end"] = os.getenv("WORKING_HOURS_END", "18")
            session["preferred_time"] = None
            return "BOOKING_TIME_CHECK", context

        check_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
        slots = get_available_slots(check_date)

        if slots and preferred_time in slots:
            confirmed_time = preferred_time

            current_counts = count_bookings(check_date)
            slot_key_count = sum(
                v for k, v in current_counts.items()
                if k.endswith(f"_{confirmed_time}")
            )

            if slot_key_count >= 3:
                available_days = {}
                today = date.today()
                for i in range(7):
                    check = today + timedelta(days=i)
                    day_slots = get_available_slots(check)
                    if day_slots:
                        available_days[check.strftime("%A %d %B %Y")] = str(check)
                session["available_days"] = list(available_days.values())
                context["available_days"] = list(available_days.keys())
                return "BOOKING_DAY_PICK", context

            doctor_id = slots.get(confirmed_time, ["UNASSIGNED"])[0]
            queue_number = get_next_queue_number(session["preferred_date"], confirmed_time)

            write_booking(
                patient_name=session["name"],
                booking_type="ADVANCE",
                date=session["preferred_date"],
                slot_time=confirmed_time,
                doctor_id=doctor_id,
                queue_number=queue_number
            )

            session["confirmed_slot"] = {
                "date": check_date.strftime("%A %d %B %Y"),
                "time": confirmed_time,
                "doctor": doctor_id,
                "queue_number": queue_number
            }

            context["confirmed_slot"] = session["confirmed_slot"]
            context["name"] = session["name"]
            return "BOOKING_CONFIRM", context

        available_days = {}
        today = date.today()
        for i in range(7):
            check = today + timedelta(days=i)
            day_slots = get_available_slots(check)
            if day_slots:
                available_days[check.strftime("%A %d %B %Y")] = str(check)

        session["available_days"] = list(available_days.values())
        context["available_days"] = list(available_days.keys())
        return "BOOKING_DAY_PICK", context

    if step == "BOOKING_DAY_PICK_WAIT":
        slot_number = intent_data.get("slot_number")
        if slot_number and session.get("available_days"):
            try:
                picked_day = session["available_days"][int(slot_number) - 1]
                session["preferred_date"] = picked_day
                check_date = datetime.strptime(picked_day, "%Y-%m-%d").date()
                slots = get_available_slots(check_date)
                session["available_times"] = list(slots.keys())
                context["available_times"] = list(slots.keys())
                context["date"] = check_date.strftime("%A %d %B %Y")
            except:
                pass
        return "BOOKING_TIME_PICK", context

    if step == "BOOKING_TIME_PICK_WAIT":
        slot_number = intent_data.get("slot_number")
        extracted_time = intent_data.get("time")

        if slot_number and session.get("available_times"):
            try:
                picked_time = session["available_times"][int(slot_number) - 1]
                session["confirmed_slot"] = picked_time
            except:
                pass
        elif extracted_time and extracted_time in session.get("available_times", []):
            session["confirmed_slot"] = extracted_time

        if session.get("confirmed_slot") and session.get("preferred_date"):
            check_date = datetime.strptime(session["preferred_date"], "%Y-%m-%d").date()
            confirmed_time = session["confirmed_slot"]
            slots = get_available_slots(check_date)

            current_counts = count_bookings(check_date)
            slot_key_count = sum(
                v for k, v in current_counts.items()
                if k.endswith(f"_{confirmed_time}")
            )

            if slot_key_count >= 3:
                context["slot_full"] = True
                return "BOOKING_DAY_PICK", context

            doctor_id = slots.get(confirmed_time, ["UNASSIGNED"])[0]
            queue_number = get_next_queue_number(session["preferred_date"])

            write_booking(
                patient_name=session["name"],
                booking_type="ADVANCE",
                date=session["preferred_date"],
                slot_time=confirmed_time,
                doctor_id=doctor_id,
                queue_number=queue_number
            )

            session["confirmed_slot"] = {
                "date": check_date.strftime("%A %d %B %Y"),
                "time": confirmed_time,
                "doctor": doctor_id,
                "queue_number": queue_number
            }

            context["confirmed_slot"] = session["confirmed_slot"]
            context["name"] = session["name"]
            return "BOOKING_CONFIRM", context

    return step, context


def handle_message(phone_number, message_text):
    if phone_number not in sessions:
        sessions[phone_number] = {
            "flow": None,
            "step": "START",
            "name": None,
            "preferred_date": None,
            "preferred_time": None,
            "confirmed_slot": None,
            "invalid_count": 0,
            "history": [],
            "available_days": [],
            "available_times": []
        }

    session = sessions[phone_number]

    if "HELP" in message_text.upper() or "HUMAN" in message_text.upper():
        response = generate_response("HELP", {"clinic_phone": CLINIC_PHONE}, session["history"])
        send_message(phone_number, response)
        sessions.pop(phone_number, None)
        return

    intent_data = extract_intent(
        step=session["step"],
        message=message_text,
        history=session["history"]
    )
    print("Step:", session["step"], "Intent data:", intent_data)

    next_step = route_step(session["step"], intent_data, session)

    if intent_data.get("name") and session["name"] is None:
        session["name"] = intent_data.get("name")
    
    next_step, context = handle_business_logic(next_step, intent_data, session)

    context["name"] = session.get("name")
    context["clinic_phone"] = CLINIC_PHONE
    context["clinic_name"] = CLINIC_NAME

    print("Generating response for step:", next_step, "context:", context)
    response = generate_response(next_step, context, session["history"])

    session["history"].append({"role": "user", "content": message_text})
    session["history"].append({"role": "assistant", "content": response})

    wait_transitions = {
        "WALKIN_GDPR": "WALKIN_GDPR_WAIT",
        "WALKIN_NAME": "WALKIN_NAME_WAIT",
        "BOOKING_GDPR": "BOOKING_GDPR_WAIT",
        "BOOKING_NAME": "BOOKING_NAME_WAIT",
        "BOOKING_TIME": "BOOKING_TIME_CHECK",
        "BOOKING_DAY_PICK": "BOOKING_DAY_PICK_WAIT",
        "BOOKING_TIME_PICK": "BOOKING_TIME_PICK_WAIT",
    }

    if next_step in wait_transitions:
        session["step"] = wait_transitions[next_step]
    else:
        session["step"] = next_step

    send_message(phone_number, response)

    end_steps = ["END_NO", "END_INVALID", "END_NO_SLOTS", "HELP", "WALKIN_NO_SLOTS", "WALKIN_CONFIRM", "BOOKING_CONFIRM"]
    if next_step in end_steps:
        sessions.pop(phone_number, None)