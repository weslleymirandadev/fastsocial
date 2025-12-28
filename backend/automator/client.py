import time
import logging
import random
import os
from pathlib import Path
from typing import Optional, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

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

# Configure a module logger
logger = logging.getLogger(__name__)

# Ensure logs pass through DatabaseApiLogHandler so they are forwarded to the database-api.
try:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)

    already = any(h.__class__.__name__ == "DatabaseApiLogHandler" for h in logger.handlers)
    if not already:
        db_handler = DatabaseApiLogHandler()
        db_handler.setLevel(logging.INFO)
        logger.addHandler(db_handler)
        logger.propagate = False
except Exception:
    pass


class LoginError(Exception):
    """Exceção lançada quando há erro de login (ex: senha incorreta)."""
    pass


class InstagramClient:
    def __init__(
        self,
        username: str,
        password: str,
        wait_min_seconds: float = 5.0,
        wait_max_seconds: float = 15.0,
        headless: bool = False,
    ):
        self.username = username.strip().lower().replace("@", "")
        self.password = password.strip()
        self.wait_min_seconds = wait_min_seconds
        self.wait_max_seconds = max(wait_max_seconds, wait_min_seconds)
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self._setup_driver()
        self._login()

    def _setup_driver(self) -> None:
        """Configura o driver Chrome com técnicas anti-detecção avançadas."""
        chrome_options = Options()
        
        # User agents mais recentes e realistas (Chrome 131+)
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        chrome_options.add_argument(f"--user-agent={user_agent}")
        
        # Configurações anti-detecção essenciais
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        # Remove flags que indicam automação
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--lang=pt-BR,pt")
        
        # Headers e comportamento de navegador real
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-popup-blocking")
                
        # Perfil persistente para manter sessão
        profile_dir = Path.home() / ".fastsocial_chrome_profiles" / self.username
        profile_dir.mkdir(parents=True, exist_ok=True)
        chrome_options.add_argument(f"--user-data-dir={profile_dir}")
        
        # Prefs para parecer mais humano e moderno
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.images": 1,  # Permite imagens
            "profile.default_content_setting_values.geolocation": 2,  # Bloqueia geolocalização
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            if not self.headless:
                self.driver.maximize_window()
            
            # Remove propriedades de automação e adiciona propriedades reais via JavaScript
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                        // Remove webdriver property
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                        
                        // Adiciona propriedades do Chrome
                        window.navigator.chrome = {
                            runtime: {},
                            loadTimes: function() {},
                            csi: function() {},
                            app: {}
                        };
                        
                        // Plugins realistas
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => {
                                return [
                                    {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                                    {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                                    {name: 'Native Client', filename: 'internal-nacl-plugin'}
                                ];
                            }
                        });
                        
                        // Languages
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['pt-BR', 'pt', 'en-US', 'en']
                        });
                        
                        // Permissions
                        const originalQuery = window.navigator.permissions.query;
                        window.navigator.permissions.query = (parameters) => (
                            parameters.name === 'notifications' ?
                                Promise.resolve({ state: Notification.permission }) :
                                originalQuery(parameters)
                        );
                        
                        // WebGL Vendor
                        const getParameter = WebGLRenderingContext.prototype.getParameter;
                        WebGLRenderingContext.prototype.getParameter = function(parameter) {
                            if (parameter === 37445) {
                                return 'Intel Inc.';
                            }
                            if (parameter === 37446) {
                                return 'Intel Iris OpenGL Engine';
                            }
                            return getParameter.call(this, parameter);
                        };
                        
                        // Canvas fingerprinting protection
                        const toBlob = HTMLCanvasElement.prototype.toBlob;
                        const toDataURL = HTMLCanvasElement.prototype.toDataURL;
                        const getImageData = CanvasRenderingContext2D.prototype.getImageData;
                        
                        // Override console.debug para evitar logs de automação
                        const originalDebug = console.debug;
                        console.debug = function() {};
                    """
                },
            )
            
            # Adiciona headers HTTP realistas
            self.driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                "userAgent": user_agent,
                "acceptLanguage": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "platform": "Win32"
            })
            
            logger.info(f"Driver Chrome configurado para @{self.username} (headless={self.headless}) com UA: {user_agent[:50]}...")
        except Exception as e:
            logger.error(f"Erro ao configurar driver: {e}")
            raise

    def _human_delay(self, min_seconds: Optional[float] = None, max_seconds: Optional[float] = None) -> None:
        """Aplica delay humano com variação aleatória."""
        min_delay = min_seconds if min_seconds is not None else self.wait_min_seconds
        max_delay = max_seconds if max_seconds is not None else self.wait_max_seconds
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _human_type(self, element, text: str, typing_speed: float = 0.05) -> None:
        """Digita texto de forma humana, caractere por caractere com variação.
        
        Cada letra tem um intervalo variável (milissegundos) para parecer mais humano.
        O intervalo base é em segundos, mas varia aleatoriamente para cada caractere.
        """
        for char in text:
            element.send_keys(char)
            # Variação mais realista: entre 30ms e 150ms por caractere (0.03 a 0.15 segundos)
            # Com alguns caracteres tendo pausas maiores (simulando hesitação)
            base_delay = typing_speed
            if random.random() < 0.1:  # 10% de chance de pausa maior (hesitação)
                delay = random.uniform(base_delay * 2, base_delay * 4)
            else:
                delay = random.uniform(base_delay * 0.6, base_delay * 1.8)
            time.sleep(delay)
        self._human_delay(0.3, 0.8)

    def _human_click(self, element) -> None:
        """Clica em elemento simulando movimento humano com arrasto lento do mouse."""
        try:
            # Obtém a localização e tamanho do elemento
            location = element.location
            size = element.size
            element_center_x = location['x'] + size['width'] // 2
            element_center_y = location['y'] + size['height'] // 2
            
            # Obtém o tamanho do viewport
            viewport_width = self.driver.execute_script("return window.innerWidth")
            viewport_height = self.driver.execute_script("return window.innerHeight")
            
            # Calcula uma posição inicial próxima ao elemento (mas não muito perto)
            distance_from_element = random.randint(80, 200)
            start_x = element_center_x + int(distance_from_element * random.uniform(-0.8, 0.8))
            start_y = element_center_y + int(distance_from_element * random.uniform(-0.8, 0.8))
            
            # Garante que está dentro do viewport
            start_x = max(50, min(start_x, viewport_width - 50))
            start_y = max(50, min(start_y, viewport_height - 50))
            
            # Calcula a distância total
            dx = element_center_x - start_x
            dy = element_center_y - start_y
            
            # Número de passos para movimento gradual (mais passos = mais lento)
            num_steps = random.randint(12, 18)
            
            actions = ActionChains(self.driver)
            
            # Move para uma posição inicial conhecida (canto superior esquerdo do viewport)
            # Isso reseta a referência para offsets relativos
            actions.move_by_offset(-viewport_width // 2, -viewport_height // 2)
            actions.pause(random.uniform(0.05, 0.1))
            
            # Move para a posição inicial calculada
            actions.move_by_offset(start_x, start_y)
            actions.pause(random.uniform(0.15, 0.25))
            
            # Move gradualmente em pequenos passos até o elemento
            prev_x, prev_y = start_x, start_y
            for i in range(num_steps):
                # Calcula o progresso (0 a 1)
                progress = (i + 1) / num_steps
                
                # Usa uma curva de easing para movimento mais natural
                # Easing out: começa rápido e termina devagar
                eased_progress = 1 - (1 - progress) ** 2
                
                # Calcula a posição atual na trajetória
                current_x = start_x + dx * eased_progress
                current_y = start_y + dy * eased_progress
                
                # Calcula o offset relativo ao passo anterior
                offset_x = current_x - prev_x
                offset_y = current_y - prev_y
                
                # Adiciona um pouco de variação aleatória para parecer mais humano
                noise_x = random.uniform(-1.5, 1.5)
                noise_y = random.uniform(-1.5, 1.5)
                
                # Move para a próxima posição (offset relativo)
                actions.move_by_offset(int(offset_x + noise_x), int(offset_y + noise_y))
                # Pausa entre movimentos (mais lento para simular arrasto)
                actions.pause(random.uniform(0.1, 0.18))
                
                prev_x, prev_y = current_x, current_y
            
            # Garante que está exatamente no elemento
            actions.move_to_element(element)
            actions.pause(random.uniform(0.15, 0.3))
            
            # Clica no elemento
            actions.click()
            actions.perform()
            self._human_delay(0.5, 1.0)
        except Exception as e:
            try:
                # Fallback: movimento mais simples mas ainda gradual
                actions = ActionChains(self.driver)
                # Move para o elemento com pausa maior para simular movimento lento
                actions.move_to_element(element)
                actions.pause(random.uniform(0.3, 0.6))
                actions.click()
                actions.perform()
                self._human_delay(0.5, 1.0)
            except Exception as e2:
                logger.warning(f"Erro no fallback, usando click direto: {e2}")
                element.click()
                self._human_delay(0.5, 1.0)

    def _random_mouse_movement(self) -> None:
        """Move o mouse aleatoriamente para parecer humano."""
        try:
            actions = ActionChains(self.driver)
            # Move para posição aleatória
            x_offset = random.randint(-100, 100)
            y_offset = random.randint(-100, 100)
            actions.move_by_offset(x_offset, y_offset)
            actions.pause(random.uniform(0.1, 0.3))
            actions.move_by_offset(-x_offset, -y_offset)
            actions.perform()
        except Exception:
            pass  # Ignora erros de movimento de mouse

    def _is_logged_in(self) -> bool:
        """Verifica se já está logado no Instagram.
        
        O Instagram na guia anônima não mostra "accounts/login" na URL, faz login diretamente em "/".
        A verificação é feita procurando pelo span "Mais" que só aparece quando logado.
        """
        try:
            # Navega para a página inicial do Instagram
            self.driver.get("https://www.instagram.com/")
            self._human_delay(2, 4)
            
            # Procura pelo span "Mais" que só aparece quando logado
            # Usa os mesmos seletores do método _logout para consistência
            mais_selectors = [
                "//span[normalize-space(text())='Mais']",
                "//span[normalize-space(text())='More']",
                "//span[contains(normalize-space(text()), 'Mais')]",
                "//span[contains(normalize-space(text()), 'More')]",
                "//span[contains(text(), 'Mais')]",
                "//span[contains(text(), 'More')]",
                "//span[text()='Mais']",
                "//span[text()='More']",
            ]
            
            for selector in mais_selectors:
                try:
                    mais_span = self.driver.find_element(By.XPATH, selector)
                    if mais_span.is_displayed():
                        logger.info(f"Span 'Mais' encontrado - usuário está logado (@{self.username})")
                        return True
                except NoSuchElementException:
                    continue
            
            # Se não encontrou o span "Mais", não está logado
            logger.debug("Span 'Mais' não encontrado - usuário não está logado")
            return False
                
        except Exception as e:
            logger.debug(f"Erro ao verificar se está logado: {e}")
            # Em caso de erro, assume que não está logado (mais seguro)
            return False

    def _logout(self) -> None:
        """Faz logout do Instagram clicando em 'Mais' e depois em 'Sair'."""
        try:
            logger.info(f"Fazendo logout para @{self.username}")
            
            # Navega para a página inicial se não estiver lá
            if "instagram.com" not in self.driver.current_url or "accounts/login" in self.driver.current_url:
                self.driver.get("https://www.instagram.com/")
                self._human_delay(2, 4)
            
            wait = WebDriverWait(self.driver, 10)
            
            # Procura pelo span "Mais" (menu de perfil)
            # Usa normalize-space() para ignorar espaços em branco e busca case-insensitive
            mais_selectors = [
                # XPath com normalize-space (ignora espaços extras)
                "//span[normalize-space(text())='Mais']",
                "//span[normalize-space(text())='More']",
                "//span[contains(normalize-space(text()), 'Mais')]",
                "//span[contains(normalize-space(text()), 'More')]",
                # XPath simples (fallback)
                "//span[contains(text(), 'Mais')]",
                "//span[contains(text(), 'More')]",
                "//span[text()='Mais']",
                "//span[text()='More']",
                # Busca usando classes CSS (baseado no DevTools)
                "//span[contains(@class, 'x1lliihq') and contains(text(), 'Mais')]",
                "//span[contains(@class, 'x193iq5w') and contains(text(), 'Mais')]",
                # Busca por qualquer span que contenha o texto
                "//span[translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='mais']",
                "//span[translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='more']",
            ]
            
            mais_span = None
            for selector in mais_selectors:
                try:
                    logger.debug(f"Tentando encontrar 'Mais' com seletor: {selector}")
                    mais_span = wait.until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    if mais_span and mais_span.is_displayed():
                        logger.info(f"Encontrado span 'Mais' usando seletor: {selector}")
                        # Aguarda um pouco para garantir que está clicável
                        mais_span = wait.until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        break
                except (TimeoutException, StaleElementReferenceException) as e:
                    logger.debug(f"Seletor '{selector}' não encontrou elemento: {e}")
                    continue
            
            if not mais_span:
                logger.info("Não encontrou 'Mais' diretamente. Tentando abrir menu de perfil primeiro...")
                # Tenta encontrar o botão de perfil/menu de outra forma
                profile_selectors = [
                    'a[href*="/accounts/edit/"]',
                    'a[href*="/"]',  # Link do perfil atual
                    'a[aria-label*="Profile" i]',
                    'a[aria-label*="Perfil" i]',
                    'svg[aria-label*="Profile" i]',
                    'img[alt*="profile picture" i]',
                    'img[alt*="foto do perfil" i]',
                    # Tenta encontrar avatar/perfil por classes comuns
                    'div[role="button"][tabindex="0"]',  # Botão de perfil
                ]
                
                profile_clicked = False
                for selector in profile_selectors:
                    try:
                        profile_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        if profile_element.is_displayed():
                            logger.info(f"Encontrado elemento de perfil, clicando: {selector}")
                            self._human_click(profile_element)
                            self._human_delay(2, 3)
                            profile_clicked = True
                            break
                    except (NoSuchElementException, ElementNotInteractableException):
                        continue
                
                # Tenta encontrar "Mais" novamente após clicar no perfil
                if profile_clicked:
                    self._human_delay(1, 2)
                    for selector in mais_selectors:
                        try:
                            mais_span = wait.until(
                                EC.presence_of_element_located((By.XPATH, selector))
                            )
                            if mais_span and mais_span.is_displayed():
                                mais_span = wait.until(
                                    EC.element_to_be_clickable((By.XPATH, selector))
                                )
                                logger.info("Encontrado 'Mais' após clicar no perfil")
                                break
                        except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                            continue
            
            if not mais_span:
                logger.warning("Não foi possível encontrar o botão 'Mais'. Tentando busca mais ampla...")
                # Tenta encontrar qualquer elemento que possa abrir o menu
                try:
                    # Procura por avatares ou ícones de perfil
                    avatar_selectors = [
                        'img[alt*="profile picture" i]',
                        'img[alt*="foto do perfil" i]',
                        'img[alt*="Profile" i]',
                        'img[alt*="Perfil" i]',
                    ]
                    
                    for avatar_selector in avatar_selectors:
                        try:
                            avatar = self.driver.find_element(By.CSS_SELECTOR, avatar_selector)
                            if avatar.is_displayed():
                                logger.info("Encontrado avatar, clicando...")
                                self._human_click(avatar)
                                self._human_delay(2, 3)
                                
                                # Tenta encontrar "Mais" novamente
                                for selector in mais_selectors:
                                    try:
                                        mais_span = wait.until(
                                            EC.presence_of_element_located((By.XPATH, selector))
                                        )
                                        if mais_span and mais_span.is_displayed():
                                            mais_span = wait.until(
                                                EC.element_to_be_clickable((By.XPATH, selector))
                                            )
                                            logger.info("Encontrado 'Mais' após clicar no avatar")
                                            break
                                    except (TimeoutException, NoSuchElementException, StaleElementReferenceException):
                                        continue
                                
                                if mais_span:
                                    break
                        except NoSuchElementException:
                            continue
                            
                except Exception as e:
                    logger.debug(f"Erro ao tentar encontrar avatar: {e}")
            
            if not mais_span:
                # Última tentativa: usa JavaScript para encontrar e clicar no elemento
                logger.info("Tentando encontrar e clicar em 'Mais' usando JavaScript...")
                try:
                    # Busca todos os spans e clica no que contém "Mais" ou "More"
                    clicked = self.driver.execute_script("""
                        var spans = document.querySelectorAll('span');
                        for (var i = 0; i < spans.length; i++) {
                            var text = spans[i].textContent || spans[i].innerText;
                            if (text) {
                                var normalized = text.trim().toLowerCase();
                                if (normalized === 'mais' || normalized === 'more') {
                                    spans[i].click();
                                    return true;
                                }
                            }
                        }
                        return false;
                    """)
                    
                    if clicked:
                        self._human_delay(1, 2)
                        logger.info("Encontrado e clicado em 'Mais' via JavaScript")
                        mais_span = True  # Marca como encontrado para continuar o fluxo
                    else:
                        logger.warning("Não foi possível encontrar 'Mais' mesmo com JavaScript")
                except Exception as e:
                    logger.debug(f"Erro ao buscar 'Mais' via JavaScript: {e}")
            
            if mais_span:
                # Se encontrou via XPath/CSS, clica normalmente
                # Se mais_span é True, já foi clicado via JavaScript
                if mais_span is not True:
                    try:
                        # Verifica se é um WebElement válido
                        if hasattr(mais_span, 'click'):
                            self._human_click(mais_span)
                            self._human_delay(1, 2)
                        else:
                            # Se foi encontrado via JS mas não é WebElement, tenta clicar via JS
                            self.driver.execute_script("arguments[0].click();", mais_span)
                            self._human_delay(1, 2)
                    except Exception as e:
                        logger.warning(f"Erro ao clicar em 'Mais': {e}. Tentando via JavaScript...")
                        try:
                            self.driver.execute_script("arguments[0].click();", mais_span)
                            self._human_delay(1, 2)
                        except Exception:
                            pass
            else:
                logger.warning("Não foi possível encontrar 'Mais'. Continuando com logout direto...")
            
            # Procura pelo span "Sair" (Log Out)
            sair_selectors = [
                "//span[contains(text(), 'Sair')]",
                "//span[contains(text(), 'Log Out')]",
                "//span[contains(text(), 'Log out')]",
                "//span[text()='Sair']",
                "//span[text()='Log Out']",
                "//span[text()='Log out']",
                "//div[contains(text(), 'Sair')]",
                "//div[contains(text(), 'Log Out')]",
            ]
            
            sair_span = None
            for selector in sair_selectors:
                try:
                    sair_span = wait.until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    if sair_span.is_displayed():
                        break
                except TimeoutException:
                    continue
            
            if not sair_span:
                # Tenta encontrar novamente após alguns segundos (menu pode estar animando)
                self._human_delay(1, 2)
                for selector in sair_selectors:
                    try:
                        sair_span = self.driver.find_element(By.XPATH, selector)
                        if sair_span.is_displayed():
                            break
                    except NoSuchElementException:
                        continue
            
            if sair_span:
                self._human_click(sair_span)
                self._human_delay(2, 4)
                
                # Verifica se o logout foi bem-sucedido
                if "accounts/login" in self.driver.current_url.lower() or "login" in self.driver.current_url.lower():
                    logger.info(f"Logout realizado com sucesso para @{self.username}")
                else:
                    logger.warning("Logout pode não ter sido completado")
            else:
                logger.error("Não foi possível encontrar o botão 'Sair'")
                raise Exception("Não foi possível encontrar o botão 'Sair' para fazer logout")
                
        except Exception as e:
            logger.error(f"Erro ao fazer logout: {e}")
            # Tenta navegar diretamente para a página de login como fallback
            try:
                self.driver.get("https://www.instagram.com/")
                self._human_delay(2, 4)
            except Exception:
                pass
            raise

    def _login(self) -> None:
        """Faz login no Instagram com tratamento de desafios."""
        try:
            logger.info(f"Iniciando login para @{self.username}")
            
            # Verifica se já está logado e faz logout se necessário
            if self._is_logged_in():
                logger.info(f"Usuário já está logado. Fazendo logout antes de fazer login novamente...")
                self._logout()
            
            # Navega para a rota "/" que contém os campos de login se não estiver logado
            self.driver.get("https://www.instagram.com/")
            self._human_delay(2, 4)

            # Aguarda campos de login aparecerem
            wait = WebDriverWait(self.driver, 15)
            
            # Verifica se existe uma div com o texto "Trocar de conta" e clica se existir
            try:
                trocar_conta_div = self.driver.find_element(
                    By.XPATH,
                    "//div[contains(text(), 'Trocar de conta')]"
                )
                if trocar_conta_div.is_displayed():
                    logger.info("Div 'Trocar de conta' encontrada. Clicando...")
                    self._human_click(trocar_conta_div)
                    self._human_delay(1, 2)
            except NoSuchElementException:
                # Não encontrou a div, continua normalmente
                pass
            
            # Tenta encontrar campo de username (pode ser input[name="username"] ou input[aria-label*="username"])
            username_selectors = [
                'input[name="username"]',
                'input[aria-label*="username" i]',
                'input[aria-label*="nome" i]',
                'input[type="text"]',
            ]
            
            username_input = None
            for selector in username_selectors:
                try:
                    username_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not username_input:
                raise Exception("Não foi possível encontrar campo de username")
            
            # Move mouse e digita username
            self._random_mouse_movement()
            self._human_click(username_input)
            self._human_delay(0.3, 0.5)
            
            # Limpa o campo de forma mais robusta
            username_input.send_keys(Keys.CONTROL + "a")
            username_input.send_keys(Keys.DELETE)
            self._human_delay(0.2, 0.4)
            
            # Digita username caractere por caractere
            self._human_type(username_input, self.username)
            
            # Aguarda um pouco antes de ir para o campo de senha
            self._human_delay(0.5, 1.0)
            
            # Encontra campo de senha
            password_selectors = [
                'input[name="password"]',
                'input[aria-label*="password" i]',
                'input[aria-label*="senha" i]',
                'input[type="password"]',
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    password_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if password_input.is_displayed():
                        break
                except NoSuchElementException:
                    continue
            
            if not password_input:
                raise Exception("Não foi possível encontrar campo de senha")
            
            self._human_click(password_input)
            self._human_delay(0.3, 0.5)
            
            # Limpa o campo de senha de forma mais robusta
            password_input.send_keys(Keys.CONTROL + "a")
            password_input.send_keys(Keys.DELETE)
            self._human_delay(0.2, 0.4)
            
            # Digita senha caractere por caractere (mais lento para senha)
            for char in self.password:
                password_input.send_keys(char)
                # Delay um pouco maior para senha (mais seguro)
                time.sleep(random.uniform(0.08, 0.15))
            
            # Aguarda um pouco após digitar a senha
            self._human_delay(1.0, 1.5)
            
            # Tenta encontrar e clicar no botão "Mostrar" para mostrar a senha
            try:
                show_button_selectors = [
                    "//button[contains(text(), 'Mostrar')]",
                    "//button[contains(text(), 'Show')]",
                    "//button[@aria-label='Mostrar']",
                    "//button[@aria-label='Show']",
                ]
                
                show_button = None
                for selector in show_button_selectors:
                    try:
                        show_button = self.driver.find_element(By.XPATH, selector)
                        if show_button.is_displayed() and show_button.is_enabled():
                            logger.info("Botão 'Mostrar' encontrado. Clicando...")
                            self._human_click(show_button)
                            self._human_delay(0.5, 1.0)
                            break
                    except NoSuchElementException:
                        continue
                
                if not show_button:
                    logger.debug("Botão 'Mostrar' não encontrado. Continuando...")
            except Exception as e:
                logger.debug(f"Erro ao procurar botão 'Mostrar': {e}. Continuando...")
            
            # Aguarda um pouco antes de tentar fazer login
            self._human_delay(0.8, 1.2)
            
            password_input.send_keys(Keys.RETURN)
            
            self._human_delay(3, 6)
            
            # Verifica se há mensagem de erro de senha incorreta
            page_source = self.driver.page_source
            if "Sua senha está incorreta. Confira-a" in page_source:
                logger.warning(f"Erro de login detectado: senha incorreta para @{self.username}. Passando para próxima persona.")
                raise LoginError(f"Senha incorreta para @{self.username}")
            
            # Se não houve erro, assume que login foi bem-sucedido
            logger.info(f"Login bem-sucedido para @{self.username}")
            self._human_delay(2, 4)
            
            # Fecha popups comuns (salvar informações, notificações, etc)
            self._dismiss_popups()
            return
            
        except Exception as e:
            logger.error(f"Erro durante login para @{self.username}: {e}")
            raise

    def _dismiss_popups(self) -> None:
        """Fecha popups comuns do Instagram após login."""
        popup_selectors = [
            'button:contains("Not Now")',
            'button:contains("Agora não")',
            'button:contains("Save Info")',
            'button:contains("Salvar informações")',
            'button[aria-label*="Close" i]',
            'button[aria-label*="Fechar" i]',
            'svg[aria-label*="Close" i]',
        ]
        
        for selector in popup_selectors:
            try:
                if "contains" in selector:
                    button = self.driver.find_element(
                        By.XPATH,
                        "//button[contains(text(), 'Not Now') or contains(text(), 'Agora não') or contains(text(), 'Save Info') or contains(text(), 'Salvar informações')]"
                    )
                else:
                    button = self.driver.find_element(By.CSS_SELECTOR, selector)
                
                if button.is_displayed():
                    self._human_click(button)
                    self._human_delay(1, 2)
            except (NoSuchElementException, ElementNotInteractableException):
                continue

    def open_dm_conversation(self, username: str) -> bool:
        """Abre a conversa de DM com o usuário especificado.
        
        Navega para o perfil, clica em 'Enviar mensagem' e aguarda o campo de texto aparecer.
        Retorna True se conseguiu abrir a conversa, False caso contrário.
        """
        if not self.driver:
            logger.error("Driver não inicializado")
            return False
        
        try:
            target_username = username.strip().lower().replace("@", "")
            logger.info(f"Abrindo conversa de DM com @{target_username}")
            
            # Navega para o perfil do usuário
            profile_url = f"https://www.instagram.com/{target_username}/"
            self.driver.get(profile_url)
            self._human_delay(2, 4)
            
            # Verifica se o perfil existe
            if "Sorry, this page isn't available" in self.driver.page_source:
                logger.error(f"Perfil @{target_username} não encontrado")
                return False
            
            wait = WebDriverWait(self.driver, 10)
            
            # Primeiro tenta encontrar uma DIV com o texto "Enviar mensagem"
            div_message_selectors = [
                "//div[contains(text(), 'Enviar mensagem')]",
                "//div[contains(text(), 'Send Message')]",
                "//div[text()='Enviar mensagem']",
                "//div[text()='Send Message']",
            ]
            
            div_message_found = False
            for selector in div_message_selectors:
                try:
                    div_message = wait.until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    if div_message.is_displayed():
                        logger.info("Encontrada DIV 'Enviar mensagem', clicando...")
                        self._human_click(div_message)
                        self._human_delay(2, 4)
                        div_message_found = True
                        break
                except TimeoutException:
                    continue
            
            opcoes_svg_found = False
            # Se não encontrou a DIV, tenta o fluxo alternativo: SVG "Opções" -> Button "Enviar mensagem"
            if not div_message_found:
                logger.info("DIV 'Enviar mensagem' não encontrada. Tentando fluxo alternativo...")
                
                # Procura SVG com aria-label "Opções"
                opcoes_svg_selectors = [
                    'svg[aria-label="Opções"]',
                    'svg[aria-label="Options"]',
                    'svg[aria-label*="Opções" i]',
                    'svg[aria-label*="Options" i]',
                ]
                
                
                opcoes_svg = None
                for selector in opcoes_svg_selectors:
                    try:
                        opcoes_svg = wait.until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                        if opcoes_svg.is_displayed():
                            opcoes_svg_found = True
                            break
                    except TimeoutException:
                        continue
                
                if opcoes_svg:
                    logger.info("Encontrado SVG 'Opções', clicando...")
                    self._human_click(opcoes_svg)
                    self._human_delay(1, 2)
                    
                    # Agora procura o button com texto "Enviar mensagem"
                    button_message_selectors = [
                        "//button[contains(text(), 'Enviar mensagem')]",
                        "//button[contains(text(), 'Send Message')]",
                        "//button[text()='Enviar mensagem']",
                        "//button[text()='Send Message']",
                    ]
                    
                    button_message = None
                    for selector in button_message_selectors:
                        try:
                            button_message = wait.until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                            if button_message.is_displayed():
                                break
                        except TimeoutException:
                            continue
                    
                    if button_message:
                        logger.info("Encontrado button 'Enviar mensagem', clicando...")
                        self._human_click(button_message)
                        self._human_delay(2, 4)
                    else:
                        logger.warning("Não foi possível encontrar button 'Enviar mensagem' após clicar em Opções")
                else:
                    logger.warning("Não foi possível encontrar SVG 'Opções'. Continuando com busca normal...")
            
            # Procura botão de mensagem (fallback ou se o fluxo acima não funcionou)
            
            # Se ainda não encontrou nenhum botão, retorna erro
            if not div_message_found and not opcoes_svg_found:
                logger.error(f"Não foi possível encontrar botão de mensagem para @{target_username}")
                return False
            
            # Aguarda a caixa de mensagem aparecer
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao abrir conversa de DM com @{username}: {e}")
            return False

    def send_dm(self, username: str, message: str) -> bool:
        """Envia uma mensagem na conversa de DM já aberta.
        
        Assume que a conversa já está aberta (campo de texto visível).
        Apenas encontra o campo, digita a mensagem e envia.
        """
        if not self.driver:
            logger.error("Driver não inicializado")
            return False
        
        try:
            wait = WebDriverWait(self.driver, 10)
            
            # Encontra o campo de mensagem (já deve estar visível)
            message_field_selectors = [
                'div[aria-label*="Mensagem" i]',
            ]
            
            message_field = None
            for selector in message_field_selectors:
                try:
                    message_field = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    if message_field.is_displayed():
                        break
                except TimeoutException:
                    continue
            
            if not message_field:
                logger.error("Não foi possível encontrar campo de texto para mensagem")
                return False
            
            # Digita a mensagem
            self._human_click(message_field)
            self._human_delay(0.5, 1.0)
            
            message_field.clear()
            self._human_type(message_field, message)
            
            self._human_delay(1, 2)
            
            # Primeiro tenta enviar com Enter
            logger.info("Tentando enviar mensagem com Enter...")
            self._human_click(message_field)
            self._human_delay(0.3, 0.5)
            message_field.send_keys(Keys.RETURN)
            
            # Aguarda um pouco para ver se a mensagem foi enviada
            self._human_delay(1, 2)
            
            # Verifica se o Enter funcionou
            # Se o campo foi limpo ou se o texto mudou, provavelmente funcionou
            enter_worked = False
            try:
                # Tenta obter o texto atual do campo
                current_text = ""
                if message_field.tag_name == "div" and message_field.get_attribute("contenteditable") == "true":
                    current_text = message_field.text or message_field.get_attribute("innerText") or ""
                else:
                    current_text = message_field.get_attribute("value") or message_field.text or ""
                
                # Se o campo está vazio ou não contém mais a mensagem completa, provavelmente funcionou
                if not current_text or message not in current_text:
                    enter_worked = True
                    logger.info("Enter funcionou! Mensagem enviada com sucesso.")
                else:
                    logger.info(f"Enter não funcionou. Campo ainda contém: '{current_text[:50]}...'")
            except Exception as e:
                logger.warning(f"Erro ao verificar se Enter funcionou: {e}. Tentando botões de envio...")
            
            # Se o Enter não funcionou, procura os botões de envio
            if not enter_worked:
                logger.info("Enter não funcionou. Procurando botões de envio...")
                
                # Lista de seletores XPath para o botão de enviar
                send_field_selectors = [
                    "//div[contains(text(), 'Enviar')]",
                    "//div[aria-label='Enviar']",
                    "//svg[aria-label='Send']",
                ]
                
                send_field = None
                for selector in send_field_selectors:
                    try:
                        send_field = wait.until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                        if send_field.is_displayed() and send_field.is_enabled():
                            logger.info(f"Botão de enviar encontrado via XPath: {selector}")
                            break
                    except (TimeoutException, NoSuchElementException):
                        continue
                
                if send_field:
                    logger.info("Clicando no botão de enviar")
                    self._human_click(send_field)
                else:
                    logger.warning("Não foi possível encontrar botão de envio. Mensagem pode não ter sido enviada.")
            
            self._human_delay(2, 4)
            
            logger.info(f"Mensagem enviada com sucesso para @{username}")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem para @{username}: {e}")
            return False

    def check_mutual_follow(self, other_username: str) -> Tuple[bool, bool]:
        """Retorna (eu_sigo_ele, ele_me_segue) para o usuário alvo."""
        if not self.driver:
            logger.error("Driver não inicializado")
            return False, False
        
        try:
            target_username = other_username.strip().lower().replace("@", "")
            logger.info(f"Verificando follow mútuo com @{target_username}")
            
            # Navega para o perfil
            profile_url = f"https://www.instagram.com/{target_username}/"
            self.driver.get(profile_url)
            self._human_delay(2, 4)
            
            # Verifica se o perfil existe
            if "Sorry, this page isn't available" in self.driver.page_source:
                logger.error(f"Perfil @{target_username} não encontrado")
                return False, False
            
            # Verifica se a persona segue o restaurante
            # Procura botões de follow/unfollow para determinar o estado
            following_xpath = "//button[contains(text(), 'Following') or contains(text(), 'Seguindo') or contains(text(), 'Requested') or contains(text(), 'Solicitado')]"
            follow_xpath = "//button[contains(text(), 'Follow') or contains(text(), 'Seguir')]"
            
            persona_follows = False
            try:
                following_button = self.driver.find_element(By.XPATH, following_xpath)
                if following_button.is_displayed():
                    persona_follows = True
            except NoSuchElementException:
                pass
            
            # Para verificar se o restaurante segue a persona, precisamos verificar
            # se conseguimos ver o botão de mensagem (que geralmente só aparece se houver follow mútuo)
            # ou verificar a lista de seguidores do restaurante
            restaurant_follows = False
            
            # Tenta verificar através do botão de mensagem
            # Se o botão de mensagem está disponível, pode indicar que nos segue
            try:
                message_button = self.driver.find_element(
                    By.XPATH,
                    "//button[contains(text(), 'Message') or contains(text(), 'Mensagem')] | //a[contains(text(), 'Message') or contains(text(), 'Mensagem')]"
                )
                if message_button.is_displayed():
                    # Se há botão de mensagem, há chance de que nos siga
                    # Mas não é garantia, então vamos tentar uma verificação mais precisa
                    restaurant_follows = None  # Indeterminado
            except NoSuchElementException:
                pass
            
            # Tenta verificar através da lista de seguidores (mais preciso)
            # Navega para a lista de seguidores do restaurante
            try:
                # Procura pelo link de seguidores (pode estar em diferentes formatos)
                followers_selectors = [
                    "//a[contains(@href, '/followers/')]",
                    "//a[contains(text(), 'followers') or contains(text(), 'seguidores')]",
                ]
                
                followers_link = None
                for selector in followers_selectors:
                    try:
                        followers_link = self.driver.find_element(By.XPATH, selector)
                        break
                    except NoSuchElementException:
                        continue
                
                if followers_link:
                    followers_url = followers_link.get_attribute("href")
                    if not followers_url:
                        # Tenta construir a URL
                        followers_url = f"https://www.instagram.com/{target_username}/followers/"
                    
                    self.driver.get(followers_url)
                    self._human_delay(2, 4)
                    
                    # Procura pelo nosso username na lista de seguidores
                    current_username = self.username.lower()
                    
                    # Verifica se há links com nosso username na lista
                    try:
                        # Procura por links que contenham nosso username
                        our_profile_links = self.driver.find_elements(
                            By.XPATH,
                            f"//a[contains(@href, '/{current_username}/')]"
                        )
                        # Verifica se algum link está visível e contém nosso username
                        for link in our_profile_links:
                            try:
                                href = link.get_attribute("href")
                                if href and current_username in href.lower():
                                    restaurant_follows = True
                                    break
                            except StaleElementReferenceException:
                                continue
                        
                        if restaurant_follows is None:
                            restaurant_follows = False
                    except Exception as e:
                        logger.debug(f"Erro ao verificar seguidores: {e}")
                        restaurant_follows = False
                    
                    # Volta para o perfil
                    self.driver.get(profile_url)
                    self._human_delay(1, 2)
            except (NoSuchElementException, Exception) as e:
                # Se não conseguir acessar lista de seguidores, assume False
                logger.debug(f"Não foi possível verificar lista de seguidores: {e}")
                if restaurant_follows is None:
                    restaurant_follows = False
            
            # Se ainda não determinou, usa heurística baseada em mensagem
            if restaurant_follows is None:
                restaurant_follows = False
            
            logger.info(
                f"Follow status: persona segue restaurante={persona_follows}, "
                f"restaurante segue persona={restaurant_follows}"
            )
            
            return persona_follows, restaurant_follows
            
        except Exception as e:
            logger.error(f"Erro ao verificar follow com @{other_username}: {e}")
            return False, False

    def follow(self, username: str) -> bool:
        """Segue o usuário indicado."""
        if not self.driver:
            logger.error("Driver não inicializado")
            return False
        
        try:
            target_username = username.strip().lower().replace("@", "")
            logger.info(f"Seguindo @{target_username}")
            
            # Navega para o perfil
            profile_url = f"https://www.instagram.com/{target_username}/"
            self.driver.get(profile_url)
            self._human_delay(2, 4)
            
            # Verifica se o perfil existe
            if "Sorry, this page isn't available" in self.driver.page_source:
                logger.error(f"Perfil @{target_username} não encontrado")
                return False
            
            # Procura botão de follow
            follow_button_selectors = [
                'button:contains("Follow")',
                'button:contains("Seguir")',
            ]
            
            follow_button = None
            wait = WebDriverWait(self.driver, 10)
            
            for selector in follow_button_selectors:
                try:
                    follow_button = wait.until(
                        EC.element_to_be_clickable((
                            By.XPATH,
                            "//button[contains(text(), 'Follow') or contains(text(), 'Seguir')]"
                        ))
                    )
                    break
                except TimeoutException:
                    continue
            
            if not follow_button:
                # Pode já estar seguindo
                following_button = self.driver.find_elements(
                    By.XPATH,
                    "//button[contains(text(), 'Following') or contains(text(), 'Seguindo')]"
                )
                if following_button:
                    logger.info(f"Já está seguindo @{target_username}")
                    return True
                
                logger.error(f"Não foi possível encontrar botão de follow para @{target_username}")
                return False
            
            self._human_click(follow_button)
            self._human_delay(2, 4)
            
            # Verifica se o follow foi bem-sucedido
            following_indicators = self.driver.find_elements(
                By.XPATH,
                "//button[contains(text(), 'Following') or contains(text(), 'Seguindo') or contains(text(), 'Requested') or contains(text(), 'Solicitado')]"
            )
            
            if following_indicators:
                logger.info(f"Follow enviado com sucesso para @{target_username}")
                self._human_delay(self.wait_min_seconds, self.wait_max_seconds)
                return True
            else:
                logger.warning(f"Follow pode não ter sido aplicado para @{target_username}")
                return False
                
        except Exception as e:
            logger.error(f"Erro ao seguir @{username}: {e}")
            return False

    def __del__(self):
        """Fecha o driver ao destruir o objeto."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

    def quit(self):
        """Fecha o driver explicitamente."""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
            except Exception:
                pass
