import os
import logging
import logging.config

# Réduire le niveau de log pour httpx
logging.getLogger("httpx").setLevel(logging.WARNING)

# Assurer que le répertoire logs existe
os.makedirs('logs', exist_ok=True)

def configure_logging():
    """Configure le système de logging avec rotation des fichiers"""
    
    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            },
            'simple': {
                'format': '%(asctime)s - %(message)s'
            },
            'detailed': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'simple',
                'stream': 'ext://sys.stdout',
            },
            'info_file_handler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'INFO',
                'formatter': 'standard',
                'filename': 'logs/info.log',
                'maxBytes': 10485760,  # 10MB
                'backupCount': 10,
                'encoding': 'utf8',
            },
            'error_file_handler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'ERROR',
                'formatter': 'detailed',
                'filename': 'logs/errors.log',
                'maxBytes': 10485760,  # 10MB
                'backupCount': 20,
                'encoding': 'utf8',
            },
            'debug_file_handler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'DEBUG',
                'formatter': 'detailed',
                'filename': 'logs/debug.log',
                'maxBytes': 10485760,  # 10MB
                'backupCount': 5,
                'encoding': 'utf8',
            }
        },
        'loggers': {
            '': {  # root logger
                'handlers': ['console', 'info_file_handler', 'error_file_handler', 'debug_file_handler'],
                'level': 'INFO',
                'propagate': True
            },
            'telegram': {
                'handlers': ['info_file_handler', 'error_file_handler'],
                'level': 'INFO',
                'propagate': False
            },
            'httpx': {  # Pour réduire les logs verbeux de certaines librairies
                'handlers': ['error_file_handler'],
                'level': 'WARNING',
                'propagate': False
            },
        }
    }
    
    logging.config.dictConfig(logging_config)
    return logging.getLogger(__name__)

# Fonction pour obtenir un logger configuré
def get_logger(name):
    return logging.getLogger(name)