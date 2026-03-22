"""
АСУ «КомпТех» — Веб-приложение (Flask)
"""
import os
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.jinja_env.globals.update(enumerate=enumerate)
app.secret_key = os.environ.get("SECRET_KEY", "komptech-secret-2025")

# ── Подключение к БД ─────────────────────────────────────────────
def get_db():
    url = os.environ.get("DATABASE_URL")
    if url:
        # Railway передаёт строку вида postgres://...
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    # Локальная разработка
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", 5432),
        dbname=os.environ.get("DB_NAME", "komptech_db"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASS", "12345"),
    )

def query(sql, params=None, one=False):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone() if one else cur.fetchall()

def execute(sql, params=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            try:
                return cur.fetchone()[0]
            except Exception:
                return None

# ── Главная ──────────────────────────────────────────────────────
@app.route("/")
def index():
    stats = {
        "products":  query("SELECT COUNT(*) c FROM products",        one=True)["c"],
        "clients":   query("SELECT COUNT(*) c FROM clients",          one=True)["c"],
        "orders":    query("SELECT COUNT(*) c FROM orders",           one=True)["c"],
        "revenue":   query("SELECT COALESCE(SUM(amount),0) c FROM payments WHERE status='проведён'", one=True)["c"],
        "low_stock": query("SELECT COUNT(*) c FROM warehouse WHERE quantity_in_stock < 5", one=True)["c"],
        "new_orders":query("SELECT COUNT(*) c FROM orders WHERE status='новый'", one=True)["c"],
    }
    recent_orders = query("""
        SELECT o.order_id, TO_CHAR(o.order_date,'DD.MM.YYYY') dt,
               COALESCE(cl.last_name||' '||cl.first_name, cl.org_name,'—') client,
               o.total_amount, o.status
        FROM orders o JOIN clients cl ON cl.client_id=o.client_id
        ORDER BY o.order_id DESC LIMIT 5
    """)
    return render_template("index.html", stats=stats, recent_orders=recent_orders)

# ── Товары ───────────────────────────────────────────────────────
@app.route("/products")
def products():
    search = request.args.get("q", "")
    cat    = request.args.get("cat", "")
    cats   = query("SELECT category_id, name FROM categories ORDER BY name")
    rows   = query("""
        SELECT p.product_id, p.article, p.name, c.name cat, m.name manuf,
               p.retail_price, COALESCE(w.quantity_in_stock,0) stock,
               p.warranty_months, p.status
        FROM products p
        LEFT JOIN categories c ON c.category_id=p.category_id
        LEFT JOIN manufacturers m ON m.manufacturer_id=p.manufacturer_id
        LEFT JOIN warehouse w ON w.product_id=p.product_id
        WHERE (%s='' OR c.category_id::text=%s)
          AND (p.name ILIKE %s OR p.article ILIKE %s)
        ORDER BY p.product_id
    """, (cat, cat, f"%{search}%", f"%{search}%"))
    return render_template("products.html", rows=rows, cats=cats,
                           search=search, cat=cat)

@app.route("/products/add", methods=["GET","POST"])
def product_add():
    cats  = query("SELECT category_id, name FROM categories ORDER BY name")
    manuf = query("SELECT manufacturer_id, name FROM manufacturers ORDER BY name")
    if request.method == "POST":
        f = request.form
        try:
            pid = execute("""
                INSERT INTO products (name,category_id,manufacturer_id,article,
                    description,retail_price,warranty_months,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING product_id
            """, (f["name"], f["category_id"] or None, f["manufacturer_id"] or None,
                  f["article"] or None, f["description"] or None,
                  float(f["retail_price"]), int(f.get("warranty_months",12)),
                  f["status"]))
            execute("INSERT INTO warehouse (product_id,quantity_in_stock) VALUES (%s,0) ON CONFLICT DO NOTHING", (pid,))
            flash("Товар добавлен!", "success")
            return redirect(url_for("products"))
        except Exception as e:
            flash(str(e), "danger")
    return render_template("product_form.html", cats=cats, manuf=manuf, product=None)

@app.route("/products/edit/<int:pid>", methods=["GET","POST"])
def product_edit(pid):
    cats  = query("SELECT category_id, name FROM categories ORDER BY name")
    manuf = query("SELECT manufacturer_id, name FROM manufacturers ORDER BY name")
    product = query("SELECT * FROM products WHERE product_id=%s", (pid,), one=True)
    if request.method == "POST":
        f = request.form
        try:
            execute("""
                UPDATE products SET name=%s,category_id=%s,manufacturer_id=%s,
                    article=%s,description=%s,retail_price=%s,
                    warranty_months=%s,status=%s WHERE product_id=%s
            """, (f["name"], f["category_id"] or None, f["manufacturer_id"] or None,
                  f["article"] or None, f["description"] or None,
                  float(f["retail_price"]), int(f.get("warranty_months",12)),
                  f["status"], pid))
            flash("Товар обновлён!", "success")
            return redirect(url_for("products"))
        except Exception as e:
            flash(str(e), "danger")
    return render_template("product_form.html", cats=cats, manuf=manuf, product=product)

# ── Клиенты ──────────────────────────────────────────────────────
@app.route("/clients")
def clients():
    search = request.args.get("q", "")
    rows = query("""
        SELECT client_id, client_type,
               COALESCE(last_name||' '||first_name, org_name,'—') name,
               phone, email, discount_pct,
               TO_CHAR(registered_at,'DD.MM.YYYY') reg
        FROM clients
        WHERE last_name ILIKE %s OR first_name ILIKE %s
           OR org_name ILIKE %s OR phone ILIKE %s
        ORDER BY client_id
    """, (f"%{search}%",)*4)
    return render_template("clients.html", rows=rows, search=search)

@app.route("/clients/add", methods=["GET","POST"])
def client_add():
    if request.method == "POST":
        f = request.form
        try:
            execute("""
                INSERT INTO clients (client_type,last_name,first_name,patronymic,
                    org_name,inn,phone,email,address,discount_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (f["client_type"],
                  f["last_name"] or None, f["first_name"] or None, f["patronymic"] or None,
                  f["org_name"] or None, f["inn"] or None,
                  f["phone"] or None, f["email"] or None, f["address"] or None,
                  float(f.get("discount_pct",0) or 0)))
            flash("Клиент добавлен!", "success")
            return redirect(url_for("clients"))
        except Exception as e:
            flash(str(e), "danger")
    return render_template("client_form.html", client=None)

@app.route("/clients/edit/<int:cid>", methods=["GET","POST"])
def client_edit(cid):
    client = query("SELECT * FROM clients WHERE client_id=%s", (cid,), one=True)
    if request.method == "POST":
        f = request.form
        try:
            execute("""
                UPDATE clients SET client_type=%s,last_name=%s,first_name=%s,
                    patronymic=%s,org_name=%s,inn=%s,phone=%s,email=%s,
                    address=%s,discount_pct=%s WHERE client_id=%s
            """, (f["client_type"],
                  f["last_name"] or None, f["first_name"] or None, f["patronymic"] or None,
                  f["org_name"] or None, f["inn"] or None,
                  f["phone"] or None, f["email"] or None, f["address"] or None,
                  float(f.get("discount_pct",0) or 0), cid))
            flash("Клиент обновлён!", "success")
            return redirect(url_for("clients"))
        except Exception as e:
            flash(str(e), "danger")
    return render_template("client_form.html", client=client)

# ── Заказы ───────────────────────────────────────────────────────
@app.route("/orders")
def orders():
    status = request.args.get("status", "")
    rows = query("""
        SELECT o.order_id, TO_CHAR(o.order_date,'DD.MM.YYYY HH24:MI') dt,
               COALESCE(cl.last_name||' '||cl.first_name,cl.org_name,'—') client,
               COALESCE(e.last_name||' '||e.first_name,'—') manager,
               o.total_amount,
               COALESCE(SUM(p.amount) FILTER(WHERE p.status='проведён'),0) paid,
               o.status
        FROM orders o
        JOIN clients cl ON cl.client_id=o.client_id
        LEFT JOIN employees e ON e.employee_id=o.employee_id
        LEFT JOIN payments p ON p.order_id=o.order_id
        WHERE (%s='' OR o.status=%s)
        GROUP BY o.order_id,cl.last_name,cl.first_name,cl.org_name,e.last_name,e.first_name
        ORDER BY o.order_id DESC
    """, (status, status))
    return render_template("orders.html", rows=rows, status=status)

@app.route("/orders/add", methods=["GET","POST"])
def order_add():
    clients_list = query("SELECT client_id, COALESCE(last_name||' '||first_name,org_name) nm FROM clients ORDER BY nm")
    employees    = query("SELECT employee_id, last_name||' '||first_name nm FROM employees ORDER BY nm")
    if request.method == "POST":
        f = request.form
        try:
            oid = execute("""
                INSERT INTO orders (client_id,employee_id,comment)
                VALUES (%s,%s,%s) RETURNING order_id
            """, (f["client_id"], f["employee_id"] or None, f["comment"] or None))
            flash(f"Заказ №{oid} создан! Добавьте товары.", "success")
            return redirect(url_for("order_detail", oid=oid))
        except Exception as e:
            flash(str(e), "danger")
    return render_template("order_form.html", clients=clients_list, employees=employees)

@app.route("/orders/<int:oid>")
def order_detail(oid):
    order = query("""
        SELECT o.*, TO_CHAR(o.order_date,'DD.MM.YYYY HH24:MI') dt,
               COALESCE(cl.last_name||' '||cl.first_name,cl.org_name,'—') client_name,
               cl.phone, cl.email,
               COALESCE(e.last_name||' '||e.first_name,'—') manager_name
        FROM orders o
        JOIN clients cl ON cl.client_id=o.client_id
        LEFT JOIN employees e ON e.employee_id=o.employee_id
        WHERE o.order_id=%s
    """, (oid,), one=True)
    items = query("""
        SELECT oi.item_id, p.name, oi.quantity, oi.unit_price, oi.discount_pct,
               ROUND(oi.quantity*oi.unit_price*(1-oi.discount_pct/100),2) total
        FROM order_items oi JOIN products p ON p.product_id=oi.product_id
        WHERE oi.order_id=%s
    """, (oid,))
    payments = query("""
        SELECT TO_CHAR(payment_date,'DD.MM.YYYY') dt, amount, payment_method, status
        FROM payments WHERE order_id=%s ORDER BY payment_date
    """, (oid,))
    products_avail = query("""
        SELECT p.product_id, p.name, p.retail_price,
               COALESCE(w.quantity_in_stock,0) stock
        FROM products p LEFT JOIN warehouse w ON w.product_id=p.product_id
        WHERE p.status='в наличии' AND COALESCE(w.quantity_in_stock,0)>0
        ORDER BY p.name
    """)
    paid = sum(float(p["amount"]) for p in payments if p["status"]=="проведён")
    return render_template("order_detail.html", order=order, items=items,
                           payments=payments, products=products_avail, paid=paid)

@app.route("/orders/<int:oid>/add_item", methods=["POST"])
def order_add_item(oid):
    f = request.form
    try:
        execute("""
            INSERT INTO order_items (order_id,product_id,quantity,unit_price,discount_pct)
            VALUES (%s,%s,%s,%s,%s)
        """, (oid, f["product_id"], int(f["quantity"]),
              float(f["unit_price"]), float(f.get("discount_pct",0) or 0)))
        flash("Товар добавлен в заказ!", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("order_detail", oid=oid))

@app.route("/orders/<int:oid>/pay", methods=["POST"])
def order_pay(oid):
    f = request.form
    try:
        execute("""
            INSERT INTO payments (order_id,amount,payment_method,status)
            VALUES (%s,%s,%s,'проведён')
        """, (oid, float(f["amount"]), f["payment_method"]))
        execute("UPDATE orders SET status='оплачен' WHERE order_id=%s AND status='новый'", (oid,))
        flash("Оплата проведена!", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("order_detail", oid=oid))

@app.route("/orders/<int:oid>/status", methods=["POST"])
def order_status(oid):
    execute("UPDATE orders SET status=%s WHERE order_id=%s",
            (request.form["status"], oid))
    flash("Статус обновлён!", "success")
    return redirect(url_for("order_detail", oid=oid))

# ── Склад ────────────────────────────────────────────────────────
@app.route("/warehouse")
def warehouse():
    rows = query("""
        SELECT w.product_id, p.article, p.name, c.name cat,
               w.quantity_in_stock stock, p.retail_price,
               CASE WHEN w.quantity_in_stock=0   THEN 'zero'
                    WHEN w.quantity_in_stock<5    THEN 'low'
                    ELSE 'ok' END badge,
               TO_CHAR(w.updated_at,'DD.MM.YYYY HH24:MI') upd
        FROM warehouse w JOIN products p ON p.product_id=w.product_id
        LEFT JOIN categories c ON c.category_id=p.category_id
        ORDER BY w.quantity_in_stock ASC
    """)
    return render_template("warehouse.html", rows=rows)

@app.route("/warehouse/adjust/<int:pid>", methods=["POST"])
def warehouse_adjust(pid):
    qty = int(request.form["qty"])
    execute("UPDATE warehouse SET quantity_in_stock=%s, updated_at=NOW() WHERE product_id=%s", (qty, pid))
    flash("Остаток обновлён!", "success")
    return redirect(url_for("warehouse"))

# ── Поставки ─────────────────────────────────────────────────────
@app.route("/supplies")
def supplies():
    rows = query("""
        SELECT s.supply_id, TO_CHAR(s.supply_date,'DD.MM.YYYY') dt,
               sp.name supplier, s.status, s.total_amount,
               COUNT(si.supply_item_id) items
        FROM supplies s JOIN suppliers sp ON sp.supplier_id=s.supplier_id
        LEFT JOIN supply_items si ON si.supply_id=s.supply_id
        GROUP BY s.supply_id, sp.name ORDER BY s.supply_id DESC
    """)
    return render_template("supplies.html", rows=rows)

@app.route("/supplies/add", methods=["GET","POST"])
def supply_add():
    suppliers = query("SELECT supplier_id, name FROM suppliers ORDER BY name")
    if request.method == "POST":
        f = request.form
        sid = execute("""
            INSERT INTO supplies (supplier_id, comment) VALUES (%s,%s)
            RETURNING supply_id
        """, (f["supplier_id"], f["comment"] or None))
        flash(f"Поставка №{sid} создана!", "success")
        return redirect(url_for("supply_detail", sid=sid))
    return render_template("supply_form.html", suppliers=suppliers)

@app.route("/supplies/<int:sid>")
def supply_detail(sid):
    supply = query("""
        SELECT s.*, TO_CHAR(s.supply_date,'DD.MM.YYYY') dt, sp.name supplier_name
        FROM supplies s JOIN suppliers sp ON sp.supplier_id=s.supplier_id
        WHERE s.supply_id=%s
    """, (sid,), one=True)
    items = query("""
        SELECT si.supply_item_id, p.name, si.quantity, si.purchase_price,
               si.quantity*si.purchase_price total
        FROM supply_items si JOIN products p ON p.product_id=si.product_id
        WHERE si.supply_id=%s
    """, (sid,))
    products_list = query("SELECT product_id, name FROM products WHERE status!='снят с продажи' ORDER BY name")
    return render_template("supply_detail.html", supply=supply, items=items, products=products_list)

@app.route("/supplies/<int:sid>/add_item", methods=["POST"])
def supply_add_item(sid):
    f = request.form
    try:
        execute("""
            INSERT INTO supply_items (supply_id, product_id, quantity, purchase_price)
            VALUES (%s,%s,%s,%s)
        """, (sid, f["product_id"], int(f["quantity"]), float(f["purchase_price"])))
        flash("Товар добавлен в поставку!", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("supply_detail", sid=sid))

# ── Сервис ───────────────────────────────────────────────────────
@app.route("/service")
def service():
    rows = query("""
        SELECT sr.request_id, TO_CHAR(sr.received_date,'DD.MM.YYYY') dt,
               COALESCE(cl.last_name||' '||cl.first_name,cl.org_name,'—') client,
               p.name product, sr.status,
               COALESCE(e.last_name||' '||e.first_name,'—') master,
               LEFT(sr.problem_desc,60) descr
        FROM service_requests sr
        JOIN clients cl ON cl.client_id=sr.client_id
        JOIN products p ON p.product_id=sr.product_id
        LEFT JOIN employees e ON e.employee_id=sr.master_id
        ORDER BY sr.request_id DESC
    """)
    return render_template("service.html", rows=rows)

@app.route("/service/add", methods=["GET","POST"])
def service_add():
    clients_list = query("SELECT client_id, COALESCE(last_name||' '||first_name,org_name) nm FROM clients ORDER BY nm")
    products_list = query("SELECT product_id, name FROM products ORDER BY name")
    if request.method == "POST":
        f = request.form
        execute("""
            INSERT INTO service_requests (client_id, product_id, problem_desc)
            VALUES (%s,%s,%s)
        """, (f["client_id"], f["product_id"], f["problem_desc"]))
        flash("Заявка создана!", "success")
        return redirect(url_for("service"))
    return render_template("service_form.html", clients=clients_list, products=products_list)

@app.route("/service/update/<int:rid>", methods=["POST"])
def service_update(rid):
    f = request.form
    execute("""
        UPDATE service_requests SET status=%s, result=%s,
            issued_date=CASE WHEN %s IN ('выдана','выполнена') THEN NOW() ELSE NULL END
        WHERE request_id=%s
    """, (f["status"], f.get("result") or None, f["status"], rid))
    flash("Статус обновлён!", "success")
    return redirect(url_for("service"))

# ── Отчёты ───────────────────────────────────────────────────────
@app.route("/reports")
def reports():
    sales = query("""
        SELECT TO_CHAR(DATE_TRUNC('month',o.order_date),'MM.YYYY') period,
               c.name cat, SUM(oi.quantity) qty,
               ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct/100)),2) revenue
        FROM order_items oi
        JOIN orders o ON o.order_id=oi.order_id
        JOIN products p ON p.product_id=oi.product_id
        JOIN categories c ON c.category_id=p.category_id
        WHERE o.status!='отменён'
        GROUP BY 1,2 ORDER BY 1 DESC, 4 DESC
    """)
    top = query("""
        SELECT p.name, SUM(oi.quantity) qty,
               ROUND(SUM(oi.quantity*oi.unit_price*(1-oi.discount_pct/100)),2) revenue
        FROM order_items oi
        JOIN orders o ON o.order_id=oi.order_id
        JOIN products p ON p.product_id=oi.product_id
        WHERE o.status!='отменён'
        GROUP BY p.name ORDER BY qty DESC LIMIT 10
    """)
    debts = query("""
        SELECT o.order_id, TO_CHAR(o.order_date,'DD.MM.YYYY') dt,
               COALESCE(cl.last_name||' '||cl.first_name,cl.org_name,'—') client,
               o.total_amount,
               COALESCE(SUM(p.amount) FILTER(WHERE p.status='проведён'),0) paid,
               o.total_amount-COALESCE(SUM(p.amount) FILTER(WHERE p.status='проведён'),0) debt
        FROM orders o JOIN clients cl ON cl.client_id=o.client_id
        LEFT JOIN payments p ON p.order_id=o.order_id
        WHERE o.status NOT IN ('отменён')
        GROUP BY o.order_id,cl.last_name,cl.first_name,cl.org_name
        HAVING o.total_amount-COALESCE(SUM(p.amount) FILTER(WHERE p.status='проведён'),0)>0
        ORDER BY 6 DESC
    """)
    return render_template("reports.html", sales=sales, top=top, debts=debts)

# ── Запуск ───────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
