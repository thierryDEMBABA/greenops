from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import datetime
from typing import List
from pydantic import BaseModel

# test ci
print("Service Lecture démarré avec succès - V1.2 - 2024-06-01")

# Connexion à la base de données PostgreSQL (partagée avec le service calcul)
DATABASE_URL = "postgresql://greenops_user:greenops_password@postgres:5432/greenops_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Mapping de la table existante 'carbon_metrics' créée par le service calcul
class CarbonMetricsDB(Base):
    __tablename__ = "carbon_metrics"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    container_name = Column(String, default="total_host")
    power_watts = Column(Float, nullable=False)
    carbon_gco2 = Column(Float, nullable=False)

app = FastAPI(title="GreenOps Data Schema Reader Service")

# Modèle Pydantic pour structurer le JSON propre renvoyé au Frontend Vue.js
class CarbonMetricResponse(BaseModel):
    id: int
    timestamp: datetime.datetime
    container_name: str
    power_watts: float
    carbon_gco2: float

    class Config:
        from_attributes = True

# Dépendance pour obtenir la session de base de données
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ROUTES MÉTIER DE LECTURE ---

@app.get("/latest", response_model=CarbonMetricResponse)
def get_latest_metric(db: Session = Depends(get_db)):
    """
    Récupère la toute dernière mesure enregistrée. 
    Parfait pour alimenter une jauge ou un compteur "Temps Réel" sur Vue.js.
    """
    latest_record = db.query(CarbonMetricsDB).order_by(CarbonMetricsDB.timestamp.desc()).first()
    if not latest_record:
        # Si la base est encore vide au premier démarrage, on renvoie une structure à zéro
        return CarbonMetricsDB(id=0, timestamp=datetime.datetime.utcnow(), container_name="dev_env", power_watts=0.0, carbon_gco2=0.0)
    return latest_record

@app.get("/history", response_model=List[CarbonMetricResponse])
def get_metrics_history(limit: int = 100, db: Session = Depends(get_db)):
    """
    Récupère l'historique des données énergétiques et carbone.
    Ce JSON linéaire sera directement lu par des librairies de chartes graphiques (Chart.js, ApexCharts) dans Vue.js.
    """
    metrics = db.query(CarbonMetricsDB).order_by(CarbonMetricsDB.timestamp.desc()).limit(limit).all()
    return metrics

if __name__ == "__main__":
    import uvicorn
    # Le port 8084 correspond exactement à la configuration de l'API Gateway Nginx
    uvicorn.run(app, host="0.0.0.0", port=8084)