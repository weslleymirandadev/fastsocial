import logging
import time
import requests
from datetime import datetime
from typing import List, Dict, Set, Optional
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, ChallengeRequired
try:
    from .models import Message, InboxCheckResult
    from .email_sender import EmailSender
    from .config import settings
except ImportError:
    # Para execução direta
    from models import Message, InboxCheckResult
    from email_sender import EmailSender
    from config import settings

logger = logging.getLogger(__name__)


class InboxMonitor:
    def __init__(self, check_interval: int = 60):
        self.db_url = settings.DATABASE_API_URL.rstrip("/")
        self.check_interval = check_interval
        self.email_sender = EmailSender()
        self.clients: Dict[int, Client] = {}  # persona_id -> Client
        self.running = False
        
    def _get_personas(self) -> List[Dict]:
        """Busca todas as personas da database-api."""
        try:
            resp = requests.get(f"{self.db_url}/personas/", timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Erro ao buscar personas da database-api: {e}")
            return []
    
    def _get_processed_item_ids(self, persona_id: int) -> Set[str]:
        """Busca os item_ids já processados para uma persona."""
        try:
            resp = requests.get(
                f"{self.db_url}/inbox-messages/persona/{persona_id}/last-checked",
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            return set(data.get("item_ids", []))
        except Exception as e:
            logger.warning(f"Erro ao buscar item_ids processados para persona {persona_id}: {e}")
            return set()
    
    def _save_message(self, persona_id: int, message: Message) -> bool:
        """Salva uma mensagem na database-api."""
        try:
            payload = {
                "persona_id": persona_id,
                "thread_id": message.thread_id,
                "item_id": message.item_id,
                "sender_user_id": message.user_id,
                "sender_username": message.username,
                "message_text": message.text,
                "received_at": message.timestamp.isoformat(),
                "email_sent": False
            }
            resp = requests.post(
                f"{self.db_url}/inbox-messages/",
                json=payload,
                timeout=10
            )
            resp.raise_for_status()
            result = resp.json()
            return result.get("created", False)  # Retorna True se foi criada (nova), False se já existia
        except Exception as e:
            logger.error(f"Erro ao salvar mensagem na database-api: {e}")
            return False
    
    def _mark_email_sent(self, item_id: str):
        """Marca uma mensagem como email enviado (atualiza na database-api)."""
        # Por enquanto, não implementamos isso, mas podemos adicionar depois
        pass
        
    def _login_account(self, persona: Dict) -> Optional[Client]:
        """Faz login na conta do Instagram usando dados da persona."""
        try:
            client = Client()
            username = persona["instagram_username"]
            password = persona["instagram_password"]
            client.login(username, password)
            logger.info(f"Login realizado com sucesso para persona @{username} (ID: {persona['id']})")
            return client
        except LoginRequired:
            logger.error(f"Erro de login para persona @{persona.get('instagram_username')}: Credenciais inválidas")
            return None
        except PleaseWaitFewMinutes as e:
            logger.error(f"Erro de login para persona @{persona.get('instagram_username')}: {e}")
            return None
        except ChallengeRequired:
            logger.error(f"Erro de login para persona @{persona.get('instagram_username')}: Challenge necessário (2FA ou verificação)")
            return None
        except Exception as e:
            logger.error(f"Erro inesperado ao fazer login para persona @{persona.get('instagram_username')}: {e}")
            return None
    
    def _get_inbox_messages(self, client: Client, account_username: str) -> List[Message]:
        """Obtém todas as mensagens do inbox."""
        try:
            threads = client.direct_threads(amount=20)
            messages = []
            
            for thread in threads:
                thread_id = str(thread.id)
                
                # Obtém informações do usuário da conversa
                user_id = str(thread.user_id) if hasattr(thread, 'user_id') else "unknown"
                username = "unknown"
                
                # Tenta obter o username do thread
                if hasattr(thread, 'users') and thread.users:
                    username = thread.users[0].username if isinstance(thread.users, list) else getattr(thread.users, 'username', 'unknown')
                elif hasattr(thread, 'username'):
                    username = thread.username
                elif hasattr(thread, 'thread_title'):
                    username = thread.thread_title
                
                # Obtém as mensagens da thread
                try:
                    thread_messages = client.direct_messages(thread_id=thread_id, amount=20)
                    
                    for msg in thread_messages:
                        item_id = None
                        text = ''
                        timestamp = datetime.now()
                        
                        # Tenta obter item_id de diferentes formas
                        if hasattr(msg, 'item_id'):
                            item_id = str(msg.item_id)
                        elif hasattr(msg, 'id'):
                            item_id = str(msg.id)
                        elif hasattr(msg, 'pk'):
                            item_id = str(msg.pk)
                        
                        if not item_id:
                            continue
                        
                        # Obtém o texto da mensagem
                        if hasattr(msg, 'text'):
                            text = msg.text or ''
                        elif hasattr(msg, 'message'):
                            text = msg.message or ''
                        
                        # Obtém o timestamp
                        if hasattr(msg, 'timestamp'):
                            ts = msg.timestamp
                            if isinstance(ts, (int, float)):
                                timestamp = datetime.fromtimestamp(ts)
                            elif isinstance(ts, datetime):
                                timestamp = ts
                        elif hasattr(msg, 'created_at'):
                            ts = msg.created_at
                            if isinstance(ts, (int, float)):
                                timestamp = datetime.fromtimestamp(ts)
                            elif isinstance(ts, datetime):
                                timestamp = ts
                        
                        message = Message(
                            thread_id=thread_id,
                            user_id=user_id,
                            username=username,
                            text=text,
                            timestamp=timestamp,
                            item_id=item_id
                        )
                        messages.append(message)
                except Exception as e:
                    logger.warning(f"Erro ao obter mensagens da thread {thread_id}: {e}")
                    continue
            
            return messages
            
        except Exception as e:
            logger.error(f"Erro ao obter mensagens do inbox para @{account_username}: {e}")
            return []
    
    def _get_new_messages(self, persona_id: int, all_messages: List[Message]) -> List[Message]:
        """Filtra apenas as mensagens novas (que ainda não foram processadas na database-api)."""
        processed_ids = self._get_processed_item_ids(persona_id)
        new_messages = [msg for msg in all_messages if msg.item_id not in processed_ids]
        return new_messages
    
    def check_persona(self, persona: Dict) -> InboxCheckResult:
        """Verifica o inbox de uma persona específica."""
        persona_id = persona["id"]
        username = persona["instagram_username"]
        
        try:
            # Faz login se necessário
            if persona_id not in self.clients:
                client = self._login_account(persona)
                if not client:
                    return InboxCheckResult(
                        persona_id=persona_id,
                        account_username=username,
                        new_messages=[],
                        check_time=datetime.now(),
                        success=False,
                        error="Falha no login"
                    )
                self.clients[persona_id] = client
            else:
                client = self.clients[persona_id]
            
            # Obtém todas as mensagens
            all_messages = self._get_inbox_messages(client, username)
            
            # Filtra apenas as novas
            new_messages = self._get_new_messages(persona_id, all_messages)
            
            # Salva novas mensagens na database-api e envia email
            saved_count = 0
            for msg in new_messages:
                if self._save_message(persona_id, msg):
                    saved_count += 1
            
            # Envia email se houver novas mensagens
            if new_messages:
                logger.info(f"Persona @{username} (ID: {persona_id}): {len(new_messages)} nova(s) mensagem(ns) detectada(s), {saved_count} salva(s)")
                self.email_sender.send_notification(username, new_messages)
            
            return InboxCheckResult(
                persona_id=persona_id,
                account_username=username,
                new_messages=new_messages,
                check_time=datetime.now(),
                success=True
            )
            
        except Exception as e:
            logger.error(f"Erro ao verificar persona @{username} (ID: {persona_id}): {e}")
            # Tenta fazer login novamente na próxima vez
            if persona_id in self.clients:
                del self.clients[persona_id]
            
            return InboxCheckResult(
                persona_id=persona_id,
                account_username=username,
                new_messages=[],
                check_time=datetime.now(),
                success=False,
                error=str(e)
            )
    
    def check_all_personas(self) -> List[InboxCheckResult]:
        """Verifica o inbox de todas as personas."""
        personas = self._get_personas()
        results = []
        
        for persona in personas:
            result = self.check_persona(persona)
            results.append(result)
            # Pequeno delay entre contas para evitar rate limiting
            time.sleep(2)
        
        return results
    
    def start_monitoring(self):
        """Inicia o loop de monitoramento."""
        self.running = True
        logger.info("Iniciando monitoramento de inbox das personas")
        
        while self.running:
            try:
                results = self.check_all_personas()
                
                # Log resumo
                total_new = sum(len(r.new_messages) for r in results)
                successful = sum(1 for r in results if r.success)
                logger.info(f"Verificação concluída: {successful}/{len(results)} personas OK, {total_new} nova(s) mensagem(ns)")
                
            except Exception as e:
                logger.error(f"Erro no loop de monitoramento: {e}")
            
            # Aguarda antes da próxima verificação
            if self.running:
                time.sleep(self.check_interval)
    
    def stop_monitoring(self):
        """Para o monitoramento."""
        self.running = False
        logger.info("Monitoramento parado")
        
        # Fecha conexões
        for persona_id, client in self.clients.items():
            try:
                client.logout()
            except:
                pass
        self.clients.clear()
