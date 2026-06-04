# 1. Utiliser une image Python officielle et légère
FROM python:3.11-slim

# 2. Définir le dossier de travail dans le conteneur
WORKDIR /app

# 3. Installer les dépendances système minimales si nécessaire
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. Copier d'abord le fichier des dépendances pour maximiser le cache Docker
COPY requirements.txt .

# 5. Installer les bibliothèques Python
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copier le reste du code source (le fichier main.py)
COPY . .

# 7. Exposer le port interne utilisé par Uvicorn
EXPOSE 8000

# 8. Commande pour démarrer le microservice FastAPI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]