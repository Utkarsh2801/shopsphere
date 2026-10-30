import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import psycopg
from psycopg.rows import dict_row

DB=dict(host=os.getenv('DB_HOST','postgres'),dbname=os.getenv('DB_NAME','shopsphere'),user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],connect_timeout=3)
CART_URL=os.getenv('CART_URL','http://cart-service:8001').rstrip('/')
PRODUCT_URL=os.getenv('PRODUCT_URL','http://product-service:8000').rstrip('/')
TIMEOUT=float(os.getenv('HTTP_TIMEOUT_SECONDS','3'))
def connection(): return psycopg.connect(**DB)
def fetch(url):
    with urlopen(url,timeout=TIMEOUT) as r: return json.load(r)
def clear_cart(cid):
    req=Request(f'{CART_URL}/carts/{cid}',method='DELETE')
    with urlopen(req,timeout=TIMEOUT): pass

def cid_from(path):
    m=re.fullmatch(r'/orders/([A-Za-z0-9_-]{1,50})',path)
    return m.group(1) if m else None
class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        b=json.dumps(data,default=str).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
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
                    orders=cur.fetchall()
            return self.reply(200,{'customer_id':cid,'orders':orders})
        except psycopg.Error: return self.reply(503,{'error':'database unavailable'})
    def do_POST(self):
        cid=cid_from(urlparse(self.path).path)
        if not cid: return self.reply(404,{'error':'not found'})
        try:
            cart=fetch(f'{CART_URL}/carts/{cid}')
            products=fetch(f'{PRODUCT_URL}/products')
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
            print('upstream failure:',type(e).__name__,flush=True)
            return self.reply(503,{'error':'dependent service unavailable; order not created'})
        items=cart.get('items',[])
        if not items: return self.reply(400,{'error':'cart empty'})
        catalog={p['id']:p for p in products}
        lines=[]
        for item in items:
            product=catalog.get(item['product_id'])
            if product is None: return self.reply(409,{'error':f"product {item['product_id']} not found"})
            lines.append((item['product_id'],item['quantity'],product['price']))
        total=sum(qty*price for _,qty,price in lines)
        try:
            # This transaction atomically commits order + order lines in ONE database.
            with connection() as c:
                with c.cursor() as cur:
                    cur.execute('INSERT INTO orders(customer_id,total_price,status) VALUES(%s,%s,%s) RETURNING id',(cid,total,'created'))
                    oid=cur.fetchone()[0]
                    for pid,qty,price in lines:
                        cur.execute('INSERT INTO order_items(order_id,product_id,quantity,unit_price) VALUES(%s,%s,%s,%s)',(oid,pid,qty,price))
        except psycopg.Error as e:
            print('transaction failure:',type(e).__name__,flush=True)
            return self.reply(503,{'error':'database transaction failed'})
        # Separate HTTP call: NOT part of the SQL transaction.
        try:
            clear_cart(cid)
            return self.reply(201,{'order_id':oid,'total_price':total,'status':'created','cart_cleared':True})
        except (HTTPError, URLError, TimeoutError, OSError):
            return self.reply(201,{'order_id':oid,'total_price':total,'status':'created','cart_cleared':False,'warning':'cart cleanup failed; do not retry checkout blindly'})

print('Order API listening on 8002',flush=True)
ThreadingHTTPServer(('0.0.0.0',8002),Handler).serve_forever()
