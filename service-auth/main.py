import datetime
from fastapi import FastAPI, HTTPException, Depends, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import jwt
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator


# Configuration de la sécurité
SECRET_KEY = "SUPER_SECRET_KEY_GREENOPS_PLATFORM" # À changer en production
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Connexion à la base de données PostgreSQL (utilise les variables du Docker Compose)
DATABASE_URL = "postgresql://greenops_user:greenops_password@postgres:5432/greenops_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modèle de table SQLAlchemy pour la base de données
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

# Création des tables au démarrage si elles n'existent pas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="GreenOps Auth Service")

# Configuration du Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],  # Autorise votre Frontend Vue.js
    allow_credentials=True,
    allow_methods=["*"],  # Autorise POST, GET, OPTIONS, PUT, DELETE
    allow_headers=["*"],  # Autorise tous les headers (y compris Authorization pour le JWT)
)

# Modèles Pydantic pour la validation des données entrantes (Requêtes HTTP)
class UserCreate(BaseModel):
    username: EmailStr
    password: str

class UserLogin(BaseModel):
    username: EmailStr
    password: str

# Dépendance pour obtenir la session de base de données
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ROUTES METIER ---

@app.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    email = body.get("username")
    password = body.get("password")
    # Vérifier si l'utilisateur existe déjà
    db_user = db.query(UserDB).filter(UserDB.email == email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Cet email est déjà enregistré.")
    
    # Hachage du mot de passe et enregistrement
    hashed_pwd = pwd_context.hash(password)
    new_user = UserDB(email=email, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    return {"message": "Utilisateur créé avec succès"}

@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    email = body.get("username")
    password = body.get("password")

    # Vérifier l'utilisateur
    db_user = db.query(UserDB).filter(UserDB.email == email).first()
    if not db_user or not pwd_context.verify(password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")
    
    # Génération du Token JWT valide pour 1 jour
    expiration = datetime.datetime.utcnow() + datetime.timedelta(days=1)
    payload = {
        "sub": db_user.email,
        "user_id": db_user.id,
        "exp": expiration
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer"}

@app.get("/verify")
def verify_token(token: str):
    # Route interne permettant aux autres microservices de vérifier un JWT
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"valid": True, "user_email": payload.get("sub"), "user_id": payload.get("user_id")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Le token a expiré.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide.")

if __name__ == "__main__":
    import uvicorn
    # Le port 8082 correspond exactement à ce qu'attend Nginx (voir nginx.conf)
    uvicorn.run(app, host="0.0.0.0", port=8082)


# @app.on_event("startup")
# async def startup_event():
Instrumentator().instrument(app).expose(app, endpoint="/metrics")