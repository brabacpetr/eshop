import sqlite3
import os

def ziskat_cestu_databaze():
    """Vrátí absolutní cestu k databázi shop.db v stejném adresáři jako tento skript."""
    aktualni_adresar = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(aktualni_adresar, 'shop.db')


def ziskat_db():
    """Otevře připojení k databázi s row_factory nastaveným na sqlite3.Row."""
    cesta_db = ziskat_cestu_databaze()
    pripojeni = sqlite3.connect(cesta_db)
    pripojeni.row_factory = sqlite3.Row
    return pripojeni


def inicializovat_db():
    """Vytvoří všechny tabulky pokud ještě neexistují."""
    pripojeni = ziskat_db()
    kurzor = pripojeni.cursor()

    # Tabulka kategorií
    kurzor.execute('''
        CREATE TABLE IF NOT EXISTS kategorie (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazev TEXT NOT NULL UNIQUE
        )
    ''')

    # Tabulka produktů
    kurzor.execute('''
        CREATE TABLE IF NOT EXISTS produkt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nazev TEXT NOT NULL,
            popis TEXT,
            cena REAL NOT NULL,
            kategorie_id INTEGER REFERENCES kategorie(id),
            sklad INTEGER NOT NULL DEFAULT 0,
            je_doporuceny INTEGER NOT NULL DEFAULT 0,
            obrazek TEXT
        )
    ''')

    # Tabulka objednávek
    kurzor.execute('''
        CREATE TABLE IF NOT EXISTS objednavka (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jmeno_zakaznika TEXT NOT NULL,
            email_zakaznika TEXT NOT NULL,
            telefon_zakaznika TEXT,
            ulice TEXT NOT NULL,
            mesto TEXT NOT NULL,
            psc TEXT NOT NULL,
            doprava TEXT NOT NULL,
            platba TEXT NOT NULL,
            stav TEXT NOT NULL DEFAULT 'nova',
            kupon_id INTEGER REFERENCES slevovy_kupon(id),
            mezisoucet REAL NOT NULL,
            sleva REAL NOT NULL DEFAULT 0,
            celkem REAL NOT NULL,
            vytvoreno TEXT NOT NULL
        )
    ''')

    # Tabulka položek objednávky
    kurzor.execute('''
        CREATE TABLE IF NOT EXISTS polozka_objednavky (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            objednavka_id INTEGER NOT NULL REFERENCES objednavka(id),
            produkt_id INTEGER REFERENCES produkt(id),
            nazev_produktu TEXT NOT NULL,
            cena_produktu REAL NOT NULL,
            mnozstvi INTEGER NOT NULL
        )
    ''')

    # Tabulka slevových kuponů
    kurzor.execute('''
        CREATE TABLE IF NOT EXISTS slevovy_kupon (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kod TEXT NOT NULL UNIQUE,
            sleva_procent INTEGER NOT NULL,
            datum_expirace TEXT,
            limit_pouziti INTEGER,
            pocet_pouziti INTEGER NOT NULL DEFAULT 0
        )
    ''')

    pripojeni.commit()
    pripojeni.close()


def naplnit_db():
    """Vloží testovací data. Je idempotentní - pokud data již existují, přeskočí vkládání."""
    pripojeni = ziskat_db()
    kurzor = pripojeni.cursor()

    # Zkontroluj, zda již existují kategorie
    kurzor.execute('SELECT COUNT(*) as pocet FROM kategorie')
    pocet_kategorii = kurzor.fetchone()['pocet']

    if pocet_kategorii > 0:
        print("Databáze již obsahuje data. Vynechávám naplnění.")
        pripojeni.close()
        return

    # Vložení kategorií
    kategorie = [
        ('Elektronika',),
        ('Oblečení',),
        ('Knihy',)
    ]
    kurzor.executemany('INSERT INTO kategorie (nazev) VALUES (?)', kategorie)
    pripojeni.commit()

    # Vložení produktů
    produkty = [
        ('Bezdrátová sluchátka', 'Kvalitní bezdrátová sluchátka s aktivním potlačením hluku', 1299.00, 1, 15, 1, 'placeholder.jpg'),
        ('USB-C Kabel', 'Odolný USB-C kabel, délka 2m', 199.00, 1, 50, 0, 'placeholder.jpg'),
        ('Pánské tričko', 'Pohodlné bavlněné tričko v více barvách', 399.00, 2, 30, 1, 'placeholder.jpg'),
        ('Dámský svetr', 'Příjemný a teplý svetr z přírodních materiálů', 599.00, 2, 20, 0, 'placeholder.jpg'),
        ('Učebnice Pythonu', 'Obsáhlá příručka pro začátečníky i pokročilé', 499.00, 3, 25, 1, 'placeholder.jpg'),
        ('Detektivní román', 'Napínavý román v češtině od známého autora', 349.00, 3, 40, 0, 'placeholder.jpg')
    ]
    kurzor.executemany(
        'INSERT INTO produkt (nazev, popis, cena, kategorie_id, sklad, je_doporuceny, obrazek) VALUES (?, ?, ?, ?, ?, ?, ?)',
        produkty
    )
    pripojeni.commit()

    # Vložení slevového kuponu
    kupon = ('TEST10', 10, None, None)
    kurzor.execute(
        'INSERT INTO slevovy_kupon (kod, sleva_procent, datum_expirace, limit_pouziti) VALUES (?, ?, ?, ?)',
        kupon
    )
    pripojeni.commit()

    print("Databáze byla úspěšně naplněna testovacími daty.")
    pripojeni.close()
