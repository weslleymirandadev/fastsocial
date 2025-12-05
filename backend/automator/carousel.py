import requests
import logging
from datetime import datetime, timezone, timedelta
import random
import time
from collections import defaultdict
from typing import List, Dict, Any, Optional
from .client import InstagramClient
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
BRT = timezone(timedelta(hours=-3))


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
        # Emit an event to the frontend websocket hub with stats and related objects
        stats = {
            "total": 1,  # This will be incremented by the database API
            "success": 1 if success else 0,
            "fail": 0 if success else 1
        }

        # Try to get restaurant details
        restaurant = {}
        try:
            r = requests.get(f"{self.db_url}/restaurants/{restaurant_id}", timeout=3)
            if r.status_code == 200:
                restaurant = r.json()
        except Exception as e:
            logger.debug(f"Failed to fetch restaurant {restaurant_id}: {e}")

        # Try to get persona details
        persona = {}
        try:
            p = requests.get(f"{self.db_url}/personas/{persona_id}", timeout=3)
            if p.status_code == 200:
                persona = p.json()
        except Exception as e:
            logger.debug(f"Failed to fetch persona {persona_id}: {e}")

        # Try to get phrase details
        phrase = {}
        try:
            ph = requests.get(f"{self.db_url}/phrases/{phrase_id}", timeout=3)
            if ph.status_code == 200:
                phrase = ph.json()
        except Exception as e:
            logger.debug(f"Failed to fetch phrase {phrase_id}: {e}")

        # Create the event with all collected information
        event = {
            "type": "dm_log",
            "success": bool(success),
            "sent_at": datetime.now(BRT).isoformat(),
            "automation_run_id": self.automation_run_id,
            "stats": stats,
            "restaurant": restaurant or {"id": restaurant_id},
            "persona": persona or {"id": persona_id},
            "phrase": phrase or {"id": phrase_id},
        }

        try:
            # Send event to the database API
            response = requests.post(
                f"{self.db_url}/automation/emit",
                json=event,
                timeout=3
            )
            if response.status_code != 200:
                logger.error(f"Failed to emit event: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Failed to send event to WebSocket hub: {e}")

    def _get_next_phrase(self, phrases: List[Dict], last_phrase_id: Optional[int]) -> Dict:
        """Seleciona aleatoriamente uma frase garantindo diversidade.

        TODO: refazer essa lógica
            Na primeira vez, envia sequencialmente as mensagens de 1 até a 200
            Checar também a ultima mensagem enviada para o restaurante:
                - se for a mesma escolhida, muda para a próxima

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

    def _update_follow_status(
        self,
        restaurant_id: int,
        persona_id: int,
        restaurant_follows_persona: Optional[bool] = None,
        persona_follows_restaurant: Optional[bool] = None,
    ) -> None:
        """Envia o status de follow atual para o database-api.

        Best-effort: erros aqui não devem quebrar a automação.
        """
        payload: Dict[str, Any] = {
            "restaurant_id": restaurant_id,
            "persona_id": persona_id,
        }
        if restaurant_follows_persona is not None:
            payload["restaurant_follows_persona"] = bool(restaurant_follows_persona)
        if persona_follows_restaurant is not None:
            payload["persona_follows_restaurant"] = bool(persona_follows_restaurant)

        try:
            requests.post(f"{self.db_url}/follow-status/", json=payload, timeout=5)
        except Exception as e:
            logger.debug(f"Falha ao atualizar follow-status no database-api: {e}")

    def _ensure_mutual_follow(
        self,
        client: InstagramClient,
        restaurant: Dict[str, Any],
        persona: Dict[str, Any],
    ) -> bool:
        """Garante a lógica de follow antes do envio da mensagem.

        - Checa se persona segue o restaurante e se o restaurante segue a persona.
        - Se ainda não houver follow, envia follow da persona -> restaurante.
        - Atualiza o banco com o status atual.
        - Retorna True somente quando ambos se seguem.
        """
        rest_username = restaurant.get("instagram_username")
        if not rest_username:
            logger.warning("Restaurante sem instagram_username, não é possível checar follow.")
            return False

        try:
            persona_follows, restaurant_follows = client.check_mutual_follow(rest_username)
        except Exception as e:
            logger.error(f"Erro ao checar follow entre persona={persona.get('instagram_username')} e restaurante={rest_username}: {e}")
            return False

        # Atualiza status inicial observado
        self._update_follow_status(
            restaurant_id=restaurant["id"],
            persona_id=persona["id"],
            restaurant_follows_persona=restaurant_follows,
            persona_follows_restaurant=persona_follows,
        )

        # Se ainda não seguimos o restaurante, envia follow e permanece em standby
        if not persona_follows:
            followed = client.follow(rest_username)
            if followed:
                persona_follows = True
                self._update_follow_status(
                    restaurant_id=restaurant["id"],
                    persona_id=persona["id"],
                    persona_follows_restaurant=True,
                )

        # Somente se houver follow mútuo liberamos o envio de mensagem
        if persona_follows and restaurant_follows:
            return True

        logger.info(
            f"Follow ainda não é mútuo entre persona=@{persona.get('instagram_username')} "
            f"e restaurante=@{rest_username} → standby, sem enviar mensagem agora."
        )
        return False

    def _send_multipart_dm(
        self,
        client: InstagramClient,
        username: str,
        text: str,
        start_index: int = 0,
    ) -> (bool, Optional[int]):
        parts = [p.strip() for p in text.split(";") if p.strip()]

        if not parts:
            return False, None

        overall_success = True
        failed_index: int | None = None

        for idx in range(start_index, len(parts)):
            part = parts[idx]
            part_success = client.send_dm(username, part)
            if not part_success:
                overall_success = False
                failed_index = idx
                break
            time.sleep(random.randint(5, 10))

        return overall_success, failed_index

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

                # Verifica descanso em dias para este restaurante (horário de Brasília)
                if last_msg and last_msg.get("sent_at"):
                    raw_sent_at = last_msg["sent_at"]
                    try:
                        if raw_sent_at.endswith("Z"):
                            last_sent = datetime.fromisoformat(raw_sent_at.replace("Z", "+00:00")).astimezone(BRT)
                        else:
                            last_sent = datetime.fromisoformat(raw_sent_at)
                            if last_sent.tzinfo is None:
                                last_sent = last_sent.replace(tzinfo=BRT)
                            else:
                                last_sent = last_sent.astimezone(BRT)

                        now_brt = datetime.now(BRT)
                        days_since = (now_brt.date() - last_sent.date()).days
                    except Exception as e:
                        logger.warning(
                            f"@{rest_username} | Erro ao interpretar sent_at='{raw_sent_at}' ({e}) → tratando como em descanso. Pulando."
                        )
                        continue

                    if days_since < self.rest_days:
                        logger.info(
                            f"@{rest_username} | Último envio há {days_since} dia(s) → em descanso ({self.rest_days} dias). Pulando."
                        )
                        continue

                # Escolha da persona respeitando descanso e evitando repetição imediata
                persona_index = base_persona_index
                if last_msg:
                    last_persona_id = last_msg.get("persona_id")
                    if last_persona_id is not None and last_persona_id == personas[persona_index]["id"]:
                        persona_index = (persona_index + 1) % len(personas)

                persona = personas[persona_index]

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

                # 1) Primeiro tenta enviar diretamente todas as partes da mensagem
                success, failed_index = self._send_multipart_dm(
                    client,
                    rest_username,
                    next_phrase["text"],
                    start_index=0,
                )

                # 2) Se alguma parte falhar, aplica lógica de follow mútuo e retenta
                if not success:
                    logger.warning(
                        f"Falha ao enviar para @{rest_username} na primeira tentativa, checando follow..."
                    )

                    if self._ensure_mutual_follow(client, restaurant, persona):
                        # Retoma a partir da parte que falhou, se conhecida
                        retry_start_index = failed_index if failed_index is not None else 0
                        success, _ = self._send_multipart_dm(
                            client,
                            rest_username,
                            next_phrase["text"],
                            start_index=retry_start_index,
                        )

                # Emite evento para frontend via websocket hub (database-api).
                # A emissão real é feita em `_log_message`, que tenta enriquecer o evento.

                if not success:
                    logger.warning(f"Falha ao enviar para @{rest_username} mesmo após checar follow")

                self._log_message(rest_id, persona["id"], next_phrase["id"], success)

            logger.info(f"Bloco {block_number} concluído!\n")

        logger.info("Automação finalizada com sucesso!")

        # Registra fim do ciclo de automação
        if self.automation_run_id is not None:
            try:
                requests.post(f"{self.db_url}/runs/{self.automation_run_id}/finish")
            except Exception as e:
                logger.warning(f"Falha ao registrar fim da automation run {self.automation_run_id}: {e}")