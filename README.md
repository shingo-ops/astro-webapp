# Jarvis CRM

Multi-tenant B2B SaaS CRM Platform

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite
- **Backend**: FastAPI + Python 3.12
- **Database**: PostgreSQL 16
- **Infrastructure**: Docker Compose + Nginx + SSL (Let's Encrypt)
- **Deployment**: GitHub Actions (Auto Deploy)

## Architecture

- Dockerized microservices
- HTTPS-only with automatic certificate renewal
- Automatic deployment on push to main branch

## Environment

- **Production**: https://jarvis-claude.uk
- **Branch Strategy**:
  - `main`: Production (auto-deploy)
  - `develop`: Development

## Deployment

Push to `main` branch triggers automatic deployment via GitHub Actions.

---

© 2026 Jarvis CRM - Powered by Claude Code
