from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    LoginRequired,
    FeedbackRequired,
    PleaseWaitFewMinutes,
)

try:
    from ..logging_to_dbapi import DatabaseApiLogHandler
except Exception:
    try:
        from .logging_to_dbapi import DatabaseApiLogHandler
    except Exception:
        try:
            from automator.logging_to_dbapi import DatabaseApiLogHandler
        except Exception:
            from logging_to_dbapi import DatabaseApiLogHandler

import time
import logging
import random
import time
import logging
import random


# Configure a module logger
logger = logging.getLogger(__name__)

# Ensure logs pass through DatabaseApiLogHandler so they are forwarded to the database-api.
try:
    # Configure basic formatting if no handlers are present (useful when this module
    # is used standalone outside of the main app process).
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)

    # Attach the DatabaseApiLogHandler directly to this module logger so all
    # logs emitted here go through that handler.
    already = any(h.__class__.__name__ == "DatabaseApiLogHandler" for h in logger.handlers)
    if not already:
        db_handler = DatabaseApiLogHandler()
        db_handler.setLevel(logging.INFO)
        logger.addHandler(db_handler)
        # Prevent double-emitting: don't propagate to root once handled here
        logger.propagate = False
except Exception:
    # Best-effort: do not raise if logging handler cannot be attached
    pass


class InstagramClient:
    def __init__(
        self,
        username: str,
        password: str,
        wait_min_seconds: float = 5.0,
        wait_max_seconds: float = 15.0,
    ):
        self.username = username.strip().lower()
        self.password = password
        self.wait_min_seconds = wait_min_seconds
        self.wait_max_seconds = max(wait_max_seconds, wait_min_seconds)

        self.cl = Client()
        self.cl.delay_range = [1, 5]  # comportamento mais humano

        self._login()

    def _login(self) -> None:
        """Faz login e trata desafio se necessário"""
        try:
            self.cl.login(self.username, self.password)
            logger.info(f"Login bem-sucedido → @{self.username}")
        except ChallengeRequired:
            logger.warning(f"Desafio detectado para @{self.username}")
            try:
                # Tenta resolver automaticamente por e-mail/SMS
                self.cl.challenge_resolve(self.cl.last_json)
                logger.info(f"Desafio resolvido automaticamente para @{self.username}")
            except Exception as e:
                logger.error(f"Não foi possível resolver desafio para @{self.username}: {e}")
                raise
        except PleaseWaitFewMinutes:
            logger.error("Instagram pediu para esperar alguns minutos. Pausando...")
            time.sleep(300)
            self._login()
        except Exception as e:
            logger.error(f"Falha no login @{self.username}: {e}")
            raise

    def send_dm(self, username: str, message: str) -> bool:
        """
        Envia DM e retorna True/False
        """
        try:
            user_id = self.cl.user_id_from_username(username.strip().lower())
            self.cl.direct_send(message, user_ids=[user_id])
            logger.info(f"DM enviado → @{username} | {message[:50]}{'...' if len(message)>50 else ''}")
            delay = random.uniform(self.wait_min_seconds, self.wait_max_seconds)
            time.sleep(delay)  # respeito ao limite com jitter configurável

            return True
        except LoginRequired:
            logger.warning("Sessão expirada. Refazendo login...")
            self._login()
            return self.send_dm(username, message)
        except FeedbackRequired:
            logger.warning("FeedbackRequired - pulando este envio")
            time.sleep(60)
            return False
        except Exception as e:
            logger.error(f"Erro ao enviar DM para @{username}: {e}")
            return False

    def check_mutual_follow(self, other_username: str) -> tuple[bool, bool]:
        """Retorna (eu_sigo_ele, ele_me_segue) para o usuário alvo.

        Usa instagrapi.user_friendship para obter as flags de following/followed_by.
        """
        try:
            user_id = self.cl.user_id_from_username(other_username.strip().lower())
            friendship = self.cl.user_friendship(user_id)
            # following  -> logged-in user (persona) follows target (restaurante)
            # followed_by -> target (restaurante) follows logged-in user (persona)
            return bool(getattr(friendship, "following", False)), bool(
                getattr(friendship, "followed_by", False)
            )
        except Exception as e:
            logger.error(f"Erro ao checar relação de follow com @{other_username}: {e}")
            return False, False

    def follow(self, username: str) -> bool:
        """Segue o usuário indicado a partir da conta logada."""
        try:
            user_id = self.cl.user_id_from_username(username.strip().lower())
            self.cl.user_follow(user_id)
            logger.info(f"Follow enviado para @{username} a partir de @{self.username}")
            delay = random.uniform(self.wait_min_seconds, self.wait_max_seconds)
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"Erro ao seguir @{username}: {e}")
            return False