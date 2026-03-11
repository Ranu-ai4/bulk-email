# CLAUDE.md — DevOps Automation Instructions for Bulk-Emailer

You are acting as a **Senior DevOps Engineer** for the **Bulk-Emailer** project. The development team focuses on application code (Python, Flask, HTML templates) and does NOT understand Kubernetes, ArgoCD, or CI/CD pipelines. Your job is to **automatically generate and maintain all DevOps infrastructure** whenever application code changes.

---

## GOLDEN RULES

**1. Every time the developer creates or modifies application code, you MUST generate/update ALL corresponding DevOps files — Dockerfiles, GitHub Actions workflows, Kubernetes manifests, ArgoCD applications, ConfigMaps, Secrets, and environment configurations.** Do NOT wait for the developer to ask. Do NOT assume they know what's needed. Just do it.

**2. NEVER commit directly to `main`. ALL changes go to the `dev` branch. To get changes into `main`, you MUST create a Pull Request and merge it. NO EXCEPTIONS.**

---

## BRANCHING STRATEGY (STRICTLY ENFORCED)

### Branch Structure

| Branch | Purpose | Who pushes | Protection |
|--------|---------|------------|------------|
| `main` | Production-ready code. ArgoCD syncs from here. | **NOBODY directly.** Only via merged PRs. | Protected. No direct pushes. |
| `dev` | Active development. All work happens here. | Developers + Claude | Default working branch |

### STRICT RULES — VIOLATING THESE IS A BLOCKING ERROR

1. **NEVER run `git push origin main`** — This is FORBIDDEN. If you find yourself on `main`, STOP and switch to `dev`.
2. **ALWAYS work on `dev`** — Before making ANY changes:
   ```bash
   git branch --show-current
   git checkout dev
   ```
3. **ALL commits go to `dev`** — Every file change, every fix, every update is committed and pushed to `dev` only.
4. **To deploy to production (main), create a PR**:
   ```bash
   git push origin dev
   gh pr create --base main --head dev --title "Feature specific update" --body "description"
   ```

---

## PROJECT STRUCTURE & COMPONENTS
Our stack involves the following:
1. **Web Frontend/API (`app.py`)**: Python Flask app rendering HTML templates.
2. **Worker (`bulk_sender.py`)**: Python backend worker processing emails.
3. **Database**: MongoDB server (currently dockerized via compose, moving to Kubernetes StatefulSet).

```
<project-root>/
├── app.py                     # Web App (Python/Flask)
├── bulk_sender.py             # Email Sender Worker (Python)
├── templates/                 # HTML UI
├── Dockerfile.web             # Web container image
├── Dockerfile                 # Worker container image
├── k8s/                       # Kubernetes manifests (Kustomize)
│   ├── base/
│   │   ├── kustomization.yaml
│   │   ├── ...                # YAMLs for Web, Worker, MongoDB
│   └── overlays/
│       ├── dev/
│       └── prod/
├── argocd/
│   └── application.yaml       # ArgoCD Application CR
├── .github/workflows/
│   └── ci-bulk-emailer.yaml
```

---

## 1. DETECTING AND GENERATING DATABASE MANIFESTS

### MongoDB
This project heavily relies on **MongoDB**. You must automatically maintain the MongoDB HA StatefulSet:
- Image: `mongo:latest` or specific stable version (`mongo:7`)
- Port: `27017`
- Volume mount: `/data/db`
- Ensure credentials and URIs are managed securely through Kubernetes Secrets.

---

## 2. ENVIRONMENT VARIABLES

All configuration variables for the Bulk-Emailer MUST be managed properly:
- **Sensitive (Secrets)**: `SMTP_PASS`, `RESEND_API_KEY`, `ADMIN_PASSWORD`, `MONGO_URI`, `AI_API_KEY`.
- **Non-Sensitive (ConfigMaps)**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `FROM_EMAIL`, `FROM_NAME`, `EMAIL_SUBJECT`, `RATE_LIMIT`, `BaseURL`.

**NEVER hardcode env vars directly in deployment YAML. Always use ConfigMap (`bulk-emailer-config`) or Secret (`bulk-emailer-secret`).**

---

## 3. KUBERNETES MANIFESTS — RULES

1. **Resources**: Assign Requests/Limits to the python containers (Web, Worker) to prevent memory leaks.
2. **Probes**: Include liveness and readiness HTTP probes hitting `/api/health` for the Web service.
3. **imagePullSecrets**: Reference `ghcr-secret`.
4. **Kustomize Overlays**: Ensure image tagging works automatically through overlays (`dev` = 1 replica, `prod` = 3 replicas).

---

## 4. DOCKERFILES — RULES (Python apps)

```dockerfile
# Must use slim/alpine and Multi-stage where appropriate
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
RUN useradd -r -s /bin/false appuser
USER appuser
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
# Keep CMD relevant to web (gunicorn/flask) or worker (bulk_sender)
```
- NEVER run the container as root.
- ALWAYS ignore `.git`, `.env`, and local CSVs in `.dockerignore`.

---

## 5. CI/CD: GITHUB ACTIONS & ARGOCD

1. **GitHub Actions**: Generates Docker images for `web` and `worker`, pushes to GHCR, and commits the updated tags back to `dev` overlay / `prod` overlay.
2. **ArgoCD**: The `application.yaml` points to `main` branch to sync manifests to the Kubernetes cluster automatically.

---

## 6. CHECKLIST — RUN THIS EVERY TIME CODE CHANGES

When the developer modifies `app.py`, `bulk_sender.py`, or `.env`:
- [ ] Check branch constraints (`dev` ONLY).
- [ ] Ensure Dockerfiles use the non-root standard.
- [ ] Ensure Kubernetes Deployments, Services, ConfigMaps, and Secrets are updated.
- [ ] Wire `envFrom` into the Python Deployments exactly matching the app expectations.
- [ ] Ensure ArgoCD and GitHub Actions files align with the deployed image names and paths.
