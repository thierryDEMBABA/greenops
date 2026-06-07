import os
import json
import random
import asyncio
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, Gauge, REGISTRY
import aio_pika


app = FastAPI(title="GreenOps Energy Simulator")

# --- VARIABLES GLOBALES RABBITMQ ---
RABBITMQ_USER = os.getenv("RABBITMQ_DEFAULT_USER", "greenuser")
RABBITMQ_PASS = os.getenv("RABBITMQ_DEFAULT_PASS", "greenpassword")
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")

RABBITMQ_URL = f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}/"

rabbitmq_connection = None
rabbitmq_channel = None

# 1. Déclaration des métriques Prometheus (Gauges = valeurs qui montent et descendent)
ENERGY_USAGE = Gauge(
    'greenops_simulated_core_power_watts', 
    'Consommation énergétique simulée du processeur en Watts',
    ['service_name']
)
CARBON_INTENSITY = Gauge(
    'greenops_simulated_carbon_intensity', 
    'Intensité carbone du réseau électrique simulée en gCO2/kWh'
)


# --- ÉVÉNEMENTS CYCLE DE VIE ---

@app.on_event("startup")
async def startup_event():
    """Connexion robuste à RabbitMQ au démarrage du simulateur"""
    global rabbitmq_connection, rabbitmq_channel
    loop = asyncio.get_event_loop()
    
    for attempt in range(1, 6):
        try:
            rabbitmq_connection = await aio_pika.connect_robust(RABBITMQ_URL, loop=loop)
            rabbitmq_channel = await rabbitmq_connection.channel()
            # On s'assure que la file existe côté producteur
            await rabbitmq_channel.declare_queue("metrics_queue", durable=True)
            print("[RabbitMQ Publisher] Connected and queue 'metrics_queue' declared.")
            return
        except Exception as e:
            print(f"[RabbitMQ Publisher] Connection attempt {attempt}/5 failed. Retrying in 5s... {e}")
            await asyncio.sleep(5)

@app.on_event("shutdown")
async def shutdown_event():
    """Fermeture propre de la connexion RabbitMQ"""
    if rabbitmq_connection:
        await rabbitmq_connection.close()
        print("[RabbitMQ Publisher] Connection closed.")



# --- FONCTIONS MÉTIER ---

async def push_to_rabbitmq(service_name: str, watts: float):
    """Envoie la métrique générée dans la file RabbitMQ de manière asynchrone"""
    if rabbitmq_channel:
        try:
            payload = {
                "timestamp": asyncio.get_event_loop().time(), # Ou datetime au choix
                "service": service_name,
                "watts": watts
            }
            await rabbitmq_channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(payload).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key="metrics_queue"
            )
        except Exception as e:
            print(f"Failed to push message to RabbitMQ: {e}")

# Fonction pour mettre à jour les métriques avec des valeurs réalistes
def update_simulated_metrics():
    """Génère les valeurs aléatoires pour Prometheus et prépare les données pour RabbitMQ"""
    # 1. Génération des valeurs
    auth_watts = round(random.uniform(5.0, 12.0), 2)
    frontend_watts = round(random.uniform(2.0, 6.0), 2)
    gateway_watts = round(random.uniform(1.5, 4.0), 2)
    
    # 2. Mise à jour des Gauges Prometheus locales
    ENERGY_USAGE.labels(service_name='service-auth').set(auth_watts)
    ENERGY_USAGE.labels(service_name='frontend').set(frontend_watts)
    ENERGY_USAGE.labels(service_name='api-gateway').set(gateway_watts)
    
    CARBON_INTENSITY.set(random.uniform(35.0, 75.0))
    
    # On retourne un dictionnaire pour pouvoir l'envoyer à RabbitMQ juste après
    return {
        "service-auth": auth_watts,
        "frontend": frontend_watts,
        "api-gateway": gateway_watts
    }

# 2. La route magique /metrics attendue par Prometheus
@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """
    Route scrapée par Prometheus. Met à jour les données, 
    planifie l'envoi vers RabbitMQ sans bloquer, et répond instantanément.
    """
    # Mise à jour locale pour Prometheus
    current_metrics = update_simulated_metrics()
    
    # Envoi asynchrone vers RabbitMQ pour chaque service (Non-bloquant pour le scraper Prometheus)
    for service, watts in current_metrics.items():
        asyncio.create_task(push_to_rabbitmq(service, watts))
    
    # Génération du flux au format Prometheus
    return PlainTextResponse(generate_latest(REGISTRY))

@app.get("/")
def read_root():
    return {"status": "Simulator is running", "route_metrics": "/metrics","rabbitmq_status": "Connected" if rabbitmq_channel else "Not Connected"}