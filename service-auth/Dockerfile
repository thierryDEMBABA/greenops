# Utilise une image Python légère officielle
FROM python:3.11-slim

# Définit le dossier de travail dans le conteneur
WORKDIR /app

# Copie le fichier des dépendances
COPY requirements.txt .

# Installe les dépendances nécessaires
RUN pip install --no-cache-dir -r requirements.txt

# Copie le reste du code source
COPY main.py .

# Expose le port interne du microservice
EXPOSE 8082

# Lance l'application
CMD ["python", "main.py"]