import sqlite3
from typing import Generator

DB_FILE = "database.db"

def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS restaurantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        instagram TEXT UNIQUE,
        bloco INTEGER NOT NULL,
        ultima_frase INTEGER DEFAULT 0,
        ultima_persona TEXT DEFAULT '',
        criado_em TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS personas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT,
        username TEXT,
        senha TEXT,
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS frases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero INTEGER UNIQUE NOT NULL,
        texto TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS envios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        restaurante_id INTEGER,
        persona_id INTEGER,
        frase_id INTEGER,
        data_envio TEXT DEFAULT (datetime('now')),
        bloco INTEGER
    )''')

    conn.commit()
    conn.close()