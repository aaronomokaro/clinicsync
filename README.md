Clinic-Sync
WhatsApp-native autonomous AI appointment booking system for private healthcare clinics.

Removing manual administrative bottlenecks from clinic operations via conversational AI.


What It Does
Clinic-Sync lets patients book appointments at private clinics entirely through WhatsApp, with no human admin involvement in the booking flow. The AI agent handles the full patient journey from initial greeting through to confirmed appointment and clinical documentation, working against a live scheduling database synced in real time.
Built for private clinics in Nigeria where appointment booking is manual, phone-based, and a significant operational drain.

Architecture
Agentic Booking Flow
End-to-end autonomous agent built on Claude API and MCP:
Patient message (WhatsApp)
    Twilio / Wassenger routing
        Claude AI Agent (MCP)
            Google Sheets live scheduling database
                Slot verification and booking
                    Confirmation sent back to patient
The agent handles:

Initial greeting and intent classification
Doctor availability check against live roster
Time slot selection with 30-minute patient-facing blocks
10-minute internal slot grid management
Break rule enforcement (30-minute breaks after 4 continuous hours)
Appointment confirmation and clinical documentation
Multi-turn conversation with context maintained across the session

Scheduling Database
Google Sheets acts as the live scheduling database via the Google Sheets API. The MCP layer gives the Claude agent direct read/write access to:

Doctor availability grid (daily verification protocol)
Real-time slot capacity
Break and shift rules
Appointment history

Verification Protocol
A daily doctor availability verification protocol runs before the first booking window opens each day, confirming roster data is current before any patient-facing interactions begin. This prevents the agent from booking slots against stale availability data.
Multi-Tenant SaaS Architecture
Two product tiers:
TierDescriptionSheet MasterGoogle Sheets as the scheduling backend. Lower setup cost, suitable for smaller clinics.EHR MasterIntegration with existing Electronic Health Record systems. For clinics with established digital infrastructure.

Tech Stack
LayerTechnologyAI AgentAnthropic Claude APIAgent ToolingMCP (Model Context Protocol)MessagingTwilio, Wassenger (WhatsApp Business API)Scheduling DBGoogle Sheets APIInfrastructureMulti-tenant SaaS

Key Design Decisions
Why WhatsApp? Nigerian private clinic patients already communicate via WhatsApp. Zero friction adoption - no app download, no new interface to learn.
Why Google Sheets as the database? Clinic administrators already manage rosters in spreadsheets. Using Sheets as the live database means zero change to existing admin workflows at onboarding.
Why MCP? MCP gives Claude structured, typed access to external tools (Sheets, WhatsApp routing) with clear capability boundaries. This avoids unstructured tool-calling and makes the agent's actions auditable.
Why no urgency triage in V1? The AI is strictly a booking tool. No clinical decision-making, no urgency assessment. This keeps V1 outside medical device classification under Nigerian NAFDAC and UK MHRA frameworks.
