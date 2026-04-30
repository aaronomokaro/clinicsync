import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]

creds = Credentials.from_service_account_file(
    os.getenv("GOOGLE_CREDENTIALS_FILE"),
    scopes=SCOPES
)

client = gspread.authorize(creds)
sheet = client.open_by_key(os.getenv("GOOGLE_SHEETS_ID"))


def get_available_doctors():
    doctors_sheet = sheet.worksheet("Doctors")
    all_doctors = doctors_sheet.get_all_records()

    available = []
    for doctor in all_doctors:
        if doctor["Available today"] == "YES":
            available.append(doctor)

    return available


def parse_time(time_str, date):
    for fmt in ["%H:%M", "%I:%M", "%-H:%M"]:
        try:
            return datetime.strptime(time_str.strip(), fmt).replace(
                year=date.year, month=date.month, day=date.day
            )
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {time_str}")


def generate_slots(doctor, date, is_walkin=False):
    slots = []
    now = datetime.now()

    start = parse_time(doctor["Start time"], date)
    end = parse_time(doctor["End time"], date)
    break_start = parse_time(doctor["Break Start"], date)
    break_end = parse_time(doctor["Break End"], date)

    current = start
    while current < end:
        if current >= break_start and current < break_end:
            current += timedelta(minutes=30)
            continue
        if is_walkin:
            cutoff = now - timedelta(minutes=21)
            if current > cutoff:
                slots.append(current.strftime("%H:%M"))
        else:
            if current > now:
                slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)

    return slots


def count_bookings(date):
    bookings_sheet = sheet.worksheet("Bookings")
    all_bookings = bookings_sheet.get_all_records()

    date_str = date.strftime("%Y-%m-%d")

    counts = {}
    for booking in all_bookings:
        if booking["Date"] == date_str:
            key = f"{booking['Doctor ID']}_{booking['Slot Time']}"
            if key not in counts:
                counts[key] = 0
            counts[key] += 1

    return counts


def get_future_doctor_availability(date):
    date_str = date.strftime("%Y-%m-%d")
    
    schedule_sheet = sheet.worksheet("Schedule")
    all_entries = schedule_sheet.get_all_records()
    
    date_entries = [e for e in all_entries if e["Date"] == date_str]
    
    if not date_entries:
        all_doctors = get_available_doctors()
        return len(all_doctors)
    
    confirmed = [e for e in date_entries if e["Available"] == "YES"]
    return len(confirmed)


def get_future_capacity(date):
    slots_per_doctor = int(os.getenv("SLOTS_PER_DOCTOR"))
    confirmed_doctors = get_future_doctor_availability(date)
    
    if confirmed_doctors <= 1:
        return slots_per_doctor
    else:
        return (confirmed_doctors - 1) * slots_per_doctor

def get_available_slots(date, is_walkin=False):
    try:
        today = datetime.now().date()

        if date == today:
            available_doctors = get_available_doctors()
            booking_counts = count_bookings(date)
            available_slots = {}

            for doctor in available_doctors:
                slots = generate_slots(doctor, date, is_walkin=is_walkin)
                for slot in slots:
                    key = f"{doctor['Doctor ID']}_{slot}"
                    count = booking_counts.get(key, 0)
                    if count < 3:
                        if slot not in available_slots:
                            available_slots[slot] = []
                        available_slots[slot].append(doctor["Doctor ID"])

            return dict(sorted(available_slots.items()))

        else:
            booking_counts = count_bookings(date)
            confirmed_doctors = get_future_doctor_availability(date)

            if confirmed_doctors <= 1:
                cap_per_slot = 3
            else:
                cap_per_slot = (confirmed_doctors - 1) * 3

            standard_start = os.getenv("FUTURE_DAY_START", "09:00")
            standard_end = os.getenv("FUTURE_DAY_END", "17:00")

            current = datetime.strptime(standard_start, "%H:%M")
            end = datetime.strptime(standard_end, "%H:%M")

            available_slots = {}

            while current < end:
                slot = current.strftime("%H:%M")
                slot_key = f"UNASSIGNED_{slot}"
                slot_count = booking_counts.get(slot_key, 0)

                if slot_count < cap_per_slot:
                    available_slots[slot] = ["UNASSIGNED"]

                current += timedelta(minutes=30)

            return dict(sorted(available_slots.items()))

    except Exception as e:
        print(f"get_available_slots error: {e}")
        return {}


def write_booking(patient_name, booking_type, date, slot_time, doctor_id, queue_number):
    bookings_sheet = sheet.worksheet("Bookings")

    booking_id = f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        booking_id,
        patient_name,
        booking_type,
        date,
        slot_time,
        doctor_id,
        queue_number,
        "CONFIRMED",
        timestamp
    ]

    bookings_sheet.append_row(row)

def get_next_queue_number(date, slot_time=None):
    bookings_sheet = sheet.worksheet("Bookings")
    all_bookings = bookings_sheet.get_all_records()
    
    date_str = date.strftime("%Y-%m-%d") if hasattr(date, 'strftime') else date
    
    count = len([b for b in all_bookings if b["Date"] == date_str])
    return count + 1  