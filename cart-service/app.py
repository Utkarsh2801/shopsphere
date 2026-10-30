import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import psycopg
from psycopg.rows import dict_row

DB = dict(host=os.getenv('DB_HOST','postgres'), dbname=os.getenv('DB_NAME','shopsphere'), user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'], connect_timeout=3)

def connection(): return psycopg.connect(**DB)
def customer_id(path):
    m = re.fullmatch(r'/carts/([A-Za-z0-9_-]{1,50})', path)
    return m.group(1) if m else None
class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body=json.dumps(data).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def body(self):
        n=int(self.headers.get('Content-Length','0'))
        if n<1 or n>8192: raise ValueError('invalid body size')
        return json.loads(self.rfile.read(n))
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/health': return self.reply(200,{'status':'ok'})
        try:
            if path=='/ready':
                with connection() as c: c.execute('SELECT 1')
                return self.reply(200,{'status':'ready'})
            cid=customer_id(path)
            if not cid: return self.reply(404,{'error':'not found'})
            with connection() as c:
                with c.cursor(row_factory=dict_row) as cur:
                    cur.execute('SELECT product_id, quantity FROM cart_items WHERE customer_id=%s ORDER BY product_id',(cid,))
                    items=cur.fetchall()
            return self.reply(200,{'customer_id':cid,'items':items})
        except psycopg.Error as e:
            print('database error:',type(e).__name__,flush=True)
            return self.reply(503,{'error':'database unavailable'})
    def do_POST(self):
        m=re.fullmatch(r'/carts/([A-Za-z0-9_-]{1,50})/items',urlparse(self.path).path)
        if not m: return self.reply(404,{'error':'not found'})
        try:
            payload=self.body(); pid=payload['product_id']; qty=payload['quantity']
            if type(pid) is not int or pid<1 or type(qty) is not int or qty<1 or qty>100:
                raise ValueError('invalid product_id or quantity')
        except (ValueError, TypeError, KeyError, json.JSONDecodeError): return self.reply(400,{'error':'product_id and quantity must be positive integers (quantity <=100)'})
        try:
            with connection() as c:
                with c.cursor() as cur:
                    cur.execute('''INSERT INTO cart_items(customer_id,product_id,quantity) VALUES(%s,%s,%s)
                        ON CONFLICT(customer_id,product_id) DO UPDATE SET quantity=cart_items.quantity+EXCLUDED.quantity''',(m.group(1),pid,qty))
            return self.reply(201,{'status':'added','customer_id':m.group(1),'product_id':pid})
        except psycopg.Error:
            return self.reply(503,{'error':'database unavailable'})
    def do_DELETE(self):
        cid=customer_id(urlparse(self.path).path)
        if not cid: return self.reply(404,{'error':'not found'})
        try:
            with connection() as c:
                with c.cursor() as cur:
                    cur.execute('DELETE FROM cart_items WHERE customer_id=%s',(cid,))
            return self.reply(200,{'status':'cleared','customer_id':cid})
        except psycopg.Error: return self.reply(503,{'error':'database unavailable'})

print('Cart API listening on 8001',flush=True)
ThreadingHTTPServer(('0.0.0.0',8001),Handler).serve_forever()
