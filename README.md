# ShopSphere

ShopSphere is a small online-store demo and Kubernetes learning project. It
includes a browser-based storefront, separate product, cart, and order APIs, and
a PostgreSQL database.

## Project structure

```text
frontend/                 Storefront and NGINX API routing
product-service/          Product API and container image
cart-service/             Cart API and container image
order-service/            Order and checkout API and container image
k8s/                      Kubernetes manifests for the app, database, and monitoring
helm/shopsphere-api/       Helm chart for the Product API
gitops/                   Argo CD application configuration
.github/workflows/        Product image build and publish workflow
scripts/                  Local Kubernetes access helpers
```

The storefront reads products, manages a demo customer's cart, and places
orders. The services use PostgreSQL for product, cart, and order data.

## Running the demo

The app's Kubernetes resources are in `k8s/`. Once the app is deployed to a
cluster with the required database secret and services, run:

```sh
./scripts/port-forward.sh
```

Then open [http://localhost:8080](http://localhost:8080). The script requires
`kubectl` configured for the cluster. Set `NAMESPACE` or `LOCAL_PORT` to
override its defaults.

## What this project demonstrates

- Splitting an application into small services, each with its own container.
- Using Kubernetes Deployments, Services, health probes, resource limits, and
  persistent storage to run the services and database.
- Making checkout retries safer with idempotency keys and a database transaction.
  Cart cleanup is a separate operation, so a saved order can still need
  reconciliation if that cleanup fails.
- Building and publishing a multi-platform Product API image with GitHub
  Actions, then updating its Helm image tag for Argo CD to deploy.
- Exposing Product API request metrics for Prometheus.

This is a learning/demo project, not a production-ready commerce system.
