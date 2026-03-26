"""
E-shop aplikace s Flask a SQLite
"""
from flask import Flask, jsonify, render_template, flash, redirect, url_for, request, abort, session
from databaze import inicializovat_db, ziskat_db
from functools import wraps
from werkzeug.utils import secure_filename
import datetime
import os
import uuid

# Vytvoření Flask aplikace
app = Flask(__name__)

# Nastavení tajného klíče pro relace a flash zprávy
app.secret_key = 'k7mP9wQxZ2nL4bVjHrTyFgS1DaEcIuOp'

# Heslo administrátora
ADMIN_HESLO = os.environ.get('ADMIN_HESLO', 'admin123')

# Cesta ke složce pro nahrávání obrázků
SLOZKA_OBRAZKU = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')

# Inicializace databáze při importu aplikace
inicializovat_db()


def admin_required(f):
    """Dekorátor chránící admin route — přesměruje na přihlášení pokud admin není přihlášen."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_prihlaseni'))
        return f(*args, **kwargs)
    return wrapper


@app.route('/')
def index():
    """
    Hlavní stránka e-shopu - zobrazí doporučené produkty
    """
    databaze = ziskat_db()
    doporucene = databaze.execute(
        'SELECT p.*, k.nazev as kategorie_nazev FROM produkt p '
        'LEFT JOIN kategorie k ON p.kategorie_id = k.id WHERE p.je_doporuceny = 1'
    ).fetchall()
    databaze.close()
    return render_template('index.html', doporucene=doporucene)


@app.route('/produkty')
def produkty():
    """
    Seznam všech produktů s možností filtrování podle kategorie
    """
    databaze = ziskat_db()
    aktivni_kategorie_id = request.args.get('kategorie', type=int)

    if aktivni_kategorie_id:
        seznam_produktu = databaze.execute(
            'SELECT p.*, k.nazev as kategorie_nazev FROM produkt p '
            'LEFT JOIN kategorie k ON p.kategorie_id = k.id WHERE p.kategorie_id = ?',
            (aktivni_kategorie_id,)
        ).fetchall()
    else:
        seznam_produktu = databaze.execute(
            'SELECT p.*, k.nazev as kategorie_nazev FROM produkt p '
            'LEFT JOIN kategorie k ON p.kategorie_id = k.id'
        ).fetchall()

    kategorie = databaze.execute('SELECT * FROM kategorie ORDER BY nazev').fetchall()
    databaze.close()
    return render_template('produkty.html', produkty=seznam_produktu,
                           kategorie=kategorie, aktivni_kategorie_id=aktivni_kategorie_id)


@app.route('/produkt/<int:produkt_id>')
def detail_produktu(produkt_id):
    """
    Detail produktu
    """
    databaze = ziskat_db()
    produkt = databaze.execute(
        'SELECT p.*, k.nazev as kategorie_nazev FROM produkt p '
        'LEFT JOIN kategorie k ON p.kategorie_id = k.id WHERE p.id = ?',
        (produkt_id,)
    ).fetchone()
    databaze.close()
    if produkt is None:
        abort(404)
    return render_template('detail_produktu.html', produkt=produkt)


@app.route('/debug/produkty')
def debug_produkty():
    """
    Debug route pro vrácení všech produktů z databáze jako JSON
    """
    databaze = ziskat_db()
    kurzor = databaze.cursor()
    kurzor.execute('SELECT * FROM produkt')
    sloupce = [sloupec[0] for sloupec in kurzor.description]
    produkty = []

    for radek in kurzor.fetchall():
        produkt = {}
        for i, sloupec in enumerate(sloupce):
            produkt[sloupec] = radek[i]
        produkty.append(produkt)

    return jsonify(produkty)



@app.route('/kosik/pridat', methods=['POST'])
def pridat_do_kosiku():
    # Přidání produktu do košíku
    produkt_id = request.form.get('produkt_id', type=int)
    mnozstvi = request.form.get('mnozstvi', type=int) or 1

    if not produkt_id or mnozstvi < 1:
        flash('Neplatný požadavek.', 'error')
        return redirect(url_for('produkty'))

    databaze = ziskat_db()
    produkt = databaze.execute('SELECT * FROM produkt WHERE id = ?', (produkt_id,)).fetchone()
    databaze.close()

    if produkt is None:
        abort(404)

    kosik = session.get('kosik', {})
    stavajici_mnozstvi = kosik.get(str(produkt_id), 0)
    nove_mnozstvi = stavajici_mnozstvi + mnozstvi

    if nove_mnozstvi > produkt['sklad']:
        flash(
            f'Nelze přidat {mnozstvi} ks — na skladě je pouze {produkt["sklad"]} ks '
            f'(v košíku již máte {stavajici_mnozstvi} ks).',
            'error'
        )
        return redirect(url_for('detail_produktu', produkt_id=produkt_id))

    kosik[str(produkt_id)] = nove_mnozstvi
    session['kosik'] = kosik
    flash(f'Produkt „{produkt["nazev"]}" byl přidán do košíku.', 'success')
    return redirect(url_for('zobraz_kosik'))


@app.route('/kosik')
def zobraz_kosik():
    # Zobrazení košíku
    kosik = session.get('kosik', {})
    polozky = []
    mezisoucet = 0.0

    if kosik:
        databaze = ziskat_db()
        for produkt_id_str, mnozstvi in list(kosik.items()):
            produkt = databaze.execute(
                'SELECT * FROM produkt WHERE id = ?', (int(produkt_id_str),)
            ).fetchone()
            if produkt is None:
                # Produkt byl smazán — tiše odebrat z košíku
                del kosik[produkt_id_str]
                session['kosik'] = kosik
                continue
            radek_cena = produkt['cena'] * mnozstvi
            mezisoucet += radek_cena
            polozky.append({
                'produkt_id': int(produkt_id_str),
                'nazev': produkt['nazev'],
                'cena': produkt['cena'],
                'obrazek': produkt['obrazek'],
                'mnozstvi': mnozstvi,
                'radek_cena': radek_cena,
                'sklad': produkt['sklad'],
            })
        databaze.close()

    # Slevový kupón
    sleva = 0.0
    kupon = None
    kupon_id = session.get('kupon_id')
    if kupon_id:
        databaze = ziskat_db()
        kupon = databaze.execute(
            'SELECT * FROM slevovy_kupon WHERE id = ?', (kupon_id,)
        ).fetchone()
        databaze.close()
        if kupon:
            sleva = round(mezisoucet * kupon['sleva_procent'] / 100, 2)

    celkem = round(mezisoucet - sleva, 2)
    return render_template('kosik.html', polozky=polozky,
                           mezisoucet=round(mezisoucet, 2),
                           sleva=sleva, celkem=celkem, kupon=kupon)


@app.route('/kosik/aktualizovat', methods=['POST'])
def aktualizovat_kosik():
    # Aktualizace množství položky v košíku
    produkt_id = request.form.get('produkt_id', type=int)
    mnozstvi = request.form.get('mnozstvi', type=int) or 0

    if not produkt_id:
        return redirect(url_for('zobraz_kosik'))

    kosik = session.get('kosik', {})

    if mnozstvi <= 0:
        kosik.pop(str(produkt_id), None)
        session['kosik'] = kosik
        flash('Položka byla odebrána z košíku.', 'info')
        return redirect(url_for('zobraz_kosik'))

    databaze = ziskat_db()
    produkt = databaze.execute('SELECT * FROM produkt WHERE id = ?', (produkt_id,)).fetchone()
    databaze.close()

    if produkt is None or mnozstvi > produkt['sklad']:
        flash('Požadované množství není dostupné.', 'error')
        return redirect(url_for('zobraz_kosik'))

    kosik[str(produkt_id)] = mnozstvi
    session['kosik'] = kosik
    return redirect(url_for('zobraz_kosik'))


@app.route('/kosik/odebrat', methods=['POST'])
def odebrat_z_kosiku():
    # Odebrání položky z košíku
    produkt_id = request.form.get('produkt_id', type=int)
    kosik = session.get('kosik', {})
    if produkt_id:
        kosik.pop(str(produkt_id), None)
        session['kosik'] = kosik
    flash('Položka byla odebrána z košíku.', 'success')
    return redirect(url_for('zobraz_kosik'))


@app.route('/kosik/kupon', methods=['POST'])
def pouzit_kupon():
    # Uplatnění slevového kupónu
    kod = request.form.get('kod', '').strip().upper()

    if not kod:
        flash('Zadejte kód kupónu.', 'error')
        return redirect(url_for('zobraz_kosik'))

    databaze = ziskat_db()
    kupon = databaze.execute(
        'SELECT * FROM slevovy_kupon WHERE UPPER(kod) = ?', (kod,)
    ).fetchone()
    databaze.close()

    if kupon is None:
        flash('Neplatný kód kupónu.', 'error')
        return redirect(url_for('zobraz_kosik'))

    # Kontrola expirace
    if kupon['datum_expirace']:
        dnes = datetime.date.today()
        if dnes > datetime.date.fromisoformat(kupon['datum_expirace']):
            flash('Platnost tohoto kupónu vypršela.', 'error')
            return redirect(url_for('zobraz_kosik'))

    # Kontrola limitu použití
    if kupon['limit_pouziti'] is not None and kupon['pocet_pouziti'] >= kupon['limit_pouziti']:
        flash('Tento kupón byl již plně vyčerpán.', 'error')
        return redirect(url_for('zobraz_kosik'))

    session['kupon_id'] = kupon['id']
    flash(f'Kupón {kupon["kod"]} byl uplatněn — sleva {kupon["sleva_procent"]} %.', 'success')
    return redirect(url_for('zobraz_kosik'))


CENA_DOPRAVY = {'posta': 89.0, 'dpd': 119.0}
PRIPLATEK_DOBIRKA = 30.0


def _nacist_polozky_kosiku(kosik):
    """Načte položky košíku z databáze a vrátí seznam i mezisoučet."""
    polozky = []
    mezisoucet = 0.0
    databaze = ziskat_db()
    for produkt_id_str, mnozstvi in list(kosik.items()):
        produkt = databaze.execute(
            'SELECT * FROM produkt WHERE id = ?', (int(produkt_id_str),)
        ).fetchone()
        if produkt is None:
            kosik.pop(produkt_id_str, None)
            session['kosik'] = kosik
            continue
        radek_cena = produkt['cena'] * mnozstvi
        mezisoucet += radek_cena
        polozky.append({
            'produkt_id': int(produkt_id_str),
            'nazev': produkt['nazev'],
            'cena': produkt['cena'],
            'mnozstvi': mnozstvi,
            'radek_cena': radek_cena,
        })
    databaze.close()
    return polozky, round(mezisoucet, 2)


def _nacist_kupon(kupon_id, mezisoucet):
    """Vrátí kupon a vypočtenou slevu, nebo (None, 0.0)."""
    if not kupon_id:
        return None, 0.0
    databaze = ziskat_db()
    kupon = databaze.execute(
        'SELECT * FROM slevovy_kupon WHERE id = ?', (kupon_id,)
    ).fetchone()
    databaze.close()
    if kupon is None:
        return None, 0.0
    sleva = round(mezisoucet * kupon['sleva_procent'] / 100, 2)
    return kupon, sleva


@app.route('/pokladna', methods=['GET', 'POST'])
def pokladna():
    # Přesměruj na košík pokud je prázdný
    kosik = session.get('kosik', {})
    if not kosik:
        flash('Váš košík je prázdný.', 'info')
        return redirect(url_for('zobraz_kosik'))

    polozky, mezisoucet = _nacist_polozky_kosiku(kosik)
    kupon_id = session.get('kupon_id')
    kupon, sleva = _nacist_kupon(kupon_id, mezisoucet)

    if request.method == 'GET':
        return render_template('pokladna.html', polozky=polozky,
                               mezisoucet=mezisoucet, sleva=sleva, kupon=kupon,
                               cena_dopravy=CENA_DOPRAVY,
                               priplatek_dobirka=PRIPLATEK_DOBIRKA,
                               chyby={}, formular={})

    # POST — zpracování objednávky
    jmeno = request.form.get('jmeno', '').strip()
    email = request.form.get('email', '').strip()
    telefon = request.form.get('telefon', '').strip()
    ulice = request.form.get('ulice', '').strip()
    mesto = request.form.get('mesto', '').strip()
    psc = request.form.get('psc', '').strip()
    doprava = request.form.get('doprava', '')
    platba = request.form.get('platba', '')

    chyby = {}
    if not jmeno:
        chyby['jmeno'] = 'Jméno je povinné.'
    if not email:
        chyby['email'] = 'E-mail je povinný.'
    if not ulice:
        chyby['ulice'] = 'Ulice je povinná.'
    if not mesto:
        chyby['mesto'] = 'Město je povinné.'
    if not psc:
        chyby['psc'] = 'PSČ je povinné.'
    if doprava not in CENA_DOPRAVY:
        chyby['doprava'] = 'Vyberte způsob dopravy.'
    if platba not in ('prevod', 'dobirka'):
        chyby['platba'] = 'Vyberte způsob platby.'

    if chyby:
        formular = {'jmeno': jmeno, 'email': email, 'telefon': telefon,
                    'ulice': ulice, 'mesto': mesto, 'psc': psc,
                    'doprava': doprava, 'platba': platba}
        return render_template('pokladna.html', polozky=polozky,
                               mezisoucet=mezisoucet, sleva=sleva, kupon=kupon,
                               cena_dopravy=CENA_DOPRAVY,
                               priplatek_dobirka=PRIPLATEK_DOBIRKA,
                               chyby=chyby, formular=formular)

    # Výpočet celkové ceny
    hodnota_dopravy = CENA_DOPRAVY[doprava]
    poplatek_dobirka = PRIPLATEK_DOBIRKA if platba == 'dobirka' else 0.0
    celkem = round(mezisoucet + hodnota_dopravy + poplatek_dobirka - sleva, 2)

    # Uložení objednávky do databáze
    databaze = ziskat_db()
    kurzor = databaze.cursor()
    cas_vytvoreni = datetime.datetime.now().isoformat(timespec='seconds')
    kurzor.execute(
        '''INSERT INTO objednavka
           (jmeno_zakaznika, email_zakaznika, telefon_zakaznika, ulice, mesto, psc,
            doprava, platba, stav, kupon_id, mezisoucet, sleva, celkem, vytvoreno)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'nova', ?, ?, ?, ?, ?)''',
        (jmeno, email, telefon, ulice, mesto, psc, doprava, platba,
         kupon_id, mezisoucet, sleva, celkem, cas_vytvoreni)
    )
    objednavka_id = kurzor.lastrowid

    # Uložení položek objednávky a snížení skladu
    for polozka in polozky:
        kurzor.execute(
            '''INSERT INTO polozka_objednavky
               (objednavka_id, produkt_id, nazev_produktu, cena_produktu, mnozstvi)
               VALUES (?, ?, ?, ?, ?)''',
            (objednavka_id, polozka['produkt_id'],
             polozka['nazev'], polozka['cena'], polozka['mnozstvi'])
        )
        kurzor.execute(
            'UPDATE produkt SET sklad = sklad - ? WHERE id = ?',
            (polozka['mnozstvi'], polozka['produkt_id'])
        )

    # Zvýšení počtu použití kupónu
    if kupon_id:
        kurzor.execute(
            'UPDATE slevovy_kupon SET pocet_pouziti = pocet_pouziti + 1 WHERE id = ?',
            (kupon_id,)
        )

    databaze.commit()
    databaze.close()

    # Vymazání košíku a kupónu ze session
    session.pop('kosik', None)
    session.pop('kupon_id', None)

    return redirect(url_for('potvrzeni_objednavky', objednavka_id=objednavka_id))


@app.route('/objednavka/<int:objednavka_id>')
def potvrzeni_objednavky(objednavka_id):
    databaze = ziskat_db()
    objednavka = databaze.execute(
        'SELECT * FROM objednavka WHERE id = ?', (objednavka_id,)
    ).fetchone()
    if objednavka is None:
        databaze.close()
        abort(404)
    polozky = databaze.execute(
        'SELECT * FROM polozka_objednavky WHERE objednavka_id = ?', (objednavka_id,)
    ).fetchall()
    kupon = None
    if objednavka['kupon_id']:
        kupon = databaze.execute(
            'SELECT * FROM slevovy_kupon WHERE id = ?', (objednavka['kupon_id'],)
        ).fetchone()
    databaze.close()
    return render_template('potvrzeni_objednavky.html',
                           objednavka=objednavka, polozky=polozky, kupon=kupon,
                           cena_dopravy=CENA_DOPRAVY)


STATICKE_STRANKY = {
    'podminky': {
        'titulek': 'Obchodní podmínky',
        'sekce': [
            ('1. Základní ustanovení',
             'Tyto obchodní podmínky upravují práva a povinnosti prodávajícího a kupujícího '
             'při nákupu zboží prostřednictvím internetového obchodu MůjShop.'),
            ('2. Objednávka a uzavření smlouvy',
             'Objednávku podáváte vyplněním a odesláním objednávkového formuláře. '
             'Po přijetí objednávky vám zašleme potvrzení e-mailem. '
             'Kupní smlouva je uzavřena okamžikem odeslání potvrzení.'),
            ('3. Ceny a platba',
             'Všechny ceny jsou uvedeny včetně DPH. Přijímáme platbu bankovním převodem '
             'a dobírkou. U bankovního převodu je splatnost 5 pracovních dní od objednávky.'),
            ('4. Dodací podmínky',
             'Zboží doručujeme prostřednictvím České pošty nebo přepravní společnosti DPD. '
             'Standardní doba dodání je 2–5 pracovních dní od potvrzení objednávky.'),
            ('5. Odstoupení od smlouvy',
             'V souladu s § 1829 odst. 1 OZ máte právo odstoupit od smlouvy do 14 dnů '
             'od převzetí zboží bez udání důvodu. Zboží musí být vráceno nepoškozené '
             'v původním obalu.'),
        ]
    },
    'soukromi': {
        'titulek': 'Ochrana osobních údajů',
        'sekce': [
            ('Zpracování osobních údajů',
             'Vaše osobní údaje (jméno, adresa, e-mail, telefon) zpracováváme výhradně '
             'za účelem vyřízení objednávky a doručení zboží. Nepředáváme je třetím '
             'stranám s výjimkou dopravce.'),
            ('Správce údajů',
             'Správcem osobních údajů je provozovatel e-shopu MůjShop. Zpracování '
             'probíhá v souladu s nařízením GDPR (EU) 2016/679.'),
            ('Doba uchování',
             'Osobní údaje uchováváme po dobu nezbytnou k plnění smlouvy a poté '
             'po dobu stanovenou právními předpisy (obvykle 10 let pro účetní doklady).'),
            ('Vaše práva',
             'Máte právo na přístup ke svým údajům, jejich opravu nebo výmaz. '
             'Žádost podávejte e-mailem na adresu provozovatele. Máte také právo podat '
             'stížnost u Úřadu pro ochranu osobních údajů.'),
        ]
    },
    'vraceni': {
        'titulek': 'Vrácení zboží a reklamace',
        'sekce': [
            ('Právo na odstoupení',
             'Jako spotřebitel máte právo odstoupit od kupní smlouvy do 14 dnů od '
             'převzetí zboží bez udání důvodu (§ 1829 OZ). Lhůta je zachována, pokud '
             'zašlete oznámení před jejím uplynutím.'),
            ('Postup vrácení',
             'O záměru vrátit zboží nás informujte e-mailem. Zboží zašlete doporučenou '
             'zásilkou (ne na dobírku). Náklady na vrácení hradí kupující.'),
            ('Vrácení peněz',
             'Kupní cenu vrátíme do 14 dnů od obdržení zboží zpět, stejným způsobem '
             'jakým jste platili, pokud se nedohodneme jinak.'),
            ('Reklamace',
             'Na zakoupené zboží se vztahuje zákonná záruční lhůta 24 měsíců. '
             'Reklamaci uplatňujte e-mailem s popisem závady a fotografiemi. '
             'Reklamaci vyřídíme do 30 dnů od jejího uplatnění.'),
        ]
    },
}


@app.route('/stranka/<slug>')
def staticka_stranka(slug):
    stranka = STATICKE_STRANKY.get(slug)
    if stranka is None:
        abort(404)
    return render_template('stranka.html', stranka=stranka)


# ─── Admin: přihlášení ────────────────────────────────────────────────────────

@app.route('/admin/prihlaseni', methods=['GET', 'POST'])
def admin_prihlaseni():
    if session.get('admin'):
        return redirect(url_for('admin_prehled'))
    if request.method == 'POST':
        if request.form.get('heslo') == ADMIN_HESLO:
            session['admin'] = True
            return redirect(url_for('admin_prehled'))
        flash('Špatné heslo.', 'error')
    return render_template('admin/prihlaseni.html')


@app.route('/admin/odhlaseni')
def admin_odhlaseni():
    session.pop('admin', None)
    return redirect(url_for('admin_prihlaseni'))


# ─── Admin: přehled (dashboard) ───────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin_prehled():
    databaze = ziskat_db()
    pocet_produktu = databaze.execute('SELECT COUNT(*) as n FROM produkt').fetchone()['n']
    pocet_objednavek = databaze.execute('SELECT COUNT(*) as n FROM objednavka').fetchone()['n']
    pocet_novych = databaze.execute(
        "SELECT COUNT(*) as n FROM objednavka WHERE stav = 'nova'"
    ).fetchone()['n']
    posledni_objednavky = databaze.execute(
        'SELECT * FROM objednavka ORDER BY id DESC LIMIT 5'
    ).fetchall()
    databaze.close()
    return render_template('admin/prehled.html',
                           pocet_produktu=pocet_produktu,
                           pocet_objednavek=pocet_objednavek,
                           pocet_novych=pocet_novych,
                           posledni_objednavky=posledni_objednavky)


# ─── Admin: kategorie ─────────────────────────────────────────────────────────

@app.route('/admin/kategorie', methods=['GET', 'POST'])
@admin_required
def admin_kategorie():
    databaze = ziskat_db()
    if request.method == 'POST':
        nazev = request.form.get('nazev', '').strip()
        if not nazev:
            flash('Název kategorie je povinný.', 'error')
        else:
            try:
                databaze.execute('INSERT INTO kategorie (nazev) VALUES (?)', (nazev,))
                databaze.commit()
                flash(f'Kategorie „{nazev}" byla přidána.', 'success')
            except Exception:
                flash('Kategorie s tímto názvem již existuje.', 'error')
        databaze.close()
        return redirect(url_for('admin_kategorie'))

    kategorie = databaze.execute(
        'SELECT k.*, COUNT(p.id) as pocet_produktu FROM kategorie k '
        'LEFT JOIN produkt p ON p.kategorie_id = k.id GROUP BY k.id ORDER BY k.nazev'
    ).fetchall()
    databaze.close()
    return render_template('admin/kategorie.html', kategorie=kategorie)


@app.route('/admin/kategorie/<int:kategorie_id>/smazat', methods=['POST'])
@admin_required
def admin_smazat_kategorii(kategorie_id):
    databaze = ziskat_db()
    pocet = databaze.execute(
        'SELECT COUNT(*) as n FROM produkt WHERE kategorie_id = ?', (kategorie_id,)
    ).fetchone()['n']
    if pocet > 0:
        flash('Nelze smazat kategorii, která obsahuje produkty.', 'error')
    else:
        databaze.execute('DELETE FROM kategorie WHERE id = ?', (kategorie_id,))
        databaze.commit()
        flash('Kategorie byla smazána.', 'success')
    databaze.close()
    return redirect(url_for('admin_kategorie'))


# ─── Admin: produkty ──────────────────────────────────────────────────────────

@app.route('/admin/produkty')
@admin_required
def admin_produkty():
    databaze = ziskat_db()
    produkty = databaze.execute(
        'SELECT p.*, k.nazev as kategorie_nazev FROM produkt p '
        'LEFT JOIN kategorie k ON p.kategorie_id = k.id ORDER BY p.id DESC'
    ).fetchall()
    databaze.close()
    return render_template('admin/produkty.html', produkty=produkty)


@app.route('/admin/produkt/novy', methods=['GET', 'POST'])
@admin_required
def admin_novy_produkt():
    databaze = ziskat_db()
    kategorie = databaze.execute('SELECT * FROM kategorie ORDER BY nazev').fetchall()

    if request.method == 'GET':
        databaze.close()
        return render_template('admin/formular_produktu.html',
                               kategorie=kategorie, produkt=None, chyby={})

    nazev = request.form.get('nazev', '').strip()
    popis = request.form.get('popis', '').strip()
    cena_str = request.form.get('cena', '').strip()
    sklad_str = request.form.get('sklad', '0').strip()
    kategorie_id = request.form.get('kategorie_id', type=int)
    je_doporuceny = 1 if request.form.get('je_doporuceny') else 0
    soubor = request.files.get('obrazek')

    chyby = {}
    if not nazev:
        chyby['nazev'] = 'Název je povinný.'
    try:
        cena = float(cena_str)
        if cena <= 0:
            chyby['cena'] = 'Cena musí být větší než 0.'
    except (ValueError, TypeError):
        cena = 0.0
        chyby['cena'] = 'Zadejte platnou cenu.'
    try:
        sklad = int(sklad_str)
        if sklad < 0:
            chyby['sklad'] = 'Sklad nesmí být záporný.'
    except (ValueError, TypeError):
        sklad = 0
        chyby['sklad'] = 'Zadejte platný počet kusů.'
    if not soubor or soubor.filename == '':
        chyby['obrazek'] = 'Obrázek je povinný.'

    if chyby:
        databaze.close()
        formular = {'nazev': nazev, 'popis': popis, 'cena': cena_str,
                    'sklad': sklad_str, 'kategorie_id': kategorie_id,
                    'je_doporuceny': je_doporuceny}
        return render_template('admin/formular_produktu.html',
                               kategorie=kategorie, produkt=formular, chyby=chyby)

    # Uložení obrázku
    pripona = os.path.splitext(secure_filename(soubor.filename))[1].lower()
    nazev_souboru = uuid.uuid4().hex + pripona
    soubor.save(os.path.join(SLOZKA_OBRAZKU, nazev_souboru))

    databaze.execute(
        'INSERT INTO produkt (nazev, popis, cena, kategorie_id, sklad, je_doporuceny, obrazek) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (nazev, popis, cena, kategorie_id, sklad, je_doporuceny, nazev_souboru)
    )
    databaze.commit()
    databaze.close()
    flash('Produkt byl uložen.', 'success')
    return redirect(url_for('admin_produkty'))


@app.route('/admin/produkt/<int:produkt_id>/upravit', methods=['GET', 'POST'])
@admin_required
def admin_upravit_produkt(produkt_id):
    databaze = ziskat_db()
    produkt = databaze.execute('SELECT * FROM produkt WHERE id = ?', (produkt_id,)).fetchone()
    if produkt is None:
        databaze.close()
        abort(404)
    kategorie = databaze.execute('SELECT * FROM kategorie ORDER BY nazev').fetchall()

    if request.method == 'GET':
        databaze.close()
        return render_template('admin/formular_produktu.html',
                               kategorie=kategorie, produkt=produkt, chyby={})

    nazev = request.form.get('nazev', '').strip()
    popis = request.form.get('popis', '').strip()
    cena_str = request.form.get('cena', '').strip()
    sklad_str = request.form.get('sklad', '0').strip()
    kategorie_id = request.form.get('kategorie_id', type=int)
    je_doporuceny = 1 if request.form.get('je_doporuceny') else 0
    soubor = request.files.get('obrazek')

    chyby = {}
    if not nazev:
        chyby['nazev'] = 'Název je povinný.'
    try:
        cena = float(cena_str)
        if cena <= 0:
            chyby['cena'] = 'Cena musí být větší než 0.'
    except (ValueError, TypeError):
        cena = 0.0
        chyby['cena'] = 'Zadejte platnou cenu.'
    try:
        sklad = int(sklad_str)
        if sklad < 0:
            chyby['sklad'] = 'Sklad nesmí být záporný.'
    except (ValueError, TypeError):
        sklad = 0
        chyby['sklad'] = 'Zadejte platný počet kusů.'

    if chyby:
        databaze.close()
        formular = dict(produkt)
        formular.update({'nazev': nazev, 'popis': popis, 'cena': cena_str,
                         'sklad': sklad_str, 'kategorie_id': kategorie_id,
                         'je_doporuceny': je_doporuceny})
        return render_template('admin/formular_produktu.html',
                               kategorie=kategorie, produkt=formular, chyby=chyby)

    # Nový obrázek (volitelné při editaci)
    nazev_souboru = produkt['obrazek']
    if soubor and soubor.filename != '':
        pripona = os.path.splitext(secure_filename(soubor.filename))[1].lower()
        novy_soubor = uuid.uuid4().hex + pripona
        soubor.save(os.path.join(SLOZKA_OBRAZKU, novy_soubor))
        # Smazat starý obrázek (pokud to není placeholder)
        if nazev_souboru and nazev_souboru != 'placeholder.jpg':
            stary_soubor = os.path.join(SLOZKA_OBRAZKU, nazev_souboru)
            if os.path.exists(stary_soubor):
                os.remove(stary_soubor)
        nazev_souboru = novy_soubor

    databaze.execute(
        'UPDATE produkt SET nazev=?, popis=?, cena=?, kategorie_id=?, sklad=?, '
        'je_doporuceny=?, obrazek=? WHERE id=?',
        (nazev, popis, cena, kategorie_id, sklad, je_doporuceny, nazev_souboru, produkt_id)
    )
    databaze.commit()
    databaze.close()
    flash('Produkt byl uložen.', 'success')
    return redirect(url_for('admin_produkty'))


@app.route('/admin/produkt/<int:produkt_id>/smazat', methods=['POST'])
@admin_required
def admin_smazat_produkt(produkt_id):
    databaze = ziskat_db()
    produkt = databaze.execute('SELECT * FROM produkt WHERE id = ?', (produkt_id,)).fetchone()
    if produkt is None:
        databaze.close()
        abort(404)
    # Smazat obrázek z disku (pokud to není placeholder)
    if produkt['obrazek'] and produkt['obrazek'] != 'placeholder.jpg':
        cesta = os.path.join(SLOZKA_OBRAZKU, produkt['obrazek'])
        if os.path.exists(cesta):
            os.remove(cesta)
    databaze.execute('DELETE FROM produkt WHERE id = ?', (produkt_id,))
    databaze.commit()
    databaze.close()
    flash('Produkt byl smazán.', 'success')
    return redirect(url_for('admin_produkty'))


@app.route('/admin/objednavky')
@admin_required
def admin_objednavky():
    """Seznam všech objednávek s možností filtrování podle stavu."""
    databaze = ziskat_db()
    filtr_stav = request.args.get('stav', '')
    platne_stavy = ('nova', 'zaplacena', 'odeslana', 'dokoncena', 'zrusena')
    if filtr_stav in platne_stavy:
        objednavky = databaze.execute(
            'SELECT * FROM objednavka WHERE stav = ? ORDER BY vytvoreno DESC',
            (filtr_stav,)
        ).fetchall()
    else:
        filtr_stav = ''
        objednavky = databaze.execute(
            'SELECT * FROM objednavka ORDER BY vytvoreno DESC'
        ).fetchall()
    databaze.close()
    return render_template('admin/objednavky.html', objednavky=objednavky,
                           filtr_stav=filtr_stav, platne_stavy=platne_stavy)


@app.route('/admin/objednavka/<int:objednavka_id>', methods=['GET', 'POST'])
@admin_required
def admin_detail_objednavky(objednavka_id):
    """Detail objednávky a možnost změny stavu."""
    databaze = ziskat_db()
    objednavka = databaze.execute(
        'SELECT * FROM objednavka WHERE id = ?', (objednavka_id,)
    ).fetchone()
    if objednavka is None:
        databaze.close()
        abort(404)

    if request.method == 'POST':
        novy_stav = request.form.get('stav', '')
        platne_stavy = ('nova', 'zaplacena', 'odeslana', 'dokoncena', 'zrusena')
        if novy_stav in platne_stavy:
            databaze.execute(
                'UPDATE objednavka SET stav = ? WHERE id = ?',
                (novy_stav, objednavka_id)
            )
            databaze.commit()
            flash('Stav objednávky byl aktualizován.', 'success')
        else:
            flash('Neplatný stav objednávky.', 'error')
        databaze.close()
        return redirect(url_for('admin_detail_objednavky', objednavka_id=objednavka_id))

    polozky = databaze.execute(
        'SELECT * FROM polozka_objednavky WHERE objednavka_id = ?', (objednavka_id,)
    ).fetchall()
    # Načti kupon pokud byl použit
    kupon = None
    if objednavka['kupon_id']:
        kupon = databaze.execute(
            'SELECT * FROM slevovy_kupon WHERE id = ?', (objednavka['kupon_id'],)
        ).fetchone()
    databaze.close()
    # Dopočti cenu dopravy ze záznamu (mezisoucet + sleva + celkem → doprava = celkem - mezisoucet + sleva - dobirka)
    cena_dopravy = CENA_DOPRAVY.get(objednavka['doprava'], 0)
    poplatek_dobirka = PRIPLATEK_DOBIRKA if objednavka['platba'] == 'dobirka' else 0.0
    platne_stavy = ('nova', 'zaplacena', 'odeslana', 'dokoncena', 'zrusena')
    return render_template('admin/detail_objednavky.html', objednavka=objednavka,
                           polozky=polozky, kupon=kupon,
                           cena_dopravy=cena_dopravy, poplatek_dobirka=poplatek_dobirka,
                           platne_stavy=platne_stavy)


@app.route('/admin/kupony', methods=['GET', 'POST'])
@admin_required
def admin_kupony():
    """Správa slevových kuponů — seznam a přidání nového."""
    databaze = ziskat_db()
    chyby = {}

    if request.method == 'POST':
        kod = request.form.get('kod', '').strip().upper()
        sleva_procent = request.form.get('sleva_procent', '').strip()
        datum_expirace = request.form.get('datum_expirace', '').strip() or None
        limit_pouziti = request.form.get('limit_pouziti', '').strip() or None

        # Validace
        if not kod:
            chyby['kod'] = 'Kód kuponu je povinný.'
        else:
            existujici = databaze.execute(
                'SELECT id FROM slevovy_kupon WHERE UPPER(kod) = ?', (kod,)
            ).fetchone()
            if existujici:
                chyby['kod'] = 'Kupon s tímto kódem již existuje.'

        sleva_procent_int = 0
        if not sleva_procent:
            chyby['sleva_procent'] = 'Sleva je povinná.'
        else:
            try:
                sleva_procent_int = int(sleva_procent)
                if not (1 <= sleva_procent_int <= 100):
                    chyby['sleva_procent'] = 'Sleva musí být mezi 1 a 100 %.'
            except ValueError:
                chyby['sleva_procent'] = 'Sleva musí být celé číslo.'

        if limit_pouziti is not None:
            try:
                limit_pouziti = int(limit_pouziti)
                if limit_pouziti < 1:
                    chyby['limit_pouziti'] = 'Limit musí být alespoň 1.'
            except ValueError:
                chyby['limit_pouziti'] = 'Limit musí být celé číslo.'

        if not chyby:
            databaze.execute(
                'INSERT INTO slevovy_kupon (kod, sleva_procent, datum_expirace, limit_pouziti) VALUES (?, ?, ?, ?)',
                (kod, sleva_procent_int, datum_expirace, limit_pouziti)
            )
            databaze.commit()
            flash('Kupon byl přidán.', 'success')
            databaze.close()
            return redirect(url_for('admin_kupony'))

    kupony = databaze.execute(
        'SELECT * FROM slevovy_kupon ORDER BY id DESC'
    ).fetchall()
    databaze.close()
    return render_template('admin/kupony.html', kupony=kupony, chyby=chyby,
                           formular=request.form)


@app.route('/admin/kupon/<int:kupon_id>/smazat', methods=['POST'])
@admin_required
def admin_smazat_kupon(kupon_id):
    """Smaže slevový kupon — pouze pokud nebyl nikdy použit."""
    databaze = ziskat_db()
    kupon = databaze.execute(
        'SELECT * FROM slevovy_kupon WHERE id = ?', (kupon_id,)
    ).fetchone()
    if kupon is None:
        databaze.close()
        abort(404)
    if kupon['pocet_pouziti'] > 0:
        flash('Kupon nelze smazat — byl již použit v objednávce.', 'error')
    else:
        databaze.execute('DELETE FROM slevovy_kupon WHERE id = ?', (kupon_id,))
        databaze.commit()
        flash('Kupon byl smazán.', 'success')
    databaze.close()
    return redirect(url_for('admin_kupony'))


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', debug=debug)
