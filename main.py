from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, session, flash
import sqlite3
import json
from datetime import datetime, timedelta
import pandas as pd
import os
from io import BytesIO
import hashlib
from functools import wraps

app = Flask(__name__)
app.secret_key = 'carwash_peña_blanca_secret_key'

# Admin password (hashed)
ADMIN_PASSWORD_HASH = hashlib.sha256('742211010338'.encode()).hexdigest()

# Initialize database
def init_db():
    conn = sqlite3.connect('carwash.db')
    cursor = conn.cursor()

    # Products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0,
            category TEXT,
            barcode TEXT UNIQUE,
            service_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Customers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Sales table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            total REAL NOT NULL,
            tax REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            payment_method TEXT,
            status TEXT DEFAULT 'completed',
            invoice_number TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
    ''')

    # Sale items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER,
            product_id INTEGER,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')

    # Promotions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            discount_percentage REAL DEFAULT 0,
            discount_amount REAL DEFAULT 0,
            min_purchase REAL DEFAULT 0,
            max_discount REAL DEFAULT 0,
            start_date DATE,
            end_date DATE,
            is_active BOOLEAN DEFAULT 1,
            promo_type TEXT DEFAULT 'discount',
            required_visits INTEGER DEFAULT 0,
            free_product_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Customer loyalty tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS customer_loyalty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            promotion_id INTEGER,
            visits_count INTEGER DEFAULT 0,
            earned_rewards TEXT,
            last_visit TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id),
            FOREIGN KEY (promotion_id) REFERENCES promotions (id)
        )
    ''')

    # Insert sample promotions
    cursor.execute("SELECT COUNT(*) FROM promotions")
    if cursor.fetchone()[0] == 0:
        sample_promotions = [
            ('Descuento 10%', 'Descuento del 10% en compras mayores a L. 200', 10.0, 0, 200.0, 50.0, '2025-01-01', '2025-12-31', 1),
            ('Descuento L. 25', 'Descuento fijo de L. 25 en compras mayores a L. 150', 0, 25.0, 150.0, 25.0, '2025-01-01', '2025-12-31', 1),
            ('Promoción Premium', 'Descuento 15% en servicios premium', 15.0, 0, 300.0, 100.0, '2025-01-01', '2025-12-31', 1)
        ]
        cursor.executemany(
            "INSERT INTO promotions (name, description, discount_percentage, discount_amount, min_purchase, max_discount, start_date, end_date, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
            sample_promotions
        )

    # Insert sample data
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        sample_products = [
            ('Lavado Básico', 'Lavado exterior básico', 150.00, 999, 'Servicios', 'CWP001', 'CWP1'),
            ('Lavado Premium', 'Lavado completo interior y exterior', 250.00, 999, 'Servicios', 'CWP002', 'CWP2'),
            ('Lavado Completo', 'Lavado premium + encerado', 350.00, 999, 'Servicios', 'CWP003', 'CWP3'),
            ('Encerado Simple', 'Aplicación de cera protectora', 100.00, 999, 'Servicios', 'CWP004', 'CWP4'),
            ('Shampuseado', 'Lavado con shampoo especial', 80.00, 999, 'Servicios', 'CWP005', 'CWP5'),
            ('Pulida de Rines', 'Pulido y brillo de rines', 120.00, 999, 'Servicios', 'CWP006', 'CWP6'),
            ('Shampoo para Auto', 'Shampoo especial para vehículos', 80.00, 50, 'Productos', '7501234567890', 'PROD1'),
            ('Cera Líquida', 'Cera protectora líquida', 120.00, 30, 'Productos', '7501234567891', 'PROD2'),
            ('Toalla Microfibra', 'Toalla de secado microfibra', 50.00, 25, 'Productos', '7501234567892', 'PROD3')
        ]
        cursor.executemany("INSERT INTO products (name, description, price, stock, category, barcode, service_code) VALUES (?, ?, ?, ?, ?, ?, ?)", sample_products)

    # Insert sample customer
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        sample_customers = [
            ('dennis castillo', '97164446', 'd99184263@gmail.com', 'peña blanca cortes')
        ]
        cursor.executemany("INSERT INTO customers (name, phone, email, address) VALUES (?, ?, ?, ?)", sample_customers)

    conn.commit()
    conn.close()

# Database helper functions
def get_db_connection():
    conn = sqlite3.connect('carwash.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_invoice_number():
    return f"CWP-{datetime.now().strftime('%Y%m%d%H%M%S')}"

def calculate_promotional_discount(subtotal):
    """Calcula el mejor descuento promocional aplicable"""
    conn = get_db_connection()

    # Obtener promociones activas válidas para el subtotal
    promotions = conn.execute("""
        SELECT * FROM promotions 
        WHERE is_active = 1 
        AND min_purchase <= ? 
        AND (end_date >= DATE('now') OR end_date IS NULL)
        ORDER BY discount_percentage DESC, discount_amount DESC
    """, (subtotal,)).fetchall()

    conn.close()

    best_discount = 0
    applied_promo = None

    for promo in promotions:
        if promo['discount_percentage'] > 0:
            # Descuento porcentual
            discount = (subtotal * promo['discount_percentage']) / 100
            if promo['max_discount'] > 0:
                discount = min(discount, promo['max_discount'])
        else:
            # Descuento fijo
            discount = promo['discount_amount']

        if discount > best_discount:
            best_discount = discount
            applied_promo = promo

    return best_discount, applied_promo

# Access control decorator
def require_system_access():
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('admin_logged_in'):
                flash('Acceso restringido. Inicie sesión como administrador.', 'warning')
                return redirect(url_for('admin_login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Access control decorator for system access
def require_system_login():
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('system_logged_in'):
                return redirect(url_for('system_login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Routes
@app.route('/')
def index():
    if not session.get('system_logged_in'):
        return redirect(url_for('system_login'))
    return redirect(url_for('dashboard'))

@app.route('/system_login', methods=['GET', 'POST'])
def system_login():
    if request.method == 'POST':
        password = request.form['password']
        if password == '742211010338':
            session['system_logged_in'] = True
            session['admin_logged_in'] = True  # También dar acceso admin
            flash('Acceso autorizado al sistema', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Contraseña incorrecta', 'error')

    return render_template('system_login.html')

@app.route('/system_logout')
def system_logout():
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('system_login'))

@app.route('/dashboard')
@require_system_login()
def dashboard():
    conn = get_db_connection()

    # Get statistics
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    total_sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    daily_revenue = conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM sales WHERE DATE(created_at) = DATE('now')"
    ).fetchone()[0]

    # Recent sales
    recent_sales = conn.execute("""
        SELECT s.id, s.invoice_number, c.name as customer_name, s.total, s.created_at
        FROM sales s
        LEFT JOIN customers c ON s.customer_id = c.id
        ORDER BY s.created_at DESC
        LIMIT 5
    """).fetchall()

    conn.close()

    return render_template('dashboard.html', 
                         total_products=total_products,
                         total_customers=total_customers, 
                         total_sales=total_sales,
                         daily_revenue=daily_revenue,
                         recent_sales=recent_sales)

@app.route('/products')
@require_system_login()
def products():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return render_template('products.html', products=products)

@app.route('/products/add', methods=['GET', 'POST'])
@require_system_login()
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        stock = int(request.form['stock'])
        category = request.form['category']

        conn = get_db_connection()

        # Verificar si el producto ya existe
        existing_product = conn.execute(
            "SELECT * FROM products WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()

        if existing_product:
            # Si existe, solo actualizar la cantidad
            new_stock = existing_product['stock'] + stock
            conn.execute(
                "UPDATE products SET stock = ? WHERE id = ?",
                (new_stock, existing_product['id'])
            )
            flash(f'Producto existente actualizado. Nueva cantidad: {new_stock}', 'info')
        else:
            # Si no existe, crear nuevo
            conn.execute(
                "INSERT INTO products (name, description, price, stock, category) VALUES (?, ?, ?, ?, ?)",
                (name, description, price, stock, category)
            )
            flash('Producto agregado exitosamente', 'success')

        conn.commit()
        conn.close()

        return redirect(url_for('products'))

    return render_template('add_product.html')

@app.route('/customers')
@require_system_login()
def customers():
    conn = get_db_connection()
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    conn.close()
    return render_template('customers.html', customers=customers)

@app.route('/customers/add', methods=['GET', 'POST'])
@require_system_login()
def add_customer():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        email = request.form['email']
        address = request.form['address']

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO customers (name, phone, email, address) VALUES (?, ?, ?, ?)",
            (name, phone, email, address)
        )
        conn.commit()
        conn.close()

        return redirect(url_for('customers'))

    return render_template('add_customer.html')

@app.route('/sales')
@require_system_login()
def sales():
    conn = get_db_connection()
    sales = conn.execute("""
        SELECT s.id, s.invoice_number, c.name as customer_name, s.total, s.created_at, s.status
        FROM sales s
        LEFT JOIN customers c ON s.customer_id = c.id
        ORDER BY s.created_at DESC
    """).fetchall()
    conn.close()
    return render_template('sales.html', sales=sales)

@app.route('/sales/new', methods=['GET', 'POST'])
@require_system_login()
def new_sale():
    if request.method == 'POST':
        customer_id = request.form.get('customer_id') or None
        new_customer_data = request.form.get('new_customer_data')
        payment_method = request.form['payment_method']
        items = json.loads(request.form['items'])

        conn = get_db_connection()

        # Handle new customer
        if customer_id == 'new' and new_customer_data:
            customer_data = json.loads(new_customer_data)
            cursor = conn.execute(
                "INSERT INTO customers (name, phone, email, address) VALUES (?, ?, ?, ?)",
                (customer_data['name'], customer_data['phone'], customer_data['email'], customer_data['address'])
            )
            customer_id = cursor.lastrowid

        # Calculate totals
        subtotal = sum(float(item['subtotal']) for item in items)

        # Calcular descuento promocional
        promotional_discount, applied_promo = calculate_promotional_discount(subtotal)

        total = subtotal - promotional_discount
        invoice_number = generate_invoice_number()

        # Insert sale
        cursor = conn.execute(
            "INSERT INTO sales (customer_id, total, discount, payment_method, invoice_number) VALUES (?, ?, ?, ?, ?)",
            (customer_id, total, promotional_discount, payment_method, invoice_number)
        )
        sale_id = cursor.lastrowid

        # Insert sale items and update stock
        for item in items:
            product_id = item['product_id']

            # Handle manual products
            if str(product_id).startswith('manual_'):
                # Create temporary product entry or use NULL
                product_id = None

            conn.execute(
                "INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?)",
                (sale_id, product_id, item['quantity'], item['unit_price'], item['subtotal'])
            )

            # Update product stock only for existing products
            if product_id and not str(item['product_id']).startswith('manual_'):
                conn.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (item['quantity'], product_id)
                )

        conn.commit()
        conn.close()

        return redirect(url_for('view_invoice', sale_id=sale_id))

    # GET request
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products WHERE stock > 0 ORDER BY name").fetchall()
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    conn.close()

    return render_template('new_sale.html', products=products, customers=customers)

@app.route('/sales/<int:sale_id>/invoice')
@require_system_login()
def view_invoice(sale_id):
    conn = get_db_connection()

    sale = conn.execute("""
        SELECT s.*, c.name as customer_name, c.phone, c.email, c.address
        FROM sales s
        LEFT JOIN customers c ON s.customer_id = c.id
        WHERE s.id = ?
    """, (sale_id,)).fetchone()

    items = conn.execute("""
        SELECT si.*, p.name as product_name
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        WHERE si.sale_id = ?
    """, (sale_id,)).fetchall()

    conn.close()

    return render_template('invoice.html', sale=sale, items=items)

@app.route('/reports')
@require_system_login()
def reports():
    return render_template('reports.html')

@app.route('/reports/sales_excel')
@require_system_login()
def export_sales_excel():
    conn = get_db_connection()

    sales_data = conn.execute("""
        SELECT 
            s.invoice_number as 'Número Factura',
            c.name as 'Cliente',
            s.total as 'Total',
            s.payment_method as 'Método Pago',
            s.created_at as 'Fecha'
        FROM sales s
        LEFT JOIN customers c ON s.customer_id = c.id
        ORDER BY s.created_at DESC
    """).fetchall()

    conn.close()

    # Convert to DataFrame
    columns = ['Número Factura', 'Cliente', 'Total', 'Método Pago', 'Fecha']
    df = pd.DataFrame(sales_data, columns=columns)

    # Create Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Ventas', index=False)

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'ventas_carwash_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )

@app.route('/reports/inventory_excel')
@require_system_login()
def export_inventory_excel():
    conn = get_db_connection()

    inventory_data = conn.execute("""
        SELECT 
            name as 'Producto',
            description as 'Descripción',
            price as 'Precio',
            stock as 'Stock',
            category as 'Categoría'
        FROM products
        ORDER BY category, name
    """).fetchall()

    conn.close()

    # Convert to DataFrame
    df = pd.DataFrame(inventory_data, columns=['Producto', 'Descripción', 'Precio', 'Stock', 'Categoría'])

    # Create Excel file in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Inventario', index=False)

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'inventario_carwash_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form['password']
        if hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
            session['admin_logged_in'] = True
            flash('Acceso administrativo concedido', 'success')
            return redirect(url_for('products'))
        else:
            flash('Contraseña incorrecta', 'error')

    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Sesión administrativa cerrada', 'info')
    return redirect(url_for('products'))

@app.route('/products/<int:product_id>/edit', methods=['POST'])
@require_system_login()
def edit_product(product_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = get_db_connection()

    price = float(request.form['price'])
    stock = int(request.form.get('stock', 0))

    conn.execute("UPDATE products SET price = ?, stock = ? WHERE id = ?", (price, stock, product_id))
    conn.commit()
    conn.close()

    flash('Producto actualizado correctamente', 'success')
    return redirect(url_for('products'))

@app.route('/api/search_product')
def search_product():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'success': False, 'message': 'No se proporcionó búsqueda'})

    conn = get_db_connection()

    # Buscar por código de barras, código de servicio o nombre
    product = conn.execute("""
        SELECT * FROM products 
        WHERE barcode = ? OR service_code = ? OR name LIKE ?
        LIMIT 1
    """, (query, query, f'%{query}%')).fetchone()

    conn.close()

    if product:
        return jsonify({
            'success': True,
            'product': {
                'id': product['id'],
                'name': product['name'],
                'price': product['price'],
                'stock': product['stock'],
                'barcode': product['barcode'],
                'service_code': product['service_code']
            }
        })
    else:
        return jsonify({'success': False, 'message': 'Producto no encontrado'})

@app.route('/sync_inventory', methods=['GET', 'POST'])
@require_system_login()
def sync_inventory():
    if request.method == 'POST':
        password = request.form['password']
        if hashlib.sha256(password.encode()).hexdigest() != ADMIN_PASSWORD_HASH:
            flash('Contraseña incorrecta', 'error')
            return redirect(url_for('sync_inventory'))

        if 'excel_file' not in request.files:
            flash('No se seleccionó archivo', 'error')
            return redirect(url_for('sync_inventory'))

        file = request.files['excel_file']
        if file.filename == '':
            flash('No se seleccionó archivo', 'error')
            return redirect(url_for('sync_inventory'))

        if file and file.filename.endswith('.xlsx'):
            try:
                # Leer el archivo Excel
                df = pd.read_excel(file)

                conn = get_db_connection()
                # Limpiar tabla de productos
                conn.execute("DELETE FROM products")

                # Insertar productos del Excel
                for _, row in df.iterrows():
                    conn.execute("""
                        INSERT INTO products (name, description, price, stock, category)
                        VALUES (?, ?, ?, ?, ?)
                    """, (row['Producto'], row['Descripción'], row['Precio'], row['Stock'], row['Categoría']))

                conn.commit()
                conn.close()

                flash('Inventario sincronizado exitosamente', 'success')
                return redirect(url_for('products'))
            except Exception as e:
                flash(f'Error al procesar archivo: {str(e)}', 'error')
        else:
            flash('Solo archivos .xlsx son permitidos', 'error')

    return render_template('sync_inventory.html')

@app.route('/promotions')
@require_system_login()
def promotions():
    conn = get_db_connection()
    promotions = conn.execute("SELECT * FROM promotions ORDER BY is_active DESC, created_at DESC").fetchall()
    conn.close()
    return render_template('promotions.html', promotions=promotions)

@app.route('/promotions/add', methods=['GET', 'POST'])
@require_system_login()
def add_promotion():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        discount_type = request.form['discount_type']
        discount_value = float(request.form['discount_value'])
        min_purchase = float(request.form['min_purchase'])
        max_discount = float(request.form.get('max_discount', 0))
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        discount_percentage = discount_value if discount_type == 'percentage' else 0
        discount_amount = discount_value if discount_type == 'fixed' else 0

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO promotions (name, description, discount_percentage, discount_amount, 
                                  min_purchase, max_discount, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, description, discount_percentage, discount_amount, min_purchase, max_discount, start_date, end_date))
        conn.commit()
        conn.close()

        flash('Promoción agregada exitosamente', 'success')
        return redirect(url_for('promotions'))

    return render_template('add_promotion.html')

@app.route('/promotions/<int:promo_id>/toggle')
@require_system_login()
def toggle_promotion(promo_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    conn.execute("UPDATE promotions SET is_active = NOT is_active WHERE id = ?", (promo_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('promotions'))

@app.route('/promotions/edit', methods=['POST'])
@require_system_login()
def edit_promotion():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    promo_id = request.form['promo_id']
    name = request.form['name']
    description = request.form['description']
    promo_type = request.form['promo_type']
    min_purchase = float(request.form['min_purchase'])
    start_date = request.form['start_date']
    end_date = request.form['end_date']

    if promo_type == 'loyalty':
        discount_percentage = 0
        discount_amount = 0
        max_discount = 0
        required_visits = int(request.form['required_visits'])
        free_product_name = request.form['free_product_name']
    else:
        discount_type = request.form['discount_type']
        discount_value = float(request.form['discount_value'])
        max_discount = float(request.form['max_discount'])
        required_visits = 0
        free_product_name = ''

        discount_percentage = discount_value if discount_type == 'percentage' else 0
        discount_amount = discount_value if discount_type == 'fixed' else 0

    conn = get_db_connection()
    conn.execute("""
        UPDATE promotions SET 
        name = ?, description = ?, discount_percentage = ?, discount_amount = ?, 
        min_purchase = ?, max_discount = ?, start_date = ?, end_date = ?,
        promo_type = ?, required_visits = ?, free_product_name = ?
        WHERE id = ?
    """, (name, description, discount_percentage, discount_amount, min_purchase, 
          max_discount, start_date, end_date, promo_type, required_visits, 
          free_product_name, promo_id))
    conn.commit()
    conn.close()

    flash('Promoción actualizada exitosamente', 'success')
    return redirect(url_for('promotions'))

@app.route('/api/check_promotion')
def check_promotion():
    total = float(request.args.get('total', 0))
    discount, promo = calculate_promotional_discount(total)

    if promo:
        return jsonify({
            'has_promotion': True,
            'discount': discount,
            'promo_name': promo['name'],
            'promo_description': promo['description']
        })
    else:
        return jsonify({'has_promotion': False})

@app.route('/api/dashboard_data')
def dashboard_data():
    period = int(request.args.get('period', 30))
    category = request.args.get('category', 'all')

    conn = get_db_connection()

    # Construir filtros dinámicos
    category_filter = "" if category == 'all' else f"AND p.category = '{category}'"

    # Ventas por día
    daily_sales = conn.execute(f"""
        SELECT DATE(s.created_at) as date, SUM(s.total) as total, COUNT(*) as count
        FROM sales s
        LEFT JOIN sale_items si ON s.id = si.sale_id
        LEFT JOIN products p ON si.product_id = p.id
        WHERE s.created_at >= DATE('now', '-{period} days') {category_filter}
        GROUP BY DATE(s.created_at)
        ORDER BY date
    """).fetchall()

    # Productos más vendidos
    top_products = conn.execute(f"""
        SELECT p.name, SUM(si.quantity) as quantity_sold, SUM(si.subtotal) as revenue
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE s.created_at >= DATE('now', '-{period} days') {category_filter}
        GROUP BY p.name
        ORDER BY quantity_sold DESC
        LIMIT 10
    """).fetchall()

    # Ventas por categoría
    category_sales = conn.execute(f"""
        SELECT p.category, SUM(si.subtotal) as total, COUNT(DISTINCT s.id) as sales_count
        FROM sale_items si
        JOIN products p ON si.product_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE s.created_at >= DATE('now', '-{period} days')
        GROUP BY p.category
    """).fetchall()

    # Métodos de pago
    payment_methods = conn.execute(f"""
        SELECT s.payment_method as method, SUM(s.total) as total, COUNT(*) as count
        FROM sales s
        WHERE s.created_at >= DATE('now', '-{period} days')
        GROUP BY s.payment_method
    """).fetchall()

    # Ventas por día de la semana
    weekday_sales = conn.execute(f"""
        SELECT 
            CASE CAST(strftime('%w', s.created_at) AS INTEGER)
                WHEN 0 THEN 'Domingo'
                WHEN 1 THEN 'Lunes'
                WHEN 2 THEN 'Martes'
                WHEN 3 THEN 'Miércoles'
                WHEN 4 THEN 'Jueves'
                WHEN 5 THEN 'Viernes'
                WHEN 6 THEN 'Sábado'
            END as weekday,
            SUM(s.total) as total,
            COUNT(*) as sales_count
        FROM sales s
        WHERE s.created_at >= DATE('now', '-{period} days')
        GROUP BY strftime('%w', s.created_at)
        ORDER BY CAST(strftime('%w', s.created_at) AS INTEGER)
    """).fetchall()

    # Estado del inventario
    inventory_status = conn.execute("""
        SELECT name, stock, price, category,
               CASE 
                   WHEN stock < 10 THEN 'Bajo'
                   WHEN stock < 25 THEN 'Medio'
                   ELSE 'Alto'
               END as stock_level
        FROM products
        WHERE category = 'Productos'
        ORDER BY stock ASC
    """).fetchall()

    # Nuevos clientes por mes
    new_customers = conn.execute("""
        SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count
        FROM customers
        WHERE created_at >= DATE('now', '-12 months')
        GROUP BY strftime('%Y-%m', created_at)
        ORDER BY month
    """).fetchall()

    # Análisis de fidelidad de clientes (simulado)
    customer_loyalty = conn.execute("""
        SELECT 
            c.name,
            COUNT(s.id) as total_visits,
            SUM(s.total) as total_spent,
            MAX(s.created_at) as last_visit
        FROM customers c
        LEFT JOIN sales s ON c.id = s.customer_id
        WHERE s.created_at >= DATE('now', '-{period} days')
        GROUP BY c.id, c.name
        HAVING COUNT(s.id) > 0
        ORDER BY total_visits DESC
        LIMIT 20
    """.format(period=period)).fetchall()

    conn.close()

    return jsonify({
        'daily_sales': [{'date': row['date'], 'total': row['total'], 'count': row['count']} for row in daily_sales],
        'top_products': [{'name': row['name'], 'quantity': row['quantity_sold'], 'revenue': row['revenue']} for row in top_products],
        'category_sales': [{'category': row['category'], 'total': row['total'], 'sales_count': row['sales_count']} for row in category_sales],
        'payment_methods': [{'method': row['method'], 'total': row['total'], 'count': row['count']} for row in payment_methods],
        'weekday_sales': [{'weekday': row['weekday'], 'total': row['total'], 'sales_count': row['sales_count']} for row in weekday_sales],
        'inventory_status': [{'name': row['name'], 'stock': row['stock'], 'price': row['price'], 'category': row['category'], 'stock_level': row['stock_level']} for row in inventory_status],
        'new_customers': [{'month': row['month'], 'count': row['count']} for row in new_customers],
        'customer_loyalty': [{'name': row['name'], 'total_visits': row['total_visits'], 'total_spent': row['total_spent'], 'last_visit': row['last_visit']} for row in customer_loyalty]
    })

@app.route('/api/add_promotion', methods=['POST'])
@require_system_login()
def api_add_promotion():
    try:
        data = request.json
        
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO promotions (name, description, discount_percentage, discount_amount, 
                                  min_purchase, max_discount, start_date, end_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['name'],
            data['description'],
            data['discount_value'] if data['discount_type'] == 'percentage' else 0,
            data['discount_value'] if data['discount_type'] == 'fixed' else 0,
            0,  # min_purchase
            0,  # max_discount
            data['start_date'],
            data['end_date'],
            data['active']
        ))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/edit_promotion', methods=['POST'])
@require_system_login()
def api_edit_promotion():
    try:
        data = request.json
        
        conn = get_db_connection()
        conn.execute("""
            UPDATE promotions SET name = ?, description = ?, discount_percentage = ?, 
                   discount_amount = ?, start_date = ?, end_date = ?, is_active = ?
            WHERE id = ?
        """, (
            data['name'],
            data['description'],
            data['discount_value'] if data['discount_type'] == 'percentage' else 0,
            data['discount_value'] if data['discount_type'] == 'fixed' else 0,
            data['start_date'],
            data['end_date'],
            data['active'],
            data['promotion_id']
        ))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/get_promotion/<int:promotion_id>')
@require_system_login()
def api_get_promotion(promotion_id):
    try:
        conn = get_db_connection()
        promotion = conn.execute("SELECT * FROM promotions WHERE id = ?", (promotion_id,)).fetchone()
        conn.close()
        
        if promotion:
            return jsonify({
                'id': promotion['id'],
                'name': promotion['name'],
                'description': promotion['description'],
                'discount_type': 'percentage' if promotion['discount_percentage'] > 0 else 'fixed',
                'discount_value': promotion['discount_percentage'] if promotion['discount_percentage'] > 0 else promotion['discount_amount'],
                'start_date': promotion['start_date'],
                'end_date': promotion['end_date'],
                'active': promotion['is_active']
            })
        else:
            return jsonify({'error': 'Promoción no encontrada'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete_promotion/<int:promotion_id>', methods=['DELETE'])
@require_system_login()
def api_delete_promotion(promotion_id):
    try:
        conn = get_db_connection()
        conn.execute("DELETE FROM promotions WHERE id = ?", (promotion_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/upload_background', methods=['POST'])
@require_system_login()
def upload_background():
    if 'background_file' not in request.files:
        return jsonify({'success': False, 'message': 'No se seleccionó archivo'})
    
    file = request.files['background_file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No se seleccionó archivo'})
    
    if file and file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        filename = 'custom_background.' + file.filename.split('.')[-1]
        file.save(os.path.join('static', filename))
        
        # Guardar en sesión la preferencia
        session['custom_background'] = filename
        
        return jsonify({'success': True, 'filename': filename})
    else:
        return jsonify({'success': False, 'message': 'Solo archivos PNG, JPG y JPEG son permitidos'})

@app.route('/reset_background', methods=['POST'])
@require_system_login()
def reset_background():
    session.pop('custom_background', None)
    return jsonify({'success': True})

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)

    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)