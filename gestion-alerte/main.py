from fastapi import FastAPI, HTTPException, Depends, status
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import datetime
from pydantic import BaseModel
from typing import List


# Connexion à la base PostgreSQL commune
DATABASE_URL = "postgresql://greenops_user:greenops_password@postgres:5432/greenops_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODÈLES DE TABLES POSTGRESQL ---

class AlertConfigDB(Base):
    __tablename__ = "alerts_config"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    max_power_threshold_watts = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)

class AlertHistoryDB(Base):
    __tablename__ = "alerts_history"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(Integer, index=True)
    measured_watts = Column(Float, nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)

# Création des tables d'alerte
Base.metadata.create_all(bind=engine)

app = FastAPI(title="GreenOps Alerting Management Service")

# Dépendance Base de données
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- MODÈLES PYDANTIC POUR LES REQUÊTES ---
class AlertConfigCreate(BaseModel):
    user_id: int
    max_power_threshold_watts: float

class AlertHistoryResponse(BaseModel):
    id: int
    timestamp: datetime.datetime
    measured_watts: float
    message: str
    is_read: bool

    class Config:
        from_attributes = True

# --- ROUTES MÉTIERS ---

@app.post("/configure", status_code=status.HTTP_201_CREATED)
def configure_alert_threshold(config: AlertConfigCreate, db: Session = Depends(get_db)):
    """
    Permet à l'utilisateur depuis l'interface Vue.js de définir un seuil limite en Watts.
    """
    # Mettre à jour si une config existe déjà pour cet utilisateur, sinon créer
    existing_config = db.query(AlertConfigDB).filter(AlertConfigDB.user_id == config.user_id).first()
    if existing_config:
        existing_config.max_power_threshold_watts = config.max_power_threshold_watts
        db.commit()
        return {"message": "Seuil d'alerte mis à jour avec succès"}
    
    new_config = AlertConfigDB(user_id=config.user_id, max_power_threshold_watts=config.max_power_threshold_watts)
    db.add(new_config)
    db.commit()
    return {"message": "Seuil d'alerte configuré"}


@app.post("/webhook/trigger")
def trigger_alert_from_system(measured_watts: float, db: Session = Depends(get_db)):
    """
    Endpoint (Webhook) appelé automatiquement par le système de monitoring ou Prometheus 
    lorsque les Watts dépassent les seuils configurés.
    """
    # Recherche des utilisateurs dont le seuil est dépassé par cette mesure
    configs = db.query(AlertConfigDB).filter(AlertConfigDB.max_power_threshold_watts < measured_watts, AlertConfigDB.is_active == True).all()
    
    triggered_alerts = []
    for config in configs:
        alert_event = AlertHistoryDB(
            user_id=config.user_id,
            measured_watts=measured_watts,
            message=f"Alerte GreenOps ! La consommation actuelle ({measured_watts}W) dépasse votre seuil de {config.max_power_threshold_watts}W."
        )
        db.add(alert_event)
        triggered_alerts.append(config.user_id)
        
    db.commit()
    return {"status": "processed", "alerts_generated_for_users": triggered_alerts}


@app.get("/user/{user_id}", response_model=List[AlertHistoryResponse])
def get_user_alerts_history(user_id: int, db: Session = Depends(get_db)):
    """
    Renvoie le JSON de l'historique des alertes à Vue.js pour la cloche de notification.
    """
    alerts = db.query(AlertHistoryDB).filter(AlertHistoryDB.user_id == user_id).order_by(AlertHistoryDB.timestamp.desc()).all()
    return alerts


@app.put("/ack/{alert_id}")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """
    Permet à l'utilisateur de cliquer sur "Marquer comme lu" dans son interface HTML.
    """
    alert = db.query(AlertHistoryDB).filter(AlertHistoryDB.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte non trouvée")
    alert.is_read = True
    db.commit()
    return {"message": "Alerte marquée comme lue"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)