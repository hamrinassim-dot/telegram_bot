import os
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, Message, InputMediaPhoto, ChatPermissions
from telegram.ext import Application, CommandHandler, ContextTypes, ChatMemberHandler, filters, MessageHandler
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import BadRequest, Forbidden

from collections import defaultdict
from flask import Flask, jsonify
import asyncio
from logging_config import configure_logging, get_logger
from datetime import datetime, timedelta
import yaml
import pytz
import re
import signal
import sys
import threading

# Configuration du logging dès le début
configure_logging()
logger = get_logger(__name__)

# Chargement des variables d'environnement
load_dotenv()
telegram_app = None

# Configuration Flask pour Render
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')


@app.route('/')
def home():
    try:
        logger.info("Requête reçue sur /")
        return jsonify({
            "status": "R2D2 connecté",
            "timestamp": datetime.now().isoformat(),
            "bot_running": telegram_app is not None
        }), 200
    except Exception as e:
        logger.error(f"Erreur dans home(): {e}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/health')
def health_check():
    """Health check endpoint pour Render et UptimeRobot"""
    try:
        bot_status = "running" if telegram_app else "stopped"
        logger.debug("Health check requis")
        return jsonify({
            "status": "OK",
            "message": "Service running",
            "bot_status": bot_status,
            "timestamp": datetime.now().isoformat(),
            "version": "2.0"
        }), 200
    except Exception as e:
        logger.error(f"Erreur dans health_check(): {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500

@app.route('/ping')
def ping():
    """Endpoint simple pour keepalive"""
    return "pong", 200

@app.route('/bot/status')
def bot_status():
    """Status du bot Telegram"""
    try:
        if telegram_app:
            return jsonify({
                "bot_status": "running",
                "bot_id": telegram_app.bot.id if telegram_app.bot else None
            }), 200
        else:
            return jsonify({"bot_status": "stopped"}), 200
    except Exception as e:
        logger.error(f"Erreur bot_status(): {e}")
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 - Page non trouvée: {error}")
    return jsonify({"error": "Page non trouvée"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 - Erreur interne: {error}")
    return jsonify({"error": "Erreur interne du serveur"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Gère toutes les exceptions non catchées"""
    logger.error(f"Exception non gérée: {e}", exc_info=True)
    return jsonify({"error": "Une erreur inattendue s'est produite"}), 500

def setup_signal_handlers():
    """Configure les gestionnaires de signaux pour un arrêt propre"""
    def signal_handler(sig, frame):
        logger.info(f"Signal {sig} reçu, arrêt en cours...")
        if telegram_app:
            logger.info("Arrêt du bot Telegram...")
            try:
                # Arrêt propre du bot
                asyncio.create_task(telegram_app.stop())
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt du bot: {e}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def setup_telegram_bot():
    """Configuration du bot Telegram (handlers, token, etc.)"""
    global telegram_app
    load_dotenv()

    token = os.getenv('TOKEN')
    if not token:
        logger.error("Token Telegram manquant!")
        return None
    
    # Création de l'application Telegram
    telegram_app = Application.builder().token(token).build()
    
    # Enregistrement des commandes
    for cmd in COMMAND_MAPPINGS.keys():
        telegram_app.add_handler(CommandHandler(cmd, generic_info_command))

    for savant_id in SAVANTS_INFO.keys():
        telegram_app.add_handler(CommandHandler(savant_id, savant_command_handler))

    telegram_app.add_handler(CommandHandler('reload', reload_messages))
    telegram_app.add_handler(CommandHandler('start', start))
    telegram_app.add_handler(CommandHandler('envoyer_pub_entreprise', envoyer_pub_entreprise))
    telegram_app.add_handler(CommandHandler('getid', get_chat_id))
    telegram_app.add_handler(CommandHandler('help', help_command))
    telegram_app.add_handler(ChatMemberHandler(chat_member_handler, ChatMemberHandler.CHAT_MEMBER))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_album))
    telegram_app.add_handler(CommandHandler('ban', ban_command))

    # Gestionnaire pour les commandes inconnues - doit être ajouté en DERNIER
    telegram_app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    logger.info("Tous les handlers enregistrés avec succès")
    return telegram_app


def run_telegram_bot():
    """Démarre le bot Telegram (bloquant)."""
    global telegram_app
    if not telegram_app:
        logger.error("Impossible de démarrer le bot : telegram_app est None")
        return
    
    try:
        # Création d'une boucle asyncio pour ce thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        telegram_app.run_polling(
            allowed_updates=["message", "chat_member", "my_chat_member"],
            poll_interval=3,
            drop_pending_updates=True,
            stop_signals=None
        )
        logger.info("Bot Telegram démarré avec succès")
    except Exception as e:
        logger.error(f"Erreur dans run_telegram_bot: {e}", exc_info=True)


def start_telegram_bot_thread():
    """Démarre le bot Telegram dans un thread séparé"""
    try:
        bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
        bot_thread.start()
        logger.info("Thread du bot Telegram démarré")
        return bot_thread
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du thread bot: {e}")
        return None

    
# Chargement des variables d'environnement
load_dotenv()
chat_id = int(os.getenv('CHAT_ID'))

media_groups = defaultdict(list)
timers = {}

# Délai après lequel on considère l'album complet
WAIT_TIME = 3  # secondes

# Messages
def charger_messages(path='messages.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

MESSAGES = charger_messages()

COMMAND_MAPPINGS = {
    'fourqanfemme': 'fourqanFemme',
    'diyacoran': 'diyaCoran',
    'raseel': 'raseel',
    'fourqanhomme': 'fourqanHomme',
    'diyahomme': 'diyaHomme',
    'moumarassa': 'moumarassa',
    'hopitaux': 'hospitals',
    'resto_fr': 'restaurants',
    'tout_les_savants': 'tout_les_savants',
    'lien_groupe': 'lien_groupe',
}

# Dictionnaire contenant les informations sur tous les savants
SAVANTS_INFO = {
    "raslan": {
        "nom": "Cheikh Mohamed Said Raslan",
        "description": "",
        "localisation": "https://maps.app.goo.gl/1z5YfQysnmrtg6397",
        "telegram": None
    },
    "adil_sayid": {
        "nom": "Cheikh Adil Sayid",
        "description": "Savant spécialiste du tafsir recommander par le Cheikh Hassan ibn AbdilWahab Al banna",
        "localisation": "https://maps.app.goo.gl/JRUeHTfyhYPNvQBD6",
        "telegram": "https://t.me/adelelsayd"
    },
    "khalid_othman_abou_abdil_aala": {
        "nom": "Cheikh Khalid othman Abou abdilAala",
        "description": "Recommander par plusieurs mashayks d'Arabie et d'Égypte parmis eux Cheikh Hassan ibn AbdilWahab et Cheikh Zayd al madkhali",
        "localisation": "Voir chaîne telegram du Cheikh (il change chaque semaine)",
        "telegram": "https://t.me/abuabdelaala"
    },
    "abou_hazim_mohamed_mousni": {
        "nom": "Cheikh Abou Hazim Mohamed Housni",
        "description": "Recommandé par les mashayks d'Égypte notamment Cheikh Hassan ibn AbdilWahab",
        "localisation": "https://goo.gl/maps/WYxKZJTMZzqmjBYU7",
        "telegram": "https://t.me/abuhazemsalafi"
    },
    "walid_boughdadi": {
        "nom": "Cheikh Walid boughdadi",
        "description": "Recommander par Cheikh Hassan et Cheikh Adil sayid",
        "localisation": "https://maps.app.goo.gl/CRCu4gFBYo16t3hi8",
        "localisation_cours": "https://maps.app.goo.gl/zq8iFbyrQcjZMprVA?g_st=it",
        "telegram": "https://t.me/waleed_boghdady"
    },
    "ahmed_said": {
        "nom": "Cheikh Ahmed said",
        "description": "Docteur en faculté de hadith à l'université de medine et élève de nombreux mashayks parmis eux Cheikh Salih Sindi et Cheikh Aly touwaijiry",
        "localisation": "https://maps.app.goo.gl/aysEwLu84C5tH5B38",
        "telegram": "https://t.me/drahmadsaed"
    }
}

def extract_status_change(chat_member_update):
    """Extrait le changement de statut d'un ChatMemberUpdated"""
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    
    was_member = old_status in [
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
    ]
    is_member = new_status in [
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
    ]
    
    logger.info(f"Ancien statut: {old_status}, Nouveau statut: {new_status}")
    logger.info(f"was_member: {was_member}, is_member: {is_member}")
    
    return was_member, is_member

def parse_duration(duration_str):
    """Parse la durée du ban (ex: 1h, 30m, 7d, permanent)"""
    if not duration_str or duration_str.lower() in ['permanent', 'perm', 'definitif']:
        return None  # Ban permanent
    
    # Regex pour capturer les durées (ex: 1h, 30m, 7d)
    match = re.match(r'^(\d+)([mhdj])$', duration_str.lower())
    if not match:
        return False  # Format invalide
    
    number, unit = match.groups()
    number = int(number)
    
    if unit == 'm':  # minutes
        return timedelta(minutes=number)
    elif unit == 'h':  # heures
        return timedelta(hours=number)
    elif unit in ['d', 'j']:  # jours
        return timedelta(days=number)
    
    return False

def format_duration(duration):
    """Formate une durée en texte lisible"""
    if duration is None:
        return "définitif"
    
    total_seconds = int(duration.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    
    parts = []
    if days > 0:
        parts.append(f"{days} jour{'s' if days > 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} heure{'s' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    
    return " et ".join(parts) if parts else "moins d'une minute"

"""Vérifie si l'utilisateur est administrateur du groupe"""
async def is_user_admin(context, chat_id, user_id):
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Erreur lors de la vérification admin: {e}")
        return False
    
async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les changements de statut des membres"""
    # Logs détaillés de tout l'événement
    logger.info(f"Événement de membre reçu: {update}")
    
    # Vérifier si c'est un événement de type CHAT_MEMBER
    if update.chat_member is None:
        logger.info("Ce n'est pas un événement CHAT_MEMBER")
        return
    
    # Extrait les informations sur le changement de statut
    result = extract_status_change(update.chat_member)
    if result is None:
        logger.info("Pas de changement de statut détecté")
        return
    
    was_member, is_member = result
    
    # Log pour débogage
    logger.info(
        f"Statut utilisateur : {update.chat_member.from_user.first_name} "
        f"dans {update.chat_member.chat.title}, ancien: {was_member}, nouveau: {is_member}"
    )
    
    # Si c'est un nouveau membre qui vient de rejoindre
    if not was_member and is_member:
        user = update.chat_member.new_chat_member.user
        prenom = user.first_name
        user_id = user.id
        
        logger.info(f"Nouveau membre détecté: {prenom} (ID: {user_id})")
        
        # Message de bienvenue dans le groupe
        bouton = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Cliquez ici pour activer le bot", url=f"https://t.me/{context.bot.username}?start=welcome")]
        ])
        
        message_publique = f'Bienvenue <a href="tg://user?id={user_id}">{prenom}</a> ! Pour recevoir des infos importantes, activez le bot 👇'
        try:
            message_obj = await context.bot.send_message(
            chat_id=update.chat_member.chat.id,
            text=message_publique,
            reply_markup=bouton,
            parse_mode=ParseMode.HTML,
            )

            await asyncio.sleep(10)
            await message_obj.delete()
            logger.info(f"✅ Message de bienvenue envoyé dans le groupe pour {prenom}")

        except Exception as e:
            logger.error(f"❌ Erreur d'envoi dans le groupe : {e}")
        
async def supprimer_message(message: Message):
    try:
        await message.delete()

    except BadRequest as e:
        if "message to delete not found" in str(e).lower():
            logger.info(f"❌ Message déjà supprimé ou introuvable.")

        else:
            logger.info(f"❌ Erreur inattendue : {e}")

"""Fonction générique pour envoyer un message privé avec gestion d'erreur"""
async def send_private_message(context, user, message_text, command_name, update):
    try:
        await context.bot.send_message(chat_id=user.id, text=message_text)
        logger.info(f"✅ Information envoyée à {user.first_name} via commande /{command_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Erreur d'envoi à {user.first_name} via /{command_name} : {e}")
        
        bouton = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Activer le bot", url=f"https://t.me/{context.bot.username}?start=start")]
        ])
        
        msg_bot = await update.message.reply_text(
            "❌ Je n'ai pas pu t'envoyer le message en privé. Active le bot ici 👇",
            reply_markup=bouton
        )
        
        await asyncio.sleep(10)
        await msg_bot.delete()
        return False

"""Fonction générique pour envoyer les info sur les savants"""
async def get_savant_info(savant_id):    
    if savant_id not in SAVANTS_INFO:
        return "Information non disponible pour ce savant."
        
    info = SAVANTS_INFO[savant_id]
    message = f"- {info['nom']}\n\n"
    
    if info['description']:
        message += f"{info['description']}\n\n"
        
    message += "📍 Localisation jumuah/cours :\n\n"
    message += f"{info['localisation']}\n"
    
    if 'localisation_cours' in info and info['localisation_cours']:
        message += f"\nCours :\n\n{info['localisation_cours']}\n"
        
    if info['telegram']:
        message += f"\nℹ️ Chaîne telegram :\n\n{info['telegram']}"
        
    return message    

"""Fonction pour vérifier si une commande existe"""
def command_exists(command_name):
    # Nettoie la commande (enlève les mentions du bot comme @bot_name)
    clean_command = command_name.split('@')[0]
    
    # Vérifie si la commande existe dans COMMAND_MAPPINGS ou SAVANTS_INFO
    return clean_command in COMMAND_MAPPINGS or clean_command in SAVANTS_INFO or clean_command in ['start', 'reload', 'help', 'getid', 'envoyer_pub_entreprise']

"""Gestionnaire générique pour toutes les commandes de savants"""
async def savant_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    if update.message.text[0] == '/':
        command = update.message.text[1:]  # Enlève le '/' au début
    
    # Extrait l'identifiant du savant (par exemple, 'raslan' de '/raslan')
    savant_id = command.split('@')[0]  # Gère les cas avec @nom_du_bot
    
    # Vérifie si le savant existe
    if savant_id not in SAVANTS_INFO:
        logger.warning(f"⚠️ Commande savant inconnue: /{savant_id} par {user.first_name}")
        await update.message.reply_text(f"La commande /{savant_id} n'existe pas. Vérifiez la liste des commandes disponibles avec /help.")
        
        # Supprimer le message d'erreur après un court délai
        await asyncio.sleep(5)
        await supprimer_message(update.message)
        return
    
    # Génère le message d'information pour ce savant
    message = await get_savant_info(savant_id)
    
    await send_private_message(
        context=context,
        user=user,
        message_text=message,
        command_name=command,
        update=update
    )
    
    # Supprimer le message de commande après un court délai
    await asyncio.sleep(5)
    await supprimer_message(update.message)

"""Gestionnaire pour toutes les commandes d'information"""
async def generic_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    command = update.message.text[1:].split('@')[0]  # Extrait le nom sans '/'
    
    # Vérifie si la commande existe
    if command not in COMMAND_MAPPINGS:
        user = update.effective_user
        logger.warning(f"⚠️ Commande info inconnue: /{command} par {user.first_name}")
        await update.message.reply_text(f"La commande /{command} n'existe pas. Vérifiez la liste des commandes disponibles avec /help.")
        
        # Supprimer le message d'erreur après un court délai
        await asyncio.sleep(5)
        await supprimer_message(update.message)
        return
    
    message_key = COMMAND_MAPPINGS[command]
    user = update.effective_user
    
    await send_private_message(
        context=context,
        user=user,
        message_text=MESSAGES[message_key],
        command_name=command,
        update=update
    )
    
    await asyncio.sleep(5)
    await supprimer_message(update.message)

async def envoyer_pub_entreprise(application):
    deja_envoye = set()
    pubs = MESSAGES.get('publicite_entreprise', {}).get('pub', {})
    prefix = MESSAGES.get('publicite_entreprise', {}).get('prefix', '')
    suffix = MESSAGES.get('publicite_entreprise', {}).get('suffix', '')
    separation = MESSAGES.get('publicite_entreprise',{}).get('separation', '')

    # Configuration du fuseau horaire égyptien
    timezone_egypt = pytz.timezone('Africa/Cairo')
    jour_debut = datetime(2025, 6, 20, tzinfo=timezone_egypt)
    
    while True:
        maintenant = datetime.now(timezone_egypt)
        delta_jours = (maintenant - jour_debut).days
        jour_cle = maintenant.strftime("%Y-%m-%d")
        jour_cycle = delta_jours % 3

        pubs_du_jour = []

        for cle in pubs:
            try:
                numero = int(cle[1:])  # extrait 1 de e1, 10 de e10
                if (numero - 1) % 3 == jour_cycle:
                    pubs_du_jour.append((numero, cle))
            except ValueError:
                pass

        # Trier par numéro (ex: e1 avant e4)
        pubs_du_jour.sort()

        for i, (_, cle) in enumerate(pubs_du_jour):
            if maintenant.hour == 12 + i and maintenant.minute == 0 and jour_cle not in deja_envoye:
                contenu = pubs[cle]
                texte_final = f"{separation}\n{prefix}\n{separation}\n\n{contenu}\n\n{separation}\n{suffix}\n{separation}"
                boutons = []
                cle_num = cle[1:]
                image_dir = "./img"

                # Collecte des images pour envoi en groupe
                images_a_envoyer = []
                for file in sorted(os.listdir(image_dir)):
                    if file.startswith(f"e{cle_num}_") and file.endswith((".png", ".jpg", ".jpeg")):
                        try:
                            images_a_envoyer.append(os.path.join(image_dir, file))
                        except Exception as e:
                            logger.warning(f"❌ Erreur préparation image {file} : {e}")

                # Envoi des images en groupe (média group)
                if images_a_envoyer:
                    try:
                        media_group = []
                        for image_path in images_a_envoyer:
                            with open(image_path, "rb") as photo:
                                media_group.append(InputMediaPhoto(photo.read()))
                        
                        await application.bot.send_media_group(
                            chat_id=chat_id,# 5700380278
                            media=media_group
                        )
                        logger.info(f"✅ {len(images_a_envoyer)} images envoyées en groupe pour {cle}")
                    except Exception as e:
                        logger.warning(f"❌ Erreur envoi groupe d'images pour {cle} : {e}")

                # Creation des boutons de liens interactifs
                for key, value in pubs.items():
                    if key.startswith(f"le{cle_num}_"):
                        try:
                            url, label = [s.strip() for s in value.split("|", 1)]
                            boutons.append(InlineKeyboardButton(label, url=url))
                            logger.info(f" Format valide pour le lien {key}")
                        except ValueError:
                            logger.warning(f"❌ Format invalide pour le lien {key}")

                markup = InlineKeyboardMarkup([[btn] for btn in boutons]) if boutons else None

                try:
                    await application.bot.send_message(
                        chat_id=chat_id,# 5700380278
                        text=texte_final,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup = markup
                    )
                    logger.info(f"📢 Pub '{cle}' envoyée à {12 + i}h.")
                except Exception as e:
                    logger.error(f"❌ Erreur pub '{cle}' : {e}")

            if maintenant.hour >= 12:
                deja_envoye.add(jour_cle)

        await asyncio.sleep(60)

"""Gestionnaire pour les commandes inconnues"""
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    command = update.message.text[1:].split('@')[0]
    
    logger.warning(f"⚠️ Commande inconnue: /{command} par {user.first_name}")
    
    response = await update.message.reply_text(
        f"La commande /{command} n'existe pas. Utilisez /help pour voir la liste des commandes disponibles.")
    
    # Supprimer les messages après un court délai
    await asyncio.sleep(5)
    await supprimer_message(update.message)
    await supprimer_message(response)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Affiche la liste des commandes disponibles"""
    info_commands = ", ".join([f"/{cmd}" for cmd in COMMAND_MAPPINGS.keys()])
    savant_commands = ", ".join([f"/{savant}" for savant in SAVANTS_INFO.keys()])
    
    help_text = (
        "📋 Commandes disponibles :\n\n"
        "ℹ️ Informations générales :\n"
        f"{info_commands}\n\n"
        "👳‍♂️ Savants :\n"
        f"{savant_commands}\n\n"
        "⚙️ Autres commandes :\n"
        "/help - Affiche cette aide\n"
        "/start - Démarre le bot"
    )
    
    user = update.effective_user
    await send_private_message(
        context=context, 
        user=user, 
        message_text=help_text,
        command_name="help",
        update=update
    )
    
    # Supprimer le message de commande
    await asyncio.sleep(5)
    await supprimer_message(update.message)

async def reload_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global MESSAGES
    MESSAGES = charger_messages()
    await update.message.reply_text("♻️ Messages rechargés avec succès.")

     # Supprimer le message de commande après un court délai (ex: 5 secondes)
    await asyncio.sleep(5)
    await supprimer_message(update.message)

#   Commande initialisation bot 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la commande /start, utilisée quand un utilisateur démarre le bot"""
    user = update.effective_user
    prenom = user.first_name
    msg = f"Salam {prenom}, merci d'avoir activé le bot !"
    
    await send_private_message(
    context=context,
    user=user,
    message_text=msg,
    command_name='start',
    update=update
)
    await send_private_message(
    context=context,
    user=user,
    message_text=MESSAGES['bot_usage'],
    command_name='start',
    update=update
)
    
    # Supprimer le message de commande après un court délai (ex: 5 secondes)
    await asyncio.sleep(5)
    await supprimer_message(update.message)
    logger.info(f"✅ Utilisateur {prenom} ({user.id}) a démarré le bot.")

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    chat_type = chat.type
    chat_id = chat.id

    message = f"🆔 ID de cette conversation : `{chat_id}`\n"
    message += f"💬 Type : `{chat_type}`"

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.MARKDOWN
    )

async def envoyer_rappel_lundi_jeudi(application):
    while True:
        maintenant = datetime.now()

        # Si c'est lundi (0) ou jeudi (3) à 12h00
        if maintenant.weekday() in [0, 3] and maintenant.hour == 12 and maintenant.minute == 0:
            try:
                await application.bot.send_message(chat_id=chat_id, text=MESSAGES['fr'])
                await application.bot.send_message(chat_id=chat_id, text=MESSAGES['ar'])
                logger.info("📌 Rappel envoyé à 12h (lundi ou jeudi)")
            except Exception as e:
                logger.error(f"❌ Erreur lors de l'envoi du rappel régulier : {e}")
            
            # Attendre 61 secondes pour éviter de le renvoyer plusieurs fois dans la même minute
            await asyncio.sleep(61)
        else:
            # Vérifie toutes les 60 secondes
            await asyncio.sleep(60)

async def envoyer_rappel_mardi_vendredi_dimanche(application):
    while True:
        maintenant = datetime.now()

        # Si c'est lundi (0) ou jeudi (3) à 12h00
        if maintenant.weekday() in [1, 4, 6] and maintenant.hour == 12 and maintenant.minute == 0:
            try:
                await application.bot.send_message(chat_id=chat_id, text=MESSAGES['bot_usage'])
                logger.info("📌 Rappel des commandes envoyé à 12h (mardi ou vendredi, dimanche)")
            except Exception as e:
                logger.error(f"❌ Erreur lors de l'envoi du rappel régulier : {e}")
            
            # Attendre 61 secondes pour éviter de le renvoyer plusieurs fois dans la même minute
            await asyncio.sleep(61)
        else:
            # Vérifie toutes les 60 secondes
            await asyncio.sleep(60)

async def process_media_group(group_id: str, context: ContextTypes.DEFAULT_TYPE, user_first_name):
    await asyncio.sleep(WAIT_TIME)
    messages = media_groups.get(group_id, [])
    if not messages:
        return

    total_photos = len(messages)
    if total_photos > 4:
        # Supprimer tous les messages du groupe
        for msg in messages:
            await supprimer_message(msg)

        # Envoyer un avertissement
        warning = await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚫 {user_first_name}, vous ne pouvez pas envoyer plus de 4 photos à la fois.",
        )

        # Supprimer l'avertissement après 5 secondes
        await asyncio.sleep(10)
        await supprimer_message(warning)

    # Nettoyage
    del media_groups[group_id]
    del timers[group_id]

async def handle_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    group_id = message.media_group_id
    prenom = update.message.from_user.first_name

    if not group_id:
        return

    media_groups[group_id].append(message)

    # Si c'est le premier message du groupe, on lance un timer
    if group_id not in timers:
        timers[group_id] = asyncio.create_task(process_media_group(group_id, context, prenom))

async def post_init(application):
    """Fonction exécutée après l'initialisation de l'application"""
    asyncio.create_task(envoyer_rappel_lundi_jeudi(application))
    asyncio.create_task(envoyer_rappel_mardi_vendredi_dimanche(application))
    asyncio.create_task(envoyer_pub_entreprise(application)) 
    logger.info("✅ Planificateur de messages périodiques démarré")

#   Commandes admins
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la commande /ban pour les administrateurs"""
    
    # NOUVELLE VÉRIFICATION : S'assurer qu'on a bien un message
    if not update.message:
        logger.warning("Commande /ban appelée sans message (probablement un événement chat_member)")
        return
    
    user = update.effective_user
    chat = update.effective_chat
    
    # Vérifier si c'est dans un groupe
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("❌ Cette commande ne peut être utilisée que dans un groupe.")
        return
    
    # Vérifier si l'utilisateur est admin
    if not await is_user_admin(context, chat.id, user.id):
        await update.message.reply_text("❌ Vous n'avez pas les permissions d'administrateur.")
        await asyncio.sleep(5)
        await supprimer_message(update.message)
        return
    
    # DIAGNOSTIC DÉTAILLÉ
    logger.info(f"=== DIAGNOSTIC BAN COMMAND ===")
    logger.info(f"Message ID: {update.message.message_id}")
    logger.info(f"Chat ID: {chat.id}")
    logger.info(f"User ID: {user.id}")
    logger.info(f"Message text: {update.message.text}")
    logger.info(f"Reply to message: {update.message.reply_to_message}")
    logger.info(f"Update object type: {type(update)}")
    logger.info(f"Message object: {update.message}")
    
    # Vérifier si c'est une réponse à un message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ **Comment utiliser la commande /ban :**\n\n"
            "1️⃣ Répondez au message de l'utilisateur à bannir\n"
            "2️⃣ Tapez `/ban [durée] [motif]`\n\n"
            "📝 **Exemples :**\n"
            "• `/ban 1h spam` (ban 1 heure)\n"
            "• `/ban 7d violation des règles` (ban 7 jours)\n"
            "• `/ban permanent trolling` (ban définitif)\n\n"
            "⏱️ **Durées acceptées :** 30m, 2h, 7d, permanent",
            parse_mode=ParseMode.MARKDOWN
        )
        await asyncio.sleep(10)
        await supprimer_message(update.message)
        return
    
    target_user = update.message.reply_to_message.from_user
    
    # Empêcher de se bannir soi-même
    if target_user.id == user.id:
        await update.message.reply_text("❌ Vous ne pouvez pas vous bannir vous-même.")
        await asyncio.sleep(5)
        await supprimer_message(update.message)
        return
    
    # Vérifier si la cible n'est pas un admin
    if await is_user_admin(context, chat.id, target_user.id):
        await update.message.reply_text("❌ Vous ne pouvez pas bannir un autre administrateur.")
        await asyncio.sleep(5)
        await supprimer_message(update.message)
        return
    
    # Parser les arguments
    args = context.args
    duration_str = args[0] if args else "permanent"
    motif = " ".join(args[1:]) if len(args) > 1 else "Aucun motif spécifié"
    
    # Parser la durée
    duration = parse_duration(duration_str)
    if duration is False:
        await update.message.reply_text(
            "❌ Format de durée invalide. Utilisez: 30m, 2h, 7d ou 'permanent'\n"
            "Exemple: `/ban 1h Spam` ou `/ban permanent Violation des règles`"
        )
        await asyncio.sleep(10)
        await supprimer_message(update.message)
        return
    
    # Calculer la date de fin si ce n'est pas permanent
    timezone_egypt = pytz.timezone('Africa/Cairo')
    until_date = datetime.now(timezone_egypt) + duration if duration else None
    
    # Variables pour le rapport
    ban_success = False
    ban_error = None
    
    try:
        # Bannir l'utilisateur
        if until_date:
            await context.bot.ban_chat_member(
                chat_id=chat.id,
                user_id=target_user.id,
                until_date=until_date
            )
        else:
            await context.bot.ban_chat_member(
                chat_id=chat.id,
                user_id=target_user.id
            )
        
        ban_success = True
        logger.info(f"✅ {target_user.first_name} banni par {user.first_name} - Motif: {motif}")
        
    except BadRequest as e:
        ban_error = e
        # Log mais continue le traitement pour informer
        if "user_not_participant" in str(e).lower():
            logger.warning(f"⚠️ {target_user.first_name} déjà absent du groupe - tentative de bannissement préventif")
            # Essayer un bannissement préventif
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=target_user.id)
                ban_success = True
                logger.info("✅ Bannissement préventif réussi")
            except:
                logger.error("❌ Bannissement préventif échoué")
        else:
            logger.error(f"❌ Erreur ban: {e}")
    
    except Exception as e:
        ban_error = e
        logger.error(f"❌ Erreur inattendue lors du ban: {e}")
    
    # TOUJOURS envoyer les messages informatifs, même si le ban a échoué
    ban_type = format_duration(duration)
    
    # Message de confirmation dans le groupe
    if ban_success:
        confirmation_msg = (
            f"🔨 Utilisateur banni\n\n"
            f"⏱️ Durée: {ban_type}\n"
            f"📋 Motif: {motif}\n"
            f"👮‍♂️ Par: {user.first_name}"
        )
        status_icon = "✅"
    else:
        if ban_error and "user_not_participant" in str(ban_error).lower():
            confirmation_msg = (
                f"⚠️ Tentative de bannissement\n\n"
                f"📊 Statut: Utilisateur déjà absent du groupe\n"
                f"⏱️ Durée prévue: {ban_type}\n"
                f"📋 Motif: {motif}\n"
                f"👮‍♂️ Par: {user.first_name}\n\n"
                f"💡 L'utilisateur ne peut plus envoyer de messages"
            )
        else:
            confirmation_msg = (
                f"❌ Échec du bannissement\n\n"
                f"👤 Utilisateur: {target_user.first_name}\n"
                f"📋 Motif: {motif}\n"
                f"👮‍♂️ Par: {user.first_name}\n\n"
                f"⚠️ Erreur: {ban_error}"
            )
    
    # Envoyer le message de confirmation dans le groupe
    try:
        # Test simple d'abord
        simple_msg = f"✅ un membre a été traité par {user.first_name}"
        group_message = await update.message.reply_text(simple_msg)
        logger.info(f"✅ Message simple envoyé dans le groupe (ID: {group_message.message_id})")
        
        # Puis le message détaillé
        await asyncio.sleep(1)  # Petit délai
        group_message2 = await update.message.reply_text(confirmation_msg)
        logger.info(f"✅ Message détaillé envoyé dans le groupe (ID: {group_message2.message_id})")
        
    except Exception as e:
        logger.error(f"❌ Erreur envoi confirmation groupe: {e}")
        # Essayer sans markdown en cas de problème de formatage
        try:
            await update.message.reply_text(f"Test: Ban effectué pour {target_user.first_name}")
            logger.info("✅ Message de test envoyé sans formatage")
        except Exception as e2:
            logger.error(f"❌ Erreur envoi test: {e2}")
    
    # Envoyer un message privé à l'utilisateur (même si le ban a échoué)
    try:
        if ban_success:
            private_message = (
                f"🚫 **Vous avez été banni du groupe {chat.title}**\n\n"
                f"⏱️ **Durée:** {ban_type}\n"
                f"📋 **Motif:** {motif}\n\n"
            )
            
            if duration:
                end_time = until_date.strftime("%d/%m/%Y à %H:%M")
                private_message += f"🕒 **Fin du ban:** {end_time}\n\n"
            
            private_message += "ℹ️ Si vous pensez que ce bannissement est injustifié, contactez les administrateurs."
        else:
            private_message = (
                f"⚠️ **Information du groupe {chat.title}**\n\n"
                f"Un administrateur ({user.first_name}) a tenté de vous bannir.\n"
                f"📋 **Motif:** {motif}\n\n"
                f"💡 Vous n'étiez déjà plus membre du groupe."
            )
        
        await context.bot.send_message(
            chat_id=target_user.id,
            text=private_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"✅ Message privé envoyé à {target_user.first_name}")
        
    except (BadRequest, Forbidden) as e:
        logger.warning(f"❌ Impossible d'envoyer un message privé à {target_user.first_name}: {e}")
        await update.message.reply_text(
            "⚠️ L'utilisateur n'a pas pu être notifié en privé (bot bloqué ou paramètres de confidentialité)."
        )
    
    # Supprimer le message de commande après un délai
    await asyncio.sleep(10)
    await supprimer_message(update.message)


if __name__ == '__main__':
    setup_signal_handlers()
    logger.info("=== Démarrage de l'application R2D2 ===")

    # Configure d'abord le bot
    setup_telegram_bot()
    
    # Puis démarre le bot
    bot_thread = start_telegram_bot_thread()

    # Flask
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Démarrage du serveur Flask sur le port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
else:
    setup_signal_handlers()
    logger.info("=== Démarrage en mode production ===")

    # Configure et démarre aussi en prod
    setup_telegram_bot()
    bot_thread = start_telegram_bot_thread()



