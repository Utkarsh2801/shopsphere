
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import time

from prometheus_client import (
    Counter,
    Histogram,
    start_http_server,
)

import psycopg
from psycopg.rows import dict_row

HTTP_REQUESTS = Counter(
    "shopsphere_http_requests_total",
    "Total HTTP responses",
    ["method", "route", "status"],
)

HTTP_LATENCY = Histogram(
    "shopsphere_http_request_duration_seconds",
    "Time spent handling HTTP requests",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05,
             0.1, 0.25, 0.5, 1, 2, 5),
)

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


def observe_request(handler_func):
    def wrapped(self):
        started = time.monotonic()
        try:
            return handler_func(self)
        finally:
            route = (
                self.path.split("?")[0]
                if self.path.split("?")[0]
                in ("/api/products", "/health", "/ready")
                else "other"
            )
            HTTP_LATENCY.labels(
                self.command, route
            ).observe(time.monotonic() - started)

    return wrapped

class ProductHandler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        route = self.path.split("?")[0]
        if route not in ("/api/products", "/health", "/ready"):
            route = "other"

        HTTP_REQUESTS.labels(
            method=self.command,
            route=route,
            status=str(status),
        ).inc()

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

        if self.path == "/api/products":
            try:
                with get_connection() as conn:
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            "SELECT id, name, price "
                            "FROM products ORDER BY id"
                        )
                        products = cur.fetchall()

                return self.send_json(200, [])
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

ProductHandler.do_GET = observe_request(
    ProductHandler.do_GET
)
ProductHandler.do_POST = observe_request(
    ProductHandler.do_POST
)

start_http_server(9090)

HTTPServer(("0.0.0.0", 8000), ProductHandler).serve_forever()
