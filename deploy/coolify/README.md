# Deploy SpareDrive with Coolify

Coolify manages Docker deployments on an existing host. A fork of Coolify contains the platform code. The SpareDrive repository contains the application and the deployment configuration. This setup uses the existing Windows computer and requires no purchased domain or rented server. The computer, Docker Desktop, and the Windows SpareDrive launcher must remain running while the gateway is in use.

## Windows and removable drives

The gateway runs in Docker Desktop and proxies requests to the Windows SpareDrive launcher through `host.docker.internal`. Windows owns the data drive, so the app keeps its Storage explorer, drive selection, and disconnect handling. The gateway needs no filesystem mount and uses the same accounts and storage as the native launcher.

1. Connect the drive. Start SpareDrive from the project folder with `npm run dev` if it isn't already running. Verify the selected drive at `http://127.0.0.1:8765/`.
2. Build and publish the gateway to this computer's existing local registry. Run these from the project folder:

   ```powershell
   docker build -t localhost:5000/sparedrive-windows-gateway:coolify-1 deploy/coolify/windows-gateway
   docker push localhost:5000/sparedrive-windows-gateway:coolify-1
   ```

3. Sign in to Coolify at `http://localhost:8000/`. In a SpareDrive project, add a **Docker Compose Empty** resource on the same Docker engine as the Windows launcher. Paste [compose.coolify.windows.yaml](../../compose.coolify.windows.yaml). The Windows Docker Desktop setup in this workspace uses the `coolify-testing-host` SSH bridge. If Coolify reports it unreachable, check the bridge before deploying.
4. Leave the Coolify domain field empty. Review the **Deployable Compose** view and confirm the published address is `127.0.0.1:18765`. If the Docker CLI is already running the gateway on that port, stop the CLI project before deploying via Coolify:

   ```powershell
   docker compose -p sparedrive-windows -f compose.coolify.windows.yaml down
   ```

5. Deploy and wait for the resource to become healthy. Open `http://127.0.0.1:18765/` and sign in with the same SpareDrive account.

To run the gateway directly in Docker Desktop while the dashboard is unavailable:

```powershell
docker compose -p sparedrive-windows -f compose.coolify.windows.yaml up -d --wait
```

## Family access from other devices

The gateway port is local to the host computer. To give approved devices private HTTPS access without buying a domain, run Tailscale Serve on the Windows host and admit those devices through the tailnet's access policy. The family still needs SpareDrive accounts. For Windows, run the Serve command from an Administrator console.

```powershell
tailscale serve --bg http://127.0.0.1:18765
```

Set the exact HTTPS address it prints as `httpsUrl` in the Windows SpareDrive host settings. Set `SPAREDRIVE_HTTPS_HOST` in the Coolify resource to the hostname portion, without a scheme or path. Restart the launcher and redeploy the gateway. Check access from an approved device using a non-admin SpareDrive account. [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) describes private device access and HTTPS setup.

## Route a hostname through Coolify

To use Coolify's proxy for HTTPS, first choose a hostname you control and configure DNS so the intended devices can reach the Coolify host.

1. In Coolify, edit the service's Compose file and remove the `traefik.enable: "false"` override. Remove the empty `labels:` block if it has no other entries.
2. Add an HTTPS domain under **Domains** for the `sparedrive` component. Use internal port `8080` and leave the path blank.
3. Set `SPAREDRIVE_HTTPS_HOST` in the service to the bare hostname. Set `httpsUrl` in `.runtime/host.json` to the matching full HTTPS origin. Keep the existing storage settings.
4. Restart the Windows launcher and redeploy the Coolify service. Verify the hostname and certificate from an intended device before signing in.

For a private LAN deployment with a publicly trusted certificate, use the [Coolify DNS challenge](https://coolify.io/docs/core/networking/proxy/traefik/dns-challenge) with a supported DNS provider. Configure LAN DNS separately so the hostname resolves to the host's LAN address. [Coolify Domains](https://coolify.io/docs/core/networking/domains) explains hostname, target port, and TLS settings.

## Run the application itself in a container

A Docker host with a dedicated writable filesystem can also run SpareDrive directly using the repository-root [Dockerfile](../../Dockerfile) and [compose.coolify.yaml](../../compose.coolify.yaml). In this mode the mount determines the data folder. The Windows disk picker is part of the Windows launcher.

Build and publish the app image on the target Docker engine. A registry running on the same engine can use the following image name:

```powershell
docker build -t localhost:5000/sparedrive:coolify-1 .
docker push localhost:5000/sparedrive:coolify-1
```

Create a **Docker Compose Empty** resource with the container Compose file. Set `SPAREDRIVE_IMAGE` and `SPAREDRIVE_DATA_DIR` to the image and an existing absolute path visible to the Docker daemon. Give UID 10001 write access on Linux. The app fails if the bind mount is missing. Set `SPAREDRIVE_STORAGE_ID` to the existing data folder's marker value if you want startup to reject a different folder at the same path. If you're reusing an existing storage folder, stop the previous SpareDrive server first so one process owns the data. Leave the resource's domain blank for a loopback-only deployment.

For a new data folder, use an interactive terminal on the Docker host to create the first admin:

```powershell
docker exec -it <sparedrive-container> python -m backend.container_host setup
```

Enter the new credentials when prompted. With an existing data folder and accounts, sign in with your existing credentials. For private HTTPS in this mode, set `SPAREDRIVE_HTTPS_ORIGIN` to the exact HTTPS origin and point Tailscale Serve at the published loopback port. Use a different loopback port if the Windows gateway is already using 18765.

[Coolify Services](https://coolify.io/docs/services) covers resource setup. [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) explains how the selected host directory maps to the container.
