import os
from fastapi import FastAPI, HTTPException, Header, Depends, status
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import requests
import datetime
from fastapi.middleware.cors import CORSMiddleware
import os

# Récupération dynamique des variables d'environnement injectées par Kubernetes
DB_HOST = os.getenv("DATABASE_HOST", "postgres")
DB_PORT = os.getenv("DATABASE_PORT", "5432")
DB_USER = os.getenv("DATABASE_USER", "greenops_user")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "greenops_password")
DB_NAME = os.getenv("DATABASE_NAME", "greenops_db")


# Configuration des URLs des autres composants du cluster
# PROMETHEUS_URL = "http://prometheus:9090/api/v1/query"
PROMETHEUS_URL = "http://http://prometheus-stack-server.greenops.svc.cluster.local:80/prometheus/api/v1/query"
AUTH_SERVICE_URL = "http://auth-service:8082/verify"


# Connexion à la base de données PostgreSQL
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modèle de table pour stocker l'historique des calculs GreenOps
class CarbonMetricsDB(Base):
    __tablename__ = "carbon_metrics"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    container_name = Column(String, default="total_host")
    power_watts = Column(Float, nullable=False)
    carbon_gco2 = Column(Float, nullable=False)

# Création de la table si elle n'existe pas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="GreenOps Power & Carbon Calculation Service")

# Configuration du Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],  # Autorise votre Frontend Vue.js
    allow_credentials=True,
    allow_methods=["*"],  # Autorise POST, GET, OPTIONS, PUT, DELETE
    allow_headers=["*"],  # Autorise tous les headers (y compris Authorization pour le JWT)
)

# Dépendance pour obtenir la session de base de données
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Fonction de dépendance pour valider le JWT auprès du Service d'Authentification
def verify_user_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format d'en-tête d'authentification invalide.")
    
    token = authorization.split(" ")[1]
    try:
        # On interroge le service d'authentification de manière synchrone (inter-service K8s/Docker)
        response = requests.get(f"{AUTH_SERVICE_URL}?token={token}", timeout=5)
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Session invalide ou expirée.")
        return response.json()  # Renvoie les infos de l'utilisateur (id, email)
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Le service d'authentification est indisponible.")

# --- ROUTE MÉTIER DE CALCUL ---

@app.post("/trigger-calculation", status_code=status.HTTP_201_CREATED)
def calculate_and_store_green_metrics(
    db: Session = Depends(get_db), 
    user_info: dict = Depends(verify_user_token)
):
    """
    Déclenche la collecte des métriques auprès de Prometheus, calcule l'impact carbone 
    et persiste le résultat consolidé dans PostgreSQL. Protégé par AuthJwt.
    """
    try:
        # Requête PromQL pour récupérer la consommation électrique totale de l'hôte (Scaphandre)
        # Si Scaphandre n'a pas encore de données, on utilise une valeur par défaut ou une estimation
        # prom_query = {'query': 'scaph_host_power_microwatts'}
        prom_query = {'query': 'greenops_simulated_core_power_watts'}
        response = requests.get(PROMETHEUS_URL, params=prom_query, timeout=5)
        
        power_watts = 0.0
        results_debug = []
        if response.status_code == 200:
            results = response.json().get('data', {}).get('result', [])
            results_debug = results  # Stocker les résultats pour le debug
            if results:
                # Vu que 'sum' agrège tout, results[0] redeviendra valide et unique !
                power_watts = float(results[0]['value'][1])
        
        # Si Prometheus est vide ou en attente, on simule une valeur réaliste (ex: 45 Watts)
        if power_watts == 0.0:
            power_watts = 45.3
            
        # --- FACTEUR D'INTENSITÉ CARBONE EN FRANCE ---
        # Mix électrique moyen en France : env 50g CO2e / kWh
        # Calcul des grammes de CO2 par seconde : (Watts / 1000) * (50g / 3600s)
        # Pour simplifier et simuler une heure de consommation stable à ce niveau :
        carbon_gco2 = (power_watts / 1000.0) * 50.0

        # Persistance dans PostgreSQL
        metric_record = CarbonMetricsDB(
            power_watts=round(power_watts, 2),
            carbon_gco2=round(carbon_gco2, 4)
        )
        db.add(metric_record)
        db.commit()
        db.refresh(metric_record)

        return {
            "status": "success",
            "triggered_by": user_info["user_email"],
            "data_collected": {
                "power_watts": metric_record.power_watts,
                "carbon_emitted_gco2": metric_record.carbon_gco2,
                "timestamp": metric_record.timestamp
            },
            "debug_info": {
                "prometheus_results": results_debug
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du traitement GreenOps : {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # Le port 8083 correspond exactement à la configuration de l'API Gateway Nginx
    uvicorn.run(app, host="0.0.0.0", port=8083)