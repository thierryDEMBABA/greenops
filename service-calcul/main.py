import os
import json
import asyncio
import datetime
import requests
from fastapi import FastAPI, HTTPException, Header, Depends, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import aio_pika

# --- CONFIGURATION ENVIRONNEMENT ---
DB_HOST = os.getenv("DATABASE_HOST", "postgres")
DB_PORT = os.getenv("DATABASE_PORT", "5432")
DB_USER = os.getenv("DATABASE_USER", "greenops_user")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "greenops_password")
DB_NAME = os.getenv("DATABASE_NAME", "greenops_db")

RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", "greenuser")
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", "greenpassword")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")

RABBITMQ_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/"
PROMETHEUS_URL = "http://prometheus-stack-server.greenops.svc.cluster.local/prometheus/api/v1/query"
AUTH_SERVICE_URL = "http://auth-service:8082/verify"

# --- CONFIGURATION BASE DE DONNÉES ---
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class CarbonMetricsDB(Base):
    __tablename__ = "carbon_metrics"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    container_name = Column(String, default="total_host")
    power_watts = Column(Float, nullable=False)
    carbon_gco2 = Column(Float, nullable=False)

Base.metadata.create_all(bind=engine)

# --- QUEUE DE DISPATCHING TEMPS RÉEL ---
# Cette queue fait le pont entre le consommateur RabbitMQ et le diffuseur WebSocket
websocket_queue = asyncio.Queue()

# --- GESTIONNAIRE WEBSOCKET ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Client connecté. Total actif : {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WebSocket] Client déconnecté. Restant : {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

manager = ConnectionManager()

# --- CONFIGURATION FASTAPI ---
app = FastAPI(title="GreenOps Power & Carbon Calculation Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permis pour le dev, à restreindre si nécessaire
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rabbitmq_connection = None
rabbitmq_channel = None
consumer_task = None
broadcast_task = None

def verify_user_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format d'en-tête invalide.")
    token = authorization.split(" ")[1]
    try:
        response = requests.get(f"{AUTH_SERVICE_URL}?token={token}", timeout=5)
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Session invalide.")
        return response.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Service Auth indisponible.")

# --- WORKER RABBITMQ ---
async def process_incoming_metric(message: aio_pika.IncomingMessage):
    async with message.process():
        try:
            metric_data = json.loads(message.body.decode())
            power_watts = float(metric_data.get("watts", 0.0))
            service_name = metric_data.get("service", "unknown")
            
            carbon_gco2 = (power_watts / 1000.0) * 50.0
            
            # 1. Enregistrement en Base de données
            db = SessionLocal()
            try:
                metric_record = CarbonMetricsDB(
                    container_name=service_name,
                    power_watts=round(power_watts, 2),
                    carbon_gco2=round(carbon_gco2, 4)
                )
                db.add(metric_record)
                db.commit()
            finally:
                db.close()
            
            # 2. Pousser la donnée dans la Queue interne pour exécution par la boucle principale
            payload = {
                "service": service_name,
                "watts": round(power_watts, 2),
                "carbon": round(carbon_gco2, 4),
                "timestamp": datetime.datetime.utcnow().isoformat()
            }
            await websocket_queue.put(payload)
                
        except Exception as e:
            print(f"[RabbitMQ Error] Impossible de traiter le message : {str(e)}")

async def start_rabbitmq_consumer():
    global rabbitmq_connection, rabbitmq_channel
    for attempt in range(1, 6):
        try:
            rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
            rabbitmq_channel = await rabbitmq_connection.channel()
            queue = await rabbitmq_channel.declare_queue("metrics_queue", durable=True)
            await queue.consume(process_incoming_metric)
            print("[RabbitMQ] Le consommateur écoute activement.")
            return
        except Exception as e:
            print(f"[RabbitMQ] Échec de connexion (Tentative {attempt}/5)... Re-tentative dans 5s. Erreur: {e}")
            await asyncio.sleep(5)

# --- BOUCLE DE DIFFUSION DÉDIÉE (ÉVITE LE BLOCAGE DE THREAD) ---
async def websocket_broadcast_loop():
    """Consomme la queue interne asynchrone et effectue le broadcast WS"""
    print("[WebSocket] Boucle de dispatching initialisée et prête.")
    while True:
        try:
            # Attend qu'une nouvelle métrique soit disponible dans la queue interne
            payload = await websocket_queue.get()
            # Envoie la métrique à tout le monde
            await manager.broadcast(payload)
            # Notifie que l'élément est traité
            websocket_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[WebSocket Loop Error] Erreur lors du broadcast : {e}")
            await asyncio.sleep(1)

# --- ACTIONS CYCLE DE VIE ---
@app.on_event("startup")
async def startup_event():
    global consumer_task, broadcast_task
    consumer_task = asyncio.create_task(start_rabbitmq_consumer())
    broadcast_task = asyncio.create_task(websocket_broadcast_loop())

@app.on_event("shutdown")
async def shutdown_event():
    if consumer_task:
        consumer_task.cancel()
    if broadcast_task:
        broadcast_task.cancel()
    if rabbitmq_connection:
        await rabbitmq_connection.close()

# --- ROUTE WEBSOCKET (NON-BLOQUANTE) ---
@app.websocket("/ws/live-metrics")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Maintient la session active en mode non-bloquant
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- ROUTE HTTP TRIGGER ---
@app.post("/trigger-calculation")
def calculate_on_demand(user_info: dict = Depends(verify_user_token)):
    try:
        prom_query = {'query': 'greenops_simulated_core_power_watts'}
        response = requests.get(PROMETHEUS_URL, params=prom_query, timeout=5)
        power_watts = 0.0
        if response.status_code == 200:
            results = response.json().get('data', {}).get('result', [])
            if results:
                power_watts = float(results[0]['value'][1])
        
        if power_watts == 0.0:
            power_watts = 45.3
            
        carbon_gco2 = (power_watts / 1000.0) * 50.0
        return {
            "status": "success",
            "data": {
                "power_watts": round(power_watts, 2),
                "carbon_emitted_gco2": round(carbon_gco2, 4),
                "timestamp": datetime.datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)