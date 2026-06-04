from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, Gauge, REGISTRY
import random
import time


app = FastAPI(title="GreenOps Energy Simulator")

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

# Fonction pour mettre à jour les métriques avec des valeurs réalistes
def update_simulated_metrics():
    # Simulation de la consommation de vos différents services
    ENERGY_USAGE.labels(service_name='service-auth').set(random.uniform(5.0, 12.0))
    ENERGY_USAGE.labels(service_name='frontend').set(random.uniform(2.0, 6.0))
    ENERGY_USAGE.labels(service_name='api-gateway').set(random.uniform(1.5, 4.0))
    
    # Simulation de l'intensité carbone (ex: plus basse en journée grâce au solaire)
    CARBON_INTENSITY.set(random.uniform(35.0, 75.0))

# 2. La route magique /metrics attendue par Prometheus
@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    # On met à jour les données juste avant que Prometheus ne les aspire
    update_simulated_metrics()
    # On génère le flux textuel au format standard de Prometheus
    return PlainTextResponse(generate_latest(REGISTRY))

@app.get("/")
def read_root():
    return {"status": "Simulator is running", "route_metrics": "/metrics"}