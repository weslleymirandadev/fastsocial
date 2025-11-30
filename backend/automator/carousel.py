import requests
import logging
import datetime
import random
from collections import defaultdict
from typing import List, Dict, Any, Optional
from .client import InstagramClient
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CarouselAutomator:
    def __init__(self, rest_days: int = 2, wait_min_seconds: int = 5, wait_max_seconds: int = 15):
        self.db_url = settings.DATABASE_API_URL.rstrip("/")
        self.rest_days = rest_days
        self.wait_min_seconds = wait_min_seconds
        self.wait_max_seconds = wait_max_seconds
        self.automation_run_id: Optional[int] = None

    def _get_restaurants(self) -> List[Dict[Any, Any]]:
        resp = requests.get(f"{self.db_url}/restaurants/")
        resp.raise_for_status()
        return resp.json()

    def _get_personas(self) -> List[Dict[Any, Any]]:
        resp = requests.get(f"{self.db_url}/personas/")
        resp.raise_for_status()
        return resp.json()

    def _get_phrases(self, persona_id: int) -> List[Dict[Any, Any]]:
        # Phrases are independent in the database API; fetch global list
        resp = requests.get(f"{self.db_url}/phrases/")
        resp.raise_for_status()
        return sorted(resp.json(), key=lambda x: x.get("order", 0))

    def _get_last_message(self, restaurant_id: int) -> Optional[Dict[str, Any]]:
        resp = requests.get(f"{self.db_url}/last-message/{restaurant_id}")
        if resp.status_code == 200 and resp.json():
            return resp.json()
        return None

    def _log_message(self, restaurant_id: int, persona_id: int, phrase_id: int, success: bool):
        payload = {
            "restaurant_id": restaurant_id,
            "persona_id": persona_id,
            "phrase_id": phrase_id,
            "success": success,
        }
        if self.automation_run_id is not None:
            payload["automation_run_id"] = self.automation_run_id

        requests.post(f"{self.db_url}/log/", json=payload)

    def _get_next_phrase(self, phrases: List[Dict], last_phrase_id: Optional[int]) -> Dict:
        """Seleciona aleatoriamente uma frase garantindo diversidade.

        - Se não houver histórico, sorteia qualquer frase.
        - Se houver, sorteia até cair em uma frase com id diferente da última,
          com proteção para o caso de só existir 1 frase.
        """
        if not phrases:
            raise ValueError("Lista de frases vazia")

        if last_phrase_id is None or len(phrases) == 1:
            return random.choice(phrases)

        # Tenta algumas vezes evitar repetir a última frase
        for _ in range(10):
            candidate = random.choice(phrases)
            if candidate.get("id") != last_phrase_id:
                return candidate

        # Fallback: se não conseguir (ids estranhos), retorna qualquer uma
        return random.choice(phrases)

    def run(self):
        logger.info("Iniciando automação com carrossel...")

        # Registra início de um ciclo de automação no banco
        try:
            resp = requests.post(f"{self.db_url}/runs/")
            if resp.status_code == 201:
                data = resp.json() or {}
                self.automation_run_id = data.get("id")
                logger.info(f"Automation run iniciada: id={self.automation_run_id}")
        except Exception as e:
            logger.warning(f"Falha ao registrar início da automation run: {e}")

        restaurants = self._get_restaurants()
        personas = self._get_personas()

        if not restaurants:
            logger.warning("Nenhum restaurante encontrado.")
            return
        if not personas:
            logger.error("Nenhuma persona configurada! Abortando.")
            return

        # Agrupa restaurantes por bloco
        blocks = defaultdict(list)
        for restaurant in restaurants:
            block_num = restaurant.get("bloco")
            if block_num is None:
                logger.warning(f"Restaurante {restaurant['name']} sem bloco → ignorado")
                continue
            blocks[block_num].append(restaurant)

        if not blocks:
            logger.error("Nenhum bloco válido encontrado.")
            return

        # Ordena os blocos para processamento sequencial
        sorted_blocks = sorted(blocks.items())  # (bloco, lista_restaurantes)

        logger.info(f"Encontrados {len(sorted_blocks)} blocos para processar.")

        for block_number, block_restaurants in sorted_blocks:
            # Base do carrossel de personas: bloco 1 → persona 1, bloco 2 → persona 2, etc.
            base_persona_index = (block_number - 1) % len(personas)

            logger.info(
                f"Processando Bloco {block_number} → persona base index={base_persona_index} "
                f"→ {len(block_restaurants)} restaurantes"
            )

            # Frases são globais; carregamos uma vez por bloco
            phrases = self._get_phrases(persona_id=0)  # persona_id é ignorado na implementação atual
            if not phrases:
                logger.error("Nenhuma frase configurada! Pulando bloco.")
                continue

            for restaurant in block_restaurants:
                rest_id = restaurant["id"]
                rest_username = restaurant["instagram_username"]

                # Consulta último envio para decidir descanso e rotação de persona/frase
                last_msg = self._get_last_message(rest_id)

                # Escolha da persona respeitando descanso e evitando repetição imediata
                persona_index = base_persona_index
                if last_msg:
                    # Se a última persona foi justamente a persona base, pula para a próxima
                    last_persona_id = last_msg.get("persona_id")
                    if last_persona_id is not None and last_persona_id == personas[persona_index]["id"]:
                        persona_index = (persona_index + 1) % len(personas)

                persona = personas[persona_index]

                # Verifica descanso em dias para este restaurante
                if last_msg and last_msg.get("sent_at"):
                    last_sent = datetime.fromisoformat(last_msg["sent_at"].replace("Z", "+00:00"))
                    days_since = (datetime.utcnow() - last_sent.utcfromtimestamp(last_sent.timestamp())).days
                    if days_since < self.rest_days:
                        logger.info(
                            f"@{rest_username} | Último envio há {days_since} dia(s) → em descanso ({self.rest_days} dias). Pulando."
                        )
                        continue

                # Cliente do Instagram configurado com intervalo de espera configurável
                client = InstagramClient(
                    username=persona["instagram_username"],
                    password=persona["instagram_password"],
                    wait_min_seconds=self.wait_min_seconds,
                    wait_max_seconds=self.wait_max_seconds,
                )

                # Seleciona próxima frase garantindo que não repete imediatamente
                last_phrase_id = last_msg.get("phrase_id") if last_msg else None
                next_phrase = self._get_next_phrase(phrases, last_phrase_id)

                success = client.send_dm(rest_username, next_phrase["text"])

                # Envia imediatamente o resultado para a database-api, que
                # então irá persistir e broadcastar o evento via websocket.
                try:
                    payload = {
                        "restaurant_id": rest_id,
                        "persona_id": persona["id"],
                        "phrase_id": next_phrase["id"],
                        "success": bool(success),
                    }
                    if self.automation_run_id is not None:
                        payload["automation_run_id"] = self.automation_run_id
                    # best-effort, não lançar em caso de falha de rede
                    requests.post(f"{self.db_url}/log/", json=payload, timeout=3)
                except Exception as e:
                    logger.debug(f"Falha ao notificar database-api sobre log: {e}")

                if not success:
                    logger.warning(f"Falha ao enviar para @{rest_username}")

                self._log_message(rest_id, persona["id"], next_phrase["id"], success)

            logger.info(f"Bloco {block_number} concluído!\n")

        logger.info("Automação finalizada com sucesso!")

        # Registra fim do ciclo de automação
        if self.automation_run_id is not None:
            try:
                requests.post(f"{self.db_url}/runs/{self.automation_run_id}/finish")
            except Exception as e:
                logger.warning(f"Falha ao registrar fim da automation run {self.automation_run_id}: {e}")