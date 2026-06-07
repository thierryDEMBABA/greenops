# greenOps 🌱

`greenOps` est une plateforme microservices conteneurisée conçue pour démontrer les pratiques modernes d'architecture logicielle, de déploiement cloud-native et d'observabilité complète (monitoring, tracing et centralisation des logs).

## 🚀 Architecture du Projet

Le projet est découpé en plusieurs microservices spécialisés qui communiquent entre eux via des bases de données et des courtiers de messages :

* **Frontend** (`service-frontend`) : Interface utilisateur codée en Vue.js permettant de visualiser les métriques et d'interagir avec la plateforme.
* **Authentification** (`service-auth`) : Gestion de l'authentification et de la sécurité des utilisateurs.
* **Calcul** (`service-calcul`) : Microservice métier chargé des algorithmes de traitement lourd (développé avec FastAPI).
* **Lecture** (`service-lecture`) : Service optimisé pour la lecture de données et la génération de rapports.
* **Alertes** (`service-alertes`) : Système de notification et de gestion des alertes de pannes ou d'anomalies.
* **Simulateur & Load Generator** (`service-simulator` / `load-generator`) : Générateurs de trafic et de charge pour simuler une activité utilisateur continue et tester la résilience de l'infrastructure. des outils comme keppler ou scaphandre pourront etre utilises pour un environnement concret

### 🗄️ Infrastructure et Base de données
* **Message Broker** : RabbitMQ pour la communication asynchrone et événementielle entre les services.
* **Bases de données** : PostgreSQL (persistance des données) et Redis (cache de performance).
* **Websockets**: optimisation de la communication inter service et reduction importante des requetes synchrones

---

## 📊 Stack d'Observabilité

La stack de monitoring et de logging est entièrement intégrée au cluster et déployée dans le même namespace (`greenops`) :

* **Prometheus & Kube-State-Metrics** : Collecte des métriques d'infrastructure (CPU, RAM) et applicatives.
* **Grafana** : Tableaux de bord centralisés pour la visualisation des logs et des métriques.
* **Loki & Promtail** : Collecte (via Promtail en tant que DaemonSet) et centralisation (Loki) de l'ensemble des logs de tous les conteneurs du cluster.

---

## 🛠️ Prérequis

Avant de déployer le projet, assurez-vous de disposer des outils suivants :
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) avec l'implémentation **WSL2** activée.
* Un cluster Kubernetes local activé (Docker Desktop K8s, Minikube ou Kind).
* [kubectl](https://kubernetes.io/docs/tasks/tools/) installé et configuré.
* [Helm](https://helm.sh/) (optionnel, selon votre méthode de déploiement).

---

## 📦 Déploiement

### 1. Cloner le projet
(bash)
git clone --branch feature/kubernetes --single-branch https://github.com/thierryDEMBABA/greenops.git
cd greenops

### 2. Appliquer les configurations et les déploiements
Appliquez les fichiers YAML dans l'ordre (adaptez selon la structure de vos dossiers) :
kubectl apply -f ./k8s/infrastructure/ -n greenops
kubectl apply -f ./k8s/persistance/ -n greenops
kubectl apply -f ./k8s/deployment/ -n greenops
kubectl apply -f ./k8s/logging/ -n greenops



Auteur
-  Nkenfack Thierry
