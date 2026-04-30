import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

from sheets import (
    get_available_doctors,
    generate_slots,
    count_bookings,
    get_available_slots,
    get_future_doctor_availability,
    get_future_capacity,
    write_booking,
    get_next_queue_number,
    sheet
)

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

today = date.today()
tomorrow = today + timedelta(days=1)
april_28 = date(2026, 4, 28)

# ─────────────────────────────────────────
# TEST 1 -- get_available_doctors
# ─────────────────────────────────────────
doctors = get_available_doctors()
doctor_ids = [d["Doctor ID"] for d in doctors]

check(
    "get_available_doctors -- all returned doctors are YES",
    all(d["Available today"] == "YES" for d in doctors)
)
check(
    "get_available_doctors -- DOC002 excluded because marked NO",
    "DOC002" not in doctor_ids
)
check(
    "get_available_doctors -- DOC001 included",
    "DOC001" in doctor_ids
)
check(
    "get_available_doctors -- DOC003 included",
    "DOC003" in doctor_ids
)

# ─────────────────────────────────────────
# TEST 2 -- generate_slots
# ─────────────────────────────────────────
doc001 = next(d for d in get_available_doctors() if d["Doctor ID"] == "DOC001")
doc003 = next(d for d in get_available_doctors() if d["Doctor ID"] == "DOC003")

slots_doc001 = generate_slots(doc001, tomorrow)
slots_doc003 = generate_slots(doc003, tomorrow)

check(
    "generate_slots -- returns a list",
    isinstance(slots_doc001, list)
)
check(
    "generate_slots -- DOC001 break slot 12:00 excluded",
    "12:00" not in slots_doc001
)
check(
    "generate_slots -- DOC003 break slot 12:30 excluded",
    "12:30" not in slots_doc003
)
check(
    "generate_slots -- all slots are 30 minute increments",
    all(
        s.endswith(":00") or s.endswith(":30")
        for s in slots_doc001
    )
)

# ─────────────────────────────────────────
# TEST 3 -- count_bookings
# ─────────────────────────────────────────
test_date_str = str(tomorrow)

write_booking(
    patient_name="COUNT_TEST",
    booking_type="ADVANCE",
    date=test_date_str,
    slot_time="09:00",
    doctor_id="DOC001",
    queue_number=998
)

counts = count_bookings(tomorrow)

check(
    "count_bookings -- returns a dictionary",
    isinstance(counts, dict)
)
check(
    "count_bookings -- DOC001 09:00 count is at least 1",
    counts.get("DOC001_09:00", 0) >= 1
)

# ─────────────────────────────────────────
# TEST 4 -- get_available_slots today
# ─────────────────────────────────────────
write_booking(patient_name="FULL_TEST_1", booking_type="ADVANCE", date=str(today), slot_time="16:00", doctor_id="DOC001", queue_number=991)
write_booking(patient_name="FULL_TEST_2", booking_type="ADVANCE", date=str(today), slot_time="16:00", doctor_id="DOC001", queue_number=992)
write_booking(patient_name="FULL_TEST_3", booking_type="ADVANCE", date=str(today), slot_time="16:00", doctor_id="DOC001", queue_number=993)

today_slots = get_available_slots(today)

check(
    "get_available_slots today -- returns dictionary",
    isinstance(today_slots, dict)
)
check(
    "get_available_slots today -- slots in order",
    list(today_slots.keys()) == sorted(today_slots.keys())
)
check(
    "get_available_slots today -- DOC001 excluded from 16:00 after 3 bookings",
    "DOC001" not in today_slots.get("16:00", [])
)

# ─────────────────────────────────────────
# TEST 5 -- get_available_slots future
# ─────────────────────────────────────────
future_slots = get_available_slots(tomorrow)
slots_per_doctor = int(os.getenv("SLOTS_PER_DOCTOR"))
expected_capacity = (2 - 1) * slots_per_doctor

check(
    "get_available_slots future -- returns dictionary",
    isinstance(future_slots, dict)
)
check(
    "get_available_slots future -- slot count matches expected capacity",
    len(future_slots) <= expected_capacity
)

# ─────────────────────────────────────────
# TEST 6 -- get_future_doctor_availability
# ─────────────────────────────────────────
april_28_count = get_future_doctor_availability(april_28)

check(
    "get_future_doctor_availability -- returns integer",
    isinstance(april_28_count, int)
)
check(
    "get_future_doctor_availability -- April 28 count is exactly 2",
    april_28_count == 2
)

# ─────────────────────────────────────────
# TEST 7 -- get_future_capacity
# ─────────────────────────────────────────
april_28_capacity = get_future_capacity(april_28)
expected_april_28_capacity = (2 - 1) * slots_per_doctor

check(
    "get_future_capacity -- returns integer",
    isinstance(april_28_capacity, int)
)
check(
    "get_future_capacity -- April 28 capacity is exactly 6",
    april_28_capacity == expected_april_28_capacity
)

# ─────────────────────────────────────────
# TEST 8 -- write_booking
# ─────────────────────────────────────────
write_booking(
    patient_name="WRITE_TEST",
    booking_type="WALKIN",
    date=str(today),
    slot_time="10:00",
    doctor_id="DOC003",
    queue_number=777
)

bookings_sheet = sheet.worksheet("Bookings")
all_bookings = bookings_sheet.get_all_records()
test_row = [b for b in all_bookings if b["Patient Name"] == "WRITE_TEST"]

check(
    "write_booking -- row created in Sheet",
    len(test_row) > 0
)

if test_row:
    row = test_row[-1]
    check("write_booking -- Booking ID starts with BK", str(row["Booking ID"]).startswith("BK"))
    check("write_booking -- Patient Name correct", row["Patient Name"] == "WRITE_TEST")
    check("write_booking -- Type correct", row["Type"] == "WALKIN")
    check("write_booking -- Date correct", row["Date"] == str(today))
    check("write_booking -- Slot Time correct", row["Slot Time"] == "10:00")
    check("write_booking -- Doctor ID correct", row["Doctor ID"] == "DOC003")
    check("write_booking -- Queue Number correct", str(row["Queue Number"]) == "777")
    check("write_booking -- Status is CONFIRMED", row["Status"] == "CONFIRMED")
    check("write_booking -- Timestamp exists", len(str(row["Timestamp"])) > 0)

# ─────────────────────────────────────────
# TEST 9 -- get_next_queue_number
# ─────────────────────────────────────────
all_today_bookings = [b for b in all_bookings if b["Date"] == str(today)]
expected_queue = len(all_today_bookings) + 1
actual_queue = get_next_queue_number(str(today))

check(
    "get_next_queue_number -- returns integer",
    isinstance(actual_queue, int)
)
check(
    "get_next_queue_number -- is exactly one more than current count",
    actual_queue == expected_queue
)

# ─────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────
print("\n=== LAYER 1 -- TOOL EVALUATION ===\n")
for result in results:
    print(result)

print(f"\nScore: {total_score}/{max_score} = {round(total_score/max_score*100)}%")