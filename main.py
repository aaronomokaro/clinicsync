from fastapi import FastAPI, Form
from conversation import handle_message

app = FastAPI()

@app.post("/webhook")
async def webhook(From: str = Form(...), Body: str = Form(...)):
    handle_message(From, Body)
    return {"status": "ok"}