# Local Jenkins for the release pipeline

A Jenkins in Docker that can run `ci/Jenkinsfile`. It adds the tools the pipeline calls (git, curl,
uv, node) and its plugins, and creates the user `admin` from `JENKINS_ADMIN_PASSWORD`. Only this
computer can open it, at <http://localhost:8081/>.

```powershell
cd ci\jenkins
Copy-Item .env.example .env       # then put your own password after JENKINS_ADMIN_PASSWORD=
docker compose up -d --build      # the first build downloads about 1 GB
```

Open <http://localhost:8081/> and sign in as `admin`. Then create the GitHub credential
`github-cloudstorage-credentials` and a Multibranch Pipeline for `ci/Jenkinsfile`
(see the header of `ci/Jenkinsfile`). Jobs, credentials and history live in the Docker volume
`jenkins_home` and survive restarts.

| Task | Command |
|---|---|
| See the log | `docker compose logs -f` |
| Stop | `docker compose stop` |
| Start again | `docker compose start` |
| Rebuild after changing the Dockerfile, plugins or `jenkins.yaml` | `docker compose up -d --build` |
| Remove everything, including jobs and credentials | `docker compose down -v` |

Builds run only while Docker and this container are running. Without a public address GitHub cannot
send a webhook, so set the job's scan trigger to check GitHub every minute: a push is then built
within about a minute of the computer and container being up.
