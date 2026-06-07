import os
import json
import asyncio
import datetime
import requests
from fastapi import FastAPI, HTTPException, Header, Depends, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import aio_pika
from typing import List

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

# --- MODÈLE SQLALCHEMY (Utilisé uniquement par le consommateur RabbitMQ désormais) ---
class CarbonMetricsDB(Base):
    __tablename__ = "carbon_metrics"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    container_name = Column(String, default="total_host")
    power_watts = Column(Float, nullable=False)
    carbon_gco2 = Column(Float, nullable=False)

# Création de la table si elle n'existe pas
Base.metadata.create_all(bind=engine)

# --- CONFIGURATION FASTAPI ---
app = FastAPI(title="GreenOps Power & Carbon Calculation Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables globales pour maintenir les tâches RabbitMQ
rabbitmq_connection = None
rabbitmq_channel = None
consumer_task = None

####################3 Inclusion des websockets pour le push en temps réel vers le frontend ##########################

# 1. Gestionnaire pour stocker les connexions WebSocket actives
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Nouveau client connecté. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"[WebSocket] Client déconnecté. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Envoie le message JSON à TOUS les frontends connectés"""
        if not self.active_connections:
            return
        # On itère sur une copie de la liste pour éviter les conflits si un client se déconnecte pendant l'envoi
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[WebSocket Alert] Impossible d'envoyer à un client, nettoyage en cours... Error: {e}")
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

manager = ConnectionManager()

# 2. La route WebSocket que ton Frontend Vue.js va ouvrir
@app.websocket("/ws/live-metrics")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # On maintient la connexion ouverte en attendant d'éventuels messages du client
            # (Même si ici le flux est principalement Descendant : Backend -> Frontend)
            await asyncio.sleep(1)
            # data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

#####################################################################################################################

def verify_user_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format d'en-tête d'authentification invalide.")
    
    token = authorization.split(" ")[1]
    try:
        response = requests.get(f"{AUTH_SERVICE_URL}?token={token}", timeout=5)
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Session invalide ou expirée.")
        return response.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Le service d'authentification est indisponible.")

################ --- 📥 WORKER ASYNCHRONE : ENREGISTREMENT AUTOMATIQUE (RABBITMQ -> POSTGRES) --- ##########

async def process_incoming_metric(message: aio_pika.IncomingMessage):
    """
    Consomme en continu les métriques granulaires poussées par le simulateur dans RabbitMQ.
    Calcule l'impact carbone et enregistre de manière autonome dans PostgreSQL.
    """
    async with message.process():
        try:
            metric_data = json.loads(message.body.decode())
            power_watts = float(metric_data.get("watts", 0.0))
            service_name = metric_data.get("service", "unknown")
            
            # Formule GreenOps : Intensité carbone simplifiée (50g CO2e / kWh en France)
            carbon_gco2 = (power_watts / 1000.0) * 50.0
            
            # Session éphémère isolée dédiée à la tâche de fond
            db = SessionLocal()
            try:
                metric_record = CarbonMetricsDB(
                    container_name=service_name,
                    power_watts=round(power_watts, 2),
                    carbon_gco2=round(carbon_gco2, 4),
                    timestamp=datetime.datetime.fromisoformat(metric_data["timestamp"]) if "timestamp" in metric_data else datetime.datetime.utcnow()
                )
                db.add(metric_record)
                db.commit()
                print(f"[RabbitMQ] Enregistré : {service_name} -> {power_watts}W ({carbon_gco2} gCO2)")
            finally:
                db.close()
            # 2. [NOUVEAU] Diffusion instantanée en WebSocket vers Vue.js
            live_payload = {
                "service": service_name,
                "watts": round(power_watts, 2),
                "carbon": round(carbon_gco2, 4),
                "timestamp": datetime.datetime.utcnow().isoformat()
            }
            # .broadcast est asynchrone, on utilise await
            await manager.broadcast(live_payload)
                
        except Exception as e:
            print(f"[RabbitMQ Error] Impossible de traiter le message : {str(e)}")

async def start_rabbitmq_consumer():
    """Initialise l'écoute de la queue de messages"""
    global rabbitmq_connection, rabbitmq_channel
    for attempt in range(1, 6):
        try:
            rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL)
            rabbitmq_channel = await rabbitmq_connection.channel()
            queue = await rabbitmq_channel.declare_queue("metrics_queue", durable=True)
            
            await queue.consume(process_incoming_metric)
            print("[RabbitMQ] Le consommateur écoute activement sur 'metrics_queue'")
            return
        except Exception as e:
            print(f"[RabbitMQ] Échec de connexion (Tentative {attempt}/5). Nouvelle tentative dans 5s... Error: {e}")
            await asyncio.sleep(5)

# --- GESTION DU CYCLE DE VIE DU POD ---

@app.on_event("startup")
async def startup_event():
    global consumer_task
    consumer_task = asyncio.create_task(start_rabbitmq_consumer())

@app.on_event("shutdown")
async def shutdown_event():
    # global rabbitmq_connection, consumer_task
    if consumer_task:
        consumer_task.cancel()
    if rabbitmq_connection:
        await rabbitmq_connection.close()
        print("[System] Connexions RabbitMQ fermées proprement.")

####################################################################################################################

# --- 🚀 ROUTE HTTP SYNCHRONE : REQUÊTE INSTANTANÉE (SANS ÉCRITURE SQL) ---

@app.post("/trigger-calculation", status_code=status.HTTP_200_OK)
def calculate_on_demand(user_info: dict = Depends(verify_user_token)):
    """
    Action déclenchée par l'utilisateur via le bouton du Frontend Vue.js.
    Calcule à la volée la consommation totale instantanée issue de Prometheus et la renvoie,
    sans créer de doublons dans PostgreSQL (L'écriture est déléguée au flux RabbitMQ).
    """
    try:
        # Interrogation en direct de Prometheus pour obtenir la puissance totale
        prom_query = {'query': 'greenops_simulated_core_power_watts'}
        response = requests.get(PROMETHEUS_URL, params=prom_query, timeout=5)
        
        power_watts = 0.0
        results_debug = []
        
        if response.status_code == 200:
            results = response.json().get('data', {}).get('result', [])
            results_debug = results
            if results:
                # Récupère la valeur du premier élément retourné par l'agrégation
                power_watts = float(results[0]['value'][1])
        
        # Valeur de secours si Prometheus est en cours de démarrage/vide
        if power_watts == 0.0:
            power_watts = 45.3
            
        # Calcul de l'empreinte carbone instantanée
        carbon_gco2 = (power_watts / 1000.0) * 50.0

        # On retourne directement le dictionnaire au Frontend Vue.js. 
        # Plus besoin de db.add() ni de db.commit() : Pas de pollution ni de doublon dans PostgreSQL !
        return {
            "status": "success",
            "message": "Calcul instantané effectué à la volée via Prometheus",
            "triggered_by": user_info["user_email"],
            "data": {
                "power_watts": round(power_watts, 2),
                "carbon_emitted_gco2": round(carbon_gco2, 4),
                "timestamp": datetime.datetime.utcnow().isoformat()
            },
            "debug_info": {
                "prometheus_results": results_debug
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du calcul flash GreenOps : {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)