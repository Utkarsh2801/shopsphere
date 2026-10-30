"""Phase 5 learning service: idempotent order creation, not production checkout."""
import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import psycopg
from psycopg.rows import dict_row

DB=dict(host=os.getenv('DB_HOST','postgres'), dbname=os.getenv('DB_NAME','shopsphere'), user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],connect_timeout=3)
CART_URL=os.getenv('CART_URL','http://cart-service:8001').rstrip('/')
PRODUCT_URL=os.getenv('PRODUCT_URL','http://product-service:8000').rstrip('/')
TIMEOUT=float(os.getenv('HTTP_TIMEOUT_SECONDS','3'))
def connection(): return psycopg.connect(**DB)
def fetch(url):
    with urlopen(url,timeout=TIMEOUT) as r: return json.load(r)
def clear_cart(cid):
    with urlopen(Request(f'{CART_URL}/carts/{cid}',method='DELETE'),timeout=TIMEOUT): pass
def cid_from(path):
    m=re.fullmatch(r'/orders/([A-Za-z0-9_-]{1,50})',path)
    return m.group(1) if m else None
class Handler(BaseHTTPRequestHandler):
    def reply(self,code,data):
        b=json.dumps(data,default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=='/health': return self.reply(200,{'status':'ok'})
        try:
            if p=='/ready':
                with connection() as c: c.execute('SELECT 1')
                return self.reply(200,{'status':'ready'})
            cid=cid_from(p)
            if not cid: return self.reply(404,{'error':'not found'})
            with connection() as c:
                with c.cursor(row_factory=dict_row) as cur:
                    cur.execute('SELECT id,customer_id,total_price,status,created_at FROM orders WHERE customer_id=%s ORDER BY id',(cid,))
                    rows=cur.fetchall()
            return self.reply(200,{'customer_id':cid,'orders':rows})
        except psycopg.Error as e:
            print('database GET error',type(e).__name__,flush=True)
            return self.reply(503,{'error':'database unavailable'})
    def do_POST(self):
        cid=cid_from(urlparse(self.path).path)
        if not cid: return self.reply(404,{'error':'not found'})
        key=self.headers.get('Idempotency-Key','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',key):
            return self.reply(400,{'error':'Idempotency-Key header required (8-100 letters, digits, _ or -)'})
        # Fast replay path: never delete a cart on replay, because it may contain NEW items.
        try:
            with connection() as c:
                with c.cursor(row_factory=dict_row) as cur:
                    cur.execute('SELECT o.id,o.total_price FROM orders o JOIN checkout_keys k ON k.order_id=o.id WHERE k.customer_id=%s AND k.key=%s',(cid,key))
                    previous=cur.fetchone()
            if previous: return self.reply(200,{'order_id':previous['id'],'total_price':previous['total_price'],'replayed':True,'cart_cleanup':'not_retried'})
        except psycopg.Error as e:
            print('replay query error',type(e).__name__,flush=True)
            return self.reply(503,{'error':'database unavailable'})
        try:
            cart=fetch(f'{CART_URL}/carts/{cid}')
            products=fetch(f'{PRODUCT_URL}/products')
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as e:
            print('dependency error',type(e).__name__,flush=True)
            return self.reply(503,{'error':'dependent service unavailable; retry with SAME key'})
        items=cart.get('items',[])
        if not items: return self.reply(400,{'error':'cart empty'})
        catalog={p['id']:p for p in products}
        lines=[]
        for item in items:
            product=catalog.get(item['product_id'])
            if product is None: return self.reply(409,{'error':'unknown product'})
            lines.append((item['product_id'],item['quantity'],product['price']))
        total=sum(qty*price for _,qty,price in lines)
        try:
            # DB unique constraint serializes competing attempts with the same customer/key.
            # The idempotency record and order rows commit atomically.
            with connection() as c:
                with c.cursor() as cur:
                    cur.execute('INSERT INTO checkout_keys(customer_id,key) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING key',(cid,key))
                    inserted=cur.fetchone()
                    if not inserted:
                        cur.execute('SELECT o.id,o.total_price FROM orders o JOIN checkout_keys k ON k.order_id=o.id WHERE k.customer_id=%s AND k.key=%s',(cid,key))
                        previous=cur.fetchone()
                        if not previous:
                            raise RuntimeError('checkout key exists without committed order')
                        return self.reply(200,{'order_id':previous[0],'total_price':previous[1],'replayed':True,'cart_cleanup':'not_retried'})
                    cur.execute('INSERT INTO orders(customer_id,total_price,status) VALUES(%s,%s,%s) RETURNING id',(cid,total,'created'))
                    oid=cur.fetchone()[0]
                    for pid,qty,price in lines:
                        cur.execute('INSERT INTO order_items(order_id,product_id,quantity,unit_price) VALUES(%s,%s,%s,%s)',(oid,pid,qty,price))
                    cur.execute('UPDATE checkout_keys SET order_id=%s WHERE customer_id=%s AND key=%s',(oid,cid,key))
        except (psycopg.Error,RuntimeError) as e:
            print('checkout transaction error',type(e).__name__,flush=True)
            return self.reply(503,{'error':'checkout transaction failed; retry same key'})
        # NOT in the database transaction; could fail independently.
        try:
            clear_cart(cid)
            return self.reply(201,{'order_id':oid,'total_price':total,'replayed':False,'cart_cleared':True})
        except (HTTPError,URLError,TimeoutError,OSError) as e:
            print('cart cleanup failed',type(e).__name__,flush=True)
            return self.reply(201,{'order_id':oid,'total_price':total,'replayed':False,'cart_cleared':False,'warning':'Order is saved. Cart needs manual reconciliation. Do not create a new checkout key to retry.'})

print('Order API v2 listening on 8002',flush=True)
ThreadingHTTPServer(('0.0.0.0',8002),Handler).serve_forever()
