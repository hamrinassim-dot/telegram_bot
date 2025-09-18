from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "R2D2 est connecté", 200

@app.route('/health')
def health_check():
    return "OK", 200

def run():
    app.run(host='0.0.0.0', port=8080)

@app.errorhandler(500)
def internal_error(error):
    return "Erreur interne du serveur", 500

@app.errorhandler(404)
def not_found_error(error):
    return "Page non trouvée", 404

def keep_alive():
    t = Thread(target=run)
    t.start()
