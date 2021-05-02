FROM alpine:3.13
LABEL maintainer="Thomas GUIRRIEC <thomas@guirriec.fr>"
ENV LINKY_EXPORTER_PORT=8123
ENV LINKY_EXPORTER_LOGLEVEL='INFO'
COPY requirements.txt /
COPY entrypoint.sh /
ENV VIRTUAL_ENV="/linky-exporter"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN apk add --no-cache --update \
         python3 \
    && python3 -m venv ${VIRTUAL_ENV} \
    && pip install --no-cache-dir --no-dependencies --no-binary :all: -r requirements.txt \
    && pip uninstall -y setuptools pip \
    && rm -rf \
        /root/.cache \
        /tmp/* \
        /var/cache/* \
    && chmod +x /entrypoint.sh
COPY linky_exporter.py ${VIRTUAL_ENV}
WORKDIR ${VIRTUAL_ENV}
ENTRYPOINT ["/entrypoint.sh"]
