import os, hmac, secrets
from pathlib import Path
from collections import Counter
from datetime import date
from urllib.parse import quote
from decimal import Decimal
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.engine import URL
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError

load_dotenv(Path(__file__).with_name(".env"))  # يقرأ .env الموجود بجانب app.py
if not (os.environ.get("DB_PASSWORD") or os.environ.get("DATABASE_URL")):
    raise SystemExit("لم أجد بيانات الاتصال بقاعدة البيانات (DB_PASSWORD أو DATABASE_URL). تأكد أن ملف .env موجود بجانب app.py، أو أنك أضفتها في إعدادات الاستضافة.")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
    # لو موجود DATABASE_URL (مثل رابط Neon) نستخدمه مباشرة، وإلا نبنيه من DB_USER/DB_PASSWORD... (محلياً)
    SQLALCHEMY_DATABASE_URI=(
        os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
        if os.environ.get("DATABASE_URL") else
        URL.create(
            "postgresql+psycopg",
            username=os.environ.get("DB_USER", "postgres"),
            password=os.environ["DB_PASSWORD"],
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            database=os.environ.get("DB_NAME", "shein"),
        )
    ),
    SESSION_COOKIE_SAMESITE="Lax",
)
db = SQLAlchemy(app)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change_me")
STORES = ["شي إن", "أمازون", "أخرى"]  # لإضافة متجر جديد أضف اسمه هنا
STATUSES = ["استلمت الرابط", "تم الدفع", "تم الطلب من المتجر", "وصل السعودية",
            "ضمن شحنة", "وصل صنعاء", "تم التسليم", "ملغي"]
CUSTOMER_STEPS = ["استلمنا طلبك", "تم استلام الدفع", "تم تنفيذ طلبك من المتجر", "وصل طلبك إلى السعودية",
                  "في الطريق إلى اليمن", "وصل صنعاء وجاهز للتسليم", "تم التسليم"]
# رسائل واتساب لكل مرحلة، عدّل الصياغة كما تحب (المتغيرات: {name} الاسم الأول، {code} رقم الطلب)
WA_MESSAGES = {
    "استلمت الرابط": "أهلاً {name} 🌷\nوصلنا رابط سلتك وسجلنا طلبك رقم {code}.\nملبوس العافية من الحين 😄",
    "تم الدفع": "وصلنا دفعك يا {name}، الله يعطيك العافية ✅\nالحين نجهّز طلبك {code} ونطلبه لك من {store}.",
    "تم الطلب من المتجر": "خلاص يا {name}، طلبك {code} انطلب من {store} 🛍️\nالحين في الطريق إلينا، وأول ما يوصل نخبرك.",
    "وصل السعودية": "طلبك {code} وصلنا بالسلامة يا {name} ✈️\nننتظر تكتمل الشحنة ونرسله لصنعاء.",
    "ضمن شحنة": "شحنتك في الطريق يا {name} 🚚\nلا تستعجلون علينا، الطريق طويل بس الحاجة بتوصل بإذن الله، وننبهك أول ما نوصل صنعاء.",
    "وصل صنعاء": "وصلت الشحنة صنعاء يا {name} 🎉\nاستعد، بنتواصل معك لترتيب تسليم طلبك {code}.",
    "تم التسليم": "ألف مبروك يا {name} 🎁\nملبوس العافية! نتمنى تعجبك، وننتظر صورك ورأيك.",
    "ملغي": "تم إلغاء طلبك {code} يا {name}. لو عندك أي استفسار نحن حاضرين.",
}
PAY_METHODS = ["تحويل بنكي", "محفظة إلكترونية", "حوالة (صرافة)", "نقداً"]
if ADMIN_PASSWORD == "change_me":
    print("تحذير: غيّر ADMIN_PASSWORD و SECRET_KEY قبل النشر")


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    customer_name = db.Column(db.String(120), nullable=False)
    whatsapp = db.Column(db.String(30), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    cart_link = db.Column(db.Text)
    cart_value = db.Column(db.Numeric(10, 2), nullable=False)
    delivery_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # التوصيل داخل صنعاء فقط
    actual_cost = db.Column(db.Numeric(10, 2))  # ما دفعته فعلياً لشي إن بعد الخصم والكوبون
    paid = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    pay_method = db.Column(db.String(30))
    store = db.Column(db.String(30), nullable=False, default=STORES[0])
    service_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # رسوم الخدمة حسب سعر الصرف يوم الطلب
    store_order_no = db.Column(db.String(40))  # رقم الطلب في المتجر، ممنوع تكراره داخل نفس المتجر
    status = db.Column(db.String(30), nullable=False, default=STATUSES[0])
    shipment_code = db.Column(db.String(20))
    notes = db.Column(db.Text)
    __table_args__ = (db.CheckConstraint("cart_value >= 0", name="ck_cart"),
                      db.CheckConstraint("paid >= 0", name="ck_paid"),
                      db.UniqueConstraint("store", "store_order_no", name="uq_store_order_no"))

    total = property(lambda s: s.cart_value + s.delivery_fee + s.service_fee)
    profit = property(lambda s: None if s.actual_cost is None else s.total - s.actual_cost)
    remaining = property(lambda s: s.total - s.paid)
    wa = property(lambda s: "".join(c for c in s.whatsapp if c.isdigit()))

    @property
    def pay_status(self):
        return "لم يدفع" if self.paid == 0 else ("مدفوع كامل" if self.paid >= self.total else "دفعة مقدمة")


class Shipment(db.Model):
    __tablename__ = "shipments"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    sent_on = db.Column(db.Date)
    cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    notes = db.Column(db.Text)


def dec(v):
    try:
        return max(Decimal(v or 0), Decimal(0))
    except ArithmeticError:
        return Decimal(0)


app.jinja_env.filters["money"] = lambda v: f"{v:,.2f}"


def fill(o, f):
    o.cart_value, o.paid = dec(f.get("cart_value")), dec(f.get("paid"))
    o.delivery_fee, o.service_fee = dec(f.get("delivery_fee")), dec(f.get("service_fee"))
    o.actual_cost = dec(f["actual_cost"]) if f.get("actual_cost") else None
    for k in ("customer_name", "whatsapp", "address", "cart_link", "pay_method",
              "store_order_no", "shipment_code", "notes"):
        setattr(o, k, (f.get(k) or "").strip() or None)
    if not (o.customer_name and o.whatsapp and o.address):
        raise ValueError("الاسم والواتساب والعنوان مطلوبة")
    if f.get("status") not in STATUSES or f.get("store") not in STORES:
        abort(400)
    o.status, o.store = f["status"], f["store"]


def wa_text(o, status=None):
    status = status or o.status
    text = WA_MESSAGES[status].format(name=o.customer_name.split()[0], code=o.code, store=o.store)
    return text if status == "ملغي" else text + "\n\nوهذي بطاقة طلبك بمراحله 👇"


def wa_update(o, status=None):
    return f"https://wa.me/{o.wa}?text={quote(wa_text(o, status))}"


app.jinja_env.globals.update(wa_text=wa_text, wa_update=wa_update)


def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        return fn(*a, **k) if session.get("ok") else redirect(url_for("login"))
    return w


@app.before_request
def csrf():
    if request.method == "POST":
        tok = session.get("csrf")
        if not tok or not hmac.compare_digest(request.form.get("_csrf", "").encode(), tok.encode()):
            abort(400)


@app.context_processor
def inject():
    session.setdefault("csrf", secrets.token_hex(16))
    return dict(csrf=session["csrf"], STATUSES=STATUSES, PAY_METHODS=PAY_METHODS, STORES=STORES)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form.get("user", ""), request.form.get("password", "")
        if hmac.compare_digest(u.encode(), ADMIN_USER.encode()) and \
           hmac.compare_digest(p.encode(), ADMIN_PASSWORD.encode()):
            session["ok"] = True
            return redirect(url_for("index"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    q, st, store = request.args.get("q", "").strip(), request.args.get("status", ""), request.args.get("store", "")
    qs = Order.query
    if q:
        like = f"%{q}%"
        qs = qs.filter(db.or_(Order.customer_name.ilike(like), Order.code.ilike(like),
                              Order.whatsapp.ilike(like), Order.store_order_no.ilike(like)))
    if st in STATUSES:
        qs = qs.filter_by(status=st)
    if store in STORES:
        qs = qs.filter_by(store=store)
    else:
        store = ""
    everything = Order.query.all()
    pool = [o for o in everything if not store or o.store == store]  # الإحصائيات تتبع المتجر المختار
    live = [o for o in pool if o.status != "ملغي"]
    ship_cost = 0 if store else sum(x.cost for x in Shipment.query.all())  # الشحنة مشتركة بين المتاجر
    stats = dict(count=len(live), sales=sum(o.total for o in live), paid=sum(o.paid for o in live),
                 due=sum(o.remaining for o in live), nocost=sum(1 for o in live if o.actual_cost is None),
                 profit=sum((o.profit for o in live if o.profit is not None), Decimal(0)) - ship_cost)
    return render_template("index.html", orders=qs.order_by(Order.id.desc()).all(), stats=stats,
                           counts=Counter(o.status for o in pool), store_counts=Counter(o.store for o in everything),
                           q=q, st=st, store=store)


@app.route("/orders/new", methods=["GET", "POST"])
@app.route("/orders/<int:oid>/edit", methods=["GET", "POST"])
@login_required
def edit(oid=None):
    o = db.get_or_404(Order, oid) if oid else Order()
    if request.method == "POST":
        try:
            fill(o, request.form)
            if not o.id:
                db.session.add(o)
                db.session.flush()
                o.code = f"HT-{o.id:04d}"
            db.session.commit()
            return redirect(url_for("index"))
        except ValueError as e:
            db.session.rollback(); flash(str(e))
        except IntegrityError:
            db.session.rollback(); flash("رقم طلب شي إن هذا مسجل لطلب آخر")
    return render_template("form.html", o=o, ships=Shipment.query.order_by(Shipment.id).all())


@app.route("/shipments", methods=["GET", "POST"])
@login_required
def shipments():
    if request.method == "POST":
        try:
            sent = date.fromisoformat(request.form.get("sent_on") or "")
        except ValueError:
            sent = None
        sh = Shipment(code=secrets.token_hex(4), sent_on=sent, cost=dec(request.form.get("cost")),
                      notes=(request.form.get("notes") or "").strip() or None)
        db.session.add(sh)
        db.session.flush()
        sh.code = f"SHP-{sh.id:04d}"
        db.session.commit()
        return redirect(url_for("shipments"))
    rows = [(x, Order.query.filter_by(shipment_code=x.code).all())
            for x in Shipment.query.order_by(Shipment.id.desc()).all()]
    return render_template("shipments.html", rows=rows)


@app.post("/shipments/<int:sid>/cost")
@login_required
def shipment_cost(sid):
    db.get_or_404(Shipment, sid).cost = dec(request.form.get("cost"))
    db.session.commit()
    return redirect(url_for("shipments"))


@app.route("/orders/<int:oid>/send")
@login_required
def send_update(oid):  # بطاقة الطلب (صورة) + نص واتساب
    o = db.get_or_404(Order, oid)
    card = dict(title="أهلاً " + o.customer_name.split()[0], sub="طلبك رقم " + o.code, i=STATUSES.index(o.status), steps=CUSTOMER_STEPS,
                cancelled=o.status == "ملغي", date=date.today().isoformat())
    return render_template("send.html", o=o, card=card)


@app.route("/shipments/<int:sid>/send")
@login_required
def send_batch(sid):  # رسائل شخصية لكل عملاء الشحنة + بطاقة واحدة مشتركة
    s = db.get_or_404(Shipment, sid)
    orders = Order.query.filter(Order.shipment_code == s.code, Order.status != "ملغي").order_by(Order.id).all()
    st = request.args.get("status")
    if st not in STATUSES or st == "ملغي":
        st = Counter(o.status for o in orders).most_common(1)[0][0] if orders else STATUSES[1]
    card = dict(title="مراحل طلبك", sub="شحنة " + s.code, i=STATUSES.index(st), steps=CUSTOMER_STEPS,
                cancelled=False, date=date.today().isoformat())
    return render_template("send_batch.html", s=s, orders=orders, st=st, card=card)


@app.post("/shipments/<int:sid>/status")
@login_required
def shipment_status(sid):  # تغيير حالة كل طلبات الصندوق دفعة واحدة (التسليم يبقى لكل طلب على حدة)
    s, st = db.get_or_404(Shipment, sid), request.form.get("status")
    if st not in ("ضمن شحنة", "وصل صنعاء"):
        abort(400)
    Order.query.filter(Order.shipment_code == s.code, Order.status != "ملغي").update({"status": st})
    db.session.commit()
    return redirect(url_for("shipments"))


@app.post("/orders/<int:oid>/status")
@login_required
def set_status(oid):
    s = request.form.get("status")
    if s not in STATUSES:
        abort(400)
    db.get_or_404(Order, oid).status = s
    db.session.commit()
    return redirect(url_for("index"))


def migrate():  # تحديث قاعدة البيانات القديمة، آمن لو تكرر تشغيله
    run = lambda sql, **p: db.session.execute(db.text(sql), p)
    run("ALTER TABLE orders ADD COLUMN IF NOT EXISTS store varchar(30) NOT NULL DEFAULT 'شي إن'")
    run("ALTER TABLE orders ADD COLUMN IF NOT EXISTS service_fee numeric(10,2) NOT NULL DEFAULT 0")
    if run("SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='shein_order_no'").first():
        run("ALTER TABLE orders RENAME COLUMN shein_order_no TO store_order_no")
    run("ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_shein_order_no_key")
    if not run("SELECT 1 FROM pg_constraint WHERE conname='uq_store_order_no'").first():
        run("ALTER TABLE orders ADD CONSTRAINT uq_store_order_no UNIQUE (store, store_order_no)")
    run("UPDATE orders SET status = :new WHERE status = :old", new="تم الطلب من المتجر", old="تم الطلب من شي إن")
    db.session.commit()


with app.app_context():
    db.create_all()
    migrate()

if __name__ == "__main__":
    app.run(debug=True)