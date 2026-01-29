"""
Módulo de processamento de restaurantes com deduplicação conservadora e agrupamento inteligente.

Implementa as regras estritas de:
- Deduplicação por Instagram idêntico ou Endereço Estrito
- Agrupamento por cluster (mesmo grupo/rede/dono) sem exclusão
- Distribuição em blocos de 5 a 10 registros
- Auditoria completa e rastreável
"""

import re
import logging
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict
from difflib import SequenceMatcher
import pandas as pd
from pathlib import Path
import csv
import unicodedata

logger = logging.getLogger(__name__)

def _norm_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s

def _banner_forward_fill(row: List[str], target_len: int) -> List[str]:
    row = list(row or [])
    if len(row) < target_len:
        row = row + [""] * (target_len - len(row))
    if len(row) > target_len:
        row = row[:target_len]
    filled = []
    current = ""
    for cell in row:
        cell_str = (cell or "").strip()
        if cell_str:
            current = cell_str
        filled.append(current)
    return filled

def _template_should_ignore_banner(banner_cell: str) -> bool:
    return "nao preencher" in _norm_text(banner_cell)

def _build_internal_columns(headers: List[str]) -> Tuple[List[str], Dict[str, str]]:
    """
    Gera nomes internos únicos para colunas (necessário porque o template tem colunas duplicadas,
    como Data/Persona/Frase repetidas).
    """
    internal = [f"col_{i:03d}" for i in range(len(headers))]
    mapping = {internal[i]: headers[i] for i in range(len(headers))}
    return internal, mapping

def _detect_template_columns(headers: List[str], banners: List[str]) -> Dict[str, Optional[int]]:
    """
    Detecta por posição (índice) as colunas do template. A regra do usuário:
    - Usar sempre a 2ª linha como header real
    - Não levar em consideração (na lógica) colunas sob banner "NÃO PREENCHER"
    """
    norm_headers = [_norm_text(h) for h in headers]
    ignore_flags = [_template_should_ignore_banner(b) for b in banners]

    def find_first(predicate) -> Optional[int]:
        for i, h in enumerate(norm_headers):
            if predicate(i, h):
                return i
        return None

    idx_hash = find_first(lambda i, h: h == "#")
    idx_restaurant = find_first(lambda i, h: "restaurante" in h and h != "# frase")
    idx_instagram = find_first(lambda i, h: "instagram" in h)
    idx_bloco = find_first(lambda i, h: "bloco" in h)
    idx_address = find_first(lambda i, h: "endereco" in h or "endereço" in (headers[i] or ""))

    # Campos de histórico usados para "manter por prioridade" — mas devemos ignorar colunas marcadas como NÃO PREENCHER
    idx_date = find_first(lambda i, h: (h == "data") and (not ignore_flags[i]))
    idx_persona = find_first(lambda i, h: (h == "persona") and (not ignore_flags[i]))
    idx_phrase = find_first(lambda i, h: (h == "frase") and (not ignore_flags[i]))
    
    # Detecta coluna "cliente" (pode ter variações: cliente, Cliente, CLIENTE)
    idx_cliente = find_first(lambda i, h: "cliente" in h)

    return {
        "hash": idx_hash,
        "restaurant": idx_restaurant,
        "instagram": idx_instagram,
        "bloco": idx_bloco,
        "address": idx_address,
        "date": idx_date,
        "persona": idx_persona,
        "phrase": idx_phrase,
        "cliente": idx_cliente,
    }

def load_restaurants_template_csv(input_path: str) -> Tuple[pd.DataFrame, List[str], List[str], Dict[str, str]]:
    """
    Lê o template CSV com:
    - 1ª linha: banner (ex.: "NÃO PREENCHER ...") - IGNORADA/REMOVIDA
    - 2ª linha: header real
    - Demais linhas: dados

    Retorna:
    - df com colunas internas únicas
    - headers originais (2ª linha) na ordem exata
    - banners forward-fill (vazio, já que removemos a primeira linha)
    - mapping internal_col -> header original
    """
    with open(input_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            banner_row = next(reader)  # Lê e ignora a primeira linha (banner)
        except StopIteration:
            raise ValueError("CSV vazio")
        try:
            header_row = next(reader)  # Segunda linha é o header real
        except StopIteration:
            raise ValueError("CSV não possui a segunda linha de header (linha 2)")

    headers = list(header_row)
    # Não usa mais o banner_row, cria banners vazios já que removemos a primeira linha
    banners = [""] * len(headers)

    internal_cols, internal_to_original = _build_internal_columns(headers)

    # Lê dados (pulando 2 primeiras linhas: banner + header). engine=python para tolerar quebras de linha dentro de aspas.
    df = pd.read_csv(
        input_path,
        skiprows=2,  # Pula banner (linha 1) e header será usado via names
        header=None,
        names=internal_cols,
        engine="python",
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )

    return df, headers, banners, internal_to_original

def normalize_instagram(instagram: str) -> str:
    """
    Normaliza o Instagram removendo apenas @, http://, https://, instagram.com/, www.instagram.com/
    
    Se houver espaço, faz split e usa apenas o primeiro termo (username).
    Remove parênteses abertos e fechados, mantendo apenas o conteúdo.
    
    NÃO truncar, NÃO remover sufixos geográficos ou numéricos (_sp, _rj, 01 etc.).
    """
    if not instagram or not isinstance(instagram, str):
        return ""
    
    # Remove espaços e converte para minúsculas
    normalized = instagram.strip().lower()
    
    # Remove protocolos e domínios
    normalized = re.sub(r'^https?://', '', normalized)
    normalized = re.sub(r'^www\.instagram\.com/', '', normalized)
    normalized = re.sub(r'^instagram\.com/', '', normalized)
    normalized = re.sub(r'^@', '', normalized)
    
    # Remove parênteses abertos e fechados, mantendo apenas o conteúdo
    normalized = normalized.replace('(', '').replace(')', '')
    
    # Se houver espaço, faz split e usa apenas o primeiro termo (username)
    if ' ' in normalized:
        normalized = normalized.split()[0]
    
    # Remove espaços finais
    return normalized.strip()


def normalize_address_street(street: str) -> str:
    """
    Normaliza o logradouro removendo acentos e convertendo tipos de via para abreviações.
    
    Ex.: Rua → "r", Avenida → "av", Alameda → "al"
    """
    if not street or not isinstance(street, str):
        return ""
    
    # Remove acentos (simplificado)
    normalized = street.strip().lower()
    
    # Normaliza tipos de via
    replacements = {
        r'\brua\b': 'r',
        r'\bavenida\b': 'av',
        r'\bav\.\b': 'av',
        r'\balameda\b': 'al',
        r'\brodovia\b': 'rod',
        r'\bestrada\b': 'est',
        r'\bpraça\b': 'pc',
        r'\btravessa\b': 'tv',
        r'\blargo\b': 'lg',
        r'\bvia\b': 'v',
        r'\bpassagem\b': 'psg',
    }
    
    for pattern, replacement in replacements.items():
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    
    # Remove caracteres especiais e espaços extras
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    
    return normalized.strip()


def extract_address_number(address: str) -> Optional[str]:
    """
    Extrai o número do endereço.
    
    Retorna None se não encontrar número identificável.
    """
    if not address or not isinstance(address, str):
        return None
    
    # Primeiro tenta encontrar número simples (antes do CEP ou no início)
    # Padrão: número pode estar no formato "123", "123A", "123-A"
    # CEP geralmente está no final: "12345-678" ou "12345678"
    
    # Remove CEP do final para não confundir
    address_clean = re.sub(r'\b\d{5}-?\d{3}\b', '', address)
    
    # Procura número no endereço (não CEP)
    match = re.search(r'\b(\d{1,6}[a-z]?)\b', address_clean, re.IGNORECASE)
    if match:
        number = match.group(1).upper()
        # Verifica se não é "S/N" ou "sem número"
        if not re.search(r'\bs/n\b|\bsem\s+n[úu]mero\b', address, re.IGNORECASE):
            return number
    
    # Verifica se é "S/N" ou "sem número"
    if re.search(r'\bs/n\b|\bsem\s+n[úu]mero\b', address, re.IGNORECASE):
        return None
    
    return None


def extract_cep(address: str) -> Optional[str]:
    """
    Extrai o CEP do endereço.
    
    Retorna None se não encontrar CEP.
    """
    if not address or not isinstance(address, str):
        return None
    
    # Padrões de CEP: "12345-678" ou "12345678"
    match = re.search(r'\b(\d{5}-?\d{3})\b', address)
    if match:
        cep = match.group(1).replace('-', '')
        return cep
    
    return None


def calculate_similarity(str1: str, str2: str) -> float:
    """
    Calcula similaridade entre duas strings usando SequenceMatcher.
    
    Retorna valor entre 0.0 e 1.0.
    """
    if not str1 or not str2:
        return 0.0
    
    return SequenceMatcher(None, str1.lower().strip(), str2.lower().strip()).ratio()


def has_historical_data(record: Dict[str, Any], date_col: Optional[str] = None, 
                       persona_col: Optional[str] = None, phrase_col: Optional[str] = None) -> bool:
    """
    Verifica se o registro tem histórico de contato (Data, Persona ou Frase preenchidos).
    """
    if date_col and record.get(date_col):
        return True
    if persona_col and record.get(persona_col):
        return True
    if phrase_col and record.get(phrase_col):
        return True
    return False


def detect_column_names(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    Detecta automaticamente as colunas "Restaurante", "Instagram" e "Endereço",
    independentemente de acentos ou variações de nome.
    """
    columns = {}
    df_cols_lower = {col.lower(): col for col in df.columns}
    
    # Detecta coluna de restaurante
    patterns_restaurant = ['restaurante', 'nome restaurante', 'nome', 'restaurant']
    for pattern in patterns_restaurant:
        for col_lower, col_original in df_cols_lower.items():
            if pattern in col_lower:
                columns['restaurant'] = col_original
                break
        if columns.get('restaurant'):
            break
    
    # Detecta coluna de Instagram
    patterns_instagram = ['instagram', 'insta', '@']
    for pattern in patterns_instagram:
        for col_lower, col_original in df_cols_lower.items():
            if pattern in col_lower:
                columns['instagram'] = col_original
                break
        if columns.get('instagram'):
            break
    
    # Detecta coluna de endereço
    patterns_address = ['endereço', 'endereco', 'address', 'end', 'rua', 'logradouro']
    for pattern in patterns_address:
        for col_lower, col_original in df_cols_lower.items():
            if pattern in col_lower:
                columns['address'] = col_original
                break
        if columns.get('address'):
            break
    
    # Detecta colunas de histórico
    patterns_date = ['data', 'date', 'última data', 'ultima data']
    for pattern in patterns_date:
        for col_lower, col_original in df_cols_lower.items():
            if pattern in col_lower:
                columns['date'] = col_original
                break
        if columns.get('date'):
            break
    
    patterns_persona = ['persona', 'persona usada', 'última persona', 'ultima persona']
    for pattern in patterns_persona:
        for col_lower, col_original in df_cols_lower.items():
            if pattern in col_lower:
                columns['persona'] = col_original
                break
        if columns.get('persona'):
            break
    
    patterns_phrase = ['frase', 'phrase', 'última frase', 'ultima frase']
    for pattern in patterns_phrase:
        for col_lower, col_original in df_cols_lower.items():
            if pattern in col_lower:
                columns['phrase'] = col_original
                break
        if columns.get('phrase'):
            break
    
    return columns


def deduplicate_by_instagram(records: List[Dict[str, Any]], 
                             instagram_col: str,
                             date_col: Optional[str],
                             persona_col: Optional[str],
                             phrase_col: Optional[str],
                             restaurant_col: str,
                             address_col: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Deduplica registros por Instagram idêntico.
    
    Mantém o registro com histórico (Data/Persona/Frase) ou o primeiro na ordem original.
    
    Retorna: (registros mantidos, auditoria de deduplicação)
    """
    instagram_map = {}  # normalized_instagram -> lista de índices
    kept_indices = set(range(len(records)))  # Inicia com todos
    audit = []
    
    # Agrupa por Instagram normalizado (inclui registros sem Instagram também)
    for idx, record in enumerate(records):
        instagram = record.get(instagram_col, "")
        normalized = normalize_instagram(instagram)
        
        if normalized:
            if normalized not in instagram_map:
                instagram_map[normalized] = []
            instagram_map[normalized].append(idx)
        # Registros sem Instagram não são deduplicados por este critério
    
    # Processa cada grupo de Instagrams idênticos
    for normalized_inst, indices in instagram_map.items():
        if len(indices) <= 1:
            # Sem duplicatas, mantém
            kept_indices.add(indices[0])
            continue
        
        # Tem duplicatas - decide qual manter
        candidates = [(idx, records[idx]) for idx in indices]
        
        # Prioridade 1: histórico de contato
        with_history = [(idx, rec) for idx, rec in candidates 
                       if has_historical_data(rec, date_col, persona_col, phrase_col)]
        
        if with_history:
            # Mantém o primeiro com histórico
            kept_idx = with_history[0][0]
            # Remove os outros do conjunto de mantidos
            for idx in indices:
                if idx != kept_idx:
                    kept_indices.discard(idx)
            
            kept_record = records[kept_idx]
            audit.append({
                'criterio': 'Instagram idêntico',
                'linha_mantida': f"#{kept_idx + 1} - {kept_record.get(restaurant_col, '')} | {kept_record.get(instagram_col, '')} | {kept_record.get(address_col, '') if address_col else ''}",
                'linhas_removidas': [f"#{idx + 1} - {records[idx].get(restaurant_col, '')} | {records[idx].get(instagram_col, '')} | {records[idx].get(address_col, '') if address_col else ''}" for idx in indices if idx != kept_idx],
                'justificativa': 'mantido por prioridade de histórico (Data/Persona/Frase)'
            })
        else:
            # Sem histórico, mantém o primeiro na ordem original
            kept_idx = indices[0]
            # Remove os outros do conjunto de mantidos
            for idx in indices[1:]:
                kept_indices.discard(idx)
            
            kept_record = records[kept_idx]
            audit.append({
                'criterio': 'Instagram idêntico',
                'linha_mantida': f"#{kept_idx + 1} - {kept_record.get(restaurant_col, '')} | {kept_record.get(instagram_col, '')} | {kept_record.get(address_col, '') if address_col else ''}",
                'linhas_removidas': [f"#{idx + 1} - {records[idx].get(restaurant_col, '')} | {records[idx].get(instagram_col, '')} | {records[idx].get(address_col, '') if address_col else ''}" for idx in indices[1:]],
                'justificativa': 'mantido por ordem original'
            })
    
    # Retorna apenas os registros mantidos (preserva ordem original)
    kept_records = [records[i] for i in range(len(records)) if i in kept_indices]
    
    return kept_records, audit


def deduplicate_by_address(records: List[Dict[str, Any]],
                           address_col: str,
                           date_col: Optional[str],
                           persona_col: Optional[str],
                           phrase_col: Optional[str],
                           restaurant_col: str,
                           instagram_col: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Deduplica registros por Endereço Estrito (tipo+base+número).
    
    Dois registros serão deduplicados APENAS SE:
    - Ambos tiverem número de endereço preenchido e idêntico
    - O logradouro_base for idêntico após normalização
    - CEP idêntico (quando disponível) reforça, mas não é obrigatório
    
    Retorna: (registros mantidos, auditoria de deduplicação)
    """
    address_map = {}  # (logradouro_base, numero, cep) -> lista de índices
    kept_indices = set(range(len(records)))  # Inicia com todos os índices
    audit = []
    
    # Agrupa por endereço estrito (apenas registros com número)
    for idx, record in enumerate(records):
        address = record.get(address_col, "")
        if not address or not isinstance(address, str):
            continue
        
        number = extract_address_number(address)
        if not number:
            continue
        
        logradouro_base = normalize_address_street(address)
        if not logradouro_base:
            continue
        
        # Extrai CEP se disponível (reforça, mas não é obrigatório)
        cep = extract_cep(address) or ""
        
        key = (logradouro_base, number, cep)
        if key not in address_map:
            address_map[key] = []
        address_map[key].append(idx)
    
    # Processa cada grupo de endereços idênticos
    for (logradouro, numero, cep), indices in address_map.items():
        if len(indices) <= 1:
            continue
        
        # Tem duplicatas - decide qual manter
        candidates = [(idx, records[idx]) for idx in indices]
        
        # Prioridade 1: histórico de contato
        with_history = [(idx, rec) for idx, rec in candidates 
                       if has_historical_data(rec, date_col, persona_col, phrase_col)]
        
        if with_history:
            kept_idx = with_history[0][0]
            # Remove os outros do conjunto de mantidos
            for idx in indices:
                if idx != kept_idx:
                    kept_indices.discard(idx)
            
            kept_record = records[kept_idx]
            audit.append({
                'criterio': f'Endereço Estrito (tipo+base+número)' + (f' + CEP {cep}' if cep else ''),
                'linha_mantida': f"#{kept_idx + 1} - {kept_record.get(restaurant_col, '')} | {kept_record.get(instagram_col, '')} | {kept_record.get(address_col, '')}",
                'linhas_removidas': [f"#{idx + 1} - {records[idx].get(restaurant_col, '')} | {records[idx].get(instagram_col, '')} | {records[idx].get(address_col, '')}" for idx in indices if idx != kept_idx],
                'justificativa': 'mantido por prioridade de histórico (Data/Persona/Frase)'
            })
        else:
            kept_idx = indices[0]
            # Remove os outros do conjunto de mantidos
            for idx in indices[1:]:
                kept_indices.discard(idx)
            
            kept_record = records[kept_idx]
            audit.append({
                'criterio': f'Endereço Estrito (tipo+base+número)' + (f' + CEP {cep}' if cep else ''),
                'linha_mantida': f"#{kept_idx + 1} - {kept_record.get(restaurant_col, '')} | {kept_record.get(instagram_col, '')} | {kept_record.get(address_col, '')}",
                'linhas_removidas': [f"#{idx + 1} - {records[idx].get(restaurant_col, '')} | {records[idx].get(instagram_col, '')} | {records[idx].get(address_col, '')}" for idx in indices[1:]],
                'justificativa': 'mantido por ordem original'
            })
    
    # Retorna apenas os registros mantidos
    kept_records = [records[i] for i in sorted(kept_indices)]
    
    return kept_records, audit


def identify_clusters(records: List[Dict[str, Any]],
                     restaurant_col: str,
                     instagram_col: str,
                     address_col: str) -> Dict[int, List[int]]:
    """
    Identifica clusters de registros que pertencem ao mesmo grupo/rede/dono.
    
    Retorna um dicionário: cluster_id -> lista de índices dos registros no cluster.
    """
    clusters = {}  # cluster_id -> set de índices
    record_to_cluster = {}  # índice -> cluster_id
    next_cluster_id = 1
    
    for i in range(len(records)):
        record_i = records[i]
        name_i = str(record_i.get(restaurant_col, "")).strip()
        instagram_i = normalize_instagram(str(record_i.get(instagram_col, "")))
        address_i = str(record_i.get(address_col, "")).strip()
        
        # Verifica se já pertence a algum cluster
        cluster_id = None
        for j in range(i):
            if j in record_to_cluster:
                record_j = records[j]
                name_j = str(record_j.get(restaurant_col, "")).strip()
                instagram_j = normalize_instagram(str(record_j.get(instagram_col, "")))
                address_j = str(record_j.get(address_col, "")).strip()
                
                # Verifica critérios de agrupamento
                same_cluster = False
                
                # 1. Endereço estrito idêntico
                if address_i and address_j:
                    number_i = extract_address_number(address_i)
                    number_j = extract_address_number(address_j)
                    logradouro_i = normalize_address_street(address_i)
                    logradouro_j = normalize_address_street(address_j)
                    
                    if number_i and number_j and number_i == number_j and logradouro_i == logradouro_j:
                        same_cluster = True
                    elif (not number_i or not number_j) and logradouro_i == logradouro_j and logradouro_i:
                        # Mesmo logradouro sem número (dark kitchen ou múltiplas marcas)
                        same_cluster = True
                
                # 2. Similaridade de nome >= 90%
                if not same_cluster and name_i and name_j:
                    sim_name = calculate_similarity(name_i, name_j)
                    if sim_name >= 0.90:
                        same_cluster = True
                
                # 3. Similaridade de Instagram >= 90%
                if not same_cluster and instagram_i and instagram_j:
                    sim_inst = calculate_similarity(instagram_i, instagram_j)
                    if sim_inst >= 0.90:
                        same_cluster = True
                
                # 4. Nome >= 85% E Instagram >= 85% simultaneamente
                if not same_cluster and name_i and name_j and instagram_i and instagram_j:
                    sim_name = calculate_similarity(name_i, name_j)
                    sim_inst = calculate_similarity(instagram_i, instagram_j)
                    if sim_name >= 0.85 and sim_inst >= 0.85:
                        same_cluster = True
                
                if same_cluster:
                    cluster_id = record_to_cluster[j]
                    break
        
        # Se não encontrou cluster, cria novo
        if cluster_id is None:
            cluster_id = next_cluster_id
            next_cluster_id += 1
            clusters[cluster_id] = []
        
        clusters[cluster_id].append(i)
        record_to_cluster[i] = cluster_id
    
    # Remove clusters com apenas 1 registro (não são clusters de verdade)
    return {cid: indices for cid, indices in clusters.items() if len(indices) > 1}


def distribute_into_blocks(records: List[Dict[str, Any]],
                           clusters: Dict[int, List[int]],
                           restaurant_col: str,
                           instagram_col: str,
                           address_col: Optional[str],
                           max_block_size: int = 10,
                           min_block_size: int = 5,
                           existing_blocos: Optional[Dict[int, int]] = None,
                           start_block_num: int = 1) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Distribui registros em blocos de min_block_size a max_block_size, garantindo que registros
    do mesmo cluster não fiquem no mesmo bloco.
    
    Distribui registros de um mesmo cluster de forma cíclica entre os blocos:
    1º do cluster → Bloco 1
    2º do cluster → Bloco 2
    ...
    
    IMPORTANTE: Sempre atribui blocos a TODOS os registros, sem limite no número total de blocos.
    Cada bloco deve ter entre min_block_size e max_block_size registros (quando possível).
    O último bloco pode ter menos que min_block_size se não houver registros suficientes.
    
    Retorna: (registros com campo 'Bloco' preenchido, auditoria de clusters)
    """
    # Cria cópia dos registros
    records_with_blocks = [dict(rec) for rec in records]
    
    # Garante que todos os registros receberão um bloco
    if not records_with_blocks:
        return records_with_blocks, []
    
    # Mapa: índice do registro -> cluster_id (None se não está em cluster)
    record_cluster = {}
    for cluster_id, indices in clusters.items():
        for idx in indices:
            record_cluster[idx] = cluster_id
    
    # Agrupa registros por cluster para distribuição cíclica
    cluster_records = defaultdict(list)
    standalone_records = []
    
    for idx in range(len(records_with_blocks)):
        cluster_id = record_cluster.get(idx)
        if cluster_id:
            cluster_records[cluster_id].append(idx)
        else:
            standalone_records.append(idx)
    
    # Distribui registros em blocos
    blocks = []  # Lista de listas de índices
    block_clusters = []  # Lista de sets de cluster_ids por bloco
    
    # Preserva blocos existentes se for manutenção incremental
    if existing_blocos:
        for idx, bloco_num in existing_blocos.items():
            if idx < len(records_with_blocks):
                # Ajusta índice do bloco para começar após os existentes
                adjusted_bloco = bloco_num - start_block_num + 1
                while len(blocks) < adjusted_bloco:
                    blocks.append([])
                    block_clusters.append(set())
                blocks[adjusted_bloco - 1].append(idx)
                cluster_id = record_cluster.get(idx)
                if cluster_id:
                    block_clusters[adjusted_bloco - 1].add(cluster_id)
                # Remove dos standalone se estava lá
                if idx in standalone_records:
                    standalone_records.remove(idx)
                # Remove dos clusters se estava lá
                for cid, cindices in cluster_records.items():
                    if idx in cindices:
                        cindices.remove(idx)
    
    # Primeiro, distribui registros de clusters de forma cíclica
    # Distribuição cíclica real: 1º do cluster → próximo bloco disponível, 2º → próximo, etc.
    # SEM LIMITE no número total de blocos - cria quantos forem necessários
    for cluster_id, cluster_indices in cluster_records.items():
        if not cluster_indices:  # Pula se vazio (já foi processado)
            continue
        
        for pos, idx in enumerate(cluster_indices):
            # Encontra próximo bloco disponível que não contenha este cluster
            assigned = False
            # Tenta blocos existentes primeiro
            for b_idx in range(len(blocks)):
                if len(blocks[b_idx]) < max_block_size and cluster_id not in block_clusters[b_idx]:
                    blocks[b_idx].append(idx)
                    block_clusters[b_idx].add(cluster_id)
                    assigned = True
                    break
            
            if not assigned:
                # Cria novo bloco (SEM LIMITE - cria quantos forem necessários)
                blocks.append([idx])
                block_clusters.append(set([cluster_id]))
    
    # Depois, distribui registros standalone (sem cluster)
    # Prioriza preencher blocos existentes até min_block_size antes de criar novos
    for idx in standalone_records:
        assigned = False
        # Primeiro tenta adicionar a blocos que ainda não atingiram min_block_size
        for block_idx, block_cluster_set in enumerate(block_clusters):
            if len(blocks[block_idx]) < min_block_size and len(blocks[block_idx]) < max_block_size:
                blocks[block_idx].append(idx)
                assigned = True
                break
        
        # Se não encontrou bloco para preencher até min_block_size, tenta qualquer bloco disponível
        if not assigned:
            for block_idx, block_cluster_set in enumerate(block_clusters):
                if len(blocks[block_idx]) < max_block_size:
                    blocks[block_idx].append(idx)
                    assigned = True
                    break
        
        # Se não encontrou nenhum bloco disponível, cria novo
        if not assigned:
            blocks.append([idx])
            block_clusters.append(set())
    
    # Balanceamento: garante que blocos tenham pelo menos min_block_size quando possível
    # Move registros de blocos pequenos para blocos maiores (respeitando clusters)
    # Tenta consolidar blocos pequenos até atingir min_block_size
    if len(blocks) > 1:
        # Primeira passada: tenta mover registros de blocos pequenos para blocos maiores
        max_iterations = 20  # Limita iterações para evitar loop infinito
        for iteration in range(max_iterations):
            changed = False
            
            # Encontra blocos pequenos (< min_block_size)
            small_blocks = [i for i, b in enumerate(blocks) if len(b) < min_block_size]
            if not small_blocks:
                break  # Não há mais blocos pequenos
            
            # Para cada bloco pequeno, tenta mover registros para blocos maiores
            for b_idx in small_blocks:
                if len(blocks[b_idx]) == 0:
                    continue
                
                records_to_move = list(blocks[b_idx])  # Cria cópia para iterar com segurança
                for idx in records_to_move:
                    cluster_id = record_cluster.get(idx)
                    
                    # Prioriza blocos que já têm pelo menos min_block_size mas ainda têm espaço
                    best_target = None
                    for target_idx in range(len(blocks)):
                        if (target_idx != b_idx and 
                            len(blocks[target_idx]) >= min_block_size and 
                            len(blocks[target_idx]) < max_block_size):
                            if cluster_id is None or cluster_id not in block_clusters[target_idx]:
                                best_target = target_idx
                                break
                    
                    if best_target is not None:
                        # Move para bloco maior
                        blocks[best_target].append(idx)
                        if cluster_id:
                            block_clusters[best_target].add(cluster_id)
                        blocks[b_idx].remove(idx)
                        if cluster_id:
                            block_clusters[b_idx].discard(cluster_id)
                        changed = True
                        
                        # Se o bloco pequeno ficou vazio, pode parar de tentar mover deste bloco
                        if len(blocks[b_idx]) == 0:
                            break
            
            if not changed:
                break  # Não conseguiu mais mover nada
        
        # Segunda passada: tenta consolidar blocos pequenos entre si
        small_blocks = [i for i, b in enumerate(blocks) if len(b) < min_block_size]
        if len(small_blocks) > 1:
            # Tenta consolidar blocos pequenos
            for i, b_idx1 in enumerate(small_blocks):
                if len(blocks[b_idx1]) == 0:
                    continue
                
                for b_idx2 in small_blocks[i+1:]:
                    if len(blocks[b_idx2]) == 0:
                        continue
                    
                    # Verifica se pode consolidar sem violar regra de cluster e sem exceder max_block_size
                    total_size = len(blocks[b_idx1]) + len(blocks[b_idx2])
                    if total_size > max_block_size:
                        continue
                    
                    # Verifica conflitos de cluster
                    can_consolidate = True
                    for idx in blocks[b_idx2]:
                        cluster_id = record_cluster.get(idx)
                        if cluster_id and cluster_id in block_clusters[b_idx1]:
                            can_consolidate = False
                            break
                    
                    if can_consolidate:
                        # Move todos os registros de b_idx2 para b_idx1
                        for idx in list(blocks[b_idx2]):
                            cluster_id = record_cluster.get(idx)
                            blocks[b_idx1].append(idx)
                            if cluster_id:
                                block_clusters[b_idx1].add(cluster_id)
                            if cluster_id:
                                block_clusters[b_idx2].discard(cluster_id)
                        blocks[b_idx2].clear()
                        
                        # Se consolidou e atingiu min_block_size, pode parar
                        if len(blocks[b_idx1]) >= min_block_size:
                            break
        
        # Remove blocos vazios
        blocks = [b for b in blocks if len(b) > 0]
        block_clusters = [bc for i, bc in enumerate(block_clusters) if i < len(blocks)]
    
    # GARANTE que todos os registros receberam um bloco
    # Se algum registro não foi atribuído (edge case), atribui ao último bloco ou cria novo
    all_assigned_indices = set()
    for block in blocks:
        all_assigned_indices.update(block)
    
    for idx in range(len(records_with_blocks)):
        if idx not in all_assigned_indices:
            # Registro não foi atribuído - adiciona ao último bloco ou cria novo
            if blocks and len(blocks[-1]) < max_block_size:
                blocks[-1].append(idx)
            else:
                blocks.append([idx])
                block_clusters.append(set())
    
    # Atribui números de bloco (ajustando para manutenção incremental)
    # SEM LIMITE no número total de blocos - numera sequencialmente quantos forem criados
    for block_num, block_indices in enumerate(blocks, start=start_block_num):
        for idx in block_indices:
            records_with_blocks[idx]['Bloco'] = block_num
    
    # GARANTE FINAL: Todos os registros devem ter um bloco atribuído
    for idx, record in enumerate(records_with_blocks):
        if 'Bloco' not in record or record.get('Bloco') is None:
            # Se por algum motivo não tem bloco, atribui ao último ou cria novo
            if blocks:
                record['Bloco'] = len(blocks) + start_block_num - 1
            else:
                record['Bloco'] = start_block_num
                blocks.append([idx])
                block_clusters.append(set())
    
    # Cria auditoria de clusters
    cluster_audit = []
    for cluster_id, indices in clusters.items():
        cluster_records_list = []
        for idx in indices:
            record = records_with_blocks[idx]
            cluster_records_list.append({
                'restaurante': record.get(restaurant_col, ''),
                'instagram': record.get(instagram_col, ''),
                'endereco': record.get(address_col, '') if address_col else '',
                'bloco': record.get('Bloco', '')
            })
        
        # Determina critério de associação
        if len(indices) > 0:
            criteria = []
            
            # Verifica similaridade de nome
            names = [str(records_with_blocks[idx].get(restaurant_col, '')).strip() for idx in indices]
            if len(set(names)) == 1:
                criteria.append("Nome idêntico")
            elif len(names) > 1:
                sims = [calculate_similarity(names[0], n) for n in names[1:]]
                if all(s >= 0.90 for s in sims):
                    criteria.append("Similaridade de nome ≥90%")
                elif all(s >= 0.85 for s in sims):
                    criteria.append("Similaridade de nome ≥85%")
            
            # Verifica similaridade de Instagram
            instagrams = [normalize_instagram(str(records_with_blocks[idx].get(instagram_col, ''))) for idx in indices]
            if len(set(instagrams)) == 1:
                criteria.append("Instagram idêntico")
            elif len(instagrams) > 1:
                sims = [calculate_similarity(instagrams[0], inst) for inst in instagrams[1:]]
                if all(s >= 0.90 for s in sims):
                    criteria.append("Similaridade de Instagram ≥90%")
                elif all(s >= 0.85 for s in sims):
                    criteria.append("Similaridade de Instagram ≥85%")
            
            # Verifica endereço
            if address_col:
                addresses = [str(records_with_blocks[idx].get(address_col, '')).strip() for idx in indices]
                numbers = [extract_address_number(addr) for addr in addresses]
                logradouros = [normalize_address_street(addr) for addr in addresses]
                
                if all(n and n == numbers[0] for n in numbers if n) and all(l == logradouros[0] for l in logradouros if l):
                    criteria.append("Endereço estrito idêntico")
                elif all(l == logradouros[0] for l in logradouros if l):
                    criteria.append("Endereço com logradouro igual (sem número ou dark kitchen)")
            
            cluster_audit.append({
                'id_cluster': cluster_id,
                'restaurantes': cluster_records_list,
                'criterio_associacao': '; '.join(criteria) if criteria else 'Múltiplos critérios',
                'blocos_atribuidos': sorted(set([r['bloco'] for r in cluster_records_list if r['bloco']]))
            })
    
    return records_with_blocks, cluster_audit


def process_restaurants_excel(input_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Processa arquivo Excel de restaurantes com deduplicação e agrupamento.
    
    ATRIBUIÇÃO AUTOMÁTICA DE BLOCOS:
    - Todos os registros recebem automaticamente um número de bloco
    - Blocos são criados sem limite no número total (cria quantos forem necessários)
    - Cada bloco contém entre 5 e 10 registros (quando possível)
    - Registros do mesmo cluster/grupo/rede são sempre separados em blocos distintos
    
    Args:
        input_path: Caminho do arquivo Excel de entrada
        output_path: Caminho do arquivo Excel de saída (opcional)
    
    Returns:
        Dicionário com estatísticas e caminhos dos arquivos gerados
    """
    # Lê o arquivo Excel
    try:
        df = pd.read_excel(input_path, sheet_name='Restaurantes')
    except Exception as e:
        raise ValueError(f"Erro ao ler arquivo Excel: {e}")
    
    # Detecta colunas automaticamente
    columns = detect_column_names(df)
    
    if not columns.get('restaurant') or not columns.get('instagram'):
        raise ValueError("Não foi possível detectar colunas 'Restaurante' e 'Instagram' no arquivo")
    
    restaurant_col = columns['restaurant']
    instagram_col = columns['instagram']
    address_col = columns.get('address')
    date_col = columns.get('date')
    persona_col = columns.get('persona')
    phrase_col = columns.get('phrase')
    
    # Converte DataFrame para lista de dicionários
    records = df.to_dict('records')
    original_count = len(records)
    
    logger.info(f"Processando {original_count} registros...")
    
    # Verifica se já existe coluna "Bloco" para manutenção incremental
    # IMPORTANTE: Mapear blocos ANTES da deduplicação, pois índices mudam
    original_records = df.to_dict('records')
    existing_blocos_map = {}  # índice original -> bloco
    if 'Bloco' in df.columns:
        for orig_idx, orig_record in enumerate(original_records):
            bloco_val = orig_record.get('Bloco')
            if bloco_val and pd.notna(bloco_val):
                try:
                    existing_blocos_map[orig_idx] = int(bloco_val)
                except (ValueError, TypeError):
                    pass
        max_existing_bloco = max(existing_blocos_map.values()) if existing_blocos_map else 0
        logger.info(f"Encontrados {len(existing_blocos_map)} registros com blocos existentes. Último bloco: {max_existing_bloco}")
    else:
        max_existing_bloco = 0
        existing_blocos_map = {}
    
    # 1. Deduplicação por Instagram
    records, audit_instagram = deduplicate_by_instagram(
        records, instagram_col, date_col, persona_col, phrase_col, restaurant_col, address_col
    )
    logger.info(f"Após deduplicação por Instagram: {len(records)} registros")
    
    # 2. Deduplicação por Endereço Estrito (se coluna de endereço existir)
    audit_address = []
    if address_col:
        records, audit_address = deduplicate_by_address(
            records, address_col, date_col, persona_col, phrase_col, restaurant_col, instagram_col
        )
        logger.info(f"Após deduplicação por Endereço: {len(records)} registros")
    
    # 3. Identificação de clusters
    clusters = identify_clusters(records, restaurant_col, instagram_col, address_col or '')
    logger.info(f"Identificados {len(clusters)} clusters")
    
    # 4. Mapeia blocos existentes para registros após deduplicação
    # Cria um identificador único para cada registro (restaurante + instagram) para mapear
    existing_blocos_after_dedup = {}
    if existing_blocos_map:
        # Cria mapa de identificadores únicos
        orig_identifiers = {}
        for orig_idx, orig_record in enumerate(original_records):
            rest_name = str(orig_record.get(restaurant_col, '')).strip().lower()
            insta = normalize_instagram(str(orig_record.get(instagram_col, '')))
            identifier = f"{rest_name}|{insta}"
            orig_identifiers[orig_idx] = identifier
        
        # Mapeia para registros após deduplicação
        for new_idx, record in enumerate(records):
            rest_name = str(record.get(restaurant_col, '')).strip().lower()
            insta = normalize_instagram(str(record.get(instagram_col, '')))
            identifier = f"{rest_name}|{insta}"
            
            # Encontra índice original correspondente
            for orig_idx, orig_id in orig_identifiers.items():
                if orig_id == identifier and orig_idx in existing_blocos_map:
                    existing_blocos_after_dedup[new_idx] = existing_blocos_map[orig_idx]
                    break
    
    # 4. Distribuição em blocos (SEMPRE atribui blocos a todos os registros)
    # Cada bloco deve ter entre 5 e 10 registros quando possível
    records_with_blocks, cluster_audit = distribute_into_blocks(
        records, clusters, restaurant_col, instagram_col, address_col, 
        max_block_size=10,
        min_block_size=5,
        existing_blocos=existing_blocos_after_dedup if existing_blocos_after_dedup else None,
        start_block_num=max_existing_bloco + 1 if max_existing_bloco > 0 else 1
    )
    
    # Verifica que todos os registros receberam blocos
    records_without_blocks = [i for i, rec in enumerate(records_with_blocks) if 'Bloco' not in rec or rec.get('Bloco') is None]
    if records_without_blocks:
        logger.warning(f"ATENÇÃO: {len(records_without_blocks)} registros não receberam blocos. Corrigindo...")
        # Corrige atribuindo ao último bloco ou criando novo
        max_bloco = max((rec.get('Bloco', 0) or 0 for rec in records_with_blocks), default=0)
        for idx in records_without_blocks:
            records_with_blocks[idx]['Bloco'] = max_bloco + 1
    
    total_blocks = max((rec.get('Bloco', 0) or 0 for rec in records_with_blocks), default=0)
    logger.info(f"Distribuídos {len(records_with_blocks)} registros em {total_blocks} blocos (sem limite no número total de blocos)")
    
    # 5. Renumera coluna "#" se existir
    if '#' in df.columns:
        for idx, record in enumerate(records_with_blocks, start=1):
            record['#'] = idx
    else:
        # Adiciona coluna "#" se não existir
        for idx, record in enumerate(records_with_blocks, start=1):
            record['#'] = idx
    
    # 6. Cria DataFrame final preservando todas as colunas originais
    # Primeiro, cria um DataFrame com os registros processados
    df_final = pd.DataFrame(records_with_blocks)
    
    # Garante que a coluna Bloco existe
    if 'Bloco' not in df_final.columns:
        df_final['Bloco'] = None
    
    # Preserva todas as colunas originais do DataFrame
    # Adiciona colunas que possam estar faltando
    for col in df.columns:
        if col not in df_final.columns:
            df_final[col] = None
    
    # Reordena colunas: # primeiro, depois Bloco, depois as demais na ordem original
    original_cols = [col for col in df.columns if col not in ['#', 'Bloco']]
    final_cols = ['#'] + ['Bloco'] + original_cols
    
    # Garante que todas as colunas estejam presentes
    available_cols = [col for col in final_cols if col in df_final.columns]
    df_final = df_final[available_cols]
    
    # 7. Gera arquivo de saída
    if output_path is None:
        input_file = Path(input_path)
        output_path = str(input_file.parent / f"{input_file.stem}_deduplicado_sequenciado_preciso.xlsx")
    
    # Cria auditoria de deduplicação
    audit_dedup = audit_instagram + audit_address
    df_audit_dedup = pd.DataFrame(audit_dedup) if audit_dedup else pd.DataFrame(columns=[
        'Critério de Deduplicação', 'Linha Mantida', 'Linhas Removidas', 'Justificativa'
    ])
    
    # Renomeia colunas da auditoria para português
    if not df_audit_dedup.empty:
        df_audit_dedup.columns = ['Critério de Deduplicação', 'Linha Mantida', 'Linhas Removidas', 'Justificativa']
    
    # Cria auditoria de clusters
    df_audit_clusters = pd.DataFrame(cluster_audit) if cluster_audit else pd.DataFrame(columns=[
        'ID do Cluster', 'Restaurante / Instagram / Endereço', 'Critério de Associação', 'Bloco Atribuído'
    ])
    
    # Formata auditoria de clusters
    if not df_audit_clusters.empty and 'restaurantes' in df_audit_clusters.columns:
        # Expande lista de restaurantes em string formatada
        df_audit_clusters['Restaurante / Instagram / Endereço'] = df_audit_clusters['restaurantes'].apply(
            lambda x: '\n'.join([f"{r.get('restaurante', '')} | {r.get('instagram', '')} | {r.get('endereco', '')}" for r in x]) if isinstance(x, list) else ''
        )
        if 'blocos_atribuidos' in df_audit_clusters.columns:
            df_audit_clusters['Bloco Atribuído'] = df_audit_clusters['blocos_atribuidos'].apply(
                lambda x: ', '.join(map(str, x)) if isinstance(x, list) else str(x)
            )
        else:
            df_audit_clusters['Bloco Atribuído'] = ''
        
        # Seleciona e renomeia colunas
        cols_to_keep = ['id_cluster', 'Restaurante / Instagram / Endereço', 'criterio_associacao', 'Bloco Atribuído']
        available_cols = [col for col in cols_to_keep if col in df_audit_clusters.columns]
        df_audit_clusters = df_audit_clusters[available_cols]
        
        # Renomeia para português
        rename_map = {
            'id_cluster': 'ID do Cluster',
            'criterio_associacao': 'Critério de Associação'
        }
        df_audit_clusters = df_audit_clusters.rename(columns=rename_map)
    
    # Salva arquivo Excel com múltiplas abas
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_final.to_excel(writer, sheet_name='Restaurantes', index=False)
        df_audit_dedup.to_excel(writer, sheet_name='Auditoria Deduplicação', index=False)
        df_audit_clusters.to_excel(writer, sheet_name='Auditoria Clusters (Agrupamento por Grupo/Rede)', index=False)
    
    logger.info(f"Arquivo processado salvo em: {output_path}")
    
    return {
        'input_file': input_path,
        'output_file': output_path,
        'original_count': original_count,
        'final_count': len(records_with_blocks),
        'removed_count': original_count - len(records_with_blocks),
        'clusters_identified': len(clusters),
        'blocks_created': records_with_blocks[-1].get('Bloco', 0) if records_with_blocks else 0,
        'deduplication_audit_count': len(audit_dedup),
        'cluster_audit_count': len(cluster_audit)
    }


def process_restaurants_csv(input_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Processa CSV no template fixo (baseado em `database-api/Pizzarias e restaurantes em SP  - Página1.csv`):
    - Linha 1: banner (inclui "NÃO PREENCHER")
    - Linha 2: header real
    - Demais linhas: dados

    Regras adicionais pedidas pelo usuário:
    - Usar SEMPRE a estrutura desse template (especialmente a 2ª linha)
    - NÃO levar em consideração (na lógica) colunas sob banner "NÃO PREENCHER"
      (mas preservá-las no arquivo final, pois serão usadas posteriormente)
    
    ATRIBUIÇÃO AUTOMÁTICA DE BLOCOS:
    - Todos os registros recebem automaticamente um número de bloco
    - Blocos são criados sem limite no número total (cria quantos forem necessários)
    - Cada bloco contém entre 5 e 10 registros (quando possível)
    - Registros do mesmo cluster/grupo/rede são sempre separados em blocos distintos
    """
    df, headers, banners, internal_to_original = load_restaurants_template_csv(input_path)

    # Detecta posições no template e mapeia para colunas internas
    idxs = _detect_template_columns(headers, banners)
    if idxs.get("restaurant") is None or idxs.get("instagram") is None:
        raise ValueError("Template CSV inválido: não encontrei colunas RESTAURANTE e INSTAGRAM na linha 2")

    internal_cols = list(df.columns)
    def internal_col_at(idx: Optional[int]) -> Optional[str]:
        if idx is None:
            return None
        if idx < 0 or idx >= len(internal_cols):
            return None
        return internal_cols[idx]

    restaurant_col = internal_col_at(idxs["restaurant"])
    instagram_col = internal_col_at(idxs["instagram"])
    address_col = internal_col_at(idxs["address"])
    bloco_col = internal_col_at(idxs["bloco"])
    hash_col = internal_col_at(idxs["hash"])
    date_col = internal_col_at(idxs["date"])
    persona_col = internal_col_at(idxs["persona"])
    phrase_col = internal_col_at(idxs["phrase"])
    cliente_col = internal_col_at(idxs["cliente"])

    # Verifica se coluna "cliente" existe; se não, cria e preenche com "não"
    if cliente_col is None:
        # Cria nova coluna "cliente" no DataFrame
        cliente_col = "col_cliente"
        df[cliente_col] = "não"
        # Adiciona ao mapeamento de colunas internas para originais
        internal_to_original[cliente_col] = "Cliente"
        logger.info(f"[CSV] Coluna 'cliente' não encontrada. Criada e preenchida com 'não' para todos os registros.")
    else:
        logger.info(f"[CSV] Coluna 'cliente' encontrada. Usando valores existentes.")

    # Converte para lista de dicts (usando nomes internos únicos)
    records = df.to_dict("records")
    original_count = len(records)
    logger.info(f"[CSV] Processando {original_count} registros...")

    # Manutenção incremental: preserva blocos existentes (se existir coluna "Bloco" no template)
    existing_blocos_map: Dict[int, int] = {}
    if bloco_col:
        for i, rec in enumerate(records):
            v = rec.get(bloco_col, "")
            if v is None:
                continue
            v = str(v).strip()
            if not v:
                continue
            try:
                existing_blocos_map[i] = int(float(v))
            except (ValueError, TypeError):
                continue
    max_existing_bloco = max(existing_blocos_map.values()) if existing_blocos_map else 0

    # 1) Deduplicação por Instagram idêntico (conservadora, auditável)
    records, audit_instagram = deduplicate_by_instagram(
        records,
        instagram_col=instagram_col,
        date_col=date_col,
        persona_col=persona_col,
        phrase_col=phrase_col,
        restaurant_col=restaurant_col,
        address_col=address_col,
    )
    logger.info(f"[CSV] Após deduplicação por Instagram: {len(records)} registros")

    # 2) Deduplicação por Endereço Estrito (apenas se houver coluna de endereço)
    audit_address: List[Dict[str, Any]] = []
    if address_col:
        records, audit_address = deduplicate_by_address(
            records,
            address_col=address_col,
            date_col=date_col,
            persona_col=persona_col,
            phrase_col=phrase_col,
            restaurant_col=restaurant_col,
            instagram_col=instagram_col,
        )
        logger.info(f"[CSV] Após deduplicação por Endereço: {len(records)} registros")

    # 3) Clusters (sem exclusão)
    clusters = identify_clusters(
        records,
        restaurant_col=restaurant_col,
        instagram_col=instagram_col,
        address_col=address_col or "",
    )
    logger.info(f"[CSV] Identificados {len(clusters)} clusters")

    # 4) Blocos (entre 5 e 10 por bloco, SEM LIMITE no número total de blocos) preservando blocos existentes
    # SEMPRE atribui blocos a todos os registros automaticamente
    records_with_blocks, cluster_audit = distribute_into_blocks(
        records,
        clusters,
        restaurant_col=restaurant_col,
        instagram_col=instagram_col,
        address_col=address_col,
        max_block_size=10,
        min_block_size=5,
        existing_blocos=existing_blocos_map if existing_blocos_map else None,
        start_block_num=max_existing_bloco + 1 if max_existing_bloco > 0 else 1,
    )
    
    # Verifica que todos os registros receberam blocos
    records_without_blocks = [i for i, rec in enumerate(records_with_blocks) if 'Bloco' not in rec or rec.get('Bloco') is None]
    if records_without_blocks:
        logger.warning(f"[CSV] ATENÇÃO: {len(records_without_blocks)} registros não receberam blocos. Corrigindo...")
        # Corrige atribuindo ao último bloco ou criando novo
        max_bloco = max((rec.get('Bloco', 0) or 0 for rec in records_with_blocks), default=0)
        for idx in records_without_blocks:
            records_with_blocks[idx]['Bloco'] = max_bloco + 1
    
    total_blocks = max((rec.get('Bloco', 0) or 0 for rec in records_with_blocks), default=0)
    logger.info(f"[CSV] Distribuídos {len(records_with_blocks)} registros em {total_blocks} blocos (sem limite no número total de blocos)")

    # 5) Atualiza coluna "#" em ordem sequencial (usa a coluna # do template se existir; senão cria)
    if hash_col:
        for i, rec in enumerate(records_with_blocks, start=1):
            rec[hash_col] = str(i)
    else:
        # Cria uma coluna interna extra ao final
        new_hash_internal = f"col_{len(headers):03d}"
        internal_to_original[new_hash_internal] = "#"
        headers = headers + ["#"]
        banners = banners + [""]
        for i, rec in enumerate(records_with_blocks, start=1):
            rec[new_hash_internal] = str(i)
        hash_col = new_hash_internal

    # 6) Garante que a coluna "Bloco" exista (usa a do template se existir)
    if not bloco_col:
        new_bloco_internal = f"col_{len(headers):03d}"
        internal_to_original[new_bloco_internal] = "Bloco"
        headers = headers + ["Bloco"]
        banners = banners + [""]
        for rec in records_with_blocks:
            rec[new_bloco_internal] = str(rec.get("Bloco", ""))
        bloco_col = new_bloco_internal
    else:
        # Copia o valor calculado para a coluna Bloco do template
        for rec in records_with_blocks:
            rec[bloco_col] = str(rec.get("Bloco", ""))
    
    # 7) Garante que a coluna "Cliente" exista no output final (já foi criada antes se não existia)
    if cliente_col:
        # Garante que todos os registros tenham a coluna cliente
        for rec in records_with_blocks:
            if cliente_col not in rec:
                rec[cliente_col] = "não"

    # 8) Reconstrói DataFrame final com mesma ordem e headers originais
    df_final_internal = pd.DataFrame(records_with_blocks)

    # garante todas as colunas internas originais presentes (mesma ordem)
    desired_internal_order = list(internal_to_original.keys())
    for col in desired_internal_order:
        if col not in df_final_internal.columns:
            df_final_internal[col] = ""
    df_final_internal = df_final_internal[desired_internal_order]

    # troca nomes internos pelos headers originais (pode ter duplicados; Excel aceita)
    original_headers_ordered = [internal_to_original[c] for c in desired_internal_order]
    df_final_internal.columns = original_headers_ordered

    # Output
    if output_path is None:
        input_file = Path(input_path)
        output_path = str(input_file.parent / f"{input_file.stem}_deduplicado_sequenciado_preciso.xlsx")

    # Auditoria Deduplicação
    audit_dedup = audit_instagram + audit_address
    df_audit_dedup = pd.DataFrame(audit_dedup) if audit_dedup else pd.DataFrame(
        columns=["Critério de Deduplicação", "Linha Mantida", "Linhas Removidas", "Justificativa"]
    )
    if not df_audit_dedup.empty and list(df_audit_dedup.columns) != ["Critério de Deduplicação", "Linha Mantida", "Linhas Removidas", "Justificativa"]:
        df_audit_dedup.columns = ["Critério de Deduplicação", "Linha Mantida", "Linhas Removidas", "Justificativa"]

    # Auditoria Clusters
    df_audit_clusters = pd.DataFrame(cluster_audit) if cluster_audit else pd.DataFrame(
        columns=["ID do Cluster", "Restaurante / Instagram / Endereço", "Critério de Associação", "Bloco Atribuído"]
    )
    if not df_audit_clusters.empty and "restaurantes" in df_audit_clusters.columns:
        df_audit_clusters["Restaurante / Instagram / Endereço"] = df_audit_clusters["restaurantes"].apply(
            lambda x: "\n".join(
                [f"{r.get('restaurante', '')} | {r.get('instagram', '')} | {r.get('endereco', '')}" for r in x]
            )
            if isinstance(x, list)
            else ""
        )
        df_audit_clusters["Bloco Atribuído"] = df_audit_clusters.get("blocos_atribuidos", "").apply(
            lambda x: ", ".join(map(str, x)) if isinstance(x, list) else str(x)
        )
        cols_to_keep = ["id_cluster", "Restaurante / Instagram / Endereço", "criterio_associacao", "Bloco Atribuído"]
        df_audit_clusters = df_audit_clusters[[c for c in cols_to_keep if c in df_audit_clusters.columns]]
        df_audit_clusters = df_audit_clusters.rename(
            columns={"id_cluster": "ID do Cluster", "criterio_associacao": "Critério de Associação"}
        )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_final_internal.to_excel(writer, sheet_name="Restaurantes", index=False)
        df_audit_dedup.to_excel(writer, sheet_name="Auditoria Deduplicação", index=False)
        df_audit_clusters.to_excel(writer, sheet_name="Auditoria Clusters (Agrupamento por Grupo/Rede)", index=False)

    logger.info(f"[CSV] Arquivo processado salvo em: {output_path}")
    return {
        "input_file": input_path,
        "output_file": output_path,
        "original_count": original_count,
        "final_count": len(records_with_blocks),
        "removed_count": original_count - len(records_with_blocks),
        "clusters_identified": len(clusters),
        "blocks_created": int(max(rec.get("Bloco", 0) or 0 for rec in records_with_blocks)) if records_with_blocks else 0,
        "deduplication_audit_count": len(audit_dedup),
        "cluster_audit_count": len(cluster_audit),
    }


def assign_blocks_to_restaurants(restaurants: List[Dict[str, Any]], 
                                 start_block_num: int = 1) -> List[Dict[str, Any]]:
    """
    Atribui blocos automaticamente a uma lista de restaurantes usando a lógica de agrupamento.
    
    Esta função é usada quando restaurantes são criados via bulk e precisam receber blocos
    automaticamente baseado nos critérios de deduplicação e agrupamento.
    
    Args:
        restaurants: Lista de restaurantes no formato:
            [
                {
                    "instagram_username": str,
                    "name": str,
                    "bloco": Optional[int],  # Se já tiver, preserva; se não tiver, atribui
                    "cliente": bool,
                    ...outros campos...
                },
                ...
            ]
        start_block_num: Número inicial do bloco (padrão: 1)
    
    Returns:
        Lista de restaurantes com blocos atribuídos (campo "bloco" sempre preenchido)
    """
    if not restaurants:
        return restaurants
    
    # Converte para o formato usado pelo processador
    records = []
    for idx, rest in enumerate(restaurants):
        record = {
            "restaurant": rest.get("name", ""),
            "instagram": rest.get("instagram_username", ""),
            "address": "",  # Endereço não está disponível no bulk, mas não impede o processamento
            "bloco_existente": rest.get("bloco"),  # Preserva bloco existente se houver
            "cliente": rest.get("cliente", False),
            "_original_index": idx,  # Para mapear de volta
            "_original_data": rest,  # Preserva dados originais
        }
        records.append(record)
    
    # Identifica clusters (mesmo grupo/rede/dono)
    clusters = identify_clusters(
        records,
        restaurant_col="restaurant",
        instagram_col="instagram",
        address_col="address"
    )
    
    # Preserva blocos existentes se houver
    existing_blocos_map = {}
    for idx, rec in enumerate(records):
        bloco_existente = rec.get("bloco_existente")
        if bloco_existente is not None and isinstance(bloco_existente, (int, float)):
            existing_blocos_map[idx] = int(bloco_existente)
    
    # Determina número inicial do bloco
    if existing_blocos_map:
        max_existing = max(existing_blocos_map.values())
        actual_start_block = max_existing + 1
    else:
        actual_start_block = start_block_num
    
    # Distribui em blocos (entre 5 e 10 registros por bloco quando possível)
    records_with_blocks, _ = distribute_into_blocks(
        records,
        clusters,
        restaurant_col="restaurant",
        instagram_col="instagram",
        address_col="address",
        max_block_size=10,
        min_block_size=5,
        existing_blocos=existing_blocos_map if existing_blocos_map else None,
        start_block_num=actual_start_block
    )
    
    # Converte de volta para o formato original e atribui blocos
    result = []
    for rec in records_with_blocks:
        original = rec.get("_original_data", {})
        bloco_atribuido = rec.get("Bloco")
        
        # Garante que o bloco está preenchido
        if bloco_atribuido is None:
            # Se não foi atribuído, usa o existente ou atribui ao próximo bloco disponível
            bloco_atribuido = original.get("bloco") or actual_start_block
        
        # Cria novo dict com bloco atribuído
        new_rest = dict(original)
        new_rest["bloco"] = int(bloco_atribuido)
        result.append(new_rest)
    
    max_bloco = max((r.get('bloco', 0) or 0) for r in result) if result else 0
    logger.info(f"Atribuídos blocos a {len(result)} restaurantes. Total de blocos: {max_bloco}")
    
    return result
