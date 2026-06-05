<template>
  <div id="greenops-app">
    <!-- Barre de navigation supérieure -->
    <header class="navbar">
      <div class="logo-area">
        <span class="logo-icon">logo</span>
        <h1>GreenOps Platform</h1>
      </div>
      <div class="user-status" :class="{ 'logged-in': token }">
        <span v-if="token">Connecté (JWT Valide)</span>
        <span v-else>Non authentifié</span>
      </div>
    </header>

    <!-- Système d'onglets -->
    <nav class="tabs">
      <button :class="{ active: currentTab === 'auth' }" @click="currentTab = 'auth'">Compte & Session</button>
      <button :class="{ active: currentTab === 'dashboard' }" @click="currentTab = 'dashboard'">Supervision Énergie</button>
      <button :class="{ active: currentTab === 'alertes' }" @click="currentTab = 'alertes'">Seuils & Alertes</button>
    </nav>

    <main class="content">
      <!-- 1. ONGLET AUTHENTIFICATION -->
      <section v-if="currentTab === 'auth'" class="card animate-fade">
        <div class="card-header border-teal">
          <h2>Contrôle d'Accès Authentifié</h2>
          <p class="subtitle">Gestion des jetons JWT pour la sécurisation inter-services</p>
        </div>
        <div class="card-body">
          <div v-if="!token" class="auth-form">
            <div class="input-group">
              <label>Adresse Email</label>
              <input type="email" v-model="email" placeholder="utilisateur@greenops.local" />
            </div>
            <div class="input-group">
              <label>Mot de passe</label>
              <input type="password" v-model="password" placeholder="••••••••" />
            </div>
            <div class="form-actions">
              <button @click="login" class="btn-primary">Se connecter</button>
              <button @click="register" class="btn-secondary">Créer un compte</button>
            </div>
          </div>
          <div v-else class="auth-success">
            <div class="success-banner">
              <p><strong>Session active stockée :</strong> Jeton d'autorisation actif pour l'API Gateway.</p>
            </div>
            <button @click="logout" class="btn-danger">Fermer la session (Logout)</button>
          </div>
          <p v-if="message" class="log-msg">{{ message }}</p>
        </div>
      </section>

      <!-- 2. ONGLET DASHBOARD -->
      <section v-if="currentTab === 'dashboard'" class="card animate-fade">
        <div class="card-header border-green">
          <h2>Analyse Énergétique & Empreinte Carbone</h2>
          <p class="subtitle">Collecte synchrone depuis Prometheus et conversion gCO₂e</p>
        </div>
        <div class="card-body">
          <div class="actions-panel">
            <button @click="triggerCalculation" :disabled="!token" class="btn-bolt">
              Déclencher un Calcul
            </button>
            <button @click="fetchData" class="btn-secondary">Rafraîchir les Métriques</button>
          </div>

          <div class="kpi-grid">
            <div class="kpi-card text-green">
              <span class="kpi-label">Puissance Absorbée Hôte</span>
              <span class="kpi-value">{{ latestMetric.power_watts || 0 }} <small>Watts</small></span>
            </div>
            <div class="kpi-card text-teal">
              <span class="kpi-label">Intensité Carbone (Mix FR)</span>
              <span class="kpi-value">{{ latestMetric.carbon_gco2 || 0 }} <small>gCO₂e</small></span>
            </div>
          </div>

          <!-- Zone de visualisation graphique -->
          <div class="chart-container">
            <h3 class="chart-title">Historique de Charge et Analyse Éco-Environnementale</h3>
            
            <div v-if="chartSeries.length > 0 && chartSeries[0].data && chartSeries[0].data.length > 0">
              <apexchart type="line" height="320" :options="chartOptions" :series="chartSeries"></apexchart>
            </div>
            
            <div v-else class="empty-state">
              En attente de données historiques en provenance du Service Lecture...
            </div>
          </div>
        </div>
      </section>

      <!-- 3. ONGLET GESTION DES ALERTES -->
      <section v-if="currentTab === 'alertes'" class="card animate-fade">
        <div class="card-header border-orange">
          <h2>Seuils Critiques & Notifications</h2>
          <p class="subtitle">Persistance des règles de surconsommation dans PostgreSQL & Cache Redis</p>
        </div>
        <div class="card-body">
          <div class="threshold-config bg-dark">
            <label>Seuil d'alerte critique actuel (Watts) :</label>
            <div class="input-inline">
              <input type="number" v-model="alertThreshold" />
              <button @click="saveAlertConfig" class="btn-primary">Appliquer le Seuil</button>
            </div>
          </div>

          <h3 class="section-title">Journal d'Événements d'Alerte (Historique Base de Données)</h3>
          <ul class="alert-list" v-if="alerts.length > 0">
            <li v-for="alert in alerts" :key="alert.id" :class="{ unread: !alert.is_read }">
              <div class="alert-info">
                <span class="alert-time">⏱ {{ new Date(alert.timestamp).toLocaleTimeString() }}</span>
                <p class="alert-text">{{ alert.message }}</p>
              </div>
              <button v-if="!alert.is_read" @click="acknowledgeAlert(alert.id)" class="btn-small">Acquitter</button>
            </li>
          </ul>
          <div v-else class="empty-state green-state">
            Aucun dépassement de seuil détecté. L'infrastructure respecte les critères GreenOps.
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<script>
import axios from 'axios';

// const API_BASE = "http://localhost:8000/api";
const API_BASE = "http://greenops.test/api";


export default {
  data() {
    return {
      currentTab: 'dashboard',
      email: '',
      password: '',
      token: localStorage.getItem('token') || '',
      message: '',
      
      // CORRECTION 1 : Initialisation propre pour sécuriser le rendu HTML
      latestMetric: {
        power_watts: 0,
        carbon_gco2: 0
      },
      
      alertThreshold: 60,
      alerts: [],
      chartOptions: {
        chart: { 
          id: 'carbon-realtime', 
          background: 'transparent',
          fontFamily: 'Segoe UI, sans-serif',
          toolbar: { show: false } 
        },
        theme: { mode: 'dark' },
        xaxis: { 
          categories: [], 
          labels: { style: { colors: '#8e9aa8' } },
          axisBorder: { show: false },
          axisTicks: { show: false }
        },
        yaxis: {
          labels: { style: { colors: '#8e9aa8' } }
        },
        colors: ['#2ecc71', '#00bcff'],
        stroke: { curve: 'smooth', width: 3 },
        grid: { borderColor: '#1f2d3d' },
        legend: { labels: { colors: '#e3e9ec' } }
      },
      
      // CORRECTION 2 : Harmonisation des noms initiaux avec ceux de fetchData()
      chartSeries: [
        { name: "Puissance Réelle (Watts)", data: [] },
        { name: "Estimation Carbone (gCO2)", data: [] }
      ]
    }
  },
  mounted() {
    this.fetchData();
    if (this.token) this.fetchAlerts();
    
    // Bonus : rafraîchissement en arrière-plan toutes les 15 secondes pour suivre le rythme du simulateur/Prometheus
    this.refreshInterval = setInterval(() => {
      this.triggerCalculation(); // Déclenche un nouveau calcul pour obtenir des données fraîches
      this.fetchData();
    }, 15000);
  },
  beforeDestroy() {
    if (this.refreshInterval) clearInterval(this.refreshInterval);
  },
  methods: {
    async register() {
      try {
        this.message = "";
        const payload = { username: this.email, password: this.password };
        await axios.post(`${API_BASE}/auth/register`, JSON.stringify(payload));
        this.message = "Compte créé avec succès. Veuillez vous connecter.";
      } catch (err) { 
        this.message = "Échec de l'enregistrement. Vérifiez les logs du service."; 
      }
    },
    async login() {
      try {
        this.message = "";
        const payload = { username: this.email, password: this.password };
        const res = await axios.post(`${API_BASE}/auth/login`, JSON.stringify(payload));
        this.token = res.data.access_token;
        localStorage.setItem('token', this.token);
        this.message = "Authentification réussie.";
        this.fetchAlerts();
      } catch (err) { 
        this.message = "Identifiants ou connexion à la passerelle invalides."; 
      }
    },
    logout() {
      this.token = '';
      localStorage.removeItem('token');
      this.message = "Session fermée localement.";
      this.alerts = [];
    },
    async triggerCalculation() {
      try {
        const res = await axios.post(`${API_BASE}/calcul/trigger-calculation`, {}, {
          headers: { Authorization: `Bearer ${this.token}` }
        });
        console.log("Calcul déclenché avec succès :", res.data);
        this.fetchData();
        this.fetchAlerts();
      } catch (err) { 
        alert("Action refusée : Session JWT expirée ou indisponibilité de Prometheus."); 
      }
    },
    async fetchData() {
      try {
        const latestRes = await axios.get(`${API_BASE}/donnees/latest`);
        this.latestMetric = latestRes.data;

        const historyRes = await axios.get(`${API_BASE}/donnees/history?limit=10`);
        const history = historyRes.data.reverse();
        console.log("Données historiques reçues :", history);

        // Extraction des tableaux numériques
        const puissanceData = history.map(item => item.puissance || item.power_watts || 0); 
        const carboneData = history.map(item => item.carbone || item.carbon_gco2 || 0);
        const categoriesTime = history.map(item => {
          const dateStr = item.timestamp || item.date;
          if (!dateStr) return '';
          const d = new Date(dateStr);
          return d.toLocaleTimeString('fr-FR'); 
        });
        
        // Mise à jour de l'axe X
        this.chartOptions = { 
          ...this.chartOptions, 
          xaxis: { 
            ...this.chartOptions.xaxis,
            categories: categoriesTime
          } 
        };

        // CORRECTION 2 (Suite) : Assignation avec les noms rigoureusement identiques à data()
        this.chartSeries = [
          {
            name: "Puissance Réelle (Watts)",
            data: puissanceData
          },
          {
            name: "Estimation Carbone (gCO2)",
            data: carboneData
          }
        ];
      } catch (err) { 
        console.error("Le Service Lecture Données n'a retourné aucun historique.", err); 
      }
    },
    async saveAlertConfig() {
      try {
        await axios.post(`${API_BASE}/alertes/configure`, { user_id: 1, max_power_threshold_watts: this.alertThreshold });
        alert("Seuil global persisté avec succès.");
      } catch (err) { 
        console.error("Erreur lors de l'enregistrement du seuil."); 
      }
    },
    async fetchAlerts() {
      try {
        const res = await axios.get(`${API_BASE}/alertes/user/1`);
        this.alerts = res.data;
      } catch (err) { 
        console.error("Impossible de récupérer l'historique des alertes."); 
      }
    },
    async acknowledgeAlert(id) {
      try {
        await axios.put(`${API_BASE}/alertes/ack/${id}`);
        this.fetchAlerts();
      } catch (err) { 
        console.error(err); 
      }
    }
  }
}
</script>

<style scoped>
#greenops-app { max-width: 1100px; margin: 0 auto; padding: 30px 15px; }
.navbar { display: flex; justify-content: space-between; align-items: center; background: #162431; padding: 15px 25px; border-radius: 8px; border: 1px solid #233549; margin-bottom: 25px; }
.logo-area { display: flex; align-items: center; gap: 12px; }
.logo-area h1 { margin: 0; font-size: 20px; font-weight: 600; color: #ffffff; letter-spacing: -0.5px; }
.logo-icon { font-size: 24px; }
.user-status { font-size: 13px; font-weight: 500; color: #8e9aa8; background: #0f1a24; padding: 6px 12px; border-radius: 20px; border: 1px solid #1a2b3c; }
.user-status.logged-in { color: #2ecc71; border-color: rgba(46, 204, 113, 0.2); background: rgba(46, 204, 113, 0.05); }

.tabs { margin-bottom: 25px; display: flex; gap: 8px; border-bottom: 1px solid #233549; padding-bottom: 10px; }
.tabs button { background: transparent; border: none; color: #8e9aa8; padding: 10px 18px; font-weight: 500; cursor: pointer; border-radius: 4px; transition: all 0.2s ease; font-size: 14px; }
.tabs button:hover { color: #ffffff; background: #162431; }
.tabs button.active { color: #2ecc71; background: #1a2c3a; font-weight: 600; }

.card { background: #162431; border-radius: 8px; border: 1px solid #233549; box-shadow: 0 10px 25px rgba(0,0,0,0.3); overflow: hidden; margin-bottom: 25px; }
.card-header { padding: 20px 25px; background: #192a3a; border-bottom: 1px solid #233549; }
.card-header h2 { margin: 0 0 4px 0; font-size: 18px; color: #ffffff; }
.card-header .subtitle { margin: 0; font-size: 13px; color: #8e9aa8; }
.card-body { padding: 25px; }

.border-teal { border-left: 4px solid #00bcff; }
.border-green { border-left: 4px solid #2ecc71; }
.border-orange { border-left: 4px solid #e67e22; }

.input-group { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.input-group label { font-size: 13px; color: #8e9aa8; font-weight: 500; }
.input-group input { background: #0f1a24; border: 1px solid #233549; padding: 10px 14px; color: #ffffff; border-radius: 4px; font-size: 14px; }
.input-group input:focus { border-color: #2ecc71; outline: none; }

.form-actions { display: flex; gap: 10px; margin-top: 20px; }
button { font-size: 14px; padding: 10px 20px; font-weight: 600; border-radius: 4px; cursor: pointer; border: none; transition: background 0.2s; }
.btn-primary { background: #2ecc71; color: #111c24; }
.btn-primary:hover { background: #27ae60; }
.btn-secondary { background: #233549; color: #e3e9ec; border: 1px solid #2d435c; }
.btn-secondary:hover { background: #2d435c; }
.btn-danger { background: #e74c3c; color: white; }
.btn-danger:hover { background: #c0392b; }
.btn-bolt { background: #00bcff; color: #111c24; }
.btn-bolt:hover { background: #009cd3; }
button:disabled { background: #23303d !important; color: #526070 !important; cursor: not-allowed; }

.success-banner { background: rgba(0, 188, 255, 0.05); border: 1px solid rgba(0, 188, 255, 0.2); padding: 15px; border-radius: 4px; margin-bottom: 20px; color: #00bcff; font-size: 14px; }
.log-msg { margin-top: 15px; font-size: 13px; color: #f1c40f; }

.actions-panel { display: flex; gap: 10px; margin-bottom: 25px; }
.kpi-grid { display: flex; gap: 20px; margin-bottom: 25px; }
.kpi-card { flex: 1; background: #0f1a24; padding: 20px; border-radius: 6px; border: 1px solid #233549; position: relative; }
.kpi-label { display: block; font-size: 13px; color: #8e9aa8; font-weight: 500; margin-bottom: 6px; }
.kpi-value { display: block; font-size: 32px; font-weight: 700; letter-spacing: -1px; }
.kpi-value small { font-size: 14px; font-weight: 400; color: #8e9aa8; margin-left: 4px; }
.text-green .kpi-value { color: #2ecc71; }
.text-teal .kpi-value { color: #00bcff; }

.chart-container { background: #0f1a24; padding: 20px; border-radius: 6px; border: 1px solid #233549; }
.chart-title { margin: 0 0 20px 0; font-size: 14px; color: #e3e9ec; font-weight: 600; }
.empty-state { padding: 40px; text-align: center; color: #526070; font-size: 14px; }
.green-state { color: #2ecc71; background: rgba(46, 204, 113, 0.05); border: 1px solid rgba(46, 204, 113, 0.1); border-radius: 4px; padding: 20px; text-align: center; }

.threshold-config { padding: 20px; border-radius: 6px; margin-bottom: 25px; border: 1px solid #233549; background: #0f1a24; }
.threshold-config label { display: block; font-size: 14px; margin-bottom: 10px; color: #e3e9ec; }
.input-inline { display: flex; gap: 10px; }
.input-inline input { background: #162431; border: 1px solid #233549; padding: 10px; color: white; border-radius: 4px; width: 150px; }

.section-title { font-size: 15px; margin: 25px 0 15px 0; color: #ffffff; }
.alert-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
.alert-list li { display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: #1c1c28; border-radius: 4px; border-left: 4px solid #e67e22; border-top: 1px solid #2d2d3d; border-right: 1px solid #2d2d3d; border-bottom: 1px solid #2d2d3d; }
.alert-list li.unread { background: #241e24; border-left-color: #e74c3c; }
.alert-info { display: flex; flex-direction: column; gap: 4px; }
.alert-time { font-size: 11px; color: #8e9aa8; font-weight: 600; }
.alert-text { margin: 0; font-size: 13px; color: #e3e9ec; }
.btn-small { font-size: 12px; padding: 6px 12px; background: #233549; color: #ffffff; }
.btn-small:hover { background: #2d435c; }

.animate-fade { animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
</style>
