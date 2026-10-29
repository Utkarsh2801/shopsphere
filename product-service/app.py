from flask import Flask, jsonify

app = Flask(__name__)

PRODUCTS = [
    {"id": 1, "name": "Everyday Backpack", "category": "Accessories", "price": 48.00},
    {"id": 2, "name": "Ceramic Pour-Over Set", "category": "Home", "price": 36.50},
    {"id": 3, "name": "Wireless Headphones", "category": "Electronics", "price": 89.00},
    {"id": 4, "name": "Linen Market Tote", "category": "Accessories", "price": 24.00},
]


@app.get("/api/products")
def get_products():
    return jsonify(PRODUCTS)


@app.get("/health")
def health_check():
    return jsonify({"status": "healthy"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)