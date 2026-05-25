# Hermes WebUI host-mounted deployment runbook

Target: `hermes-webui-nesquena` on `127.0.0.1:8787`, reverse-proxied by the existing `sub2api-nginx` container and protected by Cloudflare Access.

## Architecture

```text
Cloudflare Access
  -> sub2api-nginx
    -> hermes-webui-nesquena:8787
      -> /home/hermeswebui/.hermes  (host /home/ubuntu/.hermes)
      -> CAMOFOX_URL=http://camofox-browser:9377
```

## Safety boundaries

Mounted:

- `/home/ubuntu/.hermes:/home/hermeswebui/.hermes:rw`
- `/home/ubuntu/.local/share/uv:/home/ubuntu/.local/share/uv:ro`
- `/home/ubuntu/.local/bin/hermes:/home/ubuntu/.local/bin/hermes:ro`
- `/opt/hermes-webui-nesquena/workspace:/workspace:rw`

Not mounted:

- `/home/ubuntu`
- `/home/ubuntu/.ssh`
- `/home/ubuntu/.docker`
- `/home/ubuntu/.config/gh`
- `/home/ubuntu/.codex`
- `/var/run/docker.sock`

Runtime hardening:

- `no-new-privileges:true`
- Capabilities are left at Docker defaults for startup because the upstream entrypoint briefly runs as root to align UID/GID and chown bind-mounted state, then drops to UID/GID 1001 before serving. Re-adding `cap_drop: [ALL]` currently breaks startup with `Operation not permitted` during that init phase.
- `HERMES_WEBUI_SKIP_AGENT_DEPS_INSTALL=1` is set because this deployment uses the mounted host Hermes venv directly. Without the skip, upstream startup stages the full host `hermes-agent` tree, including the large mounted venv, into `/tmp` and can fail with `No space left on device`.

## Build

```bash
docker compose -f docker-compose.b1-host-camofox.yml build --pull hermes-webui-nesquena
```

## Scan

```bash
trivy image --severity CRITICAL,HIGH,MEDIUM --ignore-unfixed=false hermes-webui-nesquena:b1-host-camofox
```

## Start / recreate

```bash
docker compose -f docker-compose.b1-host-camofox.yml up -d --no-deps --force-recreate hermes-webui-nesquena
```

## Verification

```bash
curl -fsS http://127.0.0.1:8787/health

docker exec hermes-webui-nesquena sh -lc '
  id
  /home/hermeswebui/.hermes/hermes-agent/venv/bin/python -V
  test -f /home/hermeswebui/.hermes/hermes-agent/run_agent.py
  python - <<"PY"
import os
print("CAMOFOX_URL=", os.getenv("CAMOFOX_URL"))
from tools.browser_camofox import check_camofox_available
print("camofox_available=", check_camofox_available())
PY
  for p in /home/ubuntu/.ssh /home/ubuntu/.docker /home/ubuntu/.config/gh /home/ubuntu/.codex /var/run/docker.sock; do
    [ -e "$p" ] && echo "VISIBLE $p" || echo "OK hidden $p"
  done
'
```

## Reverse proxy cutover

1. Back up current Nginx config from `sub2api-nginx`.
2. Replace stale upstream `hermes-webui-b1-trixie:6060` with `hermes-webui-nesquena:8787` for `hermes.hxwhub.eu.org`.
3. Run:

```bash
docker exec sub2api-nginx nginx -t
docker exec sub2api-nginx nginx -s reload
curl -kI https://hermes.hxwhub.eu.org/
```

Cloudflare Access protected unauthenticated `HTTP/2 302` to a `cloudflareaccess.com` URL is a healthy outer-edge signal.

## Rollback

If the new container fails before Nginx cutover:

```bash
docker compose -f docker-compose.b1-host-camofox.yml logs --tail=200 hermes-webui-nesquena
docker compose -f docker-compose.b1-host-camofox.yml rm -sf hermes-webui-nesquena
```

If Nginx was cut over, restore the timestamped Nginx backup first, then `nginx -t` and reload.
