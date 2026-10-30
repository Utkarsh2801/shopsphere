
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg
from psycopg.rows import dict_row

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "postgres"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "shopsphere"),
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "connect_timeout": 3,
}


def get_connection():
    return psycopg.connect(**DB_CONFIG)


class ProductHandler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"status": "ok"})

        if self.path == "/ready":
            try:
                with get_connection() as conn:
                    conn.execute("SELECT 1")
                return self.send_json(200, {"status": "ready"})
            except psycopg.Error:
                return self.send_json(
                    503, {"status": "database unavailable"}
                )

        if self.path == "/aZZpi/products":
            try:
                with get_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            "SELECT id, name, price "
                            "FROM products ORDER BY id"
                        )
                        products = cur.fetchall()

                return self.send_json(200, products)
            except psycopg.Error as error:
                print(f"Database error: {error}", flush=True)
                return self.send_json(
                    503, {"error": "Database unavailable"}
                )

        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/api/products":
            return self.send_json(404, {"error": "Not found"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                return self.send_json(
                    400, {"error": "Invalid request size"}
                )

            payload = json.loads(
                self.rfile.read(length).decode("utf-8")
            )
            name = payload["name"]
            price = payload["price"]

            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > 200
                or type(price) is not int
                or price < 0
            ):
                return self.send_json(
                    400, {"error": "Invalid product data"}
                )

        except (ValueError, KeyError, TypeError, UnicodeError):
            return self.send_json(
                400, {"error": "Invalid JSON payload"}
            )

        try:
            with get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        INSERT INTO products (name, price)
                        VALUES (%s, %s)
                        RETURNING id, name, price
                        """,
                        (name.strip(), price),
                    )
                    product = cur.fetchone()

            return self.send_json(201, product)

        except psycopg.Error as error:
            print(f"Database error: {error}", flush=True)
            return self.send_json(
                503, {"error": "Database unavailable"}
            )


print("Starting ShopSphere Product API...", flush=True)

HTTPServer(("0.0.0.0", 8000), ProductHandler).serve_forever()
