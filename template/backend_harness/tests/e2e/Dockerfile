# TEST ONLY: the runtime image plus the offline model stand-in, inserted at the end of
# every agent profile. Built by tests/e2e.sh as app-harness:e2e; never deployed.
ARG BASE=app-harness:local
FROM ${BASE}
USER root
COPY --chmod=0755 dsh-plugin-app-e2e-model/ /opt/dsh/node_modules/dsh-plugin-app-e2e-model/
RUN ln -s /opt/dsh/node_modules/dsh-plugin-app-e2e-model "$DSH_HOME/profiles/node_modules/dsh-plugin-app-e2e-model" \
 && for patch in "$DSH_HOME"/profiles/app_*/cordis.patch.yml; do \
      printf -- '- insert:\n    - id: app-e2e-model\n      name: dsh-plugin-app-e2e-model\n' >> "$patch"; \
    done \
 && chown -R node:node "$DSH_HOME/profiles"
USER node
