from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from datetime import datetime, timedelta
from flask import jsonify
import logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Tiger',  
    'database': 'project'
}

def get_db_connection():
    try:
        conn = mysql.connector.connect(**db_config)
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to database: {err}")
        return None

# route for index.html

@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    conn = get_db_connection()
    medicines = []
    
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            if search_query:
                query = """
                SELECT * FROM medicine 
                WHERE name LIKE %s 
                OR purpose LIKE %s
                ORDER BY name
                """
                search_param = f"%{search_query}%"
                cursor.execute(query, (search_param, search_param))
            else:
                cursor.execute("SELECT * FROM medicine ORDER BY name")
                
            medicines = cursor.fetchall()
            
            for medicine in medicines:
                if medicine['expiry']:
                    medicine['expiry'] = medicine['expiry'].strftime('%Y-%m-%d')
            
        except mysql.connector.Error as err:
            print(f"Error fetching medicines: {err}")
            flash('Error fetching medicine data', 'error')
        finally:
            conn.close()
    
    user = None
    if 'user_id' in session:
        user_id = session['user_id']
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT first_name, last_name, user_category FROM users WHERE user_id = %s", (user_id,))
                user = cursor.fetchone()
            except mysql.connector.Error as err:
                print(f"Error fetching user data: {err}")
            finally:
                conn.close()
    
    return render_template('index.html', medicines=medicines, user=user, search_query=search_query)

# route for login.html

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute("SELECT * FROM users WHERE email = %s AND password = %s", (email, password))
                user = cursor.fetchone()
                
                if user:
                    session['user_id'] = user['user_id']
                    
                    cursor.execute("SELECT * FROM admins WHERE user_id = %s", (user['user_id'],))
                    admin = cursor.fetchone()
                    
                    if admin:
                        session['is_admin'] = True
                        session['admin_level'] = admin['admin_level']
                    
                    flash('Login successful!', 'success')
                    return redirect(url_for('index'))
                else:
                    flash('Invalid email or password', 'error')
            except mysql.connector.Error as err:
                flash('Database error occurred', 'error')
            finally:
                conn.close()
        
    return render_template('login.html')

# route for signup.html

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        user_id = request.form.get('userId')
        email = request.form.get('email')
        first_name = request.form.get('firstName')
        last_name = request.form.get('lastName')
        password = request.form.get('password')
        confirm_password = request.form.get('confirmPassword')
        address = request.form.get('address')
        user_category = request.form.get('userCategory')
        terms = 'terms' in request.form
        
        errors = []
        
        if not all([user_id, email, first_name, last_name, password, confirm_password, address, user_category]):
            errors.append("Please fill in all required fields")
        
        if password != confirm_password:
            errors.append("Passwords do not match")
        
        if not terms:
            errors.append("You must agree to the terms")
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('signup'))
        
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (user_id, email, first_name, last_name, password, address, user_category) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, email, first_name, last_name, password, address, user_category)
                )
                conn.commit()
                flash('Account created successfully! Please login.', 'success')
                return redirect(url_for('login'))
            except mysql.connector.IntegrityError as e:
                if "Duplicate entry" in str(e):      #   format of str(e) : Duplicate entry 'example@email.com' for key 'users.email'
                    if "email" in str(e):
                        flash('Email already exists', 'error')
                    else:
                        flash('User ID already exists', 'error')
                else:
                    flash('Error creating account', 'error')
                return redirect(url_for('signup'))
            except mysql.connector.Error as err:
                flash('Database error occurred', 'error')
                print(f"Database error: {err}")
                return redirect(url_for('signup'))
            finally:
                conn.close()
    
    return render_template('signup.html')


@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login to add items to cart'})
    
    medicine_id = request.form.get('medicine_id')
    quantity = request.form.get('quantity', '1') 
    
    try:
        quantity = max(1, int(quantity))  
    except (ValueError, TypeError):
        quantity = 1
    
    if not medicine_id:
        return jsonify({'success': False, 'message': 'Invalid medicine'})
    
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': 'Database connection failed'})
        
        cursor = conn.cursor(dictionary=True)
        
        # Get cart of the user if already created
        cursor.execute("SELECT cart_id FROM carts WHERE user_id = %s FOR UPDATE", (session['user_id'],))
        cart = cursor.fetchone()


        # create a new cart for the user if aready not there in the carts table
        if not cart:
            cursor.execute("INSERT INTO carts (user_id) VALUES (%s)", (session['user_id'],))
            cart_id = cursor.lastrowid
            conn.commit()
        else:
            cart_id = cart['cart_id']
        
        # Check existing item
        cursor.execute(
            """SELECT cart_item_id, quantity FROM cart_items 
            WHERE cart_id = %s AND medicine_id = %s FOR UPDATE""",
            (cart_id, medicine_id)
        )
        existing_item = cursor.fetchone()
        
        if existing_item:
            new_quantity = existing_item['quantity'] + quantity
            cursor.execute(
                "UPDATE cart_items SET quantity = %s WHERE cart_item_id = %s",
                (new_quantity, existing_item['cart_item_id'])
            )
        else:
            cursor.execute(
                "INSERT INTO cart_items (cart_id, medicine_id, quantity) VALUES (%s, %s, %s)",
                (cart_id, medicine_id, quantity)
            )
        
        conn.commit()
        return jsonify({
            'success': True, 
            'message': 'Item added to cart',
            'quantity': quantity 
        })
        
    except mysql.connector.Error as err:
        conn.rollback() if conn else None
        print(f"Database error in add_to_cart: {err}")
        return jsonify({'success': False, 'message': 'Database error'})
    finally:
        if conn:
            conn.close()


@app.route('/admin/expiring_medicines')
def get_expiring_medicines():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT name, stock, expiry FROM medicine 
        WHERE expiry BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 3 MONTH)
    """)
    medicines = cursor.fetchall()
    conn.close()
    return jsonify({'medicines': medicines})

@app.route('/admin/low_stock_medicines')
def get_low_stock_medicines():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT name, stock, expiry FROM medicine
        WHERE stock < 10
        ORDER BY stock ASC
    """)
    medicines = cursor.fetchall()
    conn.close()
    return jsonify({'medicines': medicines})


@app.route('/cart')
def view_cart():
    if 'user_id' not in session:
        flash('Please login to view your cart', 'error')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cart_items = []
    total = 0
    
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Get the user's cart
            cursor.execute("SELECT cart_id FROM carts WHERE user_id = %s", (session['user_id'],))
            cart = cursor.fetchone()
            
            if cart:
                # Get cart items with medicine details
                cursor.execute("""
                    SELECT ci.*, m.name, m.price, m.purpose 
                    FROM cart_items ci
                    JOIN medicine m ON ci.medicine_id = m.medicine_id
                    WHERE ci.cart_id = %s
                """, (cart['cart_id'],))
                cart_items = cursor.fetchall()
                
                # Calculate total amount 
                total = sum(item['price'] * item['quantity'] for item in cart_items)
            
        except mysql.connector.Error as err:
            print(f"Error fetching cart: {err}")
            flash('Error loading your cart', 'error')
        finally:
            conn.close()
    
    return render_template('cart.html', cart_items=cart_items, total=total)

# route to delete a medicine from the cart of a user

@app.route('/remove_from_cart/<int:item_id>')
def remove_from_cart(item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            
            # Verify item belongs to user's cart
            cursor.execute("""
                DELETE ci FROM cart_items ci
                JOIN carts c ON ci.cart_id = c.cart_id
                WHERE ci.cart_item_id = %s AND c.user_id = %s
            """, (item_id, session['user_id']))
            
            conn.commit()
            flash('Item removed from cart', 'success')
        except mysql.connector.Error as err:
            print(f"Error removing from cart: {err}")
            flash('Error removing item from cart', 'error')
        finally:
            conn.close()
    
    return redirect(url_for('view_cart'))

# route for the admin dashboard

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    stats = {
        'medicine_count': 0,
        'expiring_count': 0,
        'low_stock_count': 0
    }
    
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            
            # Get total medicines count
            cursor.execute("SELECT COUNT(*) as count FROM medicine")
            stats['medicine_count'] = cursor.fetchone()['count']
            
            # Get expiring soon count (within 3 months)
            cursor.execute("""
                SELECT COUNT(*) as count FROM medicine 
                WHERE expiry BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 3 MONTH)
            """)
            stats['expiring_count'] = cursor.fetchone()['count']
            
            # Get low stock count (less than 10)
            cursor.execute("SELECT COUNT(*) as count FROM medicine WHERE stock < 10")
            stats['low_stock_count'] = cursor.fetchone()['count']
            
        except mysql.connector.Error as err:
            print(f"Error fetching stats: {err}")
            flash('Error loading dashboard statistics', 'error')
        finally:
            conn.close()
    
    return render_template('admin_dashboard.html', **stats)


# route for adding new medicines by admin

@app.route('/admin/medicines', methods=['GET', 'POST'])
def manage_medicines():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('name')
        purpose = request.form.get('purpose')
        expiry = request.form.get('expiry')
        price = request.form.get('price')
        stock = request.form.get('stock')

        if not all([name, purpose, expiry, price,stock]):
            flash('Please fill in all fields', 'error')
            return redirect(url_for('manage_medicines'))

        try:
            expiry_date = datetime.strptime(expiry, '%Y-%m-%d').date()
            price_float = float(price)

            conn = get_db_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)

                # Manually get the next medicine_id
                cursor.execute("SELECT MAX(medicine_id) AS max_id FROM medicine")
                result = cursor.fetchone()
                next_id = (result['max_id'] or 0) + 1

                insert_query = """
                    INSERT INTO medicine (medicine_id, name, purpose, expiry, price, stock) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_query, (next_id, name, purpose, expiry_date, price_float, stock))
                conn.commit()

                flash('Medicine added successfully!', 'success')
            else:
                flash('Database connection failed', 'error')

        except ValueError as e:
            flash(f'Invalid data format: {str(e)}', 'error')
        except mysql.connector.Error as err:
            flash(f'Database error occurred: {err}', 'error')
        finally:
            if conn and conn.is_connected():
                conn.close()

        return redirect(url_for('manage_medicines'))

    # GET request - show medicine management page
    medicines = []
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM medicine ORDER BY name")
            medicines = cursor.fetchall()

            for medicine in medicines:
                if medicine['expiry']:
                    medicine['expiry'] = medicine['expiry'].strftime('%Y-%m-%d')
        except mysql.connector.Error as err:
            flash('Error fetching medicine data', 'error')
        finally:
            if conn and conn.is_connected():
                conn.close()

    return render_template('manage_medicines.html', medicines=medicines)


# route for deleting medicine by admin

@app.route('/admin/delete_medicine/<int:medicine_id>', methods=['POST'])
def delete_medicine(medicine_id):
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'})
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # First delete from cart_items to maintain referential integrity
            cursor.execute("DELETE FROM cart_items WHERE medicine_id = %s", (medicine_id,))
            # Then delete from medicines
            cursor.execute("DELETE FROM medicine WHERE medicine_id = %s", (medicine_id,))
            conn.commit()
            return jsonify({'success': True, 'message': 'Medicine deleted'})
        except mysql.connector.Error as err:
            print(f"Error deleting medicine: {err}")
            return jsonify({'success': False, 'message': 'Database error'})
        finally:
            conn.close()
    
    return jsonify({'success': False, 'message': 'Database connection failed'})


@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login to place an order'})

    data = request.get_json()
    if not data or 'updates' not in data:
        return jsonify({'success': False, 'message': 'Invalid request'})

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'})

    try:
        cursor = conn.cursor(dictionary=True)
        
        # First update quantities (same as update_cart_quantities)
        cursor.execute("""
            SELECT c.user_id, ci.cart_item_id, ci.medicine_id, m.price, m.name
            FROM cart_items ci
            JOIN carts c ON ci.cart_id = c.cart_id
            JOIN medicine m ON ci.medicine_id = m.medicine_id
            WHERE c.user_id = %s
        """, (session['user_id'],))
        valid_items = {str(item['cart_item_id']): item for item in cursor.fetchall()}

        order_items = []
        total = 0

        for update in data['updates']:
            item_id = str(update['cart_item_id'])
            if item_id in valid_items:
                med_id = valid_items[item_id]['medicine_id']
                quantity_requested = update['quantity']

                # Check current stock
                cursor.execute("SELECT stock FROM medicine WHERE medicine_id = %s", (med_id,))
                stock_result = cursor.fetchone()

                if not stock_result or stock_result['stock'] < quantity_requested:
                    conn.rollback()
                    return jsonify({
                        'success': False,
                        'message': f"Out of stock: {valid_items[item_id]['name']}"
                    })

                # Update quantity in cart (optional)
                cursor.execute("""
                    UPDATE cart_items 
                    SET quantity = %s 
                    WHERE cart_item_id = %s
                """, (quantity_requested, update['cart_item_id']))

                # Prepare order items
                order_items.append({
                    'medicine_id': med_id,
                    'quantity': quantity_requested,
                    'price': valid_items[item_id]['price'],
                    'name': valid_items[item_id]['name']
                })

                total += valid_items[item_id]['price'] * quantity_requested



        # Create order
        cursor.execute(""" 
            INSERT INTO orders (user_id, total_amount, status, order_date) 
            VALUES (%s, %s, 'pending', NOW())
        """, (session['user_id'], total))
        order_id = cursor.lastrowid

        # Add order items
        for item in order_items:
            cursor.execute(""" 
                INSERT INTO order_items (order_id, medicine_id, quantity, price) 
                VALUES (%s, %s, %s, %s)
            """, (order_id, item['medicine_id'], item['quantity'], item['price']))

        # Clear the cart
        cursor.execute("""
            DELETE ci FROM cart_items ci
            JOIN carts c ON ci.cart_id = c.cart_id
            WHERE c.user_id = %s
        """, (session['user_id'],))

        for item in order_items:
            cursor.execute("""
                UPDATE medicine
                SET stock = stock - %s
                WHERE medicine_id = %s
            """, (item['quantity'], item['medicine_id']))

        conn.commit()
        return jsonify({
            'success': True,
            'message': 'Order placed successfully! Admin will verify your order soon.',
            'order_id': order_id
        })

    except mysql.connector.Error as err:
        conn.rollback()
        print(f"Error placing order: {err}")
        return jsonify({'success': False, 'message': 'Error placing order'})
    finally:
        if conn and conn.is_connected():
            conn.close()



@app.route('/admin/orders')
def manage_orders():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    orders = []
    
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)

            # Get all orders with user info
            cursor.execute("""
                SELECT o.*, u.first_name, u.last_name, u.email 
                FROM orders o
                JOIN users u ON o.user_id = u.user_id
                ORDER BY o.order_date DESC
            """)
            orders = cursor.fetchall()

            # For each order, get the items and medicine info
            for order in orders:
                cursor.execute("""
                    SELECT oi.quantity, oi.price, m.name 
                    FROM order_items oi
                    JOIN medicine m ON oi.medicine_id = m.medicine_id
                    WHERE oi.order_id = %s
                """, (order['order_id'],))
                order_items = cursor.fetchall()
                order['order_items'] = order_items

                # Format date nicely
                if order['order_date']:
                    order['order_date'] = order['order_date'].strftime('%Y-%m-%d %H:%M')
                    
        except mysql.connector.Error as err:
            print(f"Error: {err}")
            flash('Could not load orders.', 'error')
        finally:
            conn.close()

    return render_template('manage_orders.html', orders=orders)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    user = None
    orders = []

    if conn:
        try:
            cursor = conn.cursor(dictionary=True)

            # Get user info
            cursor.execute("SELECT first_name, last_name, email, address FROM users WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()

            # Get orders
            cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY order_date DESC", (user_id,))
            orders = cursor.fetchall()

            # Add items to each order and use a new key name 'order_items'
            for order in orders:
                cursor.execute("""
                    SELECT oi.quantity, oi.price, m.name
                    FROM order_items oi
                    JOIN medicine m ON oi.medicine_id = m.medicine_id
                    WHERE oi.order_id = %s
                """, (order['order_id'],))
                order['order_items'] = cursor.fetchall()

                if order['order_date']:
                    order['order_date'] = order['order_date'].strftime('%Y-%m-%d %H:%M')

        finally:
            conn.close()

    return render_template('profile.html', user=user, orders=orders)


@app.route('/admin/update_order_status', methods=['POST'])  
def update_order_status():
    print("Endpoint hit!")  
    if 'user_id' not in session or not session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    
    try:
        order_id = request.form['order_id']  
        new_status = request.form['status']
    except KeyError as e:
        return jsonify({'success': False, 'message': f'Missing field: {str(e)}'}), 400
    
    print(f"Processing order {order_id}, new status: {new_status}")  
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()
        
        # First verify order exists
        cursor.execute("SELECT 1 FROM orders WHERE order_id = %s FOR UPDATE", (order_id,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'Order not found'}), 404
        
        if new_status.lower() == 'rejected':
            cursor.execute("""
                SELECT medicine_id, quantity 
                FROM order_items 
                WHERE order_id = %s
            """, (order_id,))
            items = cursor.fetchall()
            print(f"Items to restock: {items}")  # Debugging

            for item in items:
                cursor.execute("""
                    UPDATE medicine
                    SET stock = stock + %s 
                    WHERE medicine_id = %s
                """, (item['quantity'], item['medicine_id']))
                print(f"Restocked {item['quantity']} of medicine {item['medicine_id']}")

        cursor.execute("UPDATE orders SET status = %s WHERE order_id = %s", 
                      (new_status, order_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Order status updated'})
    
    except mysql.connector.Error as err:
        conn.rollback()
        print(f"Database error: {err}")
        return jsonify({
            'success': False, 
            'message': f'Database error: {err.msg}'
        }), 500
    
    except Exception as e:
        conn.rollback()
        print(f"Unexpected error: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'An unexpected error occurred'
        }), 500
    
    finally:
        if conn:
            conn.close()


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)