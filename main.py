from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
import openai
import os
from dotenv import load_dotenv
import json
from whatsapp import send_whatsapp_message

import base64

# Decodificar y guardar las credenciales desde variable de entorno
cred_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")
if cred_base64:
    with open("credentials.json", "wb") as f:
        f.write(base64.b64decode(cred_base64))

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()
# Activar CORS para permitir conexión desde Lovable
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Puedes reemplazar "*" por el dominio de Lovable
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


VERIFY_TOKEN = "vetbot123"

@app.get("/webhook-incoming")
def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return JSONResponse(content=int(challenge))
    else:
        return JSONResponse(status_code=403, content={"message": "Invalid token"})

def guardar_cita_en_google_sheets(phone, mensaje):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open("Agenda VetBot").sheet1
        sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            phone,
            mensaje
        ])
        print("✅ Cita guardada en Google Sheets")
        return True
    except Exception as e:
        print("❌ Error guardando en Google Sheets:", str(e))
        return False

def get_precios():
    return {
        "consulta_general": "$15.000",
        "vacunación": "$10.000",
        "urgencia": "$25.000"
    }

def get_ubicacion():
    return "Av. Los Leones 1234, Providencia, Santiago."

def get_horarios():
    return {
        "lunes_a_viernes": "9:00 a 19:00",
        "sábado": "9:00 a 13:00"
    }

class WhatsAppMessage(BaseModel):
    phone: str
    message: str

@app.post("/webhook")
def webhook(data: WhatsAppMessage):
    return procesar_mensaje(data.phone, data.message)

@app.post("/webhook-incoming")
async def receive_message(request: Request):
    body = await request.json()
    print("📩 Mensaje recibido desde Meta:")
    print(json.dumps(body, indent=2))

    try:
        print("🔄 Entró al bloque try")
        entry = body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        messages = value.get("messages")

        if messages:
            print("✅ Mensaje detectado")
            message = messages[0]
            text = message["text"]["body"]
            phone = message["from"]
            print(f"📲 Mensaje recibido: '{text}' desde {phone}")
            return procesar_mensaje(phone, text)

    except Exception as e:
        print("❌ Error procesando mensaje:", str(e))

    return {"status": "ok"}

def procesar_mensaje(phone, mensaje):
    # Detectar intención de agendar
    guardar_confirmacion = ""
    if any(p in mensaje.lower() for p in ["agendar", "reservar", "hora", "cita", "turno", "peluquería"]):
        if guardar_cita_en_google_sheets(phone, mensaje):
            print("📅 Se detectó intención de agendar → cita guardada automáticamente.")
            guardar_confirmacion = "✅ Tu cita ha sido registrada. ¡Te esperamos!"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_precios",
                "description": "Devuelve los precios actuales de los servicios de la clínica veterinaria",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_ubicacion",
                "description": "Devuelve la dirección de la clínica veterinaria",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_horarios",
                "description": "Devuelve los horarios de atención de la clínica veterinaria",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]

    response = openai.ChatCompletion.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": "Eres VetBot, un asistente de una clínica veterinaria."},
            {"role": "user", "content": mensaje}
        ],
        tools=tools,
        tool_choice="auto"
    )

    message = response["choices"][0]["message"]

    if "tool_calls" in message:
        tool_call = message["tool_calls"][0]
        function_name = tool_call["function"]["name"]

        if function_name == "get_precios":
            function_response = get_precios()
        elif function_name == "get_ubicacion":
            function_response = get_ubicacion()
        elif function_name == "get_horarios":
            function_response = get_horarios()
        else:
            function_response = "Función no disponible"

        second_response = openai.ChatCompletion.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": "Eres VetBot, un asistente de una clínica veterinaria."},
                {"role": "user", "content": mensaje},
                {"role": "assistant", "tool_calls": [tool_call]},
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": function_name,
                    "content": json.dumps(function_response)
                }
            ]
        )
        reply = second_response["choices"][0]["message"]["content"]
    else:
        reply = message["content"]

    # Añadir confirmación si fue guardado en agenda
    if guardar_confirmacion:
        reply = f"{guardar_confirmacion}\n\n{reply}"

    print(f"🤖 Respuesta enviada: {reply}")
    send_whatsapp_message(phone, reply)

    return {"reply": reply, "to": phone}

from fastapi import FastAPI

app = FastAPI()

@app.get("/api/clinicas")
def get_clinicas():
    return [
        {"id": 1, "nombre": "Clínica Arrayán", "comuna": "Providencia"},
        {"id": 2, "nombre": "Clínica Andes", "comuna": "Vitacura"},
        {"id": 3, "nombre": "Clínica Centro", "comuna": "Santiago Centro"},
    ]
