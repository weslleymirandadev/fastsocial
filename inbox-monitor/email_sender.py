import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List
from datetime import datetime
try:
    from .models import Message
    from .config import settings
except ImportError:
    # Para execução direta
    from models import Message
    from config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.email_from = settings.EMAIL_FROM or settings.SMTP_USER
        self.email_to = settings.EMAIL_TO
        
    def _create_message_body(self, account_username: str, messages: List[Message]) -> str:
        """Cria o corpo do email com as informações das mensagens."""
        body = f"""
<h2>Novas Mensagens no Instagram</h2>
<p><strong>Conta monitorada:</strong> @{account_username}</p>
<p><strong>Data/Hora:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
<p><strong>Total de novas mensagens:</strong> {len(messages)}</p>
<hr>
"""
        
        for msg in messages:
            body += f"""
<div style="margin-bottom: 20px; padding: 10px; border-left: 3px solid #007bff; background-color: #f8f9fa;">
    <p><strong>De:</strong> @{msg.username} (ID: {msg.user_id})</p>
    <p><strong>Para:</strong> @{account_username}</p>
    <p><strong>Data/Hora:</strong> {msg.timestamp.strftime('%d/%m/%Y %H:%M:%S')}</p>
    <p><strong>Mensagem:</strong></p>
    <p style="background-color: white; padding: 10px; border-radius: 5px;">{msg.text}</p>
    <p><small>Thread ID: {msg.thread_id} | Item ID: {msg.item_id}</small></p>
</div>
"""
        
        return body
    
    def send_notification(self, account_username: str, messages: List[Message]) -> bool:
        """Envia email de notificação sobre novas mensagens."""
        if not self.email_to:
            logger.warning("EMAIL_TO não configurado. Não é possível enviar email.")
            return False
            
        if not self.smtp_user or not self.smtp_password:
            logger.warning("Credenciais SMTP não configuradas. Não é possível enviar email.")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"Novas Mensagens Instagram - @{account_username}"
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            
            html_body = self._create_message_body(account_username, messages)
            msg.attach(MIMEText(html_body, 'html'))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email enviado com sucesso para {self.email_to} sobre {len(messages)} novas mensagens de @{account_username}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao enviar email: {e}")
            return False

