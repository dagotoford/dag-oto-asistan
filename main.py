import sys, sqlite3, csv, os, hashlib, secrets, shutil
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog, QDialog,
    QFormLayout, QSpinBox, QHeaderView, QGroupBox, QDialogButtonBox,
    QListWidget, QInputDialog
)

APP_DIR = Path.home() / "DagOtoAsistan"
APP_DIR.mkdir(exist_ok=True)
DB = APP_DIR / "dag_oto.db"
FIRM_NAME = "Dağ Oto Ford"
ACCOUNTANT_TEXT = "Muhasebeci Hülya Acar"
PARTNERS = ["Mekanik", "Elektrik", "Yedek Parça"]


def money(v):
    return f"{float(v):,.2f} ₺".replace(",", "X").replace(".", ",").replace("X", ".")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return salt, digest.hex()


class DBManager:
    def __init__(self):
        self.con = sqlite3.connect(DB)
        self.con.execute("PRAGMA foreign_keys=ON")
        self.init()

    def init(self):
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS customers(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS vehicles(
            id INTEGER PRIMARY KEY, customer_id INTEGER, plate TEXT UNIQUE NOT NULL,
            brand TEXT DEFAULT 'Ford', model TEXT DEFAULT '', vin TEXT DEFAULT '', km INTEGER DEFAULT 0,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS parts(
            id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            price REAL DEFAULT 0, stock REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY, job_date TEXT NOT NULL, customer_id INTEGER,
            vehicle_id INTEGER, description TEXT DEFAULT '', labor REAL DEFAULT 0,
            total REAL DEFAULT 0, paid REAL DEFAULT 0, note TEXT DEFAULT '',
            partner TEXT DEFAULT 'Mekanik',
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)
        );
        CREATE TABLE IF NOT EXISTS job_parts(
            id INTEGER PRIMARY KEY, job_id INTEGER, part_id INTEGER,
            qty REAL DEFAULT 1, unit_price REAL DEFAULT 0,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
            FOREIGN KEY(part_id) REFERENCES parts(id)
        );
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY, customer_id INTEGER, payment_date TEXT NOT NULL,
            amount REAL NOT NULL, job_id INTEGER, note TEXT DEFAULT '', partner TEXT DEFAULT 'Mekanik',
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY, customer_id INTEGER, due_date TEXT, note TEXT, done INTEGER DEFAULT 0,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY, expense_date TEXT NOT NULL, category TEXT DEFAULT '',
            description TEXT DEFAULT '', amount REAL NOT NULL, note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            salt TEXT NOT NULL, active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # Existing V1 databases do not have the new columns. Migrate them safely.
        self._add_column_if_missing("jobs", "partner", "TEXT DEFAULT 'Mekanik'")
        self._add_column_if_missing("payments", "partner", "TEXT DEFAULT 'Mekanik'")
        self.con.execute("UPDATE jobs SET partner='Mekanik' WHERE partner IS NULL OR partner=''")
        self.con.execute("UPDATE payments SET partner='Mekanik' WHERE partner IS NULL OR partner=''")
        self.con.commit()
        self.ensure_admin()

    def _add_column_if_missing(self, table, column, definition):
        cols = [r[1] for r in self.con.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            self.con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def ensure_admin(self):
        row = self.con.execute("SELECT id FROM users LIMIT 1").fetchone()
        if row:
            return
        salt, digest = hash_password("1234")
        self.con.execute(
            "INSERT INTO users(username,password_hash,salt) VALUES(?,?,?)",
            ("admin", digest, salt)
        )
        self.con.commit()

    def authenticate(self, username, password):
        row = self.con.execute(
            "SELECT id,username,password_hash,salt FROM users WHERE username=? AND active=1",
            (username.strip(),)
        ).fetchone()
        if not row:
            return None
        _, uname, stored, salt = row
        _, digest = hash_password(password, salt)
        return uname if secrets.compare_digest(stored, digest) else None

    def add_user(self, username, password):
        username = username.strip()
        if not username or not password:
            raise ValueError("Kullanıcı adı ve şifre boş bırakılamaz.")
        salt, digest = hash_password(password)
        self.con.execute(
            "INSERT INTO users(username,password_hash,salt) VALUES(?,?,?)",
            (username, digest, salt)
        )
        self.con.commit()

    def change_password(self, username, new_password):
        salt, digest = hash_password(new_password)
        self.con.execute("UPDATE users SET password_hash=?,salt=? WHERE username=?", (digest, salt, username))
        self.con.commit()

    def list_users(self):
        return self.con.execute("SELECT username,active,created_at FROM users ORDER BY username").fetchall()

    def customer_id(self, name):
        row = self.con.execute("SELECT id FROM customers WHERE name=?", (name.strip(),)).fetchone()
        if row:
            return row[0]
        cur = self.con.execute("INSERT INTO customers(name) VALUES(?)", (name.strip(),))
        self.con.commit()
        return cur.lastrowid

    def vehicle_id(self, plate, customer_id, model="", vin="", km=0):
        plate = plate.strip().upper()
        row = self.con.execute("SELECT id FROM vehicles WHERE plate=?", (plate,)).fetchone()
        if row:
            self.con.execute(
                "UPDATE vehicles SET customer_id=?, model=?, vin=?, km=? WHERE id=?",
                (customer_id, model, vin, km, row[0])
            )
            self.con.commit()
            return row[0]
        cur = self.con.execute(
            "INSERT INTO vehicles(customer_id,plate,model,vin,km) VALUES(?,?,?,?,?)",
            (customer_id, plate, model, vin, km)
        )
        self.con.commit()
        return cur.lastrowid

    def add_job(self, d, customer, plate, model, vin, km, desc, labor, total, paid,
                partner, part_code="", part_name="", qty=1, part_price=0):
        try:
            self.con.execute("BEGIN")
            cid = self.customer_id(customer)
            vid = self.vehicle_id(plate, cid, model, vin, km)
            cur = self.con.execute(
                "INSERT INTO jobs(job_date,customer_id,vehicle_id,description,labor,total,paid,partner) VALUES(?,?,?,?,?,?,?,?)",
                (d, cid, vid, desc, labor, total, paid, partner)
            )
            jid = cur.lastrowid
            if part_code:
                row = self.con.execute("SELECT id,name,price FROM parts WHERE code=?", (part_code.strip(),)).fetchone()
                if row:
                    pid = row[0]
                    up = part_price or row[2]
                    self.con.execute(
                        "INSERT INTO job_parts(job_id,part_id,qty,unit_price) VALUES(?,?,?,?)",
                        (jid, pid, qty, up)
                    )
                    self.con.execute("UPDATE parts SET stock=stock-? WHERE id=?", (qty, pid))
                else:
                    pid = self.con.execute(
                        "INSERT INTO parts(code,name,price,stock) VALUES(?,?,?,0)",
                        (part_code.strip(), part_name or "Yeni parça", part_price)
                    ).lastrowid
                    self.con.execute(
                        "INSERT INTO job_parts(job_id,part_id,qty,unit_price) VALUES(?,?,?,?)",
                        (jid, pid, qty, part_price)
                    )
            if paid:
                self.con.execute(
                    "INSERT INTO payments(customer_id,payment_date,amount,job_id,note,partner) VALUES(?,?,?,?,?,?)",
                    (cid, d, paid, jid, "Servis kaydı sırasında alınan ödeme", partner)
                )
            self.con.commit()
            return jid
        except Exception:
            self.con.rollback()
            raise

    def add_expense(self, d, category, description, amount, note):
        self.con.execute(
            "INSERT INTO expenses(expense_date,category,description,amount,note) VALUES(?,?,?,?,?)",
            (d, category, description, amount, note)
        )
        self.con.commit()

    def customer_balance(self, cid):
        billed = self.con.execute("SELECT COALESCE(SUM(total),0) FROM jobs WHERE customer_id=?", (cid,)).fetchone()[0]
        paid = self.con.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE customer_id=?", (cid,)).fetchone()[0]
        return billed, paid, billed - paid


db = DBManager()


class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dağ Oto Ford - Giriş")
        self.setFixedSize(430, 360)
        layout = QVBoxLayout(self)
        title = QLabel("DAĞ OTO FORD")
        title.setObjectName("loginTitle")
        layout.addWidget(title)
        subtitle = QLabel("Muhasebe & Servis Yönetim Sistemi")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        form = QFormLayout()
        self.firm = QComboBox(); self.firm.addItem(FIRM_NAME)
        self.username = QLineEdit(); self.username.setPlaceholderText("Kullanıcı adı")
        self.password = QLineEdit(); self.password.setPlaceholderText("Şifre"); self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Firma", self.firm)
        form.addRow("Kullanıcı adı", self.username)
        form.addRow("Şifre", self.password)
        layout.addLayout(form)
        self.info = QLabel("İlk giriş: admin / 1234  — Ayarlar bölümünden değiştirin.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        btn = QPushButton("Programa Gir")
        btn.clicked.connect(self.login)
        layout.addWidget(btn)
        self.password.returnPressed.connect(self.login)
        self.user = None

    def login(self):
        user = db.authenticate(self.username.text(), self.password.text())
        if not user:
            QMessageBox.warning(self, "Giriş başarısız", "Kullanıcı adı veya şifre hatalı.")
            return
        self.user = user
        self.accept()


class UserSettingsDialog(QDialog):
    def __init__(self, current_user, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.setWindowTitle("Ayarlar - Kullanıcı Yönetimi")
        self.resize(600, 430)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Firma: <b>{FIRM_NAME}</b>"))
        layout.addWidget(QLabel(f"Sabit muhasebeci: <b>{ACCOUNTANT_TEXT}</b>"))
        self.list = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        add = QPushButton("Kullanıcı Ekle")
        add.clicked.connect(self.add_user)
        change = QPushButton("Seçili / Kendi Şifremi Değiştir")
        change.clicked.connect(self.change_password)
        buttons.addWidget(add); buttons.addWidget(change)
        layout.addLayout(buttons)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def refresh_list(self):
        self.list.clear()
        for username, active, created in db.list_users():
            self.list.addItem(f"{username}   |   {'Aktif' if active else 'Pasif'}   |   {created}")

    def add_user(self):
        username, ok = QInputDialog.getText(self, "Kullanıcı Ekle", "Yeni kullanıcı adı:")
        if not ok:
            return
        password, ok = QInputDialog.getText(self, "Kullanıcı Ekle", "Yeni şifre:", QLineEdit.Password)
        if not ok:
            return
        try:
            db.add_user(username, password)
            self.refresh_list()
            QMessageBox.information(self, "Tamam", "Kullanıcı oluşturuldu.")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Hata", "Bu kullanıcı adı zaten kullanılıyor.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))

    def change_password(self):
        item = self.list.currentItem()
        username = self.current_user
        if item:
            username = item.text().split("|")[0].strip()
        password, ok = QInputDialog.getText(self, "Şifre Değiştir", f"{username} için yeni şifre:", QLineEdit.Password)
        if not ok or not password:
            return
        db.change_password(username, password)
        QMessageBox.information(self, "Tamam", "Şifre değiştirildi.")


class ExpenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Günlük Gider Ekle")
        self.resize(500, 330)
        f = QFormLayout(self)
        self.dt = QDateEdit(); self.dt.setCalendarPopup(True); self.dt.setDate(datetime.now().date())
        self.category = QComboBox(); self.category.setEditable(True)
        self.category.addItems(["Yakıt", "Elektrik", "Kira", "Personel", "Yemek", "Parça", "Vergi", "Fatura", "Diğer"])
        self.desc = QLineEdit(); self.desc.setPlaceholderText("Örn. Günlük yakıt / elektrik faturası")
        self.amount = QDoubleSpinBox(); self.amount.setMaximum(999999999); self.amount.setDecimals(2)
        self.note = QLineEdit()
        f.addRow("Tarih", self.dt)
        f.addRow("Gider türü", self.category)
        f.addRow("Açıklama", self.desc)
        f.addRow("Tutar", self.amount)
        f.addRow("Not", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)

    def save(self):
        if self.amount.value() <= 0:
            QMessageBox.warning(self, "Eksik bilgi", "Gider tutarı 0'dan büyük olmalı.")
            return
        db.add_expense(
            self.dt.date().toString("yyyy-MM-dd"), self.category.currentText().strip(),
            self.desc.text().strip(), self.amount.value(), self.note.text().strip()
        )
        self.accept()


class ServiceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Yeni Servis Kaydı")
        self.resize(650, 620)
        f = QFormLayout(self)
        self.dt = QDateEdit(); self.dt.setCalendarPopup(True); self.dt.setDate(datetime.now().date())
        self.partner = QComboBox(); self.partner.addItems(PARTNERS)
        self.customer = QLineEdit()
        self.plate = QLineEdit(); self.plate.setPlaceholderText("Örn. 44 ABC 123")
        self.model = QLineEdit(); self.model.setPlaceholderText("Örn. F-MAX / 4145 / 4142")
        self.vin = QLineEdit()
        self.km = QSpinBox(); self.km.setMaximum(9999999)
        self.desc = QLineEdit()
        self.labor = QDoubleSpinBox(); self.labor.setMaximum(999999999); self.labor.setDecimals(2)
        self.total = QDoubleSpinBox(); self.total.setMaximum(999999999); self.total.setDecimals(2)
        self.paid = QDoubleSpinBox(); self.paid.setMaximum(999999999); self.paid.setDecimals(2)
        self.part_code = QLineEdit(); self.part_code.setPlaceholderText("Parça kodu")
        self.part_name = QLineEdit(); self.part_name.setPlaceholderText("Kod bulunamazsa parça adı")
        self.qty = QDoubleSpinBox(); self.qty.setMinimum(0.01); self.qty.setMaximum(99999); self.qty.setValue(1)
        self.part_price = QDoubleSpinBox(); self.part_price.setMaximum(999999999); self.part_price.setDecimals(2)
        f.addRow("Tarih", self.dt)
        f.addRow("Ortak / Bölüm *", self.partner)
        f.addRow("Müşteri *", self.customer)
        f.addRow("Plaka *", self.plate)
        f.addRow("Araç / Model", self.model); f.addRow("Şasi / VIN", self.vin); f.addRow("Kilometre", self.km)
        f.addRow("Yapılan iş", self.desc); f.addRow("İşçilik", self.labor); f.addRow("Toplam", self.total)
        f.addRow("Bu işlemde alınan ödeme", self.paid)
        box = QGroupBox("Parça (isteğe bağlı)")
        pf = QFormLayout(box)
        pf.addRow("Parça kodu", self.part_code); pf.addRow("Parça adı", self.part_name)
        pf.addRow("Adet", self.qty); pf.addRow("Birim fiyat", self.part_price)
        f.addRow(box)
        hint = QLabel("Bu kayıt seçtiğiniz ortağın cirosuna yazılır. Ödeme de aynı bölüme bağlanır.")
        hint.setWordWrap(True); f.addRow(hint)
        self.save = QPushButton("Kaydet")
        self.save.clicked.connect(self.save_job)
        f.addRow(self.save)
        self.part_code.editingFinished.connect(self.lookup_part)

    def lookup_part(self):
        code = self.part_code.text().strip()
        if not code:
            return
        row = db.con.execute("SELECT name,price FROM parts WHERE code=?", (code,)).fetchone()
        if row:
            self.part_name.setText(row[0]); self.part_price.setValue(row[1])
        else:
            self.part_name.setPlaceholderText("Bu kod katalogda yok — kaydederken yeni parça olarak eklenir")

    def save_job(self):
        if not self.customer.text().strip() or not self.plate.text().strip():
            QMessageBox.warning(self, "Eksik bilgi", "Müşteri ve plaka zorunludur.")
            return
        if self.total.value() <= 0:
            QMessageBox.warning(self, "Eksik bilgi", "Toplam tutarı girin.")
            return
        if self.paid.value() > self.total.value():
            QMessageBox.warning(self, "Hatalı ödeme", "Ödeme toplam tutardan büyük olamaz.")
            return
        try:
            db.add_job(
                self.dt.date().toString("yyyy-MM-dd"), self.customer.text(), self.plate.text(),
                self.model.text(), self.vin.text(), self.km.value(), self.desc.text(),
                self.labor.value(), self.total.value(), self.paid.value(), self.partner.currentText(),
                self.part_code.text(), self.part_name.text(), self.qty.value(), self.part_price.value()
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Kayıt hatası", f"Kayıt yapılamadı:\n\n{e}")


class MainWindow(QMainWindow):
    def __init__(self, username):
        super().__init__()
        self.username = username
        self.setWindowTitle(f"Dağ Oto Muhasebe & Servis — {FIRM_NAME}")
        self.resize(1320, 800)
        self.build()
        self.refresh()

    def build(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        side = QVBoxLayout()
        brand = QLabel("DAĞ OTO\nMUHASEBE & SERVİS"); brand.setObjectName("brand")
        side.addWidget(brand)
        buttons = [
            ("🏠 Ana Sayfa", self.refresh), ("📅 Günlük İşler", self.show_daily),
            ("👥 Müşteriler", self.show_customers), ("🚛 Araçlar / Plakalar", self.show_vehicles),
            ("🔧 Yeni Servis", self.new_service), ("📦 Parçalar", self.show_parts),
            ("💳 Ödemeler", self.show_payments), ("💸 Günlük Giderler", self.show_expenses),
            ("📊 Ortak Raporları", self.show_partner_reports), ("📥 Excel Aktar", self.import_excel),
            ("⚙ Ayarlar", self.settings), ("💾 Yedekle", self.backup)
        ]
        for text, slot in buttons:
            b = QPushButton(text); b.clicked.connect(slot); side.addWidget(b)
        side.addStretch()
        accountant = QLabel(f"<b>{ACCOUNTANT_TEXT}</b>\n{FIRM_NAME}\nKullanıcı: {self.username}")
        accountant.setObjectName("accountant")
        accountant.setWordWrap(True)
        side.addWidget(accountant)
        outer.addLayout(side, 0)
        self.body = QVBoxLayout(); outer.addLayout(self.body, 1)
        self.header = QLabel(); self.header.setObjectName("header"); self.body.addWidget(self.header)
        self.cards = QHBoxLayout(); self.body.addLayout(self.cards)
        self.table = QTableWidget(); self.body.addWidget(self.table, 1)

    def clear_body(self):
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def card(self, title, value):
        w = QGroupBox(); l = QVBoxLayout(w); a = QLabel(title); b = QLabel(value); b.setObjectName("big")
        l.addWidget(a); l.addWidget(b); self.cards.addWidget(w)

    def refresh(self):
        self.clear_body()
        today = date.today().isoformat()
        self.header.setText(f"Bugün — {today} | {FIRM_NAME}")
        billed, paid, balance = self.con_totals()
        today_jobs = self.con_scalar("SELECT COUNT(*) FROM jobs WHERE job_date=?", (today,))
        expense_today = self.con_scalar("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date=?", (today,))
        self.card("Bugünkü İşler", str(today_jobs))
        self.card("Toplam Ciro", money(billed))
        self.card("Toplam Ödeme", money(paid))
        self.card("Açık Borç", money(balance))
        self.card("Bugünkü Gider", money(expense_today))
        rows = db.con.execute("""
            SELECT j.job_date,c.name,v.plate,v.model,j.partner,j.description,j.total,
                   j.total-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.job_id=j.id),0)
            FROM jobs j LEFT JOIN customers c ON c.id=j.customer_id
            LEFT JOIN vehicles v ON v.id=j.vehicle_id ORDER BY j.job_date DESC,j.id DESC LIMIT 100
        """).fetchall()
        self.fill_table(["Tarih","Müşteri","Plaka","Araç","Ortak/Bölüm","Yapılan İş","Tutar","Kalan"], rows, money_cols=[6,7])

    def show_daily(self):
        self.clear_body()
        d = date.today().isoformat()
        self.header.setText(f"Günlük İşler — {d}")
        rows = db.con.execute("""
            SELECT j.job_date,c.name,v.plate,v.model,j.partner,j.description,j.total,
                   COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.job_id=j.id),0),
                   j.total-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.job_id=j.id),0)
            FROM jobs j LEFT JOIN customers c ON c.id=j.customer_id
            LEFT JOIN vehicles v ON v.id=j.vehicle_id WHERE j.job_date=? ORDER BY j.id DESC
        """, (d,)).fetchall()
        self.fill_table(["Tarih","Müşteri","Plaka","Araç","Ortak/Bölüm","Yapılan İş","Tutar","Ödenen","Kalan"], rows, money_cols=[6,7,8])

    def con_scalar(self, q, args=()):
        return db.con.execute(q, args).fetchone()[0]

    def con_totals(self):
        billed = self.con_scalar("SELECT COALESCE(SUM(total),0) FROM jobs")
        paid = self.con_scalar("SELECT COALESCE(SUM(amount),0) FROM payments")
        return billed, paid, billed - paid

    def fill_table(self, headers, rows, money_cols=None):
        money_cols = money_cols or []
        self.table.clear(); self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if c in money_cols and val is not None:
                    text = money(val)
                else:
                    text = "" if val is None else str(val)
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)

    def new_service(self):
        if ServiceDialog(self).exec():
            self.refresh()

    def show_customers(self):
        rows = db.con.execute("SELECT id,name,phone FROM customers ORDER BY name").fetchall()
        out = []
        for cid, name, phone in rows:
            billed, paid, balance = db.customer_balance(cid); out.append((name, phone, billed, paid, balance))
        self.header.setText("Müşteriler / Cari Hesaplar")
        self.fill_table(["Müşteri","Telefon","Toplam Borç","Ödenen","Kalan"], out, money_cols=[2,3,4])

    def show_vehicles(self):
        rows = db.con.execute("""SELECT v.plate,c.name,v.model,v.vin,v.km,COUNT(j.id),COALESCE(SUM(j.total),0)
             FROM vehicles v LEFT JOIN customers c ON c.id=v.customer_id
             LEFT JOIN jobs j ON j.vehicle_id=v.id GROUP BY v.id ORDER BY v.plate""").fetchall()
        self.header.setText("Araçlar / Plakalar")
        self.fill_table(["Plaka","Müşteri","Araç","VIN","KM","Servis Sayısı","Toplam"], rows, money_cols=[6])

    def show_parts(self):
        rows = db.con.execute("SELECT code,name,price,stock FROM parts ORDER BY code").fetchall()
        self.header.setText("Parça Kataloğu / Stok")
        self.fill_table(["Parça Kodu","Parça Adı","Birim Fiyat","Stok"], rows, money_cols=[2])

    def show_payments(self):
        rows = db.con.execute("""SELECT p.payment_date,c.name,p.partner,p.amount,p.note
             FROM payments p JOIN customers c ON c.id=p.customer_id ORDER BY p.payment_date DESC,p.id DESC""").fetchall()
        self.header.setText("Ödemeler / Ortağa Göre")
        self.fill_table(["Tarih","Müşteri","Ortak/Bölüm","Ödeme","Not"], rows, money_cols=[3])

    def show_expenses(self):
        self.clear_body()
        total = self.con_scalar("SELECT COALESCE(SUM(amount),0) FROM expenses")
        today = self.con_scalar("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE expense_date=?", (date.today().isoformat(),))
        self.card("Toplam Gider", money(total)); self.card("Bugünkü Gider", money(today)); self.card("Yeni Gider", "Aşağıdaki buton")
        self.header.setText("Günlük Giderler")
        add = QPushButton("➕ Günlük Gider Ekle"); add.clicked.connect(self.new_expense)
        self.body.insertWidget(1, add)
        rows = db.con.execute("SELECT expense_date,category,description,amount,note FROM expenses ORDER BY expense_date DESC,id DESC LIMIT 300").fetchall()
        self.fill_table(["Tarih","Gider Türü","Açıklama","Tutar","Not"], rows, money_cols=[3])

    def new_expense(self):
        if ExpenseDialog(self).exec():
            self.show_expenses()

    def show_partner_reports(self):
        self.clear_body()
        self.header.setText("Ortak / Bölüm Raporları")
        for partner in PARTNERS:
            billed = self.con_scalar("SELECT COALESCE(SUM(total),0) FROM jobs WHERE partner=?", (partner,))
            paid = self.con_scalar("SELECT COALESCE(SUM(amount),0) FROM payments WHERE partner=?", (partner,))
            self.card(f"{partner} Ciro", money(billed))
            self.card(f"{partner} Tahsilat", money(paid))
        rows = db.con.execute("""
            SELECT partner, COUNT(*), COALESCE(SUM(total),0),
                   COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.partner=jobs.partner),0)
            FROM jobs GROUP BY partner ORDER BY partner
        """).fetchall()
        self.fill_table(["Ortak/Bölüm","İş Sayısı","Ciro","Tahsilat"], rows, money_cols=[2,3])

    def settings(self):
        UserSettingsDialog(self.username, self).exec()

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Excel/CSV seç", "", "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        if path.lower().endswith(".xlsx"):
            try:
                from openpyxl import load_workbook
                ws = load_workbook(path, data_only=True).active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    return
                headers = [str(x or "").strip().lower() for x in rows[0]]
                aliases = {
                    "tarih":["tarih","date"], "müşteri":["müşteri","musteri","cari"],
                    "plaka":["plaka","plate"], "araç":["araç","arac","model"],
                    "işlem":["işlem","islem","yapılan iş"], "tutar":["tutar","toplam"],
                    "ödeme":["ödeme","odeme","ödenen"], "parça kodu":["parça kodu","parca kodu","kod"],
                    "ortak":["ortak","bölüm","bolum","departman"]
                }
                def find(key):
                    for a in aliases[key]:
                        if a in headers:
                            return headers.index(a)
                    return None
                idx = {k: find(k) for k in aliases}
                imported = 0; missing = []
                for n, row in enumerate(rows[1:], 2):
                    def val(k):
                        i = idx[k]
                        return "" if i is None or i >= len(row) or row[i] is None else str(row[i]).strip()
                    customer, plate = val("müşteri"), val("plaka")
                    if not customer or not plate:
                        missing.append(n); continue
                    d = val("tarih") or date.today().isoformat()
                    total = float(val("tutar").replace(",", ".")) if val("tutar") else 0
                    paid = float(val("ödeme").replace(",", ".")) if val("ödeme") else 0
                    partner = val("ortak") or "Mekanik"
                    if partner not in PARTNERS:
                        partner = "Mekanik"
                    db.add_job(d, customer, plate, val("araç"), "", 0, val("işlem"), 0, total, paid, partner, val("parça kodu"))
                    imported += 1
                QMessageBox.information(self, "Excel aktarımı", f"{imported} kayıt aktarıldı. Eksik müşteri/plaka nedeniyle atlanan satır: {len(missing)}")
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Aktarım hatası", str(e))
        else:
            QMessageBox.information(self, "CSV", "CSV aktarımı için ilk satır sütun başlığı, sonraki satırlar kayıt olacak şekilde hazırlanmalıdır.")

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Yedek kaydet", f"dag_oto_yedek_{date.today().isoformat()}.db", "Veritabanı (*.db)")
        if path:
            db.con.commit(); shutil.copy2(DB, path)
            QMessageBox.information(self, "Yedekleme", "Yedek başarıyla oluşturuldu.")


app = QApplication(sys.argv)
app.setStyleSheet("""
QMainWindow{background:#f4f6f8} QWidget{font-size:13px;color:#17212b}
QLabel#brand{background:#10243e;color:white;font-size:18px;font-weight:800;padding:20px;border-radius:8px}
QLabel#header{font-size:22px;font-weight:800;padding:6px}
QLabel#big{font-size:19px;font-weight:800}
QLabel#accountant{background:white;border:1px solid #dce2e8;border-radius:8px;padding:12px}
QLabel#loginTitle{background:#10243e;color:white;font-size:25px;font-weight:900;padding:18px;border-radius:8px;text-align:center}
QPushButton{padding:10px 12px;border:1px solid #d8dee5;border-radius:7px;background:white;text-align:left}
QPushButton:hover{background:#eef2f5}
QTableWidget{background:white;border:1px solid #dce2e8;border-radius:8px}
QHeaderView::section{padding:8px;background:#10243e;color:white;border:0}
QGroupBox{background:white;border:1px solid #dce2e8;border-radius:8px;padding:12px}
QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox,QDateEdit{padding:7px;border:1px solid #cbd3dc;border-radius:6px;background:white}
""")

login = LoginDialog()
if login.exec() != QDialog.Accepted:
    sys.exit(0)
w = MainWindow(login.user)
w.show()
sys.exit(app.exec())
