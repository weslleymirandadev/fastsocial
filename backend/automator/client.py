from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    LoginRequired,
    FeedbackRequired,
    PleaseWaitFewMinutes,
)
import time
import logging
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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