# A Jenkins that can run ci/Jenkinsfile: it adds the tools the pipeline calls (git, curl, uv, node)
# and the plugins it uses, and creates the admin user from JENKINS_ADMIN_PASSWORD on first start.
ARG UV_VERSION=0.11.21

# COPY --from cannot take a variable, so the uv image is a named stage.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM jenkins/jenkins:lts-jdk21

USER root
# git and curl are the pipeline's own tools; node is used only for the frontend syntax check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git nodejs \
    && rm -rf /var/lib/apt/lists/*
# uv downloads and manages the Python versions the tests run on (3.10, 3.12, 3.13).
COPY --from=uv /uv /uvx /usr/local/bin/

USER jenkins
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

COPY jenkins.yaml /usr/share/jenkins/casc/jenkins.yaml
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/casc/jenkins.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
