"""
Скрипт инициализации БД на Railway.
Запусти один раз после деплоя:
  python init_db.py
"""
import os
import psycopg2

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql://", 1)

SQL = """
SET client_encoding = 'UTF8';

CREATE TABLE IF NOT EXISTS categories (
    category_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);
CREATE TABLE IF NOT EXISTS manufacturers (
    manufacturer_id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE,
    country VARCHAR(100), website VARCHAR(200), contact_info TEXT
);
CREATE TABLE IF NOT EXISTS departments (
    department_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE, description TEXT
);
CREATE TABLE IF NOT EXISTS employees (
    employee_id SERIAL PRIMARY KEY,
    last_name VARCHAR(80) NOT NULL, first_name VARCHAR(80) NOT NULL,
    patronymic VARCHAR(80), position VARCHAR(100) NOT NULL,
    department_id INTEGER REFERENCES departments(department_id) ON DELETE SET NULL,
    login VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL DEFAULT 'changeme',
    email VARCHAR(150), phone VARCHAR(20),
    hire_date DATE DEFAULT CURRENT_DATE, is_active BOOLEAN DEFAULT TRUE
);
ALTER TABLE departments ADD COLUMN IF NOT EXISTS head_employee_id INTEGER REFERENCES employees(employee_id) ON DELETE SET NULL;
CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category_id INTEGER REFERENCES categories(category_id) ON DELETE SET NULL,
    manufacturer_id INTEGER REFERENCES manufacturers(manufacturer_id) ON DELETE SET NULL,
    article VARCHAR(50) UNIQUE, description TEXT,
    retail_price NUMERIC(12,2) NOT NULL CHECK (retail_price > 0),
    warranty_months INTEGER DEFAULT 12 CHECK (warranty_months >= 0),
    status VARCHAR(30) NOT NULL DEFAULT 'в наличии'
        CHECK (status IN ('в наличии', 'под заказ', 'снят с продажи')),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS warehouse (
    warehouse_id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL UNIQUE REFERENCES products(product_id) ON DELETE CASCADE,
    quantity_in_stock INTEGER NOT NULL DEFAULT 0 CHECK (quantity_in_stock >= 0),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL, inn VARCHAR(12) UNIQUE,
    contact_person VARCHAR(150), phone VARCHAR(20),
    email VARCHAR(150), address TEXT, created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS supplies (
    supply_id SERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    supply_date TIMESTAMP NOT NULL DEFAULT NOW(),
    status VARCHAR(30) NOT NULL DEFAULT 'новая'
        CHECK (status IN ('новая','подтверждена','получена','отменена')),
    total_amount NUMERIC(14,2) DEFAULT 0,
    comment TEXT, created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS supply_items (
    supply_item_id SERIAL PRIMARY KEY,
    supply_id INTEGER NOT NULL REFERENCES supplies(supply_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    purchase_price NUMERIC(12,2) NOT NULL CHECK (purchase_price > 0),
    UNIQUE (supply_id, product_id)
);
CREATE TABLE IF NOT EXISTS clients (
    client_id SERIAL PRIMARY KEY,
    client_type VARCHAR(10) NOT NULL DEFAULT 'физлицо'
        CHECK (client_type IN ('физлицо', 'юрлицо')),
    last_name VARCHAR(80), first_name VARCHAR(80), patronymic VARCHAR(80),
    org_name VARCHAR(200), inn VARCHAR(12),
    phone VARCHAR(20), email VARCHAR(150), address TEXT,
    discount_pct NUMERIC(5,2) DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    registered_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
    order_id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(client_id) ON DELETE RESTRICT,
    employee_id INTEGER REFERENCES employees(employee_id) ON DELETE SET NULL,
    order_date TIMESTAMP NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'новый'
        CHECK (status IN ('новый','оплачен','в сборке','отгружен','отменён')),
    total_amount NUMERIC(14,2) DEFAULT 0, comment TEXT
);
CREATE TABLE IF NOT EXISTS order_items (
    item_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price > 0),
    discount_pct NUMERIC(5,2) DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    UNIQUE (order_id, product_id)
);
CREATE TABLE IF NOT EXISTS payments (
    payment_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    payment_date TIMESTAMP NOT NULL DEFAULT NOW(),
    amount NUMERIC(14,2) NOT NULL CHECK (amount > 0),
    payment_method VARCHAR(20) NOT NULL DEFAULT 'наличные'
        CHECK (payment_method IN ('наличные','карта','перевод','онлайн')),
    status VARCHAR(20) NOT NULL DEFAULT 'проведён'
        CHECK (status IN ('ожидает','проведён','отклонён','возврат')),
    comment TEXT
);
CREATE TABLE IF NOT EXISTS service_requests (
    request_id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(client_id) ON DELETE RESTRICT,
    product_id INTEGER NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    order_id INTEGER REFERENCES orders(order_id) ON DELETE SET NULL,
    received_date TIMESTAMP NOT NULL DEFAULT NOW(),
    problem_desc TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'принята'
        CHECK (status IN ('принята','в работе','выполнена','отказано','выдана')),
    master_id INTEGER REFERENCES employees(employee_id) ON DELETE SET NULL,
    result TEXT, issued_date TIMESTAMP
);

-- Триггер 1: списание склада при продаже
CREATE OR REPLACE FUNCTION fn_decrease_stock_on_sale() RETURNS TRIGGER AS $$
DECLARE v_stock INTEGER; v_name VARCHAR(200);
BEGIN
    SELECT w.quantity_in_stock, p.name INTO v_stock, v_name
    FROM warehouse w JOIN products p ON p.product_id=w.product_id
    WHERE w.product_id=NEW.product_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Товар не найден на складе'; END IF;
    IF v_stock < NEW.quantity THEN
        RAISE EXCEPTION 'Недостаточно товара "%" на складе. Запрошено: %, в наличии: %', v_name, NEW.quantity, v_stock;
    END IF;
    UPDATE warehouse SET quantity_in_stock=quantity_in_stock-NEW.quantity, updated_at=NOW() WHERE product_id=NEW.product_id;
    IF (v_stock-NEW.quantity)=0 THEN UPDATE products SET status='под заказ' WHERE product_id=NEW.product_id; END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_decrease_stock_on_sale ON order_items;
CREATE TRIGGER trg_decrease_stock_on_sale AFTER INSERT ON order_items FOR EACH ROW EXECUTE FUNCTION fn_decrease_stock_on_sale();

-- Триггер 2: пересчёт суммы заказа
CREATE OR REPLACE FUNCTION fn_recalculate_order_total() RETURNS TRIGGER AS $$
DECLARE v_order_id INTEGER;
BEGIN
    v_order_id := COALESCE(NEW.order_id, OLD.order_id);
    UPDATE orders SET total_amount=(SELECT COALESCE(SUM(quantity*unit_price*(1.0-discount_pct/100.0)),0) FROM order_items WHERE order_id=v_order_id) WHERE order_id=v_order_id;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_recalculate_order_total ON order_items;
CREATE TRIGGER trg_recalculate_order_total AFTER INSERT OR UPDATE OR DELETE ON order_items FOR EACH ROW EXECUTE FUNCTION fn_recalculate_order_total();

-- Триггер 3: пополнение склада при поставке
CREATE OR REPLACE FUNCTION fn_increase_stock_on_supply() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO warehouse (product_id, quantity_in_stock, updated_at) VALUES (NEW.product_id, NEW.quantity, NOW())
    ON CONFLICT (product_id) DO UPDATE SET quantity_in_stock=warehouse.quantity_in_stock+NEW.quantity, updated_at=NOW();
    UPDATE products SET status='в наличии' WHERE product_id=NEW.product_id AND status='под заказ';
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_increase_stock_on_supply ON supply_items;
CREATE TRIGGER trg_increase_stock_on_supply AFTER INSERT ON supply_items FOR EACH ROW EXECUTE FUNCTION fn_increase_stock_on_supply();

-- Тестовые данные (только если таблицы пустые)
INSERT INTO categories (name) SELECT * FROM (VALUES ('Ноутбуки'),('Настольные ПК'),('Мониторы'),('Комплектующие'),('Периферия'),('Сетевое оборудование')) v WHERE NOT EXISTS (SELECT 1 FROM categories);
INSERT INTO manufacturers (name, country) SELECT * FROM (VALUES ('ASUS','Тайвань'),('HP','США'),('Lenovo','Китай'),('Samsung','Южная Корея'),('Logitech','Швейцария'),('Kingston','США')) v WHERE NOT EXISTS (SELECT 1 FROM manufacturers);
INSERT INTO departments (name) SELECT * FROM (VALUES ('Отдел продаж'),('Склад'),('Бухгалтерия'),('Отдел закупок'),('Сервисный центр'),('Администрация')) v WHERE NOT EXISTS (SELECT 1 FROM departments);
INSERT INTO employees (last_name,first_name,position,department_id,login) SELECT 'Иванов','Алексей','Директор',6,'ivanov' WHERE NOT EXISTS (SELECT 1 FROM employees);
INSERT INTO employees (last_name,first_name,position,department_id,login) SELECT 'Петрова','Мария','Менеджер по продажам',1,'petrova' WHERE NOT EXISTS (SELECT 1 FROM employees WHERE login='petrova');
INSERT INTO suppliers (name) SELECT 'ООО «ТехноОптПоставка»' WHERE NOT EXISTS (SELECT 1 FROM suppliers);
INSERT INTO clients (client_type,last_name,first_name,phone) SELECT 'физлицо','Морозов','Игорь','+7-916-111-11-11' WHERE NOT EXISTS (SELECT 1 FROM clients);
INSERT INTO clients (client_type,org_name,phone) SELECT 'юрлицо','ООО «ТехГрупп»','+7-495-444-44-44' WHERE NOT EXISTS (SELECT 1 FROM clients WHERE org_name IS NOT NULL);
INSERT INTO products (name,category_id,manufacturer_id,article,retail_price,warranty_months) SELECT 'ASUS VivoBook 15',1,1,'NB-ASUS-1504',65990,24 WHERE NOT EXISTS (SELECT 1 FROM products);
INSERT INTO products (name,category_id,manufacturer_id,article,retail_price,warranty_months) SELECT 'HP Laptop 15s',1,2,'NB-HP-15S',45990,24 WHERE NOT EXISTS (SELECT 1 FROM products WHERE article='NB-HP-15S');
INSERT INTO products (name,category_id,manufacturer_id,article,retail_price,warranty_months) SELECT 'Samsung 27" Monitor',3,4,'MON-SAM-27',28990,36 WHERE NOT EXISTS (SELECT 1 FROM products WHERE article='MON-SAM-27');
INSERT INTO products (name,category_id,manufacturer_id,article,retail_price,warranty_months) SELECT 'Logitech MX Keys S',5,5,'KB-LOG-MX',10990,12 WHERE NOT EXISTS (SELECT 1 FROM products WHERE article='KB-LOG-MX');
INSERT INTO products (name,category_id,manufacturer_id,article,retail_price,warranty_months) SELECT 'Kingston 16GB DDR5',4,6,'RAM-KIN-16',6990,36 WHERE NOT EXISTS (SELECT 1 FROM products WHERE article='RAM-KIN-16');
INSERT INTO warehouse (product_id,quantity_in_stock) SELECT product_id, 10 FROM products WHERE product_id NOT IN (SELECT product_id FROM warehouse);
"""

try:
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(SQL)
    print("✅ База данных инициализирована успешно!")
    conn.close()
except Exception as e:
    print(f"❌ Ошибка: {e}")
