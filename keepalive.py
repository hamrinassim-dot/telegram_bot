# app.py - Application Flask principale pour Render
from flask import Flask
import logging
import os
import signal
import sys
from logging_config import configure_logging, get_logger

# Configuration du logging dès le début
configure_logging()
logger = get_logger(__name__)

app = Flask(__name__)

# Configuration de l'application
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')

@app.route('/')
def home():
    try:
        logger.info("Requête reçue sur /")
        return "R2D2 est connecté", 200
    except Exception as e:
        logger.error(f"Erreur dans home(): {e}")
        return "Erreur serveur", 500

@app.route('/health')
def health_check():
    """Health check endpoint pour Render et UptimeRobot"""
    try:
        logger.debug("Health check requis")
        return {
            "status": "OK", 
            "message": "Service running",
            "version": "1.0"
        }, 200
    except Exception as e:
        logger.error(f"Erreur dans health_check(): {e}")
        return {"status": "ERROR", "message": str(e)}, 500

@app.route('/ping')
def ping():
    """Endpoint simple pour keepalive"""
    return "pong", 200

@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 - Page non trouvée: {error}")
    return {"error": "Page non trouvée"}, 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 - Erreur interne: {error}")
    return {"error": "Erreur interne du serveur"}, 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Gère toutes les exceptions non catchées"""
    logger.error(f"Exception non gérée: {e}", exc_info=True)
    return {"error": "Une erreur inattendue s'est produite"}, 500

def setup_signal_handlers():
    """Configure les gestionnaires de signaux pour un arrêt propre"""
    def signal_handler(sig, frame):
        logger.info(f"Signal {sig} reçu, arrêt en cours...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    setup_signal_handlers()
    logger.info("Démarrage de l'application Flask")
    
    # Pour le développement local
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)