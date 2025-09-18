# gunicorn_config.py - Configuration pour la production
import os
import multiprocessing

# Configuration du serveur
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers = min(4, (multiprocessing.cpu_count() * 2) + 1)
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
preload_app = True
timeout = 120
keepalive = 2

# Logging
loglevel = "info"
accesslog = "-"  # stdout
errorlog = "-"   # stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Processus
daemon = False
pidfile = None
tmp_upload_dir = None

# Sécurité
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Worker lifecycle
def on_starting(server):
    server.log.info("Démarrage de Gunicorn")

def on_reload(server):
    server.log.info("Rechargement de Gunicorn")

def worker_int(worker):
    worker.log.info("Worker interrompu")

def pre_fork(server, worker):
    server.log.info(f"Worker {worker.pid} sur le point de démarrer")

def post_fork(server, worker):
    server.log.info(f"Worker {worker.pid} démarré")

def worker_abort(worker):
    worker.log.error(f"Worker {worker.pid} arrêté brutalement")